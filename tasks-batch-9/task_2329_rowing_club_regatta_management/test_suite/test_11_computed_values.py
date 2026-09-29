"""Derived figures on their own terms: the posture ladder's traffic-pattern and
visibility arms, the zero-launch practice outing, the on-time home fee, the two
chronological refund brackets, the confirmed-only lane draw and the rack waterfall.
"""

import pytest

from test_helpers import (
    api_client,
    assert_entry_fee_components_sum,
    assert_heat,
    assert_heat_lane_counts_conserved,
    assert_race_lane,
    assert_rack_capacity_derived,
    assert_rack_units_conserved,
    assert_regatta,
    assert_regatta_entry,
    assert_trailer_load,
    assert_water_condition_reading,
    assert_water_session,
    validate_paginated,
)
from test_helpers.fixtures import (
    add_single,
    assign_lanes,
    book_session,
    clear_session,
    confirm_entry,
    declare_single_lineup,
    drive_regatta_to_racing,
    enrol_athlete,
    lane_of_entry,
    open_away_regatta,
    open_entry,
    open_regatta,
    open_trailer_load,
    post_reading,
    rack_entry,
    read_entry,
    read_regatta,
    read_session,
    read_shell,
    read_trailer,
    scratch_entry,
    schedule_heat,
    set_clock_to,
    submit_entry,
)

PARTIAL_REFUND_CLOCK = "2026-08-10T12:00:00Z"
NO_REFUND_CLOCK = "2026-08-11T00:00:01Z"
LANE_DRAW_CLOCK = "2026-08-12T08:30:00Z"


@pytest.fixture
def submitted_home_single(cast, single_shell):
    """One on-time HOME 1X entry submitted at the season-start instant."""
    regatta = open_regatta(name="Club Head Race", host_club="Home RC")
    rower = enrol_athlete("Rhea Rower", "COMPETITIVE", 81.0)
    entry = open_entry(regatta["id"], single_shell["id"], cast["coach_headers"])
    entry = declare_single_lineup(entry, rower["id"], cast["coach_headers"])
    entry = submit_entry(entry["id"], cast["coach_headers"])
    return {"regatta": regatta, "entry": entry, "rower": rower}


@pytest.fixture
def racing_regatta_with_a_draft_outsider(cast):
    """Two CONFIRMED singles and one DRAFT single in the same event, ready to seed."""
    regatta = open_regatta(name="Club Head Race", host_club="Home RC")
    hulls = [add_single(hull_name=name) for name in ("Kingfisher", "Heron", "Osprey")]
    fast = enrol_athlete("Fast Rower", "COMPETITIVE", 82.0)
    slow = enrol_athlete("Slow Rower", "COMPETITIVE", 84.0)

    confirmed = []
    for hull, rower, seed in ((hulls[0], fast, 370.0), (hulls[1], slow, 390.0)):
        entry = open_entry(
            regatta["id"], hull["id"], cast["coach_headers"], seed_time_seconds=seed
        )
        entry = declare_single_lineup(entry, rower["id"], cast["coach_headers"])
        entry = submit_entry(entry["id"], cast["coach_headers"])
        confirmed.append(confirm_entry(entry["id"], cast["official_headers"]))

    draft = open_entry(
        regatta["id"], hulls[2]["id"], cast["coach_headers"], seed_time_seconds=360.0
    )
    heat = schedule_heat(regatta["id"], cast["official_headers"], lane_count=4)
    drive_regatta_to_racing(regatta, racing_clock=LANE_DRAW_CLOCK)
    return {
        "regatta": regatta,
        "heat": heat,
        "fast_entry": confirmed[0],
        "slow_entry": confirmed[1],
        "draft_entry": draft,
    }


@pytest.fixture
def away_load_with_two_submitted_singles(cast):
    """An OPEN load of default geometry and two away 1X entries awaiting rack units.

    Both entries are carried to `SUBMITTED`, because PRD §3.7 recomputes
    `rack_units_used` over "the entries whose `trailer_load_id` is this load and
    whose status is `SUBMITTED`, `CONFIRMED` or `RACED`" — a `DRAFT` entry is
    outside that input set and would leave the counters at zero.
    """
    regatta = open_away_regatta(name="Away Sprints", host_club="Lakeside RC")
    hulls = [add_single(hull_name=name) for name in ("Kingfisher", "Heron")]
    entries = []
    for index, (hull, seed) in enumerate(zip(hulls, (370.0, 390.0)), start=1):
        rower = enrol_athlete(f"Rack Rower {index}", "COMPETITIVE", 80.0 + index)
        entry = open_entry(
            regatta["id"], hull["id"], cast["coach_headers"], seed_time_seconds=seed
        )
        entry = declare_single_lineup(entry, rower["id"], cast["coach_headers"])
        entries.append(submit_entry(entry["id"], cast["coach_headers"]))
    trailer = open_trailer_load(
        regatta["id"], cast["driver"]["id"], cast["boatman_headers"], tow_vehicle_code="TRUCK-1"
    )
    return {"regatta": regatta, "entries": entries, "trailer": trailer}


class TestPostureFromTrafficPattern:
    def test_a_narrow_channel_alone_restricts_otherwise_benign_water(self, cast):
        """Warm, calm, clear water is still restricted while the channel is narrow.

        PRD: "Otherwise it is `RESTRICTED` when the wind is 12.0 knots or more, or
        the visibility is 800 metres or less, or the `cold_water_flag` is raised,
        or the `traffic_pattern` is `NARROW_CHANNEL`."

        Design: Corner/calculations/corner_water_posture_narrow_channel_alone_forces_restricted
        """
        reading = assert_water_condition_reading(
            post_reading(
                cast["officer_headers"],
                air_temp_c=22.0,
                water_temp_c=19.0,
                wind_speed_kt=5.0,
                visibility_m=3000,
                traffic_pattern="NARROW_CHANNEL",
            )
        )
        assert reading["cold_water_flag"] is False, (
            "water at 19.0 degrees with a combined sum of 41.0 is not cold, got "
            f"{reading['cold_water_flag']}"
        )
        assert reading["posture"] == "RESTRICTED", (
            "the traffic pattern alone restricts the river even with light wind and "
            f"three kilometres of visibility, got {reading['posture']}"
        )
        assert reading["traffic_pattern"] == "NARROW_CHANNEL", (
            f"the observed pattern is echoed back, got {reading['traffic_pattern']}"
        )

    def test_the_standard_pattern_leaves_the_same_water_open(self, cast):
        """Swapping only the traffic pattern is what moves the posture.

        PRD: "Failing all of those, the posture is `OPEN`."

        Design: Corner/calculations/corner_water_posture_narrow_channel_alone_forces_restricted
        """
        reading = assert_water_condition_reading(
            post_reading(
                cast["officer_headers"],
                air_temp_c=22.0,
                water_temp_c=19.0,
                wind_speed_kt=5.0,
                visibility_m=3000,
                traffic_pattern="STANDARD_COUNTERCLOCKWISE",
            )
        )
        assert reading["posture"] == "OPEN", (
            "with the standard pattern in force nothing closes or restricts the "
            f"river, got {reading['posture']}"
        )
        assert reading["cold_water_flag"] is False, (
            f"the temperatures are unchanged and still not cold, got {reading['cold_water_flag']}"
        )


class TestPostureFromVisibility:
    def test_four_hundred_metres_closes_the_river(self, cast):
        """The closing visibility comparison is at-or-below.

        PRD: "The `posture` is then decided in order: it is `CLOSED` when the
        sustained wind is 20.0 knots or more, or the visibility is 400 metres or
        less."

        Design: Corner/calculations/corner_water_posture_visibility_constants_close_vs_restrict
        """
        reading = assert_water_condition_reading(
            post_reading(
                cast["officer_headers"],
                observed_at="2026-08-01T05:00:00Z",
                air_temp_c=22.0,
                water_temp_c=19.0,
                wind_speed_kt=5.0,
                visibility_m=400,
            )
        )
        assert reading["posture"] == "CLOSED", (
            "visibility sitting exactly on 400 metres closes the river, got "
            f"{reading['posture']}"
        )
        assert reading["visibility_m"] == 400, (
            f"the observed visibility is stored as whole metres, got {reading['visibility_m']}"
        )

    def test_one_metre_more_restricts_and_eight_hundred_and_one_reopens(self, cast):
        """The two visibility constants are distinct thresholds, not one.

        PRD: "Otherwise it is `RESTRICTED` when the wind is 12.0 knots or more, or
        the visibility is 800 metres or less, or the `cold_water_flag` is raised,
        or the `traffic_pattern` is `NARROW_CHANNEL`."

        Design: Corner/calculations/corner_water_posture_visibility_constants_close_vs_restrict
        """
        restricted = assert_water_condition_reading(
            post_reading(
                cast["officer_headers"],
                observed_at="2026-08-01T05:10:00Z",
                air_temp_c=22.0,
                water_temp_c=19.0,
                wind_speed_kt=5.0,
                visibility_m=401,
            )
        )
        assert restricted["posture"] == "RESTRICTED", (
            "401 metres clears the closing threshold but not the restricting one, "
            f"got {restricted['posture']}"
        )

        open_water = assert_water_condition_reading(
            post_reading(
                cast["officer_headers"],
                observed_at="2026-08-01T05:20:00Z",
                air_temp_c=22.0,
                water_temp_c=19.0,
                wind_speed_kt=5.0,
                visibility_m=801,
            )
        )
        assert open_water["posture"] == "OPEN", (
            "801 metres is strictly above the 800-metre restricting threshold, got "
            f"{open_water['posture']}"
        )


class TestZeroLaunchRequirement:
    def test_an_open_water_practice_clears_with_no_launch_named(self, cast, single_shell):
        """None of the three launch conditions holds, so the requirement is zero.

        PRD: "How many safety launches an outing needs is derived from the outing
        and the reading together, starting from zero and adding one launch for
        each of three conditions: the `session_kind` is `LEARN_TO_ROW`; the
        reading's `cold_water_flag` is raised; the reading's `posture` is
        `RESTRICTED`."

        Design: Corner/calculations/corner_launch_requirement_zero_for_open_practice_clears_with_no_drivers
        """
        reading = post_reading(
            cast["officer_headers"],
            air_temp_c=22.0,
            water_temp_c=19.0,
            wind_speed_kt=5.0,
            visibility_m=3000,
        )
        assert reading["posture"] == "OPEN", (
            f"the outing is cleared against open water, got {reading['posture']}"
        )
        session = book_session(single_shell["id"], cast["coach_headers"])
        assert session["assigned_launch_count"] == 0, (
            f"no launch driver is named on the booking, got {session['assigned_launch_count']}"
        )

        cleared = assert_water_session(
            clear_session(session["id"], reading["id"], cast["officer_headers"])
        )
        assert cleared["status"] == "CLEARED", (
            f"the outing moves PLANNED -> CLEARED, got {cleared['status']}"
        )
        assert cleared["required_launch_count"] == 0, (
            "an open-water practice needs no safety launch, got "
            f"{cleared['required_launch_count']}"
        )
        assert cleared["assigned_launch_count"] == 0, (
            f"still no driver is named, got {cleared['assigned_launch_count']}"
        )
        assert cleared["reading_id"] == reading["id"], (
            "the reading the decision was recorded against is persisted, got "
            f"{cleared['reading_id']}"
        )
        assert read_shell(single_shell["id"])["status"] == "ASSIGNED", (
            "a successful clearance drives the hull AVAILABLE -> ASSIGNED"
        )
        assert read_session(session["id"])["required_launch_count"] == 0, (
            "the stored outing reports the same requirement as the clearance response"
        )


class TestOnTimeHomeEntryFee:
    def test_a_home_single_submitted_early_pays_only_its_class_fee(
        self, cast, submitted_home_single
    ):
        """No levy on home water and no late fee before the deadline.

        PRD: "Step two: `transport_levy_cents` is 5000 cents per rack unit the
        hull occupies when the regatta's `venue_kind` is `AWAY`, using the same
        rack-unit table as the trailer (1 unit for a `1X` or `2X`, 2 for a `4+`,
        3 for an `8+`), and is zero for a `HOME` regatta."

        Design: Corner/calculations/corner_entry_fee_on_time_home_single_has_no_levy_or_late_fee
        """
        entry = assert_entry_fee_components_sum(
            assert_regatta_entry(submitted_home_single["entry"])
        )
        assert entry["status"] == "SUBMITTED", (
            f"the entry moves LINEUP_DECLARED -> SUBMITTED, got {entry['status']}"
        )
        assert entry["base_fee_cents"] == 4500, (
            f"the class entry fee for a 1X is 4500 cents, got {entry['base_fee_cents']}"
        )
        assert entry["transport_levy_cents"] == 0, (
            f"a HOME regatta levies nothing for transport, got {entry['transport_levy_cents']}"
        )
        assert entry["late_fee_cents"] == 0, (
            "the submission is well before the entry deadline, got "
            f"{entry['late_fee_cents']}"
        )
        assert entry["total_fee_cents"] == 4500, (
            f"4500 + 0 + 0 is 4500 cents, got {entry['total_fee_cents']}"
        )
        assert entry["submitted_at"].startswith("2026-08-01T00:00:00"), (
            "submission stamps the logical clock, which still reads the season-start "
            f"instant, got {entry['submitted_at']}"
        )

    def test_the_regatta_ledger_picks_the_submitted_fee_up_at_once(
        self, submitted_home_single
    ):
        """The host's running total is the submitted fee with no refund yet.

        PRD: "A regatta's `net_fee_cents` is at all times the sum, over its
        entries in status `SUBMITTED`, `CONFIRMED`, `RACED` or `SCRATCHED`, of
        `total_fee_cents` less `refund_cents` where a refund has been computed."

        Design: Corner/calculations/corner_entry_fee_on_time_home_single_has_no_levy_or_late_fee
        """
        regatta = assert_regatta(read_regatta(submitted_home_single["regatta"]["id"]))
        assert regatta["net_fee_cents"] == 4500, (
            "the one submitted entry contributes its whole 4500-cent fee, got "
            f"{regatta['net_fee_cents']}"
        )
        assert submitted_home_single["entry"]["refund_cents"] is None, (
            "no refund has been computed on a live entry, got "
            f"{submitted_home_single['entry']['refund_cents']}"
        )


class TestScratchRefundBrackets:
    def test_a_scratch_between_the_deadlines_refunds_fifty_five_percent(
        self, cast, submitted_home_single
    ):
        """Past the entry deadline but inside the scratch deadline pays 55 percent.

        PRD: "When the logical clock at the scratch is at or before the regatta's
        `entry_deadline_at`, the percentage is 100 percent (1.00); otherwise, when
        it is at or before `scratch_deadline_at`, it is 55 percent (0.55); after
        that it is zero (0.00)."

        Design: Corner/calculations/corner_scratch_refund_partial_percentage_between_deadlines
        """
        set_clock_to(PARTIAL_REFUND_CLOCK)
        entry = assert_regatta_entry(
            scratch_entry(submitted_home_single["entry"]["id"], cast["coach_headers"])
        )
        assert entry["status"] == "SCRATCHED", (
            f"the entry follows SUBMITTED -> SCRATCHED, got {entry['status']}"
        )
        assert entry["refund_cents"] == 2475, (
            "55 percent of the 4500-cent base fee rounded half up is 2475 cents, got "
            f"{entry['refund_cents']}"
        )
        assert entry["total_fee_cents"] == 4500, (
            "the assessed fee itself is not rewritten by the refund, got "
            f"{entry['total_fee_cents']}"
        )

        regatta = read_regatta(submitted_home_single["regatta"]["id"])
        assert regatta["net_fee_cents"] == 2025, (
            "the scratched entry still counts, at 4500 less 2475, got "
            f"{regatta['net_fee_cents']}"
        )

    def test_a_scratch_one_second_late_refunds_nothing(self, cast, submitted_home_single):
        """One second past the scratch deadline drops the percentage to zero.

        PRD: "From `SUBMITTED` or `CONFIRMED` the refund is computed and the
        regatta's `net_fee_cents` is recomputed; if `rack_tier` is non-null the
        entry's rack units are released and the owning trailer's
        `rack_units_used` and `rack_units_free` are recomputed."

        Design: Corner/calculations/corner_scratch_after_scratch_deadline_refunds_zero
        """
        set_clock_to(NO_REFUND_CLOCK)
        entry = assert_regatta_entry(
            scratch_entry(submitted_home_single["entry"]["id"], cast["coach_headers"])
        )
        assert entry["status"] == "SCRATCHED", (
            f"the entry follows SUBMITTED -> SCRATCHED, got {entry['status']}"
        )
        assert entry["refund_cents"] == 0, (
            "a refund was computed and came to zero, not to null, got "
            f"{entry['refund_cents']}"
        )
        assert entry["total_fee_cents"] == 4500, (
            f"the club keeps the whole assessed fee, got {entry['total_fee_cents']}"
        )

        regatta = read_regatta(submitted_home_single["regatta"]["id"])
        assert regatta["net_fee_cents"] == 4500, (
            "with nothing refunded the ledger stays at the full fee, got "
            f"{regatta['net_fee_cents']}"
        )


class TestLaneDrawCandidatePool:
    def test_only_confirmed_crews_enter_the_draw(
        self, cast, racing_regatta_with_a_draft_outsider
    ):
        """The fastest seed in the event is left out because it was never confirmed.

        PRD: "The candidate pool is every entry whose `regatta_id` matches the
        heat's regatta, whose `event_code` matches the heat's event code, and whose
        status is exactly `CONFIRMED`; entries in any other status are excluded."

        Design: Corner/calculations/corner_lane_assignment_filters_to_confirmed_and_seeds_preference_order
        """
        scenario = racing_regatta_with_a_draft_outsider
        assign_lanes(scenario["heat"]["id"], cast["official_headers"])

        rows, meta = validate_paginated(
            api_client.list_race_lanes(
                cast["official_headers"], {"heat_id": scenario["heat"]["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            "only the two confirmed crews are seeded, got "
            f"{meta['total_count']} lane rows"
        )
        seeded_entry_ids = {row["regatta_entry_id"] for row in rows}
        assert scenario["draft_entry"]["id"] not in seeded_entry_ids, (
            "the undeclared crew's 360.0-second seed would have ranked first but it "
            "is not a candidate"
        )

        draft = read_entry(scenario["draft_entry"]["id"])
        assert draft["status"] == "DRAFT", (
            f"the excluded entry is left untouched in DRAFT, got {draft['status']}"
        )

    def test_the_two_candidates_take_the_first_two_preferred_lanes(
        self, cast, racing_regatta_with_a_draft_outsider
    ):
        """The faster seed gets the most favoured lane on the course.

        PRD: "Lanes are drawn from the club's preference order — 3, 4, 2, 5, 1, 6,
        7, 8 — filtered to those numbers that are no greater than the heat's
        `lane_count`, taken in that same list order, so the fastest seed gets the
        most sheltered middle water."

        Design: Corner/calculations/corner_lane_assignment_filters_to_confirmed_and_seeds_preference_order
        """
        scenario = racing_regatta_with_a_draft_outsider
        heat = assert_heat_lane_counts_conserved(
            assert_heat(assign_lanes(scenario["heat"]["id"], cast["official_headers"]))
        )
        assert heat["status"] == "LANES_ASSIGNED", (
            f"the heat moves SCHEDULED -> LANES_ASSIGNED, got {heat['status']}"
        )
        assert heat["occupied_lane_count"] == 2, (
            f"two of the four lanes are taken, got {heat['occupied_lane_count']}"
        )
        assert heat["free_lane_count"] == 2, (
            f"two lanes remain free, got {heat['free_lane_count']}"
        )

        fast_lane = assert_race_lane(lane_of_entry(scenario["fast_entry"]["id"]))
        assert fast_lane["lane_number"] == 3, (
            "the 370.0-second seed takes lane 3, the first preferred lane, got "
            f"{fast_lane['lane_number']}"
        )
        slow_lane = assert_race_lane(lane_of_entry(scenario["slow_entry"]["id"]))
        assert slow_lane["lane_number"] == 4, (
            f"the 390.0-second seed takes lane 4, got {slow_lane['lane_number']}"
        )
        for lane, label in ((fast_lane, "faster"), (slow_lane, "slower")):
            assert lane["lane_status"] == "PENDING", (
                f"the {label} crew's lane is born PENDING, got {lane['lane_status']}"
            )
            assert lane["place"] is None, (
                f"the {label} crew has no place before the race, got {lane['place']}"
            )
            assert lane["advanced"] is False, (
                f"the {label} crew has advanced nowhere yet, got {lane['advanced']}"
            )


class TestRackWaterfall:
    def test_two_singles_fill_the_lowest_tier_left_to_right(
        self, cast, away_load_with_two_submitted_singles
    ):
        """Tier 1 is filled position by position before tier 2 is considered.

        PRD: "The server walks the tiers from tier 1 upward, stopping at whichever
        is lower of that class ceiling and the trailer's own `rack_tier_count`;
        within each tier it walks candidate starting positions from position 1 up
        to the last position at which a run of the required length still fits,
        which is the units per tier less the required units plus one."

        Design: Corner/calculations/corner_trailer_rack_waterfall_fills_lowest_tier_positions_in_order
        """
        scenario = away_load_with_two_submitted_singles
        trailer = rack_entry(
            scenario["trailer"], scenario["entries"][0]["id"], cast["boatman_headers"]
        )
        first = read_entry(scenario["entries"][0]["id"])
        assert first["rack_tier"] == 1, (
            f"the first hull rides on the lowest tier, got {first['rack_tier']}"
        )
        assert first["rack_position"] == 1, (
            f"it takes the first unit of that tier, got {first['rack_position']}"
        )
        assert first["trailer_load_id"] == scenario["trailer"]["id"], (
            f"the entry records its load, got {first['trailer_load_id']}"
        )
        assert trailer["rack_units_used"] == 1, (
            f"a 1X occupies one rack unit, got {trailer['rack_units_used']}"
        )

        trailer = assert_rack_capacity_derived(
            assert_rack_units_conserved(
                assert_trailer_load(
                    rack_entry(trailer, scenario["entries"][1]["id"], cast["boatman_headers"])
                )
            )
        )
        second = read_entry(scenario["entries"][1]["id"])
        assert second["rack_tier"] == 1, (
            "the second hull stays on tier 1 rather than moving up, got "
            f"{second['rack_tier']}"
        )
        assert second["rack_position"] == 2, (
            f"it takes the next free unit along, got {second['rack_position']}"
        )

    def test_the_load_counters_follow_the_two_assignments(
        self, cast, away_load_with_two_submitted_singles
    ):
        """Used climbs to two against the derived sixteen-unit capacity.

        PRD: "The derived `rack_unit_capacity` is the tier count multiplied by the
        units per tier. A new load is `OPEN` with `rack_units_used` 0 and
        `rack_units_free` equal to the capacity."

        Design: Corner/calculations/corner_trailer_rack_waterfall_fills_lowest_tier_positions_in_order
        """
        scenario = away_load_with_two_submitted_singles
        assert scenario["trailer"]["rack_units_used"] == 0, (
            f"a new load carries nothing, got {scenario['trailer']['rack_units_used']}"
        )
        trailer = rack_entry(
            scenario["trailer"], scenario["entries"][0]["id"], cast["boatman_headers"]
        )
        trailer = rack_entry(trailer, scenario["entries"][1]["id"], cast["boatman_headers"])

        stored = assert_rack_capacity_derived(
            assert_rack_units_conserved(read_trailer(trailer["id"]))
        )
        assert stored["rack_unit_capacity"] == 16, (
            "four tiers of four units apiece is a capacity of 16, got "
            f"{stored['rack_unit_capacity']}"
        )
        assert stored["rack_units_used"] == 2, (
            f"two singles occupy two units, got {stored['rack_units_used']}"
        )
        assert stored["rack_units_free"] == 14, (
            f"fourteen units remain free, got {stored['rack_units_free']}"
        )
        assert stored["status"] == "OPEN", (
            f"racking hulls does not seal the load, got {stored['status']}"
        )
