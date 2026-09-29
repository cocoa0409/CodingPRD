"""Immediate consistency: the first read after a write already shows the final figures."""

from test_helpers import (
    COMPLIANCE_COMPLIANT,
    OCCUPANCY_DUE_OUT,
    SERVICE_CHECKOUT,
    assert_credits,
    build_scenario,
    read_day,
    read_roster,
    validate_success,
)

ONE_DEPARTURE_DAY = {
    "forecast_occupied_rooms": 1,
    "forecast_arrivals": 0,
    "forecast_departures": 1,
    "planned_deep_clean_rooms": 0,
}


def test_the_assignment_response_and_the_next_reads_agree_at_once(api):
    """The write body, the roster read and the day read all carry the recomputed totals.

    PRD 3.4: "The create then cascades: the roster's `assigned_credits`,
    `assigned_square_feet` and `compliance_state` are recomputed, the roster's
    `required_inspection_samples` is recomputed, the forecast day's
    `allocated_credits_total` is recomputed, the roster's `version` increments, and
    the resulting roster version is reported back on the assignment as
    `roster_version_after` so the caller can chain its next write without re-reading
    the roster."

    Design: Corner/consistency_model/consistency_derived_roster_and_day_totals_are_visible_in_the_same_response
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_DEPARTURE_DAY,
        clocked_in=False,
    )
    before_roster = read_roster(api, scenario.roster_id)
    assert before_roster["version"] == 1
    assert_credits(before_roster["assigned_credits"], 0.00, "assigned_credits")
    assert_credits(
        read_day(api, scenario.day_id)["allocated_credits_total"],
        0.00,
        "allocated_credits_total",
    )

    created = validate_success(
        scenario.assign_raw(
            "101",
            SERVICE_CHECKOUT,
            expected_roster_version=1,
            headers=scenario.supervisor_headers(),
        ),
        201,
    )

    assert_credits(created["credits"], 1.00, "credits")
    assert created["square_feet_snapshot"] == 420
    assert created["roster_version_after"] == 2, (
        "the write body itself must already carry the recomputed roster version"
    )
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["assigned_credits"], 1.00, "assigned_credits")
    assert roster["assigned_square_feet"] == 420
    assert roster["compliance_state"] == COMPLIANCE_COMPLIANT
    assert roster["version"] == created["roster_version_after"]
    day = read_day(api, scenario.day_id)
    assert_credits(day["allocated_credits_total"], 1.00, "allocated_credits_total")
    again = read_roster(api, scenario.roster_id)
    assert_credits(again["assigned_credits"], 1.00, "assigned_credits")
    assert again["version"] == roster["version"], (
        "no repeated read is needed: the first read already showed the final values"
    )
