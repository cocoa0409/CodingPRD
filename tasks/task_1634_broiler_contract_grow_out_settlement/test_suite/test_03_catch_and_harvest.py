"""Catch scheduling, weighing, and harvest cascades (PRD §3.5, §2.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_catch_schedule,
    create_catch_crew_payload,
    create_catch_schedule_payload,
    create_contract_payload,
    create_grower_payload,
    create_house_payload,
    create_settlement_group_payload,
    get_success_data,
    plan_flock,
    place_flock,
    record_feed,
    record_weight_ticket,
    schedule_catch,
    set_logical_clock,
    setup_growing_flock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
LIVEHAUL = TEST_USERS["livehaul_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def _growing_flock(api, grower, contract, group, house, flock_no,
                   placed_head=1000, feed_lbs=1000, ticket_no="FT-X",
                   placed_date="2026-08-01", feed_date="2026-08-05"):
    """Plan + place + one feed delivery on an existing grower/contract/group."""
    flock = plan_flock(house["id"], contract["id"], group["id"], flock_no)
    place_flock(flock["id"], placed_date, placed_head)
    record_feed(flock["id"], feed_lbs, feed_date, "STARTER", ticket_no)
    return get_success_data(api.get_flock(flock["id"], ADMIN))


class TestCrewDailyCapacityAtExactlyMax:
    def _setup_two_growing_flocks(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-B2",
                                                    full_name="Boundary Grower 2"),
                              ADMIN))
        house1 = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=5000), ADMIN))
        house2 = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H2",
                                                  capacity_birds=5000), ADMIN))
        contract = get_success_data(
            api.create_contract(
                create_contract_payload(grower["id"], contract_no="C-B2",
                                        committed_house_count=2), ADMIN))
        get_success_data(api.activate_contract(contract["id"], ADMIN))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-42",
                                                week_ending_date="2026-11-21"),
                ANALYST))
        flock1 = _growing_flock(api, grower, contract, group, house1, "F-B21",
                                ticket_no="FT-B21")
        flock2 = _growing_flock(api, grower, contract, group, house2, "F-B22",
                                ticket_no="FT-B22")
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-B2",
                                          max_catches_per_day=1), LIVEHAUL))
        set_logical_clock("2026-09-10T00:00:00Z")
        return flock1, flock2, crew

    def test_booking_at_exactly_daily_max_succeeds(self, api, livehaul_headers):
        """PRD §3.5: "Two temporal guards protect the schedule, evaluated in
        the fixed priority order of §2.8: the crew must not already be
        committed to `max_catches_per_day` catches in `SCHEDULED` or
        `COMPLETED` status on that `catch_date` — a violation is
        `ERR_CREW_OVERBOOKED` (HTTP 409) — and the flock's age, computed as the
        current logical date minus its `placed_date`, must be at least 35 days
        — a violation is `ERR_FLOCK_TOO_YOUNG` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/crew_daily_capacity_at_exactly_max
        """
        flock1, _flock2, crew = self._setup_two_growing_flocks(api)

        schedule = validate_success(
            api.schedule_catch(flock1["id"], create_catch_schedule_payload(
                crew["id"], catch_date="2026-09-10"), livehaul_headers),
            expected_status=201)
        assert_catch_schedule(schedule)
        assert schedule["status"] == "SCHEDULED"
        flock1_after = validate_success(api.get_flock(flock1["id"], ADMIN))
        assert flock1_after["status"] == "CATCH_SCHEDULED"

    def test_booking_beyond_daily_max_rejected(self, api, livehaul_headers):
        """PRD §3.5: "the crew must not already be committed to
        `max_catches_per_day` catches in `SCHEDULED` or `COMPLETED` status on
        that `catch_date` — a violation is `ERR_CREW_OVERBOOKED` (HTTP 409)".

        Design: Difficulty/boundary_precision_check/crew_daily_capacity_at_exactly_max
        """
        flock1, flock2, crew = self._setup_two_growing_flocks(api)
        get_success_data(
            api.schedule_catch(flock1["id"], create_catch_schedule_payload(
                crew["id"], catch_date="2026-09-10"), livehaul_headers))

        resp = api.schedule_catch(flock2["id"], create_catch_schedule_payload(
            crew["id"], catch_date="2026-09-10"), livehaul_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_OVERBOOKED)

        flock2_after = validate_success(api.get_flock(flock2["id"], ADMIN))
        assert flock2_after["status"] == "GROWING", \
            "a rejected catch schedule must leave the flock untouched"


class TestCrewSameDayAggregateCapacity:
    def _setup_three_growing_flocks(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-T2",
                                                    full_name="Temporal Grower 2"),
                              ADMIN))
        houses = [
            get_success_data(
                api.create_house(create_house_payload(
                    grower["id"], house_no=f"H{i}", capacity_birds=5000), ADMIN))
            for i in (1, 2, 3)
        ]
        contract = get_success_data(
            api.create_contract(
                create_contract_payload(grower["id"], contract_no="C-T2",
                                        committed_house_count=3), ADMIN))
        get_success_data(api.activate_contract(contract["id"], ADMIN))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-45",
                                                week_ending_date="2026-12-12"),
                ANALYST))
        flocks = [
            _growing_flock(api, grower, contract, group, houses[i],
                           f"F-T2{i + 1}", ticket_no=f"FT-T2{i + 1}")
            for i in range(3)
        ]
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-T2",
                                          max_catches_per_day=2), LIVEHAUL))
        set_logical_clock("2026-09-10T00:00:00Z")
        return flocks, crew

    def test_third_same_day_booking_rejected(self, api, livehaul_headers):
        """PRD §3.5: "the crew must not already be committed to
        `max_catches_per_day` catches in `SCHEDULED` or `COMPLETED` status on
        that `catch_date` — a violation is `ERR_CREW_OVERBOOKED` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/crew_same_day_aggregate_capacity_overlap
        """
        flocks, crew = self._setup_three_growing_flocks(api)
        for flock in flocks[:2]:
            get_success_data(
                api.schedule_catch(flock["id"], create_catch_schedule_payload(
                    crew["id"], catch_date="2026-09-10"), livehaul_headers))

        resp = api.schedule_catch(flocks[2]["id"], create_catch_schedule_payload(
            crew["id"], catch_date="2026-09-10"), livehaul_headers)
        validate_error(resp, ApiErrorId.ERR_CREW_OVERBOOKED)

    def test_same_flock_next_day_booking_succeeds(self, api, livehaul_headers):
        """PRD §3.5: "the crew must not already be committed to
        `max_catches_per_day` catches in `SCHEDULED` or `COMPLETED` status on
        that `catch_date`" — capacity is a per-day aggregate over the catch
        date, so the next date is a fresh pool.

        Design: Difficulty/resource_temporal_overlap/crew_same_day_aggregate_capacity_overlap
        """
        flocks, crew = self._setup_three_growing_flocks(api)
        for flock in flocks[:2]:
            get_success_data(
                api.schedule_catch(flock["id"], create_catch_schedule_payload(
                    crew["id"], catch_date="2026-09-10"), livehaul_headers))
        validate_error(
            api.schedule_catch(flocks[2]["id"], create_catch_schedule_payload(
                crew["id"], catch_date="2026-09-10"), livehaul_headers),
            ApiErrorId.ERR_CREW_OVERBOOKED)

        schedule = validate_success(
            api.schedule_catch(flocks[2]["id"], create_catch_schedule_payload(
                crew["id"], catch_date="2026-09-11"), livehaul_headers),
            expected_status=201)
        assert schedule["status"] == "SCHEDULED"
        flock3 = validate_success(api.get_flock(flocks[2]["id"], ADMIN))
        assert flock3["status"] == "CATCH_SCHEDULED"


class TestYoungFlockCatch:
    def _setup_young_flock(self, api):
        """Flock placed 2026-08-20 (clock set first), GROWING via one delivery;
        logical clock advanced to 2026-09-01 -> age 12 days."""
        set_logical_clock("2026-08-20T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-P2",
                                                    full_name="Priority Grower 2"),
                              ADMIN))
        house = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=10000), ADMIN))
        contract = get_success_data(
            api.create_contract(create_contract_payload(grower["id"],
                                                        contract_no="C-P2"),
                                ADMIN))
        get_success_data(api.activate_contract(contract["id"], ADMIN))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-40",
                                                week_ending_date="2026-11-07"),
                ANALYST))
        flock = plan_flock(house["id"], contract["id"], group["id"], "F-P2")
        place_flock(flock["id"], "2026-08-20", 5000)
        record_feed(flock["id"], 1000, "2026-08-21", "STARTER", "FT-P2")
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-P2",
                                          max_catches_per_day=2), LIVEHAUL))
        set_logical_clock("2026-09-01T00:00:00Z")
        return flock, crew

    def test_catch_on_flock_younger_than_35_days_rejected(
            self, api, livehaul_headers):
        """PRD §3.5: "the flock's age, computed as the current logical date
        minus its `placed_date`, must be at least 35 days — a violation is
        `ERR_FLOCK_TOO_YOUNG` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_before_constraint_on_young_flock_over_capacity_catch
        """
        flock, crew = self._setup_young_flock(api)

        resp = api.schedule_catch(flock["id"], create_catch_schedule_payload(
            crew["id"], catch_date="2026-09-01"), livehaul_headers)
        validate_error(resp, ApiErrorId.ERR_FLOCK_TOO_YOUNG)

    def test_rejected_young_flock_catch_leaves_flock_growing(
            self, api, livehaul_headers):
        """PRD §3.5: "Scheduling a catch for a flock creates a `CatchSchedule`
        naming the `crew_id` and the `catch_date`, moves the flock `GROWING` →
        `CATCH_SCHEDULED`, and starts the schedule in `SCHEDULED` status."
        PRD §3.5: "the flock's age, computed as the current logical date minus
        its `placed_date`, must be at least 35 days — a violation is
        `ERR_FLOCK_TOO_YOUNG` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_before_constraint_on_young_flock_over_capacity_catch
        """
        flock, crew = self._setup_young_flock(api)
        validate_error(
            api.schedule_catch(flock["id"], create_catch_schedule_payload(
                crew["id"], catch_date="2026-09-01"), livehaul_headers),
            ApiErrorId.ERR_FLOCK_TOO_YOUNG)

        after = validate_success(api.get_flock(flock["id"], ADMIN))
        assert after["status"] == "GROWING", \
            "a rejected catch schedule must not move the flock"
        schedules = validate_success(api.list_catch_schedules(flock["id"], ADMIN))
        assert schedules == [], "no schedule row may be left behind"


class TestCatchCancelRestores:
    def _setup_catch_scheduled(self, api):
        ctx = setup_growing_flock(grower_code="G-I2", full_name="Invariant Grower 2",
                                  contract_no="C-I2", group_code="WK-47",
                                  week_ending_date="2026-12-26", flock_no="F-I2",
                                  placed_head=1000, feed_lbs=1000,
                                  set_clock_to="2026-08-01T00:00:00Z")
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-I2",
                                          max_catches_per_day=1), LIVEHAUL))
        set_logical_clock("2026-09-10T00:00:00Z")
        schedule = schedule_catch(ctx["flock"]["id"], crew["id"], "2026-09-10")
        return ctx, crew, schedule

    def test_cancel_returns_flock_to_growing(self, api, livehaul_headers):
        """PRD §3.5: "A catch schedule may instead be cancelled while
        `SCHEDULED`, which returns the flock `CATCH_SCHEDULED` → `GROWING` and
        moves the schedule to `CANCELLED`."

        Design: Difficulty/compensating_invariant/catch_cancel_restores_flock_and_crew_capacity
        """
        ctx, _crew, schedule = self._setup_catch_scheduled(api)
        assert validate_success(api.get_flock(ctx["flock"]["id"], ADMIN)
                                )["status"] == "CATCH_SCHEDULED"

        cancelled = validate_success(api.cancel_catch(schedule["id"],
                                                      livehaul_headers))
        assert cancelled["status"] == "CANCELLED"
        flock = validate_success(api.get_flock(ctx["flock"]["id"], ADMIN))
        assert flock["status"] == "GROWING"

    def test_cancelled_booking_releases_crew_capacity(self, api,
                                                      livehaul_headers):
        """PRD §3.5: "the crew must not already be committed to
        `max_catches_per_day` catches in `SCHEDULED` or `COMPLETED` status on
        that `catch_date`" — a CANCELLED schedule is neither, so the slot is
        released.
        PRD §3.5: "A catch schedule may instead be cancelled while
        `SCHEDULED`, which returns the flock `CATCH_SCHEDULED` → `GROWING` and
        moves the schedule to `CANCELLED`."

        Design: Difficulty/compensating_invariant/catch_cancel_restores_flock_and_crew_capacity
        """
        ctx, crew, schedule = self._setup_catch_scheduled(api)
        get_success_data(api.cancel_catch(schedule["id"], livehaul_headers))

        rebooked = validate_success(
            api.schedule_catch(ctx["flock"]["id"],
                               create_catch_schedule_payload(
                                   crew["id"], catch_date="2026-09-10"),
                               livehaul_headers),
            expected_status=201)
        assert rebooked["status"] == "SCHEDULED", \
            "schedule+cancel conserves the crew's same-day booking count"


class TestCatchComplete:
    def test_complete_without_weight_ticket_rejected(self, api,
                                                     livehaul_headers):
        """PRD §3.5: "Completing the catch is the harvest event, performed by
        the `LivehaulScheduler` once at least one weight ticket exists for the
        flock."
        PRD §2.8: "5. Transition legality — the target entity is in a
        from-state of the requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/endpoints/catch_complete_without_weight_ticket_rejected
        """
        ctx = setup_growing_flock(grower_code="G-E2", full_name="Endpoint Two",
                                  contract_no="C-E2", group_code="WK-E2",
                                  flock_no="F-E2", set_clock_to="2026-08-01T00:00:00Z")
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-E2",
                                          max_catches_per_day=2), LIVEHAUL))
        set_logical_clock("2026-09-10T00:00:00Z")
        schedule = schedule_catch(ctx["flock"]["id"], crew["id"], "2026-09-10")

        resp = api.complete_catch(schedule["id"], livehaul_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        flock = validate_success(api.get_flock(ctx["flock"]["id"], ADMIN))
        assert flock["status"] == "CATCH_SCHEDULED"
        schedules = validate_success(
            api.list_catch_schedules(ctx["flock"]["id"], ADMIN))
        by_id = {s["id"]: s for s in schedules}
        assert by_id[schedule["id"]]["status"] == "SCHEDULED"

    def _setup_catch_scheduled_with_ticket(self, api):
        ctx = setup_growing_flock(grower_code="G-C3", full_name="Cascade Grower",
                                  contract_no="C-C3", group_code="WK-37",
                                  week_ending_date="2026-10-17", flock_no="F-C3",
                                  set_clock_to="2026-08-01T00:00:00Z")
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-C3",
                                          max_catches_per_day=2), LIVEHAUL))
        set_logical_clock("2026-09-10T00:00:00Z")
        schedule = schedule_catch(ctx["flock"]["id"], crew["id"], "2026-09-10")
        record_weight_ticket(ctx["flock"]["id"], "WT-C3",
                             "2026-09-10T08:00:00Z", 5000)
        return ctx, schedule

    def test_complete_harvests_flock_and_computes_adj_fcr(
            self, api, livehaul_headers):
        """PRD §3.5: "Completion moves the schedule `SCHEDULED` → `COMPLETED`
        and fires a four-way cascade: the flock transitions `CATCH_SCHEDULED` →
        `HARVESTED`, its `adj_fcr` is computed, and its `livability_pct` and
        `condemnation_pct` are finalized".
        PRD §3.5: "The adjusted ratio — the one that actually feeds the
        tournament — subtracts a standard feed-waste credit of 2,000 pounds
        from the delivered total before dividing by `live_weight_lbs`".

        Design: Difficulty/transitive_cascade/catch_complete_cascade_depth3
        """
        ctx, schedule = self._setup_catch_scheduled_with_ticket(api)

        completed = validate_success(api.complete_catch(schedule["id"],
                                                        livehaul_headers))
        assert completed["status"] == "COMPLETED"

        flock = validate_success(api.get_flock(ctx["flock"]["id"], ADMIN))
        assert flock["status"] == "HARVESTED"
        # (10000 - 2000) / 5000 = 1.6, rounded half-up to 4 decimal places.
        assert flock["adj_fcr"] == pytest.approx(1.6, abs=1e-9)

    def test_complete_cascades_to_house_downtime_and_group_average(
            self, api, livehaul_headers):
        """PRD §3.5: "the house transitions `PLACED` → `DOWNTIME` with
        `downtime_until` set to the catch date plus fourteen days; the grower's
        `house_count` is recomputed; and the settlement group's averages are
        recomputed to include this flock."

        Design: Difficulty/transitive_cascade/catch_complete_cascade_depth3
        """
        ctx, schedule = self._setup_catch_scheduled_with_ticket(api)
        get_success_data(api.complete_catch(schedule["id"], livehaul_headers))

        house = validate_success(api.get_house(ctx["house"]["id"], ADMIN))
        assert house["house_status"] == "DOWNTIME"
        assert house["downtime_until"] == "2026-09-24", \
            "catch date 2026-09-10 plus fourteen days"

        group = validate_success(
            api.get_settlement_group(ctx["group"]["id"], ANALYST))
        assert group["group_avg_fcr"] == pytest.approx(1.6, abs=1e-9), \
            "the single HARVESTED member's adj_fcr becomes the group average"


class TestImmediateConsistency:
    def test_reads_after_complete_observe_full_cascade(self, api,
                                                       livehaul_headers):
        """PRD §3.5: "Completion moves the schedule `SCHEDULED` → `COMPLETED`
        and fires a four-way cascade: the flock transitions `CATCH_SCHEDULED` →
        `HARVESTED`, its `adj_fcr` is computed, and its `livability_pct` and
        `condemnation_pct` are finalized; the house transitions `PLACED` →
        `DOWNTIME` with `downtime_until` set to the catch date plus fourteen
        days; the grower's `house_count` is recomputed; and the settlement
        group's averages are recomputed to include this flock."

        Design: Corner/consistency_model/immediate_consistency_of_cascade_in_same_read
        """
        ctx = setup_growing_flock(grower_code="G-IC",
                                  full_name="Immediate Consistency",
                                  contract_no="C-IC", group_code="WK-IC",
                                  flock_no="F-IC",
                                  set_clock_to="2026-08-01T00:00:00Z")
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-IC",
                                          max_catches_per_day=2), LIVEHAUL))
        set_logical_clock("2026-09-10T00:00:00Z")
        schedule = schedule_catch(ctx["flock"]["id"], crew["id"], "2026-09-10")
        record_weight_ticket(ctx["flock"]["id"], "WT-IC",
                             "2026-09-10T08:00:00Z", 5000)

        get_success_data(api.complete_catch(schedule["id"], livehaul_headers))

        # The GETs issued immediately after completion observe every hop.
        flock = validate_success(api.get_flock(ctx["flock"]["id"], ADMIN))
        assert flock["status"] == "HARVESTED"
        assert flock["adj_fcr"] == pytest.approx(1.6, abs=1e-9)
        house = validate_success(api.get_house(ctx["house"]["id"], ADMIN))
        assert house["house_status"] == "DOWNTIME"
        assert house["downtime_until"] == "2026-09-24"
        group = validate_success(
            api.get_settlement_group(ctx["group"]["id"], ANALYST))
        assert group["group_avg_fcr"] == pytest.approx(1.6, abs=1e-9)


class TestLogicalClockDefault:
    def test_clock_defaults_to_fixed_startup_instant(self, api,
                                                     livehaul_headers):
        """PRD §2.9: "The logical clock's startup default, before any operator
        intervention, is exactly 2026-08-01T00:00:00Z, and it never falls back
        to wall-clock time."
        PRD §3.5: "the flock's age, computed as the current logical date minus
        its `placed_date`, must be at least 35 days — a violation is
        `ERR_FLOCK_TOO_YOUNG` (HTTP 422)."

        Design: Corner/cross_cutting_complexity_layers/clock_default_is_fixed_startup_instant
        """
        # The clock is never set: placement confirms against the startup
        # default, so the flock's age is 0 days no matter the wall clock.
        ctx = setup_growing_flock(grower_code="G-CLK", full_name="Clock Grower",
                                  contract_no="C-CLK", group_code="WK-CLK",
                                  flock_no="F-CLK", placed_head=1000,
                                  feed_lbs=1000, placed_date="2026-08-01",
                                  feed_date="2026-08-02", set_clock_to=None)
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-CLK",
                                          max_catches_per_day=2), LIVEHAUL))

        resp = api.schedule_catch(ctx["flock"]["id"],
                                  create_catch_schedule_payload(
                                      crew["id"], catch_date="2026-08-20"),
                                  livehaul_headers)
        validate_error(resp, ApiErrorId.ERR_FLOCK_TOO_YOUNG)
