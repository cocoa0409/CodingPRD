"""Closure cascades: case close unwinds authorizations/payments/provider ledger, and
verified stability closes the case as rehabilitated and releases its slot.

Difficulty queue (§1.8): transitive_cascade (both instances);
cross_entity_state_dependency / case_rehab_close_requires_placement_stable.
"""
from test_helpers import (
    validate_success,
    setup_services_active_case, setup_stabilizing_placement,
    request_and_approve_authorization, create_pending_payment, set_clock,
    TEST_USERS,
)

VRADMIN = TEST_USERS["vradmin_headers"]


# ─── Difficulty: depth-4 close cascade ───────────────────────────────

def _services_active_with_pending_payment(api):
    ctx = setup_services_active_case(monthly_income_cents=150000, budget_allocated_cents=1000000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=300000, comparable_benefit_cents=0)
    payment = create_pending_payment(approved["id"], 120000)
    return ctx, approved, payment


def test_case_close_cascades_states(api):
    """PRD §3.9: "A `SERVICES_ACTIVE` case releases its slot, cancels every service
    authorization in `REQUESTED` or `APPROVED` (each cancellation releasing committed
    funds and voiding its `PENDING` payments), and closes any IPE in `DRAFT`,
    `SUBMITTED`, `APPROVED`, or `AMENDING`."

    Design: Difficulty/transitive_cascade/case_close_cancel_auth_void_payment_decrement_provider
    """
    ctx, approved, payment = _services_active_with_pending_payment(api)
    closed = validate_success(api.close_case(ctx["case_id"], {"closure_reason": "consumer withdrew"},
                                             ctx["counselor_headers"]), 200)
    assert closed["status"] == "CLOSED_OTHER"
    auth = validate_success(api.get_authorization(approved["id"], VRADMIN), 200)
    assert auth["status"] == "CANCELLED"
    pay = validate_success(api.get_payment(payment["id"], VRADMIN), 200)
    assert pay["status"] == "VOIDED"


def test_case_close_cascade_unwinds_ledgers(api):
    """PRD §3.6: "Every `PENDING` payment on the cancelled authorization is then
    voided, and each such void in turn decrements the provider's
    `pending_disbursement_cents` and increments the provider's `version`."

    Design: Difficulty/transitive_cascade/case_close_cancel_auth_void_payment_decrement_provider
    """
    ctx, approved, payment = _services_active_with_pending_payment(api)
    api.close_case(ctx["case_id"], {"closure_reason": "consumer withdrew"}, ctx["counselor_headers"])
    provider = validate_success(api.get_provider(ctx["provider_id"], VRADMIN), 200)
    assert provider["pending_disbursement_cents"] == 0
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["funds_committed_cents"] == 0


# ─── Difficulty: STABLE closes case rehabilitated + releases slot ────

def test_verify_stability_closes_case_and_releases_slot(api):
    """PRD §3.8: "That closure releases the case's slot (the category's `slots_used`
    falls by one, `available_slots` rises by one, `version` increments)".

    Design: Difficulty/transitive_cascade/placement_stable_closes_case_releases_slot
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z",
                                      slot_capacity=5)
    set_clock("2026-07-30T00:00:00Z")
    placement = validate_success(api.verify_stability(ctx["placement_id"], ctx["counselor_headers"]), 200)
    assert placement["status"] == "STABLE"
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["status"] == "CLOSED_REHABILITATED"


def test_verify_stability_slot_counts_after_release(api):
    """PRD §3.8: "That closure releases the case's slot (the category's `slots_used`
    falls by one, `available_slots` rises by one, `version` increments)".

    Design: Difficulty/transitive_cascade/placement_stable_closes_case_releases_slot
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z",
                                      slot_capacity=5)
    set_clock("2026-07-30T00:00:00Z")
    api.verify_stability(ctx["placement_id"], ctx["counselor_headers"])
    category = validate_success(api.get_priority_category(ctx["category_id"], VRADMIN), 200)
    assert category["slots_used"] == 0
    assert category["available_slots"] == 5


# ─── Difficulty: case reaches CLOSED_REHABILITATED only via STABLE ──

def test_case_rehab_close_requires_placement_stable(api):
    """PRD §3.8: "Reaching `STABLE` closes the case as a successful outcome: the case
    moves from `EMPLOYED` to `CLOSED_REHABILITATED` with `closure_type` set to
    `REHABILITATED`."

    Design: Difficulty/cross_entity_state_dependency/case_rehab_close_requires_placement_stable
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z",
                                      slot_capacity=5)
    # Before verification (day 90 not yet reached), the case is still EMPLOYED.
    before = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert before["status"] == "EMPLOYED"
    set_clock("2026-07-30T00:00:00Z")
    validate_success(api.verify_stability(ctx["placement_id"], ctx["counselor_headers"]), 200)
    after = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert after["status"] == "CLOSED_REHABILITATED"


def test_case_rehab_closure_type_set_to_rehabilitated(api):
    """PRD §3.8: "the case moves from `EMPLOYED` to `CLOSED_REHABILITATED` with
    `closure_type` set to `REHABILITATED`."

    Design: Difficulty/cross_entity_state_dependency/case_rehab_close_requires_placement_stable
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z",
                                      slot_capacity=5)
    set_clock("2026-07-30T00:00:00Z")
    validate_success(api.verify_stability(ctx["placement_id"], ctx["counselor_headers"]), 200)
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["closure_type"] == "REHABILITATED"
