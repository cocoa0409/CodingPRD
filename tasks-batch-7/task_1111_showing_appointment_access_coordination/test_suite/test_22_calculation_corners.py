"""Calculation corner cases: standing thresholds, zero-terminal report, strike expiry."""
import pytest

from test_helpers import (
    api_client,
    cancel_request,
    create_confirmed_request,
    get_agent_strikes,
    make_admin_headers,
    run_sweep,
    set_clock,
    setup_vacant_auto_world,
    validate_success,
)


def test_standing_threshold_exact_20_restricted(api):
    """PRD §3.6: "An agent at 30 points or more is SUSPENDED; at 15 points or
    more but below 30, RESTRICTED; below 15, GOOD_STANDING. The boundaries are
    inclusive upward: exactly 15 points is RESTRICTED, exactly 30 is
    SUSPENDED."

    Two LATE_CANCEL strikes (2 x 10 = 20 points) yield RESTRICTED.

    Design: Corner/calculations/standing_threshold_exact_30_suspends
    """
    world = setup_vacant_auto_world()
    ba_id = world["buyer_agent"]["id"]
    for start, end in (("2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z"),
                       ("2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z")):
        req = create_confirmed_request(world["listing"]["id"], ba_id,
                                       world["seller"]["id"], start, end)
        cancel_request(req["id"], ba_id)

    agent = validate_success(api_client.get_agent(ba_id, make_admin_headers()))
    assert agent["active_strike_points"] == 20, agent
    assert agent["standing"] == "RESTRICTED", agent


def test_standing_threshold_exact_30_suspends(api):
    """PRD §3.6: "An agent at 30 points or more is SUSPENDED; ... The
    boundaries are inclusive upward: exactly 15 points is RESTRICTED, exactly
    30 is SUSPENDED."

    Three LATE_CANCEL strikes (3 x 10 = 30 points) yield SUSPENDED.

    Design: Corner/calculations/standing_threshold_exact_30_suspends
    """
    world = setup_vacant_auto_world()
    ba_id = world["buyer_agent"]["id"]
    for start, end in (("2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z"),
                       ("2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z")):
        req = create_confirmed_request(world["listing"]["id"], ba_id,
                                       world["seller"]["id"], start, end)
        cancel_request(req["id"], ba_id)

    req3 = create_confirmed_request(world["listing"]["id"], ba_id,
                                    world["seller"]["id"],
                                    "2026-05-01T14:00:00Z", "2026-05-01T14:30:00Z")
    cancel_request(req3["id"], ba_id)

    agent = validate_success(api_client.get_agent(ba_id, make_admin_headers()))
    assert agent["active_strike_points"] == 30, agent
    assert agent["standing"] == "SUSPENDED", agent


def test_report_final_zero_terminal_divide_by_zero(api):
    """PRD §3.8: "In FINAL mode, `completion_rate` is the completed count
    divided by the terminal total — the sum of completed, no-show, cancelled,
    expired, and declined counts — rounded half-up to 2 decimal places, and
    reported as 0.00 when the listing has no terminal requests at all." and
    "The report also carries the listing's `avg_feedback_score` per the rollup
    of §3.7, 0.0 when no feedback has been submitted."

    Design: Corner/calculations/report_final_zero_terminal_divide_by_zero
    """
    world = setup_vacant_auto_world()
    report = validate_success(api_client.get_activity_report(
        world["listing"]["id"], world["la_headers"], params={"mode": "FINAL"}))
    assert report["completion_rate"] == pytest.approx(0.00, abs=1e-9), report
    assert report["completed_count"] == 0, report
    assert report["avg_feedback_score"] == pytest.approx(0.0, abs=1e-9), report


def test_strike_expiry_deescalates_standing(api):
    """PRD §3.6: "A strike is born ACTIVE with `expires_at` set ninety days
    after its creation; the sweep moves ACTIVE strikes at or past that instant
    to EXPIRED and recomputes the agent's standing with each expiry." PRD §2.9:
    "an agent's `active_strike_points` always equals the sum of the `weight`
    values of that agent's StrikeRecords in ACTIVE status; strike creation
    raises it, while forgiveness and sweep-driven expiry lower it."

    Design: Corner/calculations/strike_expiry_deescalates_standing
    """
    world = setup_vacant_auto_world()
    ba_id = world["buyer_agent"]["id"]
    req = create_confirmed_request(world["listing"]["id"], ba_id,
                                   world["seller"]["id"],
                                   "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    cancel_request(req["id"], ba_id)  # LATE_CANCEL (10) at 2026-05-01T00:00:00Z

    strikes = get_agent_strikes(ba_id)
    assert strikes[0]["expires_at"] == "2026-07-30T00:00:00Z", strikes  # created_at + 90 days

    set_clock("2026-07-31T00:00:00Z")
    sweep = run_sweep()
    assert sweep["strikes_expired_count"] == 1, sweep

    agent = validate_success(api_client.get_agent(ba_id, make_admin_headers()))
    assert agent["active_strike_points"] == 0, agent
    assert agent["standing"] == "GOOD_STANDING", agent
