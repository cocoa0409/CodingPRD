"""Member's three parallel axes, the delinquency ladder, and contract progression.

Difficulty design index:
  non_linear_state_machine / member_parallel_axes_dues_advances_independently_of_membership
  boundary_precision_check / delinquency_exactly_15_days_flips_to_delinquent
  cross_entity_state_dependency / booking_create_gated_by_member_dues_axis
Corner design index:
  state_machines / contract_advances_cooling_off_to_in_term_on_sweep
  calculations / delinquency_14_days_still_past_due
  calculations / paying_overdue_invoice_clears_delinquency_to_current
  cross_cutting_complexity_layers / rate_threshold_delinquent_to_suspended_at_30_days_boundary
"""
from test_helpers import (
    validate_success, validate_error,
    setup_active_member, setup_past_due_member,
    register_member, pay_invoice, create_plan, create_location,
    set_clock, run_sweep, post_invoice, get_member, create_session,
    PLAN_PLUS,
    ApiErrorId, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ===========================================================================
# non_linear_state_machine / member_parallel_axes_dues_advances_independently
# ===========================================================================
def test_frozen_member_becomes_delinquent_independently(api):
    """PRD §2.5: "This axis is driven entirely by elapsed time since an overdue invoice and
    moves independently of the lifecycle axis, so a member can be ACTIVE on the lifecycle axis
    while SUSPENDED on the dues axis."
    PRD §3.4: "when at least 15 whole days have elapsed the member becomes DELINQUENT"

    Design: Difficulty/non_linear_state_machine/member_parallel_axes_dues_advances_independently_of_membership
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS, clock="2026-06-10T00:00:00Z")
    member = setup["member"]
    post_invoice(member["id"], period_start="2026-06-20T00:00:00Z",
                 period_end="2026-07-20T00:00:00Z", due_date="2026-06-20T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    validate_success(api.freeze_member(member["id"], {"freeze_days": 10}, STAFF), 200)
    set_clock("2026-07-06T00:00:00Z")  # 16 days past 2026-06-20 due date
    run_sweep()
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["membership_status"] == "FROZEN", "lifecycle axis untouched by the dues sweep"
    assert data["dues_status"] == "DELINQUENT", "dues axis advanced independently"


def test_freeze_does_not_silently_change_dues_axis(api):
    """PRD §2.5: "any operation that changes one axis must not silently change another except
    where this document explicitly states a cross-axis cascade."

    Design: Difficulty/non_linear_state_machine/member_parallel_axes_dues_advances_independently_of_membership
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS, clock="2026-06-10T00:00:00Z")
    member = setup["member"]
    post_invoice(member["id"], period_start="2026-06-20T00:00:00Z",
                 period_end="2026-07-20T00:00:00Z", due_date="2026-06-20T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    data = validate_success(api.freeze_member(member["id"], {"freeze_days": 10}, STAFF), 200)
    # Clock 2026-06-15 has not yet passed the 2026-06-20 due date, so dues stays CURRENT.
    assert data["membership_status"] == "FROZEN"
    assert data["dues_status"] == "CURRENT", "freeze must not touch the dues axis"


# ===========================================================================
# boundary_precision_check / delinquency_exactly_15_days_flips_to_delinquent
# ===========================================================================
def test_delinquency_at_exactly_15_days_flips_to_delinquent(api):
    """PRD §3.4: "exactly 15 is DELINQUENT"
    PRD §3.4: "when the sweep finds such a member it sets dues_status to PAST_DUE and stamps
    past_due_since with the due date of that oldest open invoice."

    Design: Difficulty/boundary_precision_check/delinquency_exactly_15_days_flips_to_delinquent
    """
    setup = setup_past_due_member(plan_shape=PLAN_PLUS)  # past_due_since 2026-06-20, swept 2026-06-21
    member = setup["member"]
    assert member["dues_status"] == "PAST_DUE"
    set_clock("2026-07-05T00:00:00Z")  # exactly 15 whole days after 2026-06-20
    run_sweep()
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["dues_status"] == "DELINQUENT"
    assert data["past_due_since"] == "2026-06-20T00:00:00.000Z", (
        f"past_due_since should be the oldest OPEN due_date, got {data['past_due_since']}"
    )


def test_delinquency_at_29_days_still_delinquent(api):
    """PRD §3.4: "29 is still DELINQUENT"

    Design: Difficulty/boundary_precision_check/delinquency_exactly_15_days_flips_to_delinquent
    """
    setup = setup_past_due_member(plan_shape=PLAN_PLUS)  # past_due_since 2026-06-20
    member = setup["member"]
    set_clock("2026-07-19T00:00:00Z")  # 29 whole days after 2026-06-20 (one below 30)
    run_sweep()
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["dues_status"] == "DELINQUENT", "29 days is below the 30-day SUSPENDED boundary"


def test_delinquency_at_14_days_still_past_due(api):
    """PRD §3.4: "14 whole days elapsed is still PAST_DUE"

    Design: Corner/calculations/delinquency_14_days_still_past_due
    """
    setup = setup_past_due_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    set_clock("2026-07-04T00:00:00Z")  # 14 whole days after 2026-06-20
    run_sweep()
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["dues_status"] == "PAST_DUE", "14 days is below the 15-day boundary"


# ===========================================================================
# cross_cutting / rate_threshold_delinquent_to_suspended_at_30_days_boundary
# ===========================================================================
def test_delinquency_at_exactly_30_days_flips_to_suspended(api):
    """PRD §3.4: "exactly 30 is SUSPENDED."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_delinquent_to_suspended_at_30_days_boundary
    """
    setup = setup_past_due_member(plan_shape=PLAN_PLUS)  # due 2026-06-20, swept 2026-06-21
    member = setup["member"]
    set_clock("2026-07-20T00:00:00Z")  # exactly 30 whole days after 2026-06-20
    run_sweep()
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["dues_status"] == "SUSPENDED"


# ===========================================================================
# calculations / paying_overdue_invoice_clears_delinquency_to_current
# ===========================================================================
def test_paying_overdue_invoice_clears_to_current(api):
    """PRD §3.4: "Paying an invoice such that the member then has zero `OPEN` invoices with a
    `due_date` before the current clock resets `dues_status` to `CURRENT` and sets
    `past_due_since` back to null, incrementing the member's `version`."

    Design: Corner/calculations/paying_overdue_invoice_clears_delinquency_to_current
    """
    setup = setup_past_due_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    overdue = setup["overdue_invoice"]
    data_inv = validate_success(api.pay_dues_invoice(overdue["id"], STAFF), 200)
    assert data_inv["status"] == "PAID"
    member_data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert member_data["dues_status"] == "CURRENT"
    assert member_data["past_due_since"] is None


# ===========================================================================
# cross_entity_state_dependency / booking_create_gated_by_member_dues_axis
# ===========================================================================
def test_suspended_member_cannot_book_even_with_free_seats(api):
    """PRD §3.5: "booking is permitted only while the member's membership_status is ACTIVE and
    their dues_status is not SUSPENDED; otherwise the request is rejected with
    ERR_MEMBER_NOT_BOOKABLE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/booking_create_gated_by_member_dues_axis
    """
    from test_helpers import setup_suspended_member
    setup = setup_suspended_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    assert member["dues_status"] == "SUSPENDED"
    session = create_session(setup["location"]["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-08-05T09:00:00Z", ends_at="2026-08-05T10:00:00Z")
    resp = api.create_booking(
        {"session_id": session["id"], "member_id": member["id"],
         "expected_session_version": session["version"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_BOOKABLE.value)


def test_suspended_member_dues_status_reported(api):
    """PRD §3.4: "when at least 30 whole days have elapsed the member becomes SUSPENDED."
    PRD §2.5: "a suspended member's membership_status is untouched by the sweep."

    Design: Difficulty/cross_entity_state_dependency/booking_create_gated_by_member_dues_axis
    """
    from test_helpers import setup_suspended_member
    setup = setup_suspended_member(plan_shape=PLAN_PLUS)
    data = validate_success(api.get_member(setup["member"]["id"], STAFF), 200)
    assert data["dues_status"] == "SUSPENDED"
    assert data["membership_status"] == "ACTIVE", "suspension does not change the lifecycle axis"


# ===========================================================================
# state_machines / contract_advances_cooling_off_to_in_term_on_sweep
# ===========================================================================
def test_contract_advances_cooling_off_to_in_term(api):
    """PRD §3.4: "While contract_status is IN_COOLING_OFF, the first sweep that observes the
    current clock strictly past cooling_off_ends_at moves it to IN_TERM."

    Design: Corner/state_machines/contract_advances_cooling_off_to_in_term_on_sweep
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location()
    member, _ = register_member(plan["id"], location["id"], clock="2026-06-10T00:00:00Z")
    # cooling_off_ends_at = 2026-06-17; advance past it.
    set_clock("2026-06-20T00:00:00Z")
    run_sweep()
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["contract_status"] == "IN_TERM"
