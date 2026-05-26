"""Optimistic-concurrency on /pairings/{id}/award and rolling-window expiry
of derived crew totals on clock advance.
"""
from test_helpers import (
    validate_error,
    set_clock,
    setup_clean_world,
    setup_completed_pairing_for_crew,
    create_crew_member,
    create_pairing,
    add_revenue_leg,
    open_bidding,
    submit_bid,
    get_pairing,
    get_crew_member,
    make_crew_member_headers,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# OCC: stale expected_pairing_version on /award
# ---------------------------------------------------------------------

def test_award_with_stale_expected_pairing_version_rejected(api, planner_headers):
    """PRD §2.10: "If that value does not equal the Pairing's current `version`,
    the award is rejected with `ERR_STALE_VERSION` and HTTP status 412. The
    most common cause is that the bidding window auto-closed and bumped
    `version` between the planner's read and write".
    PRD §3.1: "the request body must carry `expected_pairing_version` matching
    the Pairing's current `version`, and a mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/err_stale_version_on_award
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm = create_crew_member(employee_code="AB0600", seniority_number=600)
    pairing = create_pairing(pairing_code="P-2026-600")
    add_revenue_leg(pairing["id"])
    p_after_open = api.open_pairing_bidding(pairing["id"], planner_headers)
    from test_helpers import validate_success
    p_after_open_data = validate_success(p_after_open, 200)
    stale_version = p_after_open_data["version"]
    submit_bid(pairing["id"], cm, requested_seat="CAPTAIN")
    # Advance clock past bidding_close → auto-cascade BID_OPEN → BID_CLOSED bumps version.
    set_clock("2026-06-01T12:00:01Z")
    # Use the stale version captured before the auto-close.
    res = api.award_pairing(
        pairing["id"],
        {"expected_pairing_version": stale_version},
        planner_headers,
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ---------------------------------------------------------------------
# Derived field: total_duty_minutes_7d falls outside trailing 168h window
# ---------------------------------------------------------------------

def test_total_duty_minutes_7d_drops_when_clock_passes_window(api, planner_headers):
    """PRD §2.6: "Each `CrewMember` whose assignments have completed within
    the new trailing-seven-day window has their `total_flight_minutes_7d` and
    `total_duty_minutes_7d` re-evaluated by the rolling-duty calculation".
    PRD §2.7: "The **rolling 7-day window** for a given `CrewMember` spans
    from 168 hours before `current_utc` up to and including `current_utc`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_total_duty_minutes_7d_window_expiry
    """
    crew_after, pairing_after, _a = setup_completed_pairing_for_crew(
        employee_code_suffix="0800", seniority_number=800,
    )
    assert crew_after["total_duty_minutes_7d"] == pairing_after["total_duty_minutes"], (
        f"crew.total_duty_minutes_7d must equal completed Pairing.total_duty_minutes"
    )
    # Advance clock more than 168h past the actual_duty_end_utc; the prior
    # completion drops out of the trailing 7-day window.
    set_clock("2026-06-09T11:00:00Z")
    crew_after_advance = get_crew_member(crew_after["id"])
    assert crew_after_advance["total_duty_minutes_7d"] == 0, (
        f"crew.total_duty_minutes_7d must drop to 0 once the only COMPLETED "
        f"Assignment falls outside the trailing 168h window, got "
        f"{crew_after_advance['total_duty_minutes_7d']}"
    )
