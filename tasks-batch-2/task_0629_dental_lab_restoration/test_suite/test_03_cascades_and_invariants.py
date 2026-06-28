"""Transitive-cascade and compensating-invariant tests: the depth-4 ship cascade
(SLA breach -> FINAL invoice credit -> CreditMemo -> doctor ledger), the cancel
cascade freeing a machine interval, remake-count conservation, and credit-ledger
conservation across issue/void.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    TEST_USERS, make_doctor_headers,
    create_mill_job_payload, create_remake_request_payload,
    setup_shipped_case, setup_delivered_case, get_invoice_for_case, get_case,
    set_clock,
)
from test_helpers.fixtures import list_units

ADMIN = TEST_USERS["labadmin_headers"]
TECH = TEST_USERS["labtech_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_ship_breach_cascade_issues_credit_and_bumps_ledger(api):
    """PRD §3.6: "If the case is breached at ship, the server also issues a
    credit. It creates a CreditMemo in ISSUED status whose amount_cents equals
    the invoice's sla_credit_cents, recording the related case_id and the FINAL
    invoice_id, and it adds that amount to the doctor's account_credit_cents."
    PRD §3.6: "The final variant additionally computes sla_credit_cents as the
    subtotal multiplied by 0.20 and rounded half up when, and only when, the
    case's sla_breached flag is true; otherwise the SLA credit is 0."

    Design: Difficulty/transitive_cascade/ship_cascade_unit_invoice_creditmemo_ledger
    """
    # crown subtotal 12000; promised 2026-01-06T00:00:00Z; ship 1h late -> breach.
    built = setup_shipped_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
        route_overrides={"service_date": "2026-01-06T00:00:00Z"},
        stop_overrides={"window_start_at": "2026-01-06T09:00:00Z"},
        clock_at_ship="2026-01-06T01:00:00Z",
    )
    case = built["case"]
    assert case["sla_breached"] is True, "shipping 1h past promise must breach SLA"

    invoice = get_invoice_for_case(case["id"])
    assert invoice["kind"] == "FINAL"
    assert invoice["sla_credit_cents"] == 2400         # round(12000 * 0.20)
    assert invoice["total_cents"] == 10590             # 12990 - 2400

    memos = get_success_data(api.list_case_credit_memos(case["id"], BILLING))
    assert len(memos) == 1
    assert memos[0]["amount_cents"] == 2400
    assert memos[0]["status"] == "ISSUED"

    doctor = get_success_data(api.get_doctor(built["doctor"]["id"], BILLING))
    assert doctor["account_credit_cents"] == 2400, (
        "the issued memo must increment the doctor's account_credit ledger by 2400"
    )


def test_ship_breach_creditmemo_links_final_invoice(api):
    """PRD §3.6: "It creates a CreditMemo in ISSUED status whose amount_cents
    equals the invoice's sla_credit_cents, recording the related case_id and the
    FINAL invoice_id, and it adds that amount to the doctor's
    account_credit_cents."

    Design: Difficulty/transitive_cascade/ship_cascade_unit_invoice_creditmemo_ledger
    """
    built = setup_shipped_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
        route_overrides={"service_date": "2026-01-06T00:00:00Z"},
        stop_overrides={"window_start_at": "2026-01-06T09:00:00Z"},
        clock_at_ship="2026-01-06T01:00:00Z",
    )
    case = built["case"]
    invoice = get_invoice_for_case(case["id"])
    memos = get_success_data(api.list_case_credit_memos(case["id"], BILLING))
    assert memos[0]["amount_cents"] == invoice["sla_credit_cents"] == 2400
    assert memos[0]["case_id"] == case["id"]
    assert memos[0]["invoice_id"] == invoice["id"]


def test_cancel_in_design_cancels_milljob(api):
    """PRD §3.8: "Cancelling a case that has reached DESIGN carries a heavier
    cascade: every SCHEDULED mill job belonging to the case's units is cancelled
    to CANCELLED, which frees each reserved machine interval for re-scheduling,
    the case's invoice billing_status is set to VOID, and the case's version
    increments."

    Design: Difficulty/transitive_cascade/cancel_cascade_milljob_machine_release
    """
    from test_helpers.fixtures import (
        set_clock as _set_clock, create_doctor, create_material, create_machine,
        create_case, create_restoration,
    )
    _set_clock()
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    machine = create_machine()
    case = create_case(doctor["id"])
    rest = create_restoration(case["id"], material["id"], restoration_type="CROWN",
                              unit_count=1)
    get_success_data(api.submit_case(case["id"], TECH))
    unit = list_units(rest["id"])[0]
    job = get_success_data(api.create_mill_job(
        create_mill_job_payload(unit["id"], machine["id"],
                                start_at="2026-01-01T09:00:00Z", duration_minutes=90), SCHED))

    cancel_res = api.cancel_case(case["id"], make_doctor_headers(doctor["id"]))
    cancelled = validate_success(cancel_res, 200)
    assert cancelled["status"] == "CANCELLED"

    job_after = get_success_data(api.get_mill_job(job["id"], SCHED))
    assert job_after["status"] == "CANCELLED", (
        "cancelling a DESIGN case must cascade its SCHEDULED mill job to CANCELLED"
    )


def test_cancel_in_design_frees_machine_interval(api):
    """PRD §3.8: "every SCHEDULED mill job belonging to the case's units is
    cancelled to CANCELLED, which frees each reserved machine interval for
    re-scheduling". PRD §3.4: "A new job's half-open interval must also not
    intersect any non-cancelled job already booked on the same machine; an
    overlap is rejected with ERR_MACHINE_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/transitive_cascade/cancel_cascade_milljob_machine_release
    """
    from test_helpers.fixtures import (
        set_clock as _set_clock, create_doctor, create_material, create_machine,
        create_case, create_restoration,
    )
    _set_clock()
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    machine = create_machine()
    case = create_case(doctor["id"])
    rest = create_restoration(case["id"], material["id"], restoration_type="CROWN",
                              unit_count=1)
    get_success_data(api.submit_case(case["id"], TECH))
    unit = list_units(rest["id"])[0]
    get_success_data(api.create_mill_job(
        create_mill_job_payload(unit["id"], machine["id"],
                                start_at="2026-01-01T09:00:00Z", duration_minutes=90), SCHED))

    api.cancel_case(case["id"], make_doctor_headers(doctor["id"]))

    # A second case + unit can now book the same machine over the freed interval.
    case2 = create_case(doctor["id"])
    rest2 = create_restoration(case2["id"], material["id"], restoration_type="CROWN",
                               unit_count=1)
    get_success_data(api.submit_case(case2["id"], TECH))
    unit2 = list_units(rest2["id"])[0]
    res = api.create_mill_job(
        create_mill_job_payload(unit2["id"], machine["id"],
                                start_at="2026-01-01T09:00:00Z", duration_minutes=90), SCHED)
    validate_success(res, 201)


def test_remake_approval_conserves_billable_count_and_subtotal(api):
    """PRD §3.9: "Approving a remake request moves it from OPEN to APPROVED,
    transitions the targeted PASSED unit to the terminal REMADE_OUT, and spawns a
    brand-new replacement FabricationUnit in QUEUED with is_billable false and
    its remade_from_unit_id pointing at the unit it replaces". PRD §3.9: "Because
    the replacement unit is non-billable, the case's billable_unit_count and the
    invoice subtotal are conserved across the remake - warranty work is never
    re-billed."

    Design: Difficulty/compensating_invariant/remake_conserves_billable_unit_count_and_subtotal
    """
    built = setup_delivered_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    unit = built["units"][0]
    assert unit["status"] == "PASSED"

    rr = get_success_data(api.create_remake_request(
        case["id"], create_remake_request_payload(unit["id"], reason="FRACTURE"),
        make_doctor_headers(built["doctor"]["id"])))
    get_success_data(api.approve_remake_request(rr["id"], ADMIN))

    case_after = get_case(case["id"])
    assert case_after["billable_unit_count"] == 1, (
        "the non-billable replacement must not change billable_unit_count"
    )
    invoice = get_invoice_for_case(case["id"])
    assert invoice["subtotal_cents"] == 12000, "warranty remake adds no billable line"


def test_remake_approval_terminalizes_unit_and_spawns_nonbillable(api):
    """PRD §3.9: "transitions the targeted PASSED unit to the terminal REMADE_OUT,
    and spawns a brand-new replacement FabricationUnit in QUEUED with is_billable
    false and its remade_from_unit_id pointing at the unit it replaces". PRD §3.9:
    "A unit's is_billable flag is fixed at creation and never mutated thereafter,
    which is what guarantees that conservation."

    Design: Difficulty/compensating_invariant/remake_conserves_billable_unit_count_and_subtotal
    """
    built = setup_delivered_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    unit = built["units"][0]

    rr = get_success_data(api.create_remake_request(
        case["id"], create_remake_request_payload(unit["id"], reason="FRACTURE"),
        make_doctor_headers(built["doctor"]["id"])))
    get_success_data(api.approve_remake_request(rr["id"], ADMIN))

    original = get_success_data(api.get_fabrication_unit(unit["id"], ADMIN))
    assert original["status"] == "REMADE_OUT"

    remakes = get_success_data(api.list_unit_remakes(unit["id"], ADMIN))
    assert len(remakes) == 1
    assert remakes[0]["is_billable"] is False
    assert remakes[0]["remade_from_unit_id"] == unit["id"]
    assert remakes[0]["status"] == "QUEUED"


def test_credit_issue_then_void_conserves_ledger(api):
    """PRD §3.6: "issuing a memo adds its amount and voiding a memo later
    subtracts the identical amount, so the doctor's account_credit_cents always
    equals the sum of the amount_cents of that doctor's memos currently in
    ISSUED." PRD §3.9: "the memo moves from ISSUED to VOID, and the doctor's
    account_credit_cents is decremented by exactly that memo's amount_cents".

    Design: Difficulty/compensating_invariant/sla_credit_issue_then_void_conserves_account_credit
    """
    built = setup_shipped_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
        route_overrides={"service_date": "2026-01-06T00:00:00Z"},
        stop_overrides={"window_start_at": "2026-01-06T09:00:00Z"},
        clock_at_ship="2026-01-06T01:00:00Z",
    )
    case = built["case"]
    memo = get_success_data(api.list_case_credit_memos(case["id"], BILLING))[0]
    assert get_success_data(api.get_doctor(
        built["doctor"]["id"], BILLING))["account_credit_cents"] == 2400

    void_res = api.void_credit_memo(memo["id"], BILLING)
    voided = validate_success(void_res, 200)
    assert voided["status"] == "VOID"

    doctor = get_success_data(api.get_doctor(built["doctor"]["id"], BILLING))
    assert doctor["account_credit_cents"] == 0, (
        "issue(+2400) then void(-2400) must return the ledger to 0 with no drift"
    )


def test_void_memo_status_becomes_void(api):
    """PRD §3.9: "the billing operator voids the corresponding credit memo: the
    memo moves from ISSUED to VOID, and the doctor's account_credit_cents is
    decremented by exactly that memo's amount_cents, preserving the conservation
    invariant described in §3.6."

    Design: Difficulty/compensating_invariant/sla_credit_issue_then_void_conserves_account_credit
    """
    built = setup_shipped_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
        route_overrides={"service_date": "2026-01-06T00:00:00Z"},
        stop_overrides={"window_start_at": "2026-01-06T09:00:00Z"},
        clock_at_ship="2026-01-06T01:00:00Z",
    )
    case = built["case"]
    memo = get_success_data(api.list_case_credit_memos(case["id"], BILLING))[0]
    assert memo["status"] == "ISSUED"
    voided = validate_success(api.void_credit_memo(memo["id"], BILLING), 200)
    assert voided["status"] == "VOID"
    assert voided["amount_cents"] == 2400
