"""Labor-cost calculation: overtime threshold, weekend surcharge, and the
compensating labor-hours invariant on session void.
"""
from test_helpers import (
    validate_success,
    new_active_project, new_session, start_session, add_completed_session,
    make_organizer_headers, TEST_USERS,
)

OM = TEST_USERS["operations_manager_headers"]


def _in_progress_session(hourly_rate_cents, start, end):
    client, organizer, project = new_active_project(hourly_rate_cents=hourly_rate_cents,
                                                    scope_rooms=["Room"])
    session = new_session(project["id"], organizer["id"], start, end)
    start_session(session["id"], organizer["id"])
    return organizer, project, session


# ── Difficulty: overtime threshold is strict > 8h ─────────────────────────────

def test_overtime_not_triggered_at_exactly_8_hours(api):
    """PRD §3.4: "The is_overtime flag is true only when logged_hours is strictly
    greater than 8 hours."
    PRD §3.4: "The regular charge is the regular hours multiplied by the hourly rate,
    rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/overtime_threshold_strict_at_8h
    """
    organizer, project, session = _in_progress_session(6000,
                                                       "2026-03-02T09:00:00Z", "2026-03-02T17:00:00Z")
    res = api.complete_session(session["id"], {"logged_hours": 8.0},
                               make_organizer_headers(organizer["id"]))
    completed = validate_success(res, 200)
    assert completed["is_overtime"] is False
    assert completed["labor_cost_cents"] == 48000


def test_overtime_triggered_above_8_hours(api):
    """PRD §3.4: "The is_overtime flag is true only when logged_hours is strictly
    greater than 8 hours."
    PRD §3.4: "The overtime charge is the overtime hours multiplied by the hourly rate
    and then by an overtime multiplier of 1.5, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/overtime_threshold_strict_at_8h
    """
    organizer, project, session = _in_progress_session(6000,
                                                       "2026-03-02T09:00:00Z", "2026-03-02T19:00:00Z")
    res = api.complete_session(session["id"], {"logged_hours": 9.0},
                               make_organizer_headers(organizer["id"]))
    completed = validate_success(res, 200)
    assert completed["is_overtime"] is True
    # 8h regular * 6000 = 48000; 1h overtime * 6000 * 1.5 = 9000; sum = 57000 (weekday).
    assert completed["labor_cost_cents"] == 57000


# ── Corner: weekend surcharge ─────────────────────────────────────────────────

def test_weekend_surcharge_applied_on_completion(api):
    """PRD §3.4: "a weekend surcharge is applied when the session's scheduled_start,
    evaluated in UTC, falls on a Saturday or Sunday: in that case the final
    labor_cost_cents is the subtotal multiplied by 1.20 (a 20% surcharge), rounded
    half up; on a weekday, labor_cost_cents equals the subtotal with no surcharge."

    Design: Corner/state_machines/weekend_surcharge_applied_on_completion
    """
    organizer, project, session = _in_progress_session(6000,
                                                       "2026-03-07T09:00:00Z", "2026-03-07T14:00:00Z")
    res = api.complete_session(session["id"], {"logged_hours": 5},
                               make_organizer_headers(organizer["id"]))
    completed = validate_success(res, 200)
    # Saturday 5h * 6000 = 30000 subtotal; * 1.20 = 36000.
    assert completed["labor_cost_cents"] == 36000
    assert completed["is_overtime"] is False


# ── Difficulty: compensating labor-hours invariant on void ────────────────────

def test_accrued_labor_hours_returns_to_zero_after_void(api):
    """PRD §3.4: "When the session being cancelled was COMPLETED, the cancellation is
    compensating: the system subtracts that session's logged_hours back out of the
    project's accrued_labor_hours and resets the session's labor_cost_cents to 0,
    preserving the invariant that accrued_labor_hours equals the sum of logged_hours
    over the project's remaining COMPLETED sessions."

    Design: Difficulty/compensating_invariant/labor_hours_conserved_on_session_void
    """
    client, organizer, project = new_active_project(hourly_rate_cents=6000, scope_rooms=["Room"])
    session = add_completed_session(project["id"], organizer["id"], 10,
                                    "2026-03-02T09:00:00Z", "2026-03-02T19:00:00Z")
    before = validate_success(api.get_project(project["id"], OM), 200)
    assert before["accrued_labor_hours"] == 10

    voided = validate_success(api.patch_session(
        session["id"], {"status": "CANCELLED"}, make_organizer_headers(organizer["id"])), 200)
    assert voided["status"] == "CANCELLED"

    after = validate_success(api.get_project(project["id"], OM), 200)
    assert after["accrued_labor_hours"] == 0


def test_accrued_labor_hours_equals_remaining_completed_after_void(api):
    """PRD §3.4: "When the session being cancelled was COMPLETED, the cancellation is
    compensating: the system subtracts that session's logged_hours back out of the
    project's accrued_labor_hours and resets the session's labor_cost_cents to 0,
    preserving the invariant that accrued_labor_hours equals the sum of logged_hours
    over the project's remaining COMPLETED sessions."

    Design: Difficulty/compensating_invariant/labor_hours_conserved_on_session_void
    """
    client, organizer, project = new_active_project(hourly_rate_cents=6000, scope_rooms=["Room"])
    big = add_completed_session(project["id"], organizer["id"], 10,
                                "2026-03-02T09:00:00Z", "2026-03-02T19:00:00Z")
    add_completed_session(project["id"], organizer["id"], 3,
                          "2026-03-09T09:00:00Z", "2026-03-09T12:00:00Z")
    before = validate_success(api.get_project(project["id"], OM), 200)
    assert before["accrued_labor_hours"] == 13

    validate_success(api.patch_session(
        big["id"], {"status": "CANCELLED"}, make_organizer_headers(organizer["id"])), 200)

    after = validate_success(api.get_project(project["id"], OM), 200)
    assert after["accrued_labor_hours"] == 3
