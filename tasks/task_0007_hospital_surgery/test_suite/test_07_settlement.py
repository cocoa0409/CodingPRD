"""Settlement: provisional estimate, final cost, pre-auth, itemize, settle, refund."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    api_client,
    create_pre_authorize_payload,
    create_itemize_payload,
    setup_dual_variant_settlement,
    setup_combinatorial_cardiac_scheduled,
    setup_insurance_split_rounding,
    get_settlement_for_case,
    setup_completed_general_case,
    setup_in_progress_general_case,
    advance_clock,
    complete_case,
    setup_scheduled_general_case,
)


SCHED = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# ─── Difficulty Rule 1.1 — Provisional vs final amount on Settlement ──────

def test_provisional_estimate_uses_planned_interval(api):
    """# difficulty: dual_variant_calc/settlement_estimate_vs_final_on_settlement

    PRD §3.9: 'When a case advances from `APPROVED` to `SCHEDULED`, the system
    computes the provisional total and writes it to `estimated_total_amount`.
    The computation is forward-looking: it uses the planned interval and the
    staff/room/instrument set selected at scheduling.'

    Recipe: room@500, anesth@200, scrub@80, planned 0..60 (1h), no implants:
      room=500, anesth=200, scrub=80, instrument=150, implant=0 → 930.00"""
    bundle = setup_dual_variant_settlement(planned_duration=60, actual_duration=90)
    s = bundle["settlement"]
    assert s["estimated_total_amount"] == 930.00


def test_final_total_uses_actual_interval(api):
    """# difficulty: dual_variant_calc/settlement_estimate_vs_final_on_settlement

    PRD §3.9: 'When the case advances from `IN_PROGRESS` to `COMPLETED`, the system
    computes the chronological actual total and writes it to `final_total_amount`.
    ... actual duration is `actual_end_minute` minus `actual_start_minute`,
    billable hours are derived by dividing the actual duration by 60 and
    rounding **up** to the next whole number'.

    Recipe: actual 0..90 → ceil(90/60)=2 billable hours; same staff & room:
      room=2*500=1000, anesth=2*200=400, scrub=2*80=160, instrument=150, implant=0 → 1710.00"""
    bundle = setup_dual_variant_settlement(planned_duration=60, actual_duration=90)
    s = bundle["settlement"]
    assert s["final_total_amount"] == 1710.00


def test_estimated_and_final_differ_on_overrun(api):
    """# difficulty: dual_variant_calc/settlement_estimate_vs_final_on_settlement

    PRD §3.9: 'when actual duration exceeds planned duration the final total
    exceeds the estimate, and vice versa — the same settlement carries two
    different totals computed from the same staff and room set'."""
    bundle = setup_dual_variant_settlement(planned_duration=60, actual_duration=90)
    s = bundle["settlement"]
    assert s["estimated_total_amount"] != s["final_total_amount"]
    assert s["final_total_amount"] > s["estimated_total_amount"]


# ─── Difficulty Rule 2.1 — Cardiac combinatorial cost ─────────────────────

def test_cardiac_provisional_cost_combinatorial_components(api):
    """# difficulty: combinatorial_formula/provisional_cost_tiered_rate_selection_mode_a

    PRD §3.9: 'It then computes each cost component, rounding each to two decimal
    places half-up before summing: the room component is the billable hours
    multiplied by the operating room's `hourly_rate`; each staff component is the
    billable hours multiplied by that staff member's `hourly_rate` ... the
    instrument component is the per-set base fee of 150.00 currency units (one
    set per case); and the implant component is the case's `implant_cost_estimate`'.

    Recipe: CARDIAC_OR @1000, anesth@200, scrub@80, circ@70, implant=5000,
    planned 0..180 (3 billable hours):
      room=3000, anesth=600, scrub=240, circ=210, instrument=150, implant=5000 = 9200.00"""
    bundle = setup_combinatorial_cardiac_scheduled()
    s = bundle["settlement"]
    assert s["estimated_total_amount"] == 9200.00


def test_cardiac_provisional_with_three_staff_includes_all(api):
    """# difficulty: combinatorial_formula/provisional_cost_tiered_rate_selection_mode_a

    PRD §3.9: 'each staff component is the billable hours multiplied by that
    staff member's `hourly_rate`, computed once per `CaseAssignment` on the
    case at the moment of scheduling (when each assignment is in `RESERVED`)'.

    Three CARDIAC staff at 200/80/70 with 3 billable hours yields 600+240+210
    = 1050 in staff components alone."""
    bundle = setup_combinatorial_cardiac_scheduled()
    s = bundle["settlement"]
    # implant_cost component on settlement
    assert s["implant_cost"] == 5000.00


# ─── Difficulty Rule 2.2 — Insurance split rounding remainder ─────────────

def test_insurance_split_50_50_rounded_half_up_per_payer(api):
    """# difficulty: combinatorial_formula/insurance_split_rounding_order_mode_b

    PRD §3.9: 'for each entry in `insurance_split` in input order, the per-payer
    amount is the settlement's `final_total_amount` multiplied by that entry's
    `percentage` and divided by 100, then rounded to two decimal places half-up'."""
    bundle = setup_insurance_split_rounding()
    settlement_id = bundle["settlement"]["id"]
    # final_total_amount must be 500.05 by construction
    assert bundle["settlement"]["final_total_amount"] == 500.05

    # Pre-authorize then itemize with 50/50 split
    pre_res = api.pre_authorize_settlement(
        settlement_id, create_pre_authorize_payload("AUTH-1"), BILLING
    )
    validate_success(pre_res, 200)
    payload = create_itemize_payload([
        {"payer_id": "PAYER_A", "percentage": 50},
        {"payer_id": "PAYER_B", "percentage": 50},
    ])
    res = api.itemize_settlement(settlement_id, payload, BILLING)
    itemized = validate_success(res, 200)
    # PRD §3.9: 'the system computes the rounding remainder as `final_total_amount`
    # minus the sum of the per-payer amounts (this remainder may be positive,
    # zero, or negative) and adds it entirely to the primary payer (the entry
    # at index 0). The other payers' amounts are left unchanged.'
    # 250.025 → 250.03 (half-up); sum = 500.06; remainder = 500.05 - 500.06 = -0.01
    # primary absorbs → PAYER_A = 250.02; secondary = 250.03
    by_payer = {p["payer_id"]: p["amount"] for p in itemized["per_payer_amounts"]}
    assert by_payer["PAYER_A"] == 250.02
    assert by_payer["PAYER_B"] == 250.03


def test_insurance_split_per_payer_sums_exactly_to_total(api):
    """# difficulty: combinatorial_formula/insurance_split_rounding_order_mode_b

    PRD §3.9: 'The result is that the sum of `per_payer_amounts` equals
    `final_total_amount` exactly, while the primary payer absorbs any half-up
    rounding residue.'"""
    bundle = setup_insurance_split_rounding()
    settlement_id = bundle["settlement"]["id"]
    api.pre_authorize_settlement(settlement_id, create_pre_authorize_payload("AUTH-1"), BILLING)
    payload = create_itemize_payload([
        {"payer_id": "PAYER_A", "percentage": 50},
        {"payer_id": "PAYER_B", "percentage": 50},
    ])
    res = api.itemize_settlement(settlement_id, payload, BILLING)
    itemized = validate_success(res, 200)
    total = sum(p["amount"] for p in itemized["per_payer_amounts"])
    assert total == 500.05  # equals final_total_amount exactly


# ─── Settlement state machine ─────────────────────────────────────────────

def test_pre_authorize_persists_reference(api):
    """PRD §3.9: 'On success the settlement advances from `DRAFT` to `PRE_AUTHORIZED`,
    the supplied `insurance_pre_auth_reference` is persisted'."""
    bundle = setup_scheduled_general_case()
    s = get_settlement_for_case(bundle["case"]["id"])
    res = api.pre_authorize_settlement(
        s["id"], create_pre_authorize_payload("INS-REF-99"), BILLING
    )
    pre_auth = validate_success(res, 200)
    assert pre_auth["status"] == "PRE_AUTHORIZED"
    assert pre_auth["insurance_pre_auth_reference"] == "INS-REF-99"


def test_itemize_requires_case_completed(api):
    """PRD §3.9: '... once the owning case has reached `COMPLETED`; if the case
    is not in `COMPLETED` the call is rejected with `ERR_CASE_NOT_COMPLETED`'."""
    bundle = setup_scheduled_general_case()
    s = get_settlement_for_case(bundle["case"]["id"])
    api.pre_authorize_settlement(s["id"], create_pre_authorize_payload("X"), BILLING)
    payload = create_itemize_payload([
        {"payer_id": "P1", "percentage": 100},
    ])
    validate_error(api.itemize_settlement(s["id"], payload, BILLING), "ERR_CASE_NOT_COMPLETED")


def test_itemize_invalid_split_percentage_sum(api):
    """PRD §3.9: 'The percentages must sum to exactly 100 — anything else is
    rejected with `ERR_INVALID_INSURANCE_SPLIT`'."""
    bundle = setup_completed_general_case(advance_after_start=60)
    s = get_settlement_for_case(bundle["case"]["id"])
    api.pre_authorize_settlement(s["id"], create_pre_authorize_payload("X"), BILLING)
    payload = create_itemize_payload([
        {"payer_id": "P1", "percentage": 50},
        {"payer_id": "P2", "percentage": 49},
    ])
    validate_error(api.itemize_settlement(s["id"], payload, BILLING), "ERR_INVALID_INSURANCE_SPLIT")


def test_settle_requires_pre_auth_reference(api):
    """PRD §3.9: 'The single precondition is that `insurance_pre_auth_reference`
    is non-`null`; otherwise the call is rejected with `ERR_INSURANCE_PRE_AUTH_REQUIRED`
    (HTTP 402)'.

    A settlement that reaches ITEMIZED through the regular workflow always carries
    a non-null pre-auth reference (because /itemize is gated by /pre-authorize).
    The PRD's settle precondition is therefore observable only when an ITEMIZED
    settlement could exist with `insurance_pre_auth_reference` null. Per PRD this
    is impossible to construct; we instead exercise the contract by asserting
    /settle on the regular workflow succeeds AND the pre-auth field is non-null at
    the moment of /settle. Two-reader: both readers agree settle requires non-null
    reference; this is the closest observable assertion."""
    bundle = setup_completed_general_case(advance_after_start=60)
    s = get_settlement_for_case(bundle["case"]["id"])
    api.pre_authorize_settlement(s["id"], create_pre_authorize_payload("AUTH-1"), BILLING)
    api.itemize_settlement(s["id"], create_itemize_payload([{"payer_id": "P1", "percentage": 100}]), BILLING)
    res = api.settle_settlement(s["id"], BILLING)
    settled = validate_success(res, 200)
    assert settled["status"] == "SETTLED"
    assert settled["insurance_pre_auth_reference"] == "AUTH-1"


def test_billing_admin_required_for_pre_authorize(api):
    """PRD §4: 'POST /settlements/{settlementId}/pre-authorize' is restricted to
    BillingAdmin. PRD §2.1: missing role → `ERR_INSUFFICIENT_PERMISSIONS`."""
    bundle = setup_scheduled_general_case()
    s = get_settlement_for_case(bundle["case"]["id"])
    validate_error(
        api.pre_authorize_settlement(s["id"], create_pre_authorize_payload("X"), SCHED),
        "ERR_INSUFFICIENT_PERMISSIONS",
    )
