"""The two minutes-per-room readings and the quality guardrail that outranks them."""

from test_helpers import (
    DIRECTOR_HEADERS,
    PRODUCTIVITY_QUALITY_HOLD,
    SERVICE_CHECKOUT,
    assert_credits,
    assert_whole_minutes,
    build_scenario,
    get_success_data,
    validate_paginated,
)


def _reclean_of(api, assignment_id):
    """Re-clean rows are discovered only by filtering on `supersedes_assignment_id`."""
    rows, _ = validate_paginated(
        api.list_room_assignments(
            {"supersedes_assignment_id": assignment_id}, DIRECTOR_HEADERS
        )
    )
    assert len(rows) == 1, (
        f"exactly one re-clean should supersede {assignment_id}, got {len(rows)}"
    )
    return rows[0]


def _recleaned_shift(api):
    """One room cleaned, failed on the bathroom item, then re-cleaned by the same attendant."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
    )
    first = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    scenario.inspect(first["id"], bathroom_points=5)
    reclean = _reclean_of(api, first["id"])
    scenario.start(reclean["id"], "2026-08-03T11:00:00.000Z")
    scenario.complete(reclean["id"], "2026-08-03T11:40:00.000Z")
    return scenario


def test_minutes_per_room_net_exceeds_gross_once_a_room_has_been_recleaned(api):
    """Two physical cleans of one room give 135.00 minutes gross but 270.00 net.

    PRD 3.7: "Because a re-cleaned room is counted once there, the same minutes
    yield a strictly larger figure than the gross reading whenever any re-clean
    exists."

    Design: Difficulty/dual_variant_calc/minutes_per_room_gross_physical_versus_net_credited_after_reclean
    """
    scenario = _recleaned_shift(api)

    roster = get_success_data(
        scenario.close_roster_raw(300, 30, scenario.supervisor_headers())
    )

    assert_credits(roster["minutes_per_room_gross"], 135.00, "minutes_per_room_gross")
    assert_credits(roster["minutes_per_room_net"], 270.00, "minutes_per_room_net")
    assert roster["minutes_per_room_net"] > roster["minutes_per_room_gross"], (
        "the net reading must be strictly larger than the gross reading once a "
        "re-clean exists"
    )


def test_reclean_splits_the_two_room_counters_and_forces_the_quality_guardrail(api):
    """Gross counts both cleans, net counts the one room, and the shift is held on quality.

    PRD 3.7: "If any assignment on the roster whose `status` is not `CANCELLED`
    has a `reclean_generation` of 1 or more, the flag is `QUALITY_HOLD`, whatever
    the minutes say: a shift that produced a re-clean is not celebrated for being
    fast."

    Design: Difficulty/dual_variant_calc/minutes_per_room_gross_physical_versus_net_credited_after_reclean
    """
    scenario = _recleaned_shift(api)

    roster = get_success_data(
        scenario.close_roster_raw(300, 30, scenario.supervisor_headers())
    )

    assert roster["rooms_completed_gross"] == 2, (
        f"rooms_completed_gross should be 2, got {roster['rooms_completed_gross']}"
    )
    assert roster["rooms_credited_net"] == 1, (
        f"rooms_credited_net should be 1, got {roster['rooms_credited_net']}"
    )
    assert_credits(roster["target_minutes_per_room"], 45.00, "target_minutes_per_room")
    assert_credits(roster["assigned_credits"], 1.50, "assigned_credits")
    assert_whole_minutes(roster["paid_minutes"], 300, "paid_minutes")
    assert_whole_minutes(roster["overtime_minutes"], 0, "overtime_minutes")
    assert roster["productivity_flag"] == PRODUCTIVITY_QUALITY_HOLD
