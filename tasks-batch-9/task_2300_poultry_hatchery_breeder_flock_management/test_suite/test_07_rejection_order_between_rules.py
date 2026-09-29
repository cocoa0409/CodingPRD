"""Requests that break two rules at once, arranged so that the two candidate
rejections are far apart in the stated priority order.

Each pair is probed twice: once with both rules violated, to pin the code that must
win, and once with only the later rule violated, to prove the later rule is really
there and was merely masked.
"""

from test_helpers import (
    ApiClient,
    FLOCK_MANAGER,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    ApiErrorId,
    EggLotStatus,
    FlockStatus,
    LabResult,
    assert_breeder_flock,
    assert_egg_lot,
    assert_setter_load,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_success,
)

GRADE_6200 = {
    "grade_a_count": 6200,
    "cracked_count": 150,
    "dirty_count": 100,
    "small_count": 50,
}


class TestDrawVersionBeatsLotState:
    """A stale token against a condemned lot reports the token, not the state."""

    def _condemned_lot_and_planned_load(self, api: ApiClient):
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            storage_temp_c=15.0,
            collected_at="2026-07-30T00:00:00Z",
            collected_count=6500,
        )
        stale_version = lot["version"]
        unit = fx.sanitized_unit(api, code="U1", capacity_eggs=20000)
        profile = fx.create_profile(api)
        load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(unit["id"], profile["id"], "2026-08-01T18:00:00Z"),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        condemned = get_success_data(
            api.condemn_egg_lot(lot["id"], "SHELL_QUALITY", VETERINARIAN), 200
        )
        return {
            "load": load,
            "lot": condemned,
            "stale_version": stale_version,
            "current_version": condemned["version"],
        }

    def test_stale_version_wins_over_the_condemned_lot_state(self, api):
        """PRD 2.11: "`expected_egg_lot_version` or `expected_chick_batch_version` equal
        to the parent's current `version` — `ERR_STALE_VERSION` (412), on egg draws and
        allocation runs. Evaluated before any state or business rule." And PRD 2.11: "it
        is what makes a stale version against an ineligible parent report
        `ERR_STALE_VERSION` rather than a state error".

        Design: Difficulty/priority_pair_validation_conflict/items_stale_version_beats_egg_lot_state
        """
        ctx = self._condemned_lot_and_planned_load(api)
        assert_egg_lot(
            ctx["lot"],
            status=EggLotStatus.CONDEMNED.value,
            condemned_reason="SHELL_QUALITY",
            eggs_remaining=0,
            settable_count=6200,
        )
        assert ctx["stale_version"] < ctx["current_version"], (
            "condemnation must have advanced the lot's version"
        )

        response = api.draw_eggs(
            ctx["load"]["id"],
            f.draw_payload(ctx["lot"]["id"], 6000, ctx["stale_version"]),
            INCUBATION_OPERATOR,
        )

        validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)
        assert fx.list_items_of_load(api, ctx["load"]["id"]) == [], (
            "a rejected draw must not create a draw record"
        )
        assert_setter_load(fx.read_load(api, ctx["load"]["id"]), total_eggs_set=0)

    def test_current_version_then_exposes_the_lot_state_rejection(self, api):
        """PRD 2.11: "The egg lot admits the requested transition —
        `ERR_EGG_LOT_INVALID_STATE` (409), on grading, storing, sanitation hold,
        sanitation release, condemnation and egg draws. A lot in `CONSUMED` or `CONDEMNED`
        admits nothing; a `COLLECTED` lot cannot be stored; a `GRADED` lot cannot be drawn
        from."

        Design: Difficulty/priority_pair_validation_conflict/items_stale_version_beats_egg_lot_state
        """
        ctx = self._condemned_lot_and_planned_load(api)
        validate_error(
            api.draw_eggs(
                ctx["load"]["id"],
                f.draw_payload(ctx["lot"]["id"], 6000, ctx["stale_version"]),
                INCUBATION_OPERATOR,
            ),
            ApiErrorId.ERR_STALE_VERSION,
            412,
        )

        response = api.draw_eggs(
            ctx["load"]["id"],
            f.draw_payload(ctx["lot"]["id"], 6000, ctx["current_version"]),
            INCUBATION_OPERATOR,
        )

        validate_error(response, ApiErrorId.ERR_EGG_LOT_INVALID_STATE, 409)
        assert fx.list_items_of_load(api, ctx["load"]["id"]) == [], (
            "neither attempt may create a draw record"
        )
        assert_egg_lot(
            fx.read_lot(api, ctx["lot"]["id"]),
            status=EggLotStatus.CONDEMNED.value,
            eggs_remaining=0,
        )


class TestStartLayClearanceBeatsMaturity:
    """A young, untested flock reports the missing clearance first."""

    def _young_untested_flock(self, api: ApiClient):
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.create_flock(
            api,
            program["id"],
            code="F2",
            house_code="H2",
            hatch_date="2026-03-16T00:00:00Z",
            placed_at="2026-07-01T00:00:00Z",
            hen_count=8000,
        )
        return {"program": program, "flock": flock}

    def test_missing_clearance_wins_over_the_immature_flock(self, api):
        """PRD 2.11: "Salmonella clearance on record — `ERR_LAB_CLEARANCE_MISSING` (422),
        on photostimulation and egg-hold release. A `PENDING` or `INVALID` test never
        clears a flock." And PRD 2.11: "The flock is old enough to photostimulate —
        `ERR_FLOCK_NOT_MATURE` (422), on photostimulation."

        Design: Difficulty/priority_pair_validation_conflict/start_lay_lab_clearance_beats_maturity
        """
        ctx = self._young_untested_flock(api)
        assert_breeder_flock(ctx["flock"], age_weeks=19, status=FlockStatus.PLACED.value)

        response = api.start_lay(ctx["flock"]["id"], FLOCK_MANAGER)

        validate_error(response, ApiErrorId.ERR_LAB_CLEARANCE_MISSING, 422)
        after = fx.read_flock(api, ctx["flock"]["id"])
        assert_breeder_flock(
            after, status=FlockStatus.PLACED.value, settable_forecast=0
        )

    def test_clearing_the_flock_then_exposes_the_maturity_gate(self, api):
        """PRD 3.2: "Three gates guard that step beyond the state check itself: the flock's
        `age_weeks` must be at least the `stimulation_week` of its programme, and exactly
        equal is acceptable, otherwise `ERR_FLOCK_NOT_MATURE`; at least one laboratory test
        against this flock with a `test_code` of `SALMONELLA_PULLORUM` must have reached
        `NEGATIVE`, otherwise `ERR_LAB_CLEARANCE_MISSING`; and the programme must not be
        retired, otherwise `ERR_PROGRAM_RETIRED`."

        Design: Difficulty/priority_pair_validation_conflict/start_lay_lab_clearance_beats_maturity
        """
        ctx = self._young_untested_flock(api)
        validate_error(
            api.start_lay(ctx["flock"]["id"], FLOCK_MANAGER),
            ApiErrorId.ERR_LAB_CLEARANCE_MISSING,
            422,
        )
        test = fx.register_lab_test(
            api, ctx["flock"]["id"], collected_at="2026-07-25T00:00:00Z"
        )
        released = fx.release_lab_test(api, test["id"], LabResult.NEGATIVE.value)
        assert released["result"] == LabResult.NEGATIVE.value

        response = api.start_lay(ctx["flock"]["id"], FLOCK_MANAGER)

        validate_error(response, ApiErrorId.ERR_FLOCK_NOT_MATURE, 422)
        after = fx.read_flock(api, ctx["flock"]["id"])
        assert_breeder_flock(
            after,
            status=FlockStatus.PLACED.value,
            age_weeks=19,
            settable_forecast=0,
        )


class TestDrawAgeBeatsInsufficientEggs:
    """An over-large draw from an over-aged lot reports the age."""

    def _old_and_fresh_lots(self, api: ApiClient):
        fx.set_clock(api, "2026-07-21T00:00:00Z")
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        old_lot = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            storage_temp_c=18.0,
            collected_at="2026-07-21T00:00:00Z",
            collected_count=6500,
        )
        unit = fx.sanitized_unit(api, code="U1", capacity_eggs=20000)
        profile = fx.create_profile(api)
        load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(unit["id"], profile["id"], "2026-08-05T00:00:00Z"),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fresh_lot = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            storage_temp_c=15.0,
            collected_at="2026-07-30T00:00:00Z",
            collected_count=6500,
        )
        return {"old_lot": old_lot, "fresh_lot": fresh_lot, "load": load}

    def test_over_aged_lot_wins_over_the_oversized_draw(self, api):
        """PRD 2.11: "The lot is young enough to set — `ERR_EGG_TOO_OLD` (422), on egg
        draws." And PRD 2.11: "A draw never exceeds the lot's remaining settable eggs —
        `ERR_INSUFFICIENT_SETTABLE_EGGS` (422), on egg draws."

        Design: Difficulty/priority_pair_validation_conflict/draw_egg_too_old_beats_insufficient_eggs
        """
        ctx = self._old_and_fresh_lots(api)
        old_lot = fx.read_lot(api, ctx["old_lot"]["id"])
        assert_two_dp(old_lot["effective_age_days"], 11.00, "effective_age_days")
        assert_egg_lot(old_lot, eggs_remaining=6200)

        response = api.draw_eggs(
            ctx["load"]["id"],
            f.draw_payload(old_lot["id"], 9000, old_lot["version"]),
            INCUBATION_OPERATOR,
        )

        validate_error(response, ApiErrorId.ERR_EGG_TOO_OLD, 422)
        assert fx.list_items_of_load(api, ctx["load"]["id"]) == [], (
            "a rejected draw must not create a draw record"
        )
        assert_egg_lot(
            fx.read_lot(api, old_lot["id"]),
            status=EggLotStatus.IN_STORAGE.value,
            eggs_remaining=6200,
        )

    def test_a_young_enough_lot_then_exposes_the_shortfall(self, api):
        """PRD 3.5: "And `eggs_taken` must not exceed the lot's `eggs_remaining`, or
        `ERR_INSUFFICIENT_SETTABLE_EGGS`; egg conservation is what makes this exact, so
        two draws of 4000 eggs against a 6000-egg lot fail on the second, not the first."

        Design: Difficulty/priority_pair_validation_conflict/draw_egg_too_old_beats_insufficient_eggs
        """
        ctx = self._old_and_fresh_lots(api)
        old_lot = fx.read_lot(api, ctx["old_lot"]["id"])
        validate_error(
            api.draw_eggs(
                ctx["load"]["id"],
                f.draw_payload(old_lot["id"], 9000, old_lot["version"]),
                INCUBATION_OPERATOR,
            ),
            ApiErrorId.ERR_EGG_TOO_OLD,
            422,
        )
        fresh_lot = fx.read_lot(api, ctx["fresh_lot"]["id"])
        assert_two_dp(fresh_lot["effective_age_days"], 2.00, "effective_age_days")

        response = api.draw_eggs(
            ctx["load"]["id"],
            f.draw_payload(fresh_lot["id"], 9000, fresh_lot["version"]),
            INCUBATION_OPERATOR,
        )

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SETTABLE_EGGS, 422)
        assert fx.list_items_of_load(api, ctx["load"]["id"]) == [], (
            "neither attempt may create a draw record"
        )
        assert_setter_load(fx.read_load(api, ctx["load"]["id"]), total_eggs_set=0)
        for lot_id in (ctx["old_lot"]["id"], ctx["fresh_lot"]["id"]):
            assert_egg_lot(
                fx.read_lot(api, lot_id),
                status=EggLotStatus.IN_STORAGE.value,
                eggs_remaining=6200,
            )

    def test_the_fresh_lot_is_drawable_within_its_remaining_eggs(self, api):
        """PRD 3.5: "The lot's `eggs_remaining` is reduced by `eggs_taken`, the lot moves
        `IN_STORAGE → ALLOCATED` on the first draw and stays in `ALLOCATED` on every
        further draw into another planned load, the load's `total_eggs_set` and
        `weighted_age_days` are recomputed over its `ACTIVE` draws, and the lot's `version`
        increments by 1."

        Design: Difficulty/priority_pair_validation_conflict/draw_egg_too_old_beats_insufficient_eggs
        """
        ctx = self._old_and_fresh_lots(api)
        fresh_lot = fx.read_lot(api, ctx["fresh_lot"]["id"])

        response = api.draw_eggs(
            ctx["load"]["id"],
            f.draw_payload(fresh_lot["id"], 6200, fresh_lot["version"]),
            INCUBATION_OPERATOR,
        )

        item = validate_success(response, 201)
        assert item["eggs_taken"] == 6200
        assert_egg_lot(
            fx.read_lot(api, fresh_lot["id"]),
            status=EggLotStatus.ALLOCATED.value,
            eggs_remaining=0,
        )
        assert_setter_load(fx.read_load(api, ctx["load"]["id"]), total_eggs_set=6200)
