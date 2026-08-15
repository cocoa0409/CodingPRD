"""Assignment cancellation economics and the no-show cascade: budget
commit/release conservation across accept and compensating cancel, and the
four atomic side effects of reporting NO_SHOW."""
from test_helpers import (
    accepted_assignment_ctx,
    get_absence,
    get_school,
    get_substitute,
    make_coordinator_headers,
    make_substitute_headers,
    report_outcome,
    set_logical_clock,
    validate_paginated,
    validate_success,
)


def _budget_ctx():
    """School budget 200000; sub rate 20000; absence Mon 2026-08-03..Tue
    2026-08-04 (2 days at premium 1.00 -> provisional 40000), ACCEPTED."""
    return accepted_assignment_ctx(
        start_date="2026-08-03", end_date="2026-08-04", budget=200_000
    )


def test_budget_commit_moves_available_to_committed(api):
    """PRD 2.9: "`coverage_budget_committed_cents` is the provisional reserve:
    the sum of `provisional_pay_cents` over the school's assignments currently
    in `ACCEPTED`, `WORKED`, or `VERIFIED` status, initialized to zero."
    PRD 3.4: "A successful accept moves the offer to `ACCEPTED`, the absence
    from `DISPATCHING` to `ASSIGNED`, cancels every other `OFFERED` assignment
    on that absence with `cancel_reason` `ABSENCE_CANCEL` (no penalty — they
    simply lost the race), and adds the provisional pay into the school's
    committed budget."
    PRD 2.9: "The derived `coverage_budget_available_cents` is the total minus
    committed minus spent, and the system guarantees it never goes negative"

    Design: Difficulty/compensating_invariant/budget_commit_then_cancel_restores_available_exactly
    """
    ctx = _budget_ctx()
    assert ctx["assignment"]["provisional_pay_cents"] == 40000
    school = get_school(ctx["school"]["id"])
    assert school["coverage_budget_committed_cents"] == 40000
    assert school["coverage_budget_spent_cents"] == 0
    assert school["coverage_budget_available_cents"] == 160000
    assert (
        school["coverage_budget_committed_cents"]
        + school["coverage_budget_spent_cents"]
        + school["coverage_budget_available_cents"]
        == 200000
    )


def test_compensating_cancel_restores_available_exactly(api):
    """PRD 2.9: "Committed funds are released the moment the commitment
    dissolves — a cancellation of an accepted assignment, a no-show, or the
    reserve-release leg of payroll export"
    PRD 3.5: "The `cancel_reason` is pinned by the actor: `SUB_CANCEL` for a
    substitute's self-cancel, `COORDINATOR_CANCEL` for a coordinator or admin,
    and `DNR_CANCEL`, `SUSPENSION_CANCEL`, or `ABSENCE_CANCEL` for the system
    cascades — system cancels never write reliability events."
    PRD 3.5: "A substitute's self-cancel of an accepted assignment also writes
    a reliability event: `SUB_CANCEL_LATE` (−15) when the cancellation lands
    before the absence's first day with strictly less than the district's
    short-notice lead remaining, otherwise `SUB_CANCEL_EARLY` (−5)"

    Design: Difficulty/compensating_invariant/budget_commit_then_cancel_restores_available_exactly
    """
    ctx = _budget_ctx()
    set_logical_clock("2026-07-30T00:00:00Z")
    cancelled = validate_success(
        api.cancel_assignment(
            ctx["assignment"]["id"], make_substitute_headers(ctx["sub"]["id"])
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "SUB_CANCEL"

    school = get_school(ctx["school"]["id"])
    assert school["coverage_budget_committed_cents"] == 0
    assert school["coverage_budget_spent_cents"] == 0
    assert school["coverage_budget_available_cents"] == 200000, (
        "the cancel releases exactly the 40000 the accept committed"
    )

    sub = get_substitute(ctx["sub"]["id"])
    assert sub["reliability_trailing_score"] == 95, (
        "SUB_CANCEL_EARLY (-5): cancel at 2026-07-30 has 96h lead >= 24h"
    )
    assert sub["reliability_lifetime_score"] == 95


def test_no_show_full_cascade(api, district_admin_headers):
    """PRD 3.5: "Reporting `NO_SHOW` instead is the harshest event in the
    system: the provisional reserve is released from the school's committed
    budget, a `NO_SHOW` reliability event (−25) is appended and suspension
    evaluation runs, a PerformanceFlag of `flag_type` `NO_SHOW`, `severity`
    `MAJOR`, status `OPEN`, and `auto_created` true is created against the
    substitute at that school, and the absence falls back from `ASSIGNED` to
    `DISPATCHING` and re-dispatches to the next eligible candidate."

    Design: Corner/state_machines/no_show_full_cascade
    """
    ctx = accepted_assignment_ctx(start_date="2026-08-03", end_date="2026-08-03")
    assert ctx["assignment"]["provisional_pay_cents"] == 20000
    set_logical_clock("2026-08-03T13:00:00Z")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    updated = report_outcome(ctx["assignment"]["id"], "NO_SHOW", coord_headers)
    assert updated["status"] == "NO_SHOW"

    school = get_school(ctx["school"]["id"])
    assert school["coverage_budget_committed_cents"] == 0, "provisional reserve released"

    sub = get_substitute(ctx["sub"]["id"])
    assert sub["reliability_trailing_score"] == 75, "NO_SHOW event at -25"
    assert sub["reliability_lifetime_score"] == 75

    flags, meta = validate_paginated(
        api.list_substitute_flags(ctx["sub"]["id"], district_admin_headers)
    )
    assert meta["total_count"] == 1
    assert flags[0]["flag_type"] == "NO_SHOW"
    assert flags[0]["severity"] == "MAJOR"
    assert flags[0]["auto_created"] is True
    assert flags[0]["status"] == "OPEN"
    assert flags[0]["school_id"] == ctx["school"]["id"]

    absence = get_absence(ctx["absence"]["id"])
    assert absence["fill_status"] == "DISPATCHING", (
        "the absence reopened and re-dispatched; it is no longer ASSIGNED"
    )
