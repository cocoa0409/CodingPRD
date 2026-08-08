"""Sales ledger: provisional/audited cap, cap-breach cascade, booth settlement, void."""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    make_producer_headers, make_market_manager_headers, TEST_USERS,
    create_policy, create_registered_producer, create_class_a_issued_permit,
    create_approved_product, create_market, create_draft_manifest, submit_manifest,
    approve_manifest_fresh, record_sale, setup_approved_manifest,
    setup_registered_producer_with_approved_product,
)

INSPECTOR = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _dual_variant_sales(api):
    """Producer with m1 CHECKED_IN (sale 300000) and m2 APPROVED-only (sale 200000)."""
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="Sunny Bakes")
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = create_approved_product(api, pid, name="Sourdough", unit_price_cents=800)
    market = create_market(api, max_vendors_per_day=5, allowed_classes=["CLASS_A", "CLASS_B"])
    mm = make_market_manager_headers(market["id"])
    m1 = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], "2026-06-15")
    submit_manifest(api, pid, m1["id"])
    approve_manifest_fresh(api, market["id"], m1["id"])
    validate_success(api.checkin_manifest(m1["id"], mm), 200)
    m2 = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], "2026-06-16")
    submit_manifest(api, pid, m2["id"])
    approve_manifest_fresh(api, market["id"], m2["id"])
    record_sale(api, pid, m1["id"], 300000)
    record_sale(api, pid, m2["id"], 200000)
    return pid


def test_provisional_ytd_sums_all_recorded_sales(api):
    """PRD §3.8: "The provisional figure, `provisional_ytd_cents`, is the sum of
    `gross_amount_cents` across every one of the producer's sales still in `RECORDED`
    status, with no manifest filter and no exemption; this is the real-time figure that
    governs the cap-breach check of §3.5."

    Design: Difficulty/dual_variant_calc/sales_cap_provisional_vs_audited
    """
    pid = _dual_variant_sales(api)
    summary = get_success_data(api.get_compliance_summary(pid, INSPECTOR))
    assert summary["provisional_ytd_cents"] == 500000


def test_audited_ytd_counts_only_checked_in_minus_exemption(api):
    """PRD §3.8: "the `audited_ytd_cents`, is the end-of-season reconciliation view: it
    sums `gross_amount_cents` only over recorded sales whose manifest has reached
    `CHECKED_IN`, then subtracts a sampling-and-donation exemption of 50,000 cents, with
    the result floored at zero so it never goes negative."

    Design: Difficulty/dual_variant_calc/sales_cap_provisional_vs_audited
    """
    pid = _dual_variant_sales(api)
    summary = get_success_data(api.get_compliance_summary(pid, INSPECTOR))
    assert summary["audited_ytd_cents"] == 250000
    assert summary["provisional_ytd_cents"] != summary["audited_ytd_cents"]


def test_booth_fee_rounds_per_line_then_sums(api):
    """PRD §3.5: "two recorded sales of 908 cents each round to 54 cents apiece (54.48
    rounded half up), summing to 108 cents, whereas rounding the summed 1,816 cents times
    0.06 would give 109 cents."

    Design: Difficulty/combinatorial_formula/booth_fee_round_per_line_then_sum
    """
    scenario = setup_approved_manifest(api, unit_price_cents=500)
    pid = scenario["producer"]["id"]
    mid = scenario["manifest"]["id"]
    record_sale(api, pid, mid, 908)
    record_sale(api, pid, mid, 908)
    manifest = get_success_data(api.get_manifest(mid, INSPECTOR))
    assert manifest["booth_fee_cents"] == 108


def test_booth_fee_single_line_rounds_half_up(api):
    """PRD §3.5: "For the owning manifest, each of its sales still in `RECORDED` status
    contributes the round-half-up of its `gross_amount_cents` multiplied by the market
    fee rate of 0.06 (six percent), and those already-rounded per-line amounts are summed
    to form `booth_fee_cents`."

    Design: Difficulty/combinatorial_formula/booth_fee_round_per_line_then_sum
    """
    scenario = setup_approved_manifest(api, unit_price_cents=500)
    pid = scenario["producer"]["id"]
    mid = scenario["manifest"]["id"]
    record_sale(api, pid, mid, 908)  # round_half_up(908 * 0.06) = round(54.48) = 54
    manifest = get_success_data(api.get_manifest(mid, INSPECTOR))
    assert manifest["booth_fee_cents"] == 54


def _at_cap_producer(api):
    """Producer whose provisional ytd is exactly the CLASS_A cap of 7,500,000."""
    scenario = setup_approved_manifest(api, unit_price_cents=400)
    pid = scenario["producer"]["id"]
    record_sale(api, pid, scenario["manifest"]["id"], 7500000)
    return pid, scenario


def test_ytd_equal_to_cap_does_not_suspend(api):
    """PRD §3.5: "The comparison is strict: a year-to-date total equal to the cap does not
    breach, and a total of exactly one cent above the cap does."

    Design: Difficulty/boundary_precision_check/sales_cap_strict_greater_boundary
    """
    pid, _ = _at_cap_producer(api)
    producer = get_success_data(api.get_producer(pid, INSPECTOR))
    assert producer["status"] == "REGISTERED"


def test_ytd_at_cap_ledger_value(api):
    """PRD §2.6: "A producer's `ytd_gross_sales_cents` is a running money ledger and is
    treated as a conserved quantity. Recording a sale adds that sale's gross amount to the
    ledger"

    Design: Difficulty/boundary_precision_check/sales_cap_strict_greater_boundary
    """
    pid, _ = _at_cap_producer(api)
    producer = get_success_data(api.get_producer(pid, INSPECTOR))
    assert producer["ytd_gross_sales_cents"] == 7500000


def _breach_cap_setup(api):
    """Producer at exactly the cap, then one extra cent recorded to breach it."""
    scenario = setup_approved_manifest(api, unit_price_cents=400)
    pid = scenario["producer"]["id"]
    record_sale(api, pid, scenario["manifest"]["id"], 7500000)
    record_sale(api, pid, scenario["manifest"]["id"], 1)
    return pid, scenario


def test_cap_breach_suspends_producer(api):
    """PRD §3.5: "When the provisional total is strictly greater than the cap, the
    producer is suspended and the full suspension cascade of §2.8 fires — producer and
    issued permit move to `SUSPENDED` and every non-terminal manifest is voided with
    day-slots freed."

    Design: Difficulty/transitive_cascade/salescap_breach_depth_cascade
    """
    pid, _ = _breach_cap_setup(api)
    producer = get_success_data(api.get_producer(pid, INSPECTOR))
    assert producer["status"] == "SUSPENDED"
    assert producer["ytd_gross_sales_cents"] == 7500001


def test_cap_breach_voids_bound_manifest(api):
    """PRD §2.8: "Every non-terminal market manifest belonging to that producer (that is,
    any manifest in `SUBMITTED`, `APPROVED`, or `CHECKED_IN`) is moved to `VOIDED`."

    Design: Difficulty/transitive_cascade/salescap_breach_depth_cascade
    """
    pid, scenario = _breach_cap_setup(api)
    manifest = get_success_data(api.get_manifest(scenario["manifest"]["id"], INSPECTOR))
    assert manifest["status"] == "VOIDED"


def _void_ledger_setup(api):
    scenario = setup_approved_manifest(api, unit_price_cents=250)
    pid = scenario["producer"]["id"]
    sale = record_sale(api, pid, scenario["manifest"]["id"], 40000)
    return pid, sale["id"]


def test_void_sale_marks_record_voided(api):
    """PRD §3.5: "An administrator may void a recorded sale, moving it from `RECORDED` to
    `VOIDED`; a sale that is not currently `RECORDED` (already voided) yields
    `ERR_SALES_RECORD_NOT_RECORDED`."

    Design: Difficulty/compensating_invariant/sales_ledger_conserved_on_void
    """
    pid, sr_id = _void_ledger_setup(api)
    validate_success(api.void_sales_record(sr_id, ADMIN), 200)
    sale = get_success_data(api.get_sales_record(sr_id, INSPECTOR))
    assert sale["status"] == "VOIDED"


def test_void_sale_restores_ledger_to_zero(api):
    """PRD §2.6: "voiding a previously recorded sale subtracts the same amount back out,
    restoring the ledger to the value it would have held had the sale never been
    recorded. The ledger must always equal the sum of the gross amounts of the producer's
    sales that are still in `RECORDED` status."

    Design: Difficulty/compensating_invariant/sales_ledger_conserved_on_void
    """
    pid, sr_id = _void_ledger_setup(api)
    validate_success(api.void_sales_record(sr_id, ADMIN), 200)
    producer = get_success_data(api.get_producer(pid, INSPECTOR))
    assert producer["ytd_gross_sales_cents"] == 0


def test_nonpositive_gross_amount_rejected(api):
    """PRD §3.5: "A registered producer reports a sale against a manifest by supplying
    the `manifest_id` and a `gross_amount_cents`, which must be strictly greater than
    zero (a non-positive amount is `ERR_INVALID_REQUEST`)."

    Design: Corner/entities/sales_record_nonpositive_gross_returns_invalid_request
    """
    scenario = setup_approved_manifest(api, unit_price_cents=300)
    pid = scenario["producer"]["id"]
    resp = api.create_sales_record({"manifest_id": scenario["manifest"]["id"], "gross_amount_cents": 0},
                                   make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    producer = get_success_data(api.get_producer(pid, INSPECTOR))
    assert producer["ytd_gross_sales_cents"] == 0


def test_audited_ytd_floors_at_zero_below_exemption(api):
    """PRD §3.8: "then subtracts a sampling-and-donation exemption of 50,000 cents, with
    the result floored at zero so it never goes negative."

    Design: Corner/calculations/audited_ytd_floors_at_zero
    """
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="Floor Co")
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = create_approved_product(api, pid, name="Danish", unit_price_cents=300)
    market = create_market(api, max_vendors_per_day=5, allowed_classes=["CLASS_A"])
    m1 = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], "2026-06-15")
    submit_manifest(api, pid, m1["id"])
    approve_manifest_fresh(api, market["id"], m1["id"])
    validate_success(api.checkin_manifest(m1["id"], make_market_manager_headers(market["id"])), 200)
    record_sale(api, pid, m1["id"], 30000)
    summary = get_success_data(api.get_compliance_summary(pid, INSPECTOR))
    assert summary["provisional_ytd_cents"] == 30000
    assert summary["audited_ytd_cents"] == 0
