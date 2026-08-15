"""Breeding seasons, the bull battery, turnout temporal rules, BSE retests,
and supplement program cost accumulation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_aum,
    assert_date_field,
    begin_breeding,
    create_breeding_season,
    create_bull,
    create_herd_group,
    create_ranch,
    create_supplement_program,
    get_success_data,
    record_bse,
    record_delivery,
    schedule_turnout,
    set_clock,
    turn_in_turnout,
    validate_error,
    validate_success,
)

HERD_MGR = TEST_USERS["herd_manager_headers"]


class TestBullBatteryGate:
    def _setup_battery(self, api):
        """Season needing 3 bulls (exposed 51); B1, B2 PASSED, B3 FAILED; all
        three turned in."""
        ranch = create_ranch(name="Battery Ranch", hq_state="MT")
        group = create_herd_group(ranch["id"], group_name="Cows", head_count=60)
        season = create_breeding_season(ranch["id"], group["id"],
                                        exposed_head_count=51)
        bulls = [create_bull(ranch["id"], tag=f"B{i}") for i in (1, 2, 3)]
        record_bse(bulls[0]["id"], result="PASSED", exam_date="2026-03-01")
        record_bse(bulls[1]["id"], result="PASSED", exam_date="2026-03-01")
        record_bse(bulls[2]["id"], result="FAILED", exam_date="2026-03-01",
                   scrotal_cm=29.0)
        for b in bulls:
            t = schedule_turnout(b["id"], season["id"], ranch["id"])
            turn_in_turnout(t["id"])
        # Keep the exams fresh against the battery evaluation clock.
        set_clock("2026-04-15T00:00:00Z")
        return ranch, season, bulls

    def test_insufficient_battery_rejected(self, api):
        """PRD §3.4: "Advancing the season from `PLANNED` to `BREEDING` counts
        this season's turnouts that are `TURNED_IN` whose bulls are still
        `ACTIVE` in life and whose `bse_status` is `PASSED` — with lazy expiry
        applied against the current date at evaluation time — and if that count
        falls short of the season's `required_bull_count`, the advance is
        rejected with `ERR_BULL_BATTERY_INSUFFICIENT` (HTTP 422)."
        PRD §3.4: "The system derives the season's `required_bull_count` at one
        bull for every 25 exposed females, rounded up to a whole bull."

        Design: Difficulty/cross_entity_state_dependency/begin_breeding_requires_bull_battery
        """
        _ranch, season, _bulls = self._setup_battery(api)
        season = get_success_data(api.get_breeding_season(season["id"], HERD_MGR))
        assert season["required_bull_count"] == 3, "ceil(51/25) == 3"
        resp = api.begin_breeding(season["id"], HERD_MGR)
        # Only 2 of the 3 TURNED_IN bulls are qualified (B3 FAILED).
        validate_error(resp, ApiErrorId.ERR_BULL_BATTERY_INSUFFICIENT,
                       expected_status=422)

    def test_retested_bull_completes_battery(self, api):
        """PRD §3.4: "A `FAILED` result moves the bull to `FAILED` from any
        prior state, and a later `PASSED` result — a retest — returns the bull
        to `PASSED` from `FAILED`, from `EXPIRED`, or even from a previous
        `PASSED`; the retest loop is cyclic and unrestricted."
        PRD §3.4: "Breeding begins only when the battery is sufficient."

        Design: Difficulty/cross_entity_state_dependency/begin_breeding_requires_bull_battery
        """
        _ranch, season, bulls = self._setup_battery(api)
        resp = api.begin_breeding(season["id"], HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_BULL_BATTERY_INSUFFICIENT)
        # Retest the FAILED bull; now all three qualify.
        record_bse(bulls[2]["id"], result="PASSED", exam_date="2026-04-20",
                   scrotal_cm=31.0)
        set_clock("2026-04-20T00:00:00Z")
        after = begin_breeding(season["id"])
        assert after["season_status"] == "BREEDING"


class TestTurnoutTemporalRules:
    def _setup(self, api):
        """One bull with a SCHEDULED turnout on S1 (2026-04-15..2026-06-15)."""
        ranch = create_ranch(name="Turn Ranch", hq_state="CO")
        group = create_herd_group(ranch["id"], group_name="Cows", head_count=60)
        s1 = create_breeding_season(ranch["id"], group["id"],
                                    exposed_head_count=25)
        s2 = create_breeding_season(
            ranch["id"], group["id"], planned_turnout_date="2026-06-21",
            planned_removal_date="2026-08-15", exposed_head_count=25)
        bull = create_bull(ranch["id"], tag="B777", breed="CHAR",
                           birth_year=2020)
        t1 = schedule_turnout(bull["id"], s1["id"], ranch["id"])
        return ranch, s1, s2, bull, t1

    def test_closed_interval_overlap_rejected(self, api):
        """PRD §3.4: "First, the new closed interval may not intersect any
        existing `SCHEDULED` or `TURNED_IN` turnout of the same bull — an
        inclusive-intersection test — or the request fails with
        `ERR_BULL_TURNOUT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/bull_turnout_closed_interval_turnaround
        """
        ranch, s1, _s2, bull, _t1 = self._setup(api)
        resp = api.create_bull_turnout(
            {"bull_id": bull["id"], "breeding_season_id": s1["id"],
             "ranch_id": ranch["id"], "turnout_date": "2026-06-10",
             "planned_removal_date": "2026-06-15"}, HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_BULL_TURNOUT_OVERLAP,
                       expected_status=409)

    def test_turnaround_gap_boundary(self, api):
        """PRD §3.4: "Second, the bull must get its turnaround rest: fewer than
        7 days between the new turnout and any non-cancelled turnout of that
        bull, where the existing turnout's end is taken as its
        `actual_removal_date` when it was `REMOVED` and its
        `planned_removal_date` otherwise, fails with
        `ERR_BULL_TURNAROUND_TOO_SHORT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/bull_turnout_closed_interval_turnaround
        """
        ranch, _s1, s2, bull, _t1 = self._setup(api)
        # 2026-06-21 is 6 days after the prior turnout's 06-15 planned end.
        resp = api.create_bull_turnout(
            {"bull_id": bull["id"], "breeding_season_id": s2["id"],
             "ranch_id": ranch["id"], "turnout_date": "2026-06-21",
             "planned_removal_date": "2026-06-25"}, HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_BULL_TURNAROUND_TOO_SHORT,
                       expected_status=409)
        # Exactly 7 days passes — the bound is inclusive.
        ok = schedule_turnout(bull["id"], s2["id"], ranch["id"],
                              turnout_date="2026-06-22",
                              planned_removal_date="2026-06-25")
        assert ok["turnout_status"] == "SCHEDULED"


class TestBullLifecycle:
    def test_bse_retest_cycle_and_retire_terminal(self, api):
        """PRD §3.4: "A `FAILED` result moves the bull to `FAILED` from any
        prior state, and a later `PASSED` result — a retest — returns the bull
        to `PASSED` from `FAILED`, from `EXPIRED`, or even from a previous
        `PASSED`; the retest loop is cyclic and unrestricted."
        PRD §3.4: "A `HerdManager` retires a bull with a `disposition` of
        `SOLD`, `CULLED`, or `DEAD`, and the bull's `life_status` takes that
        value; all three are terminal."

        Design: Corner/state_machines/bull_bse_expiry_and_retest_cycle
        """
        ranch = create_ranch(name="R")
        b1 = create_bull(ranch["id"], tag="B1")
        b2 = create_bull(ranch["id"], tag="B2")
        b1 = record_bse(b1["id"], result="PASSED", exam_date="2026-03-01")
        assert b1["bse_status"] == "PASSED"
        b2 = record_bse(b2["id"], result="FAILED", exam_date="2026-03-01",
                        scrotal_cm=29.0)
        assert b2["bse_status"] == "FAILED"
        # Cyclic retest: FAILED -> PASSED.
        b2 = record_bse(b2["id"], result="PASSED", exam_date="2026-04-20",
                        scrotal_cm=31.0)
        assert b2["bse_status"] == "PASSED"
        assert_date_field(b2["last_bse_date"], "2026-04-20")

        retired = validate_success(api.retire_bull(
            b1["id"], {"disposition": "CULLED"}, HERD_MGR))
        assert retired["life_status"] == "CULLED"
        # Life status and BSE status are independent dimensions.
        assert retired["bse_status"] == "PASSED"

    def test_turnout_double_turnin_rejected(self, api):
        """PRD §3.4: "From `SCHEDULED`, the turnout is either turned in or
        cancelled. Turning in — moving `SCHEDULED` to `TURNED_IN` — is permitted
        while the season is `PLANNED` or `BREEDING`. Removing a turned-in bull
        moves the turnout to `REMOVED` and stamps its `actual_removal_date`
        from the supplied `removal_date`."
        PRD §2.8: "Generic transition validity: the requested transition exists
        from the resource's current, non-terminal state
        (`ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/turnout_double_turnin_rejected
        """
        ranch = create_ranch(name="R")
        group = create_herd_group(ranch["id"], group_name="G", head_count=60)
        season = create_breeding_season(ranch["id"], group["id"],
                                        exposed_head_count=25)
        bull = create_bull(ranch["id"], tag="B1")
        turnout = schedule_turnout(bull["id"], season["id"], ranch["id"])
        turned = turn_in_turnout(turnout["id"])
        assert turned["turnout_status"] == "TURNED_IN"

        resp = api.turn_in_turnout(turnout["id"], HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        from test_helpers import remove_turnout
        removed = remove_turnout(turnout["id"], removal_date="2026-06-15")
        assert removed["turnout_status"] == "REMOVED"
        assert_date_field(removed["actual_removal_date"], "2026-06-15")

    def test_turnout_outside_season_window_rejected(self, api):
        """PRD §3.4: "That interval must lie within the season's planned window,
        or scheduling fails with `ERR_TURNOUT_OUTSIDE_SEASON_WINDOW` (HTTP 422)."

        Design: Corner/validations/turnout_outside_season_window_rejected
        """
        ranch = create_ranch(name="R")
        group = create_herd_group(ranch["id"], group_name="G", head_count=60)
        season = create_breeding_season(ranch["id"], group["id"],
                                        planned_turnout_date="2026-04-15",
                                        planned_removal_date="2026-06-15",
                                        exposed_head_count=25)
        bull = create_bull(ranch["id"], tag="B1")
        resp = api.create_bull_turnout(
            {"bull_id": bull["id"], "breeding_season_id": season["id"],
             "ranch_id": ranch["id"], "turnout_date": "2026-04-01",
             "planned_removal_date": "2026-06-15"}, HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_TURNOUT_OUTSIDE_SEASON_WINDOW,
                       expected_status=422)


class TestExposureBound:
    def test_exposure_exceeds_group_rejected(self, api):
        """PRD §3.4: "The `exposed_head_count` — the number of females exposed —
        may not exceed the group's current `head_count`, or creation fails with
        `ERR_EXPOSURE_EXCEEDS_GROUP` (HTTP 422)."
        PRD §3.4: "The system derives the season's `required_bull_count` at one
        bull for every 25 exposed females, rounded up to a whole bull."

        Design: Corner/validations/exposure_exceeds_group_rejected
        """
        ranch = create_ranch(name="R")
        group = create_herd_group(ranch["id"], group_name="G", head_count=60)
        resp = api.create_breeding_season(
            {"ranch_id": ranch["id"], "herd_group_id": group["id"],
             "season_year": 2026, "planned_turnout_date": "2026-04-15",
             "planned_removal_date": "2026-06-15", "exposed_head_count": 61},
            HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_EXPOSURE_EXCEEDS_GROUP,
                       expected_status=422)
        season = create_breeding_season(ranch["id"], group["id"],
                                        exposed_head_count=60)
        assert season["required_bull_count"] == 3, "ceil(60/25) == 3"


class TestSupplementCosts:
    def test_supplement_cost_accumulation(self, api):
        """PRD §3.3: "Its `projected_consumption_lbs` is computed once from the
        group's `head_count` at creation: that head count, multiplied by the
        number of days in the feeding window counting both the first and last
        day, multiplied by the feed rate in ounces, and divided by 16 to convert
        ounces to pounds, rounded half-up to 2 decimal places."
        PRD §3.3: "each delivery records `delivered_lbs` and a `delivery_date`,
        adds the delivered weight into `delivered_lbs_total`, and recomputes
        `cost_to_date_cents` as the total delivered pounds divided by 2,000 to
        yield tons and multiplied by `cost_cents_per_ton`, rounded half-up to 2
        decimal places."
        PRD §3.3: "Completing a program moves it to `COMPLETED` and cancelling
        moves it to `CANCELLED`; both are terminal, and a program in either
        state refuses further deliveries or lifecycle actions with
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/calculations/supplement_cost_accumulation
        """
        ranch = create_ranch(name="R")
        group = create_herd_group(ranch["id"], group_name="G", head_count=50)
        program = create_supplement_program(
            group["id"], ranch["id"], start_date="2026-01-01",
            end_date="2026-02-28", feed_rate_oz_per_head_day=4,
            cost_cents_per_ton=240000)
        assert_aum(program["projected_consumption_lbs"], 737.5,
                   "50 head x 59 days x 4 oz / 16")

        program = record_delivery(program["id"], 500, "2026-01-10")
        assert_aum(program["cost_to_date_cents"], 60000.0, "0.25 t x 240000c")
        program = record_delivery(program["id"], 300, "2026-01-25")
        assert_aum(program["delivered_lbs_total"], 800)
        assert_aum(program["cost_to_date_cents"], 96000.0, "0.4 t x 240000c")

        program = validate_success(api.complete_program(program["id"], HERD_MGR))
        assert program["program_status"] == "COMPLETED"
        resp = api.record_delivery(
            program["id"], {"delivered_lbs": 50, "delivery_date": "2026-02-01"},
            HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        after = get_success_data(api.get_supplement_program(program["id"],
                                                            HERD_MGR))
        assert_aum(after["delivered_lbs_total"], 800, "terminal program frozen")
