"""Eligibility, order-of-selection slots, waitlist promotion.

Difficulty queue (§1.8): compensating_invariant / slots_conserved_reserve_then_close.
Corner queue (§1.9): state_machines + validations for eligibility and promote-next.
"""
from test_helpers import (
    validate_success, validate_error,
    create_counselor, create_category, make_counselor_headers, create_case_payload,
    bootstrap_actors, create_referral, advance_to_application, make_eligible, set_clock,
    TEST_USERS,
)

VRADMIN = TEST_USERS["vradmin_headers"]


def _eligible_case(ctx, **case_overrides):
    case_id = create_referral(ctx, **case_overrides)
    advance_to_application(ctx, case_id)
    make_eligible(ctx, case_id)
    return case_id


# ─── Difficulty: slots conserved (reserve then close) ─────────────────

def test_slots_conserved_after_close_returns_capacity(api):
    """PRD §3.9: "A `PLAN_DEVELOPMENT` case releases its slot."
    PRD §2.9: "Reserving a slot increments `slots_used` and decrements
    `available_slots`; releasing one does the reverse; either change increments the
    category's `version`."

    Design: Difficulty/compensating_invariant/slots_conserved_reserve_then_close
    """
    ctx = bootstrap_actors(provider=False, category_overrides={"slot_capacity": 2})
    case_id = _eligible_case(ctx)
    reserved = validate_success(api.get_priority_category(ctx["category_id"], VRADMIN), 200)
    assert reserved["slots_used"] == 1
    assert reserved["available_slots"] == 1

    closed = validate_success(api.close_case(case_id, {"closure_reason": "relocated out of state"},
                                             ctx["counselor_headers"]), 200)
    assert closed["status"] == "CLOSED_OTHER"
    category = validate_success(api.get_priority_category(ctx["category_id"], VRADMIN), 200)
    assert category["slots_used"] == 0
    assert category["available_slots"] == 2


def test_slots_conservation_invariant_holds_throughout(api):
    """PRD §2.9: "A category's `available_slots` is its `slot_capacity` minus
    `slots_used`, and is never allowed to fall below zero".

    Design: Difficulty/compensating_invariant/slots_conserved_reserve_then_close
    """
    ctx = bootstrap_actors(provider=False, category_overrides={"slot_capacity": 2})
    case_id = _eligible_case(ctx)
    reserved = validate_success(api.get_priority_category(ctx["category_id"], VRADMIN), 200)
    assert reserved["slot_capacity"] == reserved["available_slots"] + reserved["slots_used"] == 2

    api.close_case(case_id, {"closure_reason": "relocated"}, ctx["counselor_headers"])
    after = validate_success(api.get_priority_category(ctx["category_id"], VRADMIN), 200)
    assert after["slot_capacity"] == after["available_slots"] + after["slots_used"] == 2


# ─── Corner: eligibility outcomes ─────────────────────────────────────

def test_eligibility_no_matching_category_not_found(api):
    """PRD §3.2: "An `ELIGIBLE` decision first locates the priority category whose
    `rank` matches the rank of the reported `disability_significance` (`MSD`→1,
    `SD`→2, `NSD`→3); if no such category exists the determination is rejected with
    `ERR_CATEGORY_NOT_FOUND`."

    Design: Corner/validations/eligibility_no_matching_category_not_found
    """
    counselor = create_counselor()
    headers = make_counselor_headers(counselor["id"])
    case = validate_success(api.create_case(create_case_payload(), headers), 201)
    api.record_application(case["id"], headers)
    res = api.record_eligibility(case["id"], {"decision": "ELIGIBLE", "disability_significance": "MSD"}, headers)
    validate_error(res, "ERR_CATEGORY_NOT_FOUND")


def test_eligibility_closed_category_waitlists_case(api):
    """PRD §3.2: "If instead the category is `CLOSED` or has zero available slots,
    the case moves to `WAITLISTED`, its `waitlisted_at` is stamped with the current
    logical clock, and no slot is reserved."
    PRD §2.4: created_at "ISO 8601 UTC timestamp with three fractional digits".

    Design: Corner/state_machines/eligibility_closed_category_waitlists_case
    """
    set_clock("2026-05-02T00:00:00Z")
    counselor = create_counselor()
    headers = make_counselor_headers(counselor["id"])
    category = create_category(rank=1, label="MSD", slot_capacity=5, status="CLOSED")
    case = validate_success(api.create_case(create_case_payload(), headers), 201)
    api.record_application(case["id"], headers)
    waitlisted = validate_success(
        api.record_eligibility(case["id"], {"decision": "ELIGIBLE", "disability_significance": "MSD"}, headers), 200)
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["priority_category_id"] == category["id"]
    assert waitlisted["waitlisted_at"] == "2026-05-02T00:00:00.000Z"
    cat = validate_success(api.get_priority_category(category["id"], VRADMIN), 200)
    assert cat["slots_used"] == 0


def test_application_on_terminal_ineligible_invalid_state(api):
    """PRD §3.2: "An `INELIGIBLE` decision records the `disability_significance` and
    moves the case to the terminal `INELIGIBLE` state."
    PRD §3.2: "Recording the signed application advances the case from `REFERRED` to
    `APPLICATION` and increments the case's `version`."

    Design: Corner/state_machines/application_on_terminal_ineligible_invalid_state
    """
    counselor = create_counselor()
    headers = make_counselor_headers(counselor["id"])
    case = validate_success(api.create_case(create_case_payload(), headers), 201)
    api.record_application(case["id"], headers)
    ineligible = validate_success(
        api.record_eligibility(case["id"], {"decision": "INELIGIBLE", "disability_significance": "NSD"}, headers), 200)
    assert ineligible["status"] == "INELIGIBLE"
    res = api.record_application(case["id"], headers)
    validate_error(res, "ERR_INVALID_STATE")
    still = validate_success(api.get_case(case["id"], VRADMIN), 200)
    assert still["status"] == "INELIGIBLE"


# ─── Corner: promote-next ─────────────────────────────────────────────

def test_promote_next_promotes_waitlisted_case(api):
    """PRD §3.3: "Among the category's waitlisted cases, it chooses the one with the
    earliest `waitlisted_at`, breaking ties by the earliest `created_at` (never by
    `id`). The chosen case moves from `WAITLISTED` to `PLAN_DEVELOPMENT`, its
    `waitlisted_at` is cleared, a slot is reserved (the category's `slots_used` rises
    by one, `available_slots` falls by one, `version` increments), and the case's
    `version` increments."

    Design: Corner/state_machines/promote_next_promotes_waitlisted_case
    """
    ctx = bootstrap_actors(provider=False, category_overrides={"slot_capacity": 1})
    case_a = _eligible_case(ctx, consumer_full_name="A Ray")           # reserves the only slot
    case_b_id = create_referral(ctx, consumer_full_name="B Ray")
    advance_to_application(ctx, case_b_id)
    make_eligible(ctx, case_b_id)                                       # no slot -> WAITLISTED
    api.close_case(case_a, {"closure_reason": "moved"}, ctx["counselor_headers"])  # frees the slot

    promoted = validate_success(api.promote_next(ctx["category_id"], VRADMIN), 200)
    assert promoted["id"] == case_b_id
    assert promoted["status"] == "PLAN_DEVELOPMENT"
    category = validate_success(api.get_priority_category(ctx["category_id"], VRADMIN), 200)
    assert category["slots_used"] == 1
    assert category["available_slots"] == 0


def test_promote_next_no_waitlisted_case(api):
    """PRD §3.3: "it then confirms at least one `WAITLISTED` case exists in the
    category, rejecting with `ERR_NO_WAITLISTED_CASE` if the pool is empty."

    Design: Corner/validations/promote_next_no_waitlisted_case
    """
    category = create_category(rank=1, label="MSD", slot_capacity=5)
    res = api.promote_next(category["id"], VRADMIN)
    validate_error(res, "ERR_NO_WAITLISTED_CASE")


def test_promote_next_no_slot_available(api):
    """PRD §3.3: "The selector first confirms the category has an available slot,
    rejecting with `ERR_NO_SLOT_AVAILABLE` if none remains".

    Design: Corner/validations/promote_next_no_slot_available
    """
    ctx = bootstrap_actors(provider=False, category_overrides={"slot_capacity": 1})
    _eligible_case(ctx, consumer_full_name="A Ray")                    # occupies the slot
    case_b_id = create_referral(ctx, consumer_full_name="B Ray")
    advance_to_application(ctx, case_b_id)
    make_eligible(ctx, case_b_id)                                      # WAITLISTED, slot still occupied
    res = api.promote_next(ctx["category_id"], VRADMIN)
    validate_error(res, "ERR_NO_SLOT_AVAILABLE")
