"""Derived figures: headcount ceilings, sampling pools, credit factors, ladders and SLAs."""

from test_helpers import (
    ASSIGN_RECLEAN_REQUIRED,
    CLEAN_RECLEAN_REQUIRED,
    COMPLIANCE_COMPLIANT,
    CYCLE_RETURNED,
    INSPECTION_FAIL,
    OCCUPANCY_DUE_OUT,
    OCCUPANCY_STAYOVER,
    ORDINANCE_NONE,
    PROGRAM_EVERY_OTHER_DAY,
    SERVICE_CHECKOUT,
    SERVICE_STAYOVER,
    SHORTAGE_OK,
    SHORTAGE_WATCH,
    assert_coverage_ratio,
    assert_credits,
    assert_linen_buckets,
    assert_linen_identity,
    assert_score_pct,
    assert_whole_minutes,
    build_scenario,
    dispatch_cycle,
    read_assignment,
    read_attendant,
    read_day,
    read_linen_item,
    read_room,
    read_roster,
    read_sample_plan,
    return_cycle,
)

ONE_ROOM_DAY = {
    "forecast_occupied_rooms": 1,
    "forecast_arrivals": 0,
    "forecast_departures": 1,
    "planned_deep_clean_rooms": 0,
}


# --------------------------------------------------------------------------
# The headcount ceiling
# --------------------------------------------------------------------------


def _day_projecting_one_and_a_half_credits(api, name, max_daily_credits):
    """A one-KING-room property whose published day projects exactly 1.50 credits."""
    scenario = build_scenario(
        api,
        property_overrides={
            "name": name,
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": max_daily_credits,
        },
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
        with_worker=False,
        with_inspector=False,
        with_roster=False,
    )
    return scenario.day


def test_the_headcount_divides_by_the_lesser_of_the_two_ceilings(api):
    """The same 1.50-credit day needs one attendant at a 1.50 ceiling and two at 1.00.

    PRD 3.2: "Second, the assignable ceiling: the smaller of that per-shift figure
    and `max_daily_credits`, because a shift long enough to absorb more credits than
    the ordinance permits is still bounded by the ordinance."

    Design: Corner/calculations/calc_headcount_ceiling_is_the_lesser_of_shift_capacity_and_the_daily_credit_cap
    """
    generous = _day_projecting_one_and_a_half_credits(api, "Ceiling A", 1.50)
    tight = _day_projecting_one_and_a_half_credits(api, "Ceiling B", 1.00)

    assert_credits(
        generous["projected_required_credits"], 1.50, "projected_required_credits"
    )
    assert_credits(
        tight["projected_required_credits"], 1.50, "projected_required_credits"
    )
    assert generous["required_attendants"] == 1, (
        "1.50 credits divided by a 1.50 ceiling is exactly one attendant, got "
        f"{generous['required_attendants']}"
    )
    assert tight["required_attendants"] == 2, (
        "1.50 credits divided by a 1.00 ceiling rounds up to two attendants, got "
        f"{tight['required_attendants']}"
    )


# --------------------------------------------------------------------------
# The sampling pool
# --------------------------------------------------------------------------


def test_the_sampling_plan_sees_only_the_finished_room(api):
    """One room finished, one still being cleaned, one untouched: the plan counts one.

    PRD 3.6: "The eligible pool is the roster's assignments whose `status` is
    exactly `COMPLETED` — an already-inspected assignment has left that status and
    drops out of the pool by construction, while `ASSIGNED`, `IN_PROGRESS`,
    `CANCELLED` and `DEFERRED` rows never enter it."

    Design: Corner/calculations/calc_sampling_plan_excludes_in_progress_and_assigned_rows
    """
    scenario = build_scenario(
        api,
        rooms=[
            {"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT},
            {"number": "102", "occupancy_state": OCCUPANCY_DUE_OUT},
            {"number": "103", "occupancy_state": OCCUPANCY_DUE_OUT},
        ],
        forecast={
            "forecast_occupied_rooms": 3,
            "forecast_arrivals": 0,
            "forecast_departures": 3,
            "planned_deep_clean_rooms": 0,
        },
    )
    finished = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T09:00:00.000Z",
        "2026-08-03T09:20:00.000Z",
    )
    under_way = scenario.assign("102", SERVICE_CHECKOUT)
    scenario.start(under_way["id"], "2026-08-03T09:30:00.000Z")
    untouched = scenario.assign("103", SERVICE_CHECKOUT)

    plan = read_sample_plan(api, scenario.roster_id)

    assert plan["completed_count"] == 1, (
        f"only the finished room counts, got {plan['completed_count']}"
    )
    assert plan["sample_rate"] == 0.20
    assert plan["required_samples"] == 1
    assert plan["inspections_completed"] == 0
    assert plan["remaining_samples"] == 1
    assert plan["selected_assignment_ids"] == [finished["id"]], (
        "the plan must offer the finished room alone, got "
        f"{plan['selected_assignment_ids']!r}"
    )
    assert under_way["id"] not in plan["selected_assignment_ids"]
    assert untouched["id"] not in plan["selected_assignment_ids"]


# --------------------------------------------------------------------------
# The programme factor
# --------------------------------------------------------------------------


def test_an_alternating_day_stayover_earns_half_credit(api):
    """A 0.50-credit stayover touch on an every-other-day room prices at a quarter credit.

    PRD 3.4: "The **programme factor** is one half when the room's
    `service_program` is `EVERY_OTHER_DAY` **and** the service type is `STAYOVER`,
    and is one otherwise — alternating-day service earns half credit for the
    stayover touch, while `CHECKOUT` and `DEEP_CLEAN` work is never discounted."

    Design: Corner/calculations/calc_every_other_day_stayover_credit_is_halved_to_a_quarter_credit
    """
    scenario = build_scenario(
        api,
        rooms=[
            {
                "number": "102",
                "occupancy_state": OCCUPANCY_STAYOVER,
                "service_program": PROGRAM_EVERY_OTHER_DAY,
                "last_serviced_business_date": "2026-08-01",
            }
        ],
        forecast={
            "forecast_occupied_rooms": 1,
            "forecast_arrivals": 0,
            "forecast_departures": 0,
            "planned_deep_clean_rooms": 0,
        },
        clocked_in=False,
    )

    assignment = scenario.assign("102", SERVICE_STAYOVER)

    assert_credits(assignment["credits"], 0.25, "credits")
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["assigned_credits"], 0.25, "assigned_credits")
    assert roster["compliance_state"] == COMPLIANCE_COMPLIANT
    assert_credits(
        read_day(api, scenario.day_id)["allocated_credits_total"],
        0.25,
        "allocated_credits_total",
    )


# --------------------------------------------------------------------------
# The critical-item floor
# --------------------------------------------------------------------------


def test_a_bathroom_score_of_six_condemns_a_clean_that_scored_eighty_eight(api):
    """The weighted roll-up clears the threshold, yet the bathroom mark fails the clean.

    PRD 3.6: "Separately, `critical_fail` is true when either the bathroom score or
    the linen score is 6 or lower — those two items are the ones a guest notices
    first, and a poor mark on either condemns the clean whatever the total says."

    Design: Corner/calculations/calc_critical_item_floor_fails_an_inspection_that_scores_above_the_threshold
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
    )
    cleaned = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T09:00:00.000Z",
        "2026-08-03T09:30:00.000Z",
    )

    inspection = scenario.inspect(
        cleaned["id"],
        bathroom_points=6,
        linen_points=10,
        dust_points=10,
        amenity_points=10,
        floor_points=10,
    )

    assert_score_pct(inspection["score_pct"], 88.0)
    assert inspection["critical_fail"] is True
    assert inspection["result"] == INSPECTION_FAIL, (
        "88.0 clears the 85.0 threshold, so only the critical item can fail this clean"
    )
    assert read_assignment(api, cleaned["id"])["status"] == ASSIGN_RECLEAN_REQUIRED
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == (
        CLEAN_RECLEAN_REQUIRED
    )
    reclean = read_assignment(api, inspection["generated_reclean_assignment_id"])
    assert reclean["reclean_generation"] == 1
    assert_credits(reclean["credits"], 0.50, "re-clean credits")
    worker = read_attendant(api, scenario.worker_id)
    assert worker["quality_probation"] is True
    assert worker["lifetime_fail_count"] == 1


# --------------------------------------------------------------------------
# The shortage ladder
# --------------------------------------------------------------------------


def test_coverage_exactly_on_the_watch_floor_reads_as_watch(api):
    """Seventeen clean sets against a par of twenty land exactly on the WATCH floor.

    PRD 3.8: "`shortage_status` is then a four-rung ladder read off that ratio,
    with each comparison inclusive at its floor: a ratio at or above 1.0000 is
    `OK`; below that but at or above 0.8500 is `WATCH`; below that but at or above
    0.6000 is `SHORTAGE`; and anything below 0.6000 is `ESCALATED`."

    Design: Corner/calculations/calc_linen_coverage_exactly_at_the_watch_floor_reports_watch
    """
    scenario = build_scenario(
        api,
        room_type_overrides={"KING": {"code": "PLUSH", "linen_sets_per_room": 10}},
        rooms=["101", "102"],
        linen={"total_owned_sets": 20, "initial_soiled_sets": 3},
        with_worker=False,
        with_inspector=False,
        with_day=False,
        with_roster=False,
    )

    line = read_linen_item(api, scenario.linen_id)

    assert line["par_required_sets"] == 20, (
        f"two rooms needing ten sets each is a par of 20, got {line['par_required_sets']}"
    )
    assert_linen_buckets(line, 17, 0, 3)
    assert_coverage_ratio(line["coverage_ratio"], 0.8500)
    assert line["shortage_status"] == SHORTAGE_WATCH, (
        f"an inclusive WATCH floor must not read as SHORTAGE, got "
        f"{line['shortage_status']}"
    )
    assert_linen_identity(line)


# --------------------------------------------------------------------------
# The laundry SLA and the write-off
# --------------------------------------------------------------------------


def test_a_turnaround_exactly_on_the_sla_returns_clean_and_writes_off_the_shortfall(api):
    """Four hours against a four-hour SLA is no breach, and the two lost sets leave the ledger.

    PRD 3.8: "`turnaround_minutes` is then the whole minutes from `dispatched_at`
    to `returned_at`, truncated toward zero, and `sla_breach` is true when that
    figure is **strictly greater** than the property's `laundry_sla_minutes`."

    Design: Corner/calculations/calc_turnaround_exactly_at_the_sla_is_not_a_breach_and_writes_off_missing_sets
    """
    scenario = build_scenario(
        api,
        property_overrides={"laundry_sla_minutes": 240, "laundry_capacity_sets": 300},
        rooms=["101"],
        linen={"total_owned_sets": 20, "initial_soiled_sets": 8},
        with_worker=False,
        with_inspector=False,
        with_day=False,
        with_roster=False,
    )
    before = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(before, 12, 0, 8)
    cycle = dispatch_cycle(
        api,
        scenario.linen_id,
        8,
        "2026-08-03T08:00:00.000Z",
        "2026-08-03T12:00:00.000Z",
        before["version"],
    )
    assert_linen_buckets(read_linen_item(api, scenario.linen_id), 12, 8, 0)

    returned = return_cycle(api, cycle["id"], "2026-08-03T12:00:00.000Z", 6)

    assert_whole_minutes(returned["turnaround_minutes"], 240, "turnaround_minutes")
    assert returned["sla_breach"] is False, (
        "240 minutes is not strictly greater than a 240-minute SLA"
    )
    assert returned["status"] == CYCLE_RETURNED
    line = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(line, 18, 0, 0)
    assert line["total_owned_sets"] == 18, (
        f"the two missing sets must be written off, got {line['total_owned_sets']}"
    )
    assert_coverage_ratio(line["coverage_ratio"], 9.0000)
    assert line["shortage_status"] == SHORTAGE_OK
    assert_linen_identity(line)
