"""Assignment cancellation and serve preconditions, and the payroll reserve as
a conserved quantity under cancel-then-backfill."""
from test_helpers import (
    ApiErrorId,
    assert_coverage_gap,
    assign_staff,
    cancel_assignment,
    create_published_program,
    create_staff_physician,
    get_program,
    get_slot_for_date,
    list_gaps,
    set_clock,
    setup_published_with_assignment,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_cancel_assignment_twice_rejected_terminal_lockdown(api):
    """PRD §3.3: "Cancellation applies only to SCHEDULED assignments
    (`ERR_ASSIGNMENT_NOT_SCHEDULED`; an ACTIVATED assignment cannot be
    cancelled)."

    Design: Corner/state_machines/cancel_assignment_twice_rejected_terminal_lockdown
    """
    _program, _physician, slot, assignment = setup_published_with_assignment()
    cancel_assignment(assignment["id"])

    resp = api.cancel_assignment(assignment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_SCHEDULED, 409)

    gaps = list_gaps(slot_id=slot["id"])
    assert len(gaps) == 1, "the rejected second cancel must not open another gap"


def test_mark_served_before_window_end_rejected(api):
    """PRD §3.3: "A `SchedulerAdmin` marks an assignment served from SCHEDULED or
    ACTIVATED — anything else is `ERR_ASSIGNMENT_NOT_SERVABLE` — and never before
    the slot's `window_end` has arrived (`ERR_SERVE_BEFORE_WINDOW_END`)."

    Design: Corner/state_machines/mark_served_before_window_end_rejected
    """
    _program, _physician, _slot, assignment = setup_published_with_assignment()
    set_clock("2026-09-08T23:00:00Z")  # inside the window, before its end
    resp = api.mark_served(assignment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SERVE_BEFORE_WINDOW_END, 409)

    after = validate_success(api.get_assignment(assignment["id"], ADMIN))
    assert after["status"] == "SCHEDULED"
    entries, _meta = validate_paginated(
        api.list_pay_entries(ADMIN, params={"assignment_id": assignment["id"]})
    )
    assert entries == [], "a rejected mark-served must not create a pay entry"


def test_mark_served_cancelled_assignment_returns_not_servable(api):
    """PRD §3.3: "A `SchedulerAdmin` marks an assignment served from SCHEDULED or
    ACTIVATED — anything else is `ERR_ASSIGNMENT_NOT_SERVABLE`".

    Design: Corner/errors/mark_served_cancelled_assignment_returns_not_servable
    """
    _program, _physician, _slot, assignment = setup_published_with_assignment()
    cancel_assignment(assignment["id"])
    set_clock("2026-09-09T08:00:00Z")  # past window end
    resp = api.mark_served(assignment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_SERVABLE, 409)
    entries, _meta = validate_paginated(
        api.list_pay_entries(ADMIN, params={"assignment_id": assignment["id"]})
    )
    assert entries == []


# ─── Compensating invariant: payroll reserve under cancel + backfill ──

def _setup_reserve_scenario():
    """PUBLISHED two-day program (budget 100000) with no physicians at
    generation, then two STAFF cardiologists registered."""
    program = create_published_program(
        name="Cards Reserve",
        period_start="2026-09-08",
        period_end="2026-09-09",
        payroll_budget_cents=100_000,
    )
    p1 = create_staff_physician("Dr Alvarez")
    p2 = create_staff_physician("Dr Becker")
    slot = get_slot_for_date(program["id"], "2026-09-08")
    return program, p1, p2, slot


def test_payroll_reserve_conserved_under_cancel_then_backfill(api):
    """PRD §2.7: "`payroll_reserved_cents` is the sum of `projected_pay_cents`
    over the program's assignments in SCHEDULED or ACTIVATED status, and it is
    updated on every assignment creation, cancellation, swap, and serve."
    PRD §3.3: "the assignment's projected pay is released from the reserve".

    Reserve sequence: 0 after publish, 50000 after the first assignment, 0
    after its cancel, 50000 after the backfill — create and cancel are exact
    compensating actions.

    Design: Difficulty/compensating_invariant/payroll_reserve_conserved_under_cancel_then_backfill
    """
    program, p1, p2, slot = _setup_reserve_scenario()
    assert get_program(program["id"])["payroll_reserved_cents"] == 0

    a1 = assign_staff(slot["id"], p1["id"])
    assert get_program(program["id"])["payroll_reserved_cents"] == 50000

    cancel_assignment(a1["id"])
    assert get_program(program["id"])["payroll_reserved_cents"] == 0

    assign_staff(slot["id"], p2["id"])
    assert get_program(program["id"])["payroll_reserved_cents"] == 50000


def test_cancel_gap_resolved_by_backfill_and_cancelled_assignment_stays(api):
    """PRD §3.3: "The slot returns ASSIGNED → OPEN, a CoverageGap with `reason`
    ASSIGNMENT_CANCELLED is opened"; "When the slot had an OPEN or
    REQUISITIONED coverage gap, the gap becomes RESOLVED with
    `resolved_by_assignment_id` set to the new assignment".

    Design: Difficulty/compensating_invariant/payroll_reserve_conserved_under_cancel_then_backfill
    """
    program, p1, p2, slot = _setup_reserve_scenario()
    a1 = assign_staff(slot["id"], p1["id"])
    cancel_assignment(a1["id"])

    gaps = list_gaps(program["id"], slot_id=slot["id"])
    cancel_gaps = [g for g in gaps if g["reason"] == "ASSIGNMENT_CANCELLED"]
    assert len(cancel_gaps) == 1
    assert_coverage_gap(cancel_gaps[0])
    assert cancel_gaps[0]["status"] == "OPEN"

    a2 = assign_staff(slot["id"], p2["id"])
    gaps_after = list_gaps(program["id"], slot_id=slot["id"])
    resolved = [g for g in gaps_after if g["status"] == "RESOLVED"]
    assert len(resolved) == 1
    assert resolved[0]["resolved_by_assignment_id"] == a2["id"]

    a1_after = validate_success(api.get_assignment(a1["id"], ADMIN))
    assert a1_after["status"] == "CANCELLED", "no resurrection of the cancelled assignment"
