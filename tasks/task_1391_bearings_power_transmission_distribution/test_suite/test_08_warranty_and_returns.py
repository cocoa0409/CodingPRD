"""Warranty claims (analysis loop, tiered credit, SoD) and return
authorizations (RMA window, qty ceiling, credit netting waterfall)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    build_user_headers,
    create_product, create_branch, create_customer, create_branch_stock,
    create_confirmed_order_with_line, create_shipped_line,
    create_agreement, report_consumption, invoice_consumption,
    file_claim, begin_analysis, render_verdict,
    create_return, approve_return, reserve_line, set_clock,
    setup_stocked_scenario, setup_claim_under_analysis, setup_verdicted_claim,
    get_claim, get_consumption, get_customer, get_branch_stock,
    get_return_authorization, get_agreement,
    assert_return_credit_conservation,
    ApiErrorId, TEST_USERS,
)

ANALYST = TEST_USERS["pricing_analyst_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_loop_claim():
    """Shipped line (unit 10000, qty 2) + claim filed by wa-1, hours 100."""
    ctx = setup_stocked_scenario(list_price_cents=10000, on_hand_qty=10)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=2)
    claim = file_claim(ctx["product"]["id"], "wa-1", order_line_id=line["id"],
                       failure_mode="FATIGUE", operating_hours=100, qty=1)
    ctx.update({"order": order, "line": line, "claim": claim})
    return ctx


def test_warranty_analysis_info_request_loop_reentry(api):
    """PRD §3.7: "If more information is needed, the engineer returns the claim
    to the filer — `UNDER_ANALYSIS` back to `SUBMITTED`
    (`ERR_CLAIM_NOT_UNDER_ANALYSIS` guards the loop) — and analysis can begin
    again."

    Design: Difficulty/non_linear_state_machine/warranty_claim_analysis_info_loop_cycle
    """
    ctx = _setup_loop_claim()
    claim_id = ctx["claim"]["id"]
    analyzing = begin_analysis(claim_id, "qe-1")
    assert analyzing["status"] == "UNDER_ANALYSIS"
    returned = get_success_data(api.request_info(
        claim_id, build_user_headers("qe-1", "QualityEngineer")))
    assert returned["status"] == "SUBMITTED", (
        "info-request loop traverses UNDER_ANALYSIS -> SUBMITTED")
    reentered = begin_analysis(claim_id, "qe-1")
    assert reentered["status"] == "UNDER_ANALYSIS", (
        "loop re-entry is legal: SUBMITTED -> UNDER_ANALYSIS again")


def test_warranty_verdict_after_loop_computes_tiered_credit(api):
    """PRD §3.7: "A verdict of `CONFIRMED_DEFECT` approves the claim" and
    "coverage is 100 percent when `operating_hours` is below 2000" and
    "`credit_amount_cents` is the source unit price times `qty` times
    `coverage_pct`, rounded half-up to integer cents."
    PRD §3.7: "The claim is born `SUBMITTED`, `filed_by` records the analyst's
    `X-User-ID`" and "On approval, `verdict` and `verdict_by` persist".

    Design: Difficulty/non_linear_state_machine/warranty_claim_analysis_info_loop_cycle
    """
    ctx = _setup_loop_claim()
    claim_id = ctx["claim"]["id"]
    begin_analysis(claim_id, "qe-1")
    get_success_data(api.request_info(
        claim_id, build_user_headers("qe-1", "QualityEngineer")))
    begin_analysis(claim_id, "qe-1")
    verdicted = render_verdict(claim_id, "CONFIRMED_DEFECT", "qe-1")
    assert verdicted["status"] == "APPROVED"
    assert verdicted["verdict"] == "CONFIRMED_DEFECT"
    assert verdicted["coverage_pct"] == 1.0
    assert verdicted["credit_amount_cents"] == 10000  # 1 * 10000 * 1.0
    assert verdicted["verdict_by"] == "qe-1"
    assert verdicted["filed_by"] == "wa-1"


def _setup_tier_boundary_claims():
    """One shipped line (unit 10000, qty 4); three claims (qty 1 each) at
    hours 1999 / 2000 / 5000, all UNDER_ANALYSIS."""
    ctx = setup_stocked_scenario(list_price_cents=10000, on_hand_qty=10)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=4)
    claims = {}
    for key, hours in (("a", 1999), ("b", 2000), ("c", 5000)):
        claim = file_claim(ctx["product"]["id"], "wa-9",
                           order_line_id=line["id"], failure_mode="FATIGUE",
                           operating_hours=hours, qty=1)
        claims[key] = begin_analysis(claim["id"], "qe-9")
    ctx["claims"] = claims
    return ctx


def test_warranty_tier_boundary_1999_and_2000_hours(api):
    """PRD §3.7: "coverage is 100 percent when `operating_hours` is below 2000,
    50 percent from 2000 up to but not including 5000, and 25 percent at 5000
    hours or more — the lower bounds are inclusive, so exactly 2000 hours
    yields 50 percent and exactly 5000 yields 25 percent."

    Design: Difficulty/boundary_precision_check/warranty_hours_exactly_2000_gets_50pct
    """
    ctx = _setup_tier_boundary_claims()
    claim_a = render_verdict(ctx["claims"]["a"]["id"], "CONFIRMED_DEFECT", "qe-9")
    assert claim_a["coverage_pct"] == 1.0, "1999 < 2000 -> full coverage"
    assert claim_a["credit_amount_cents"] == 10000  # 1 * 10000 * 1.0
    claim_b = render_verdict(ctx["claims"]["b"]["id"], "CONFIRMED_DEFECT", "qe-9")
    assert claim_b["coverage_pct"] == 0.5, (
        "exactly 2000 falls in [2000, 5000) — lower bound inclusive")
    assert claim_b["credit_amount_cents"] == 5000  # 1 * 10000 * 0.5


def test_warranty_tier_boundary_5000_hours(api):
    """PRD §3.7: "coverage is 100 percent when `operating_hours` is below 2000,
    50 percent from 2000 up to but not including 5000, and 25 percent at 5000
    hours or more — the lower bounds are inclusive, so exactly 2000 hours
    yields 50 percent and exactly 5000 yields 25 percent."

    Design: Difficulty/boundary_precision_check/warranty_hours_exactly_2000_gets_50pct
    """
    ctx = _setup_tier_boundary_claims()
    claim_c = render_verdict(ctx["claims"]["c"]["id"], "CONFIRMED_DEFECT", "qe-9")
    assert claim_c["coverage_pct"] == 0.25, "5000 >= 5000 -> lowest tier"
    assert claim_c["credit_amount_cents"] == 2500  # 1 * 10000 * 0.25
    assert claim_c["status"] == "APPROVED"
    for key in ("a", "b"):
        verdicted = render_verdict(
            ctx["claims"][key]["id"], "CONFIRMED_DEFECT", "qe-9")
        assert verdicted["status"] == "APPROVED"


def _setup_return_waterfall():
    """Customer: consignment invoices 5000 + 6000 (INVOICED); shipped 10 of P1
    (list 2500); APPROVED OBSOLETE return qty 10 at original 2000.

    The two consumptions are reported one logical hour apart so the
    oldest-first waterfall order is unambiguous."""
    set_clock("2026-08-01T00:00:00Z")
    p1 = create_product(sku="BRG-6212", list_price_cents=2500)
    p2 = create_product(sku="BRG-6204", list_price_cents=1000)
    branch = create_branch(code="OKC-17")
    customer = create_customer(name="Soener Plant")
    stock1 = create_branch_stock(branch["id"], p1["id"], on_hand_qty=20)
    create_branch_stock(branch["id"], p2["id"], on_hand_qty=50)
    agreement = create_agreement(customer["id"], branch["id"], p2["id"],
                                 consigned_qty=11)
    cons1 = invoice_consumption(
        report_consumption(agreement["id"], 5, customer["id"])["id"])
    set_clock("2026-08-01T01:00:00Z")  # strictly later created_at for cons2
    cons2 = invoice_consumption(
        report_consumption(agreement["id"], 6, customer["id"])["id"])
    order, line, _ = create_shipped_line(
        customer["id"], branch["id"], p1["id"], stock1["id"], qty=10)
    ret = create_return(customer["id"], p1["id"], branch["id"], qty=10,
                        condition="OBSOLETE", original_unit_price_cents=2000,
                        requester_user_id="csr-1")
    ret = approve_return(ret["id"], approver_user_id="bm-1")
    return {"p1": p1, "p2": p2, "branch": branch, "customer": customer,
            "stock1": stock1, "agreement": agreement, "cons1": cons1,
            "cons2": cons2, "order": order, "line": line, "return": ret}


def test_return_credit_waterfall_fills_oldest_invoice_first(api):
    """PRD §3.8: "Bucket one: the customer's outstanding consignment invoices —
    consumptions in `INVOICED` status whose outstanding balance
    (`billed_amount_cents` minus that consumption's `offset_applied_cents`) is
    positive — are offset oldest first by the consumption's `created_at`
    ascending (ties broken by `reported_at` ascending), each bucket filled to
    its full outstanding before the next is touched, until the nettable amount
    is exhausted."

    Design: Difficulty/compensating_invariant/return_credit_value_conservation
    """
    ctx = _setup_return_waterfall()
    received = validate_success(api.receive_return(
        ctx["return"]["id"], {"received_qty": 10}, MANAGER), 200)
    # base = 10 * min(2000, 2500) = 20000; eligible = round(20000 * 0.85).
    assert received["eligible_credit_cents"] == 17000
    # OBSOLETE: write-down = round(17000 * 0.5).
    assert received["write_down_cents"] == 8500

    issued = validate_success(
        api.issue_return_credit(ctx["return"]["id"], MANAGER), 200)
    # nettable 8500 fills cons1 (5000) fully, then 3500 of cons2.
    assert issued["offset_applied_cents"] == 8500
    assert issued["credit_memo_cents"] == 0
    assert_return_credit_conservation(issued)
    cons1 = get_consumption(ctx["cons1"]["id"])
    cons2 = get_consumption(ctx["cons2"]["id"])
    assert cons1["offset_applied_cents"] == 5000, (
        f"oldest consumption filled first; got {cons1['offset_applied_cents']}")
    assert cons2["offset_applied_cents"] == 3500


def test_obsolete_return_receipt_scraps_without_restocking(api):
    """PRD §3.8: "Restock is condition-dependent: a `SURPLUS` return of a
    product still in `ACTIVE` status lands back on the shelf, increasing the
    receiving branch stock's `on_hand_qty` by `received_qty`; obsolete units
    are scrapped and never add stock."

    Design: Difficulty/compensating_invariant/return_credit_value_conservation
    """
    ctx = _setup_return_waterfall()
    before = get_branch_stock(ctx["stock1"]["id"])["on_hand_qty"]
    validate_success(api.receive_return(
        ctx["return"]["id"], {"received_qty": 10}, MANAGER), 200)
    issued = validate_success(
        api.issue_return_credit(ctx["return"]["id"], MANAGER), 200)
    assert issued["status"] == "CREDIT_ISSUED"
    after = get_branch_stock(ctx["stock1"]["id"])["on_hand_qty"]
    assert after == before, (
        f"OBSOLETE units are scrapped: on_hand must stay {before}, got {after}")


def test_verdict_on_approved_claim_rejected(api):
    """PRD §3.7: "The verdict ends analysis. The claim must be
    `UNDER_ANALYSIS` (`ERR_CLAIM_NOT_UNDER_ANALYSIS`)".

    Design: Corner/state_machines/verdict_on_approved_claim_rejected
    """
    ctx = setup_verdicted_claim("CONFIRMED_DEFECT", filed_by="wa-5",
                                engineer="qe-5", failure_mode="FATIGUE",
                                line_qty=1, list_price_cents=10000)
    res = api.render_verdict(ctx["claim"]["id"], {"verdict": "WEAR_OUT"},
                             build_user_headers("qe-5", "QualityEngineer"))
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_UNDER_ANALYSIS,
                   expected_status=409)
    claim = get_claim(ctx["claim"]["id"])
    assert claim["status"] == "APPROVED"
    assert claim["verdict"] == "CONFIRMED_DEFECT"
    assert claim["credit_amount_cents"] == 10000


def test_warranty_credit_rounding_half_up_on_odd_cents(api):
    """PRD §2.7: "Every monetary computation in this system rounds to 0
    decimal places (integer cents), and every rounding is round-half-up."
    PRD §3.7: "`credit_amount_cents` is the source unit price times `qty`
    times `coverage_pct`, rounded half-up to integer cents."

    Design: Corner/calculations/warranty_credit_rounding_half_up_on_odd_cents
    """
    ctx = setup_claim_under_analysis(
        filed_by="wa-7", engineer="qe-7", operating_hours=2000,
        claim_qty=1, line_qty=1, list_price_cents=9999,
        failure_mode="CONTAMINATION")
    verdicted = render_verdict(ctx["claim"]["id"], "CONFIRMED_DEFECT", "qe-7")
    # 9999 * 1 * 0.5 = 4999.5 -> round-half-up 5000.
    assert verdicted["credit_amount_cents"] == 5000, (
        f"round_half_up(4999.5) must be 5000, got {verdicted['credit_amount_cents']}")


def test_warranty_sod_verdict_by_filer_rejected(api):
    """PRD §3.7: "segregation of duties forbids the engineer who filed the
    claim from verdicting it: the verdicting `X-User-ID` must differ from
    `filed_by` (`ERR_WARRANTY_SOD_VERDICT`, 403)."

    Design: Corner/errors/warranty_sod_verdict_by_filer_rejected
    """
    ctx = setup_claim_under_analysis(filed_by="wa-x", engineer="qe-x",
                                     operating_hours=10, claim_qty=1,
                                     line_qty=1, list_price_cents=1000)
    res = api.render_verdict(ctx["claim"]["id"], {"verdict": "CONFIRMED_DEFECT"},
                             build_user_headers("wa-x", "QualityEngineer"))
    validate_error(res, ApiErrorId.ERR_WARRANTY_SOD_VERDICT, expected_status=403)
    claim = get_claim(ctx["claim"]["id"])
    assert claim["status"] == "UNDER_ANALYSIS"
    assert claim["verdict"] == "NONE"


def test_claim_must_reference_exactly_one_source(api):
    """PRD §3.7: "exactly one of `order_line_id` or `consumption_id` must be
    supplied — supplying both or neither fails with `ERR_CLAIM_REFERENCE_INVALID`
    (400)."

    Design: Corner/validations/claim_must_reference_exactly_one_source
    """
    product = create_product(sku="BRG-6029", list_price_cents=1000)
    res = api.create_warranty_claim(
        {"product_id": product["id"], "failure_mode": "FATIGUE",
         "operating_hours": 10, "qty": 1},
        build_user_headers("wa-x", "WarrantyAnalyst"))
    validate_error(res, ApiErrorId.ERR_CLAIM_REFERENCE_INVALID, expected_status=400)


def test_claim_qty_exceeds_source_line_qty(api):
    """PRD §3.7: "The claim `qty` may not exceed the source line's or
    consumption's quantity (`ERR_CLAIM_QTY_EXCEEDS_SOURCE`, 409)."

    Design: Corner/validations/claim_qty_exceeds_source_line_qty
    """
    ctx = setup_stocked_scenario(list_price_cents=1000, on_hand_qty=5)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=2)
    res = api.create_warranty_claim(
        {"product_id": ctx["product"]["id"], "order_line_id": line["id"],
         "failure_mode": "FATIGUE", "operating_hours": 10, "qty": 3},
        build_user_headers("wa-y", "WarrantyAnalyst"))
    validate_error(res, ApiErrorId.ERR_CLAIM_QTY_EXCEEDS_SOURCE, expected_status=409)


def test_return_expires_after_rma_window(api):
    """PRD §3.8: "An approved return that is not received in time lapses
    automatically to `EXPIRED` when the logical clock passes `approved_at`
    plus 30 days."
    PRD §3.8: "the return must be `APPROVED` (`ERR_RETURN_NOT_APPROVED`, 409)".

    Design: Corner/state_machines/return_expires_after_rma_window
    """
    set_clock("2026-08-02T10:00:00Z")
    product = create_product(sku="BRG-6019", list_price_cents=1000)
    branch = create_branch(code="RMA-09")
    customer = create_customer(name="RMA Plant", credit_limit_cents=1000000)
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=5)
    order, line, _ = create_shipped_line(
        customer["id"], branch["id"], product["id"], stock["id"], qty=3)
    ret = create_return(customer["id"], product["id"], branch["id"], qty=1,
                        condition="SURPLUS", original_unit_price_cents=1000,
                        requester_role="CustomerPlant")
    ret = approve_return(ret["id"], approver_user_id="bm-9")
    # 2026-09-02T10:00 is past approved_at + 30 days.
    set_clock("2026-09-02T10:00:00Z")
    expired = get_return_authorization(ret["id"])
    assert expired["status"] == "EXPIRED"
    res = api.receive_return(ret["id"], {"received_qty": 1}, MANAGER)
    validate_error(res, ApiErrorId.ERR_RETURN_NOT_APPROVED, expected_status=409)


def test_return_qty_exceeds_shipped_trigger(api):
    """PRD §3.8: "Approval requires `REQUESTED` (`ERR_RETURN_NOT_REQUESTED`,
    409) and requires the authorized `qty` not exceed the customer's cumulative
    shipped quantity of this product across all orders
    (`ERR_RETURN_QTY_EXCEEDS_SHIPPED`, 409)".

    Design: Corner/errors/return_qty_exceeds_shipped_trigger
    """
    ctx = setup_stocked_scenario(list_price_cents=1000, on_hand_qty=5)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=2)
    ret = create_return(ctx["customer"]["id"], ctx["product"]["id"],
                        ctx["branch"]["id"], qty=4, condition="SURPLUS",
                        original_unit_price_cents=1000,
                        requester_user_id="csr-1")
    res = api.approve_return(ret["id"],
                             build_user_headers("bm-2", "BranchManager"))
    validate_error(res, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_SHIPPED,
                   expected_status=409)
    assert get_return_authorization(ret["id"])["status"] == "REQUESTED"
