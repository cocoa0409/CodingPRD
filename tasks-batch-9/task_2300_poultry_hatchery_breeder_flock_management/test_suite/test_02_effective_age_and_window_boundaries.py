"""Threshold precision: the settable-age limit, the deviation-open threshold and
the hatchability threshold.

Every one of these rules is stated with an explicit inclusive or exclusive
boundary, so each is probed at the value itself and at the first value past it.
"""

from test_helpers import (
    ApiClient,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    ApiErrorId,
    EggLotStatus,
    EnvironmentStatus,
    ItemStatus,
    SetterLoadStatus,
    assert_chick_batch,
    assert_egg_lot,
    assert_environment_reading,
    assert_forecast_chain,
    assert_instant,
    assert_setter_load,
    assert_setter_load_item,
    assert_three_dp,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

GRADE_6200 = {
    "grade_a_count": 6200,
    "cracked_count": 150,
    "dirty_count": 100,
    "small_count": 50,
}


class TestSettableAgeLimit:
    """Ten effective days is allowed; the sanitation penalty pushes past it."""

    def _two_cool_lots(self, api: ApiClient):
        """Two identical cool-stored lots, one of which has been round the fumigation loop."""
        fx.set_clock(api, "2026-07-21T00:00:00Z")
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot_a = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            storage_temp_c=18.0,
            collected_at="2026-07-21T00:00:00Z",
            collected_count=6500,
        )
        lot_b = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            storage_temp_c=18.0,
            collected_at="2026-07-21T00:00:00Z",
            collected_count=6500,
        )
        get_success_data(api.sanitation_hold_egg_lot(lot_b["id"], VETERINARIAN), 200)
        lot_b = get_success_data(
            api.sanitation_release_egg_lot(lot_b["id"], INCUBATION_OPERATOR), 200
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
        fx.set_clock(api, "2026-07-31T00:00:00Z")
        return {"lot_a": lot_a, "lot_b": lot_b, "load": load}

    def test_lot_at_exactly_ten_effective_days_may_still_be_drawn(self, api):
        """PRD 3.5: "The lot's `effective_age_days` at the instant of the draw must not
        exceed the maximum settable age of 10.00 effective days — exactly 10.00 is
        allowed, 10.01 is rejected with `ERR_EGG_TOO_OLD` — and because the sanitation
        penalty is part of `effective_age_days`, fumigation cycles count against this
        limit."

        Design: Difficulty/boundary_precision_check/egg_effective_age_exactly_ten_allowed_then_penalty_rejects
        """
        ctx = self._two_cool_lots(api)
        lot_a = fx.read_lot(api, ctx["lot_a"]["id"])
        assert_two_dp(lot_a["effective_age_days"], 10.00, "effective_age_days")
        assert lot_a["sanitation_cycle_count"] == 0

        response = api.draw_eggs(
            ctx["load"]["id"],
            f.draw_payload(lot_a["id"], 6000, lot_a["version"]),
            INCUBATION_OPERATOR,
        )
        item = validate_success(response, 201)

        assert_setter_load_item(
            item, eggs_taken=6000, item_status=ItemStatus.ACTIVE.value
        )
        assert_two_dp(
            item["effective_age_days_at_set"], 10.00, "effective_age_days_at_set"
        )
        assert_egg_lot(
            fx.read_lot(api, lot_a["id"]),
            status=EggLotStatus.ALLOCATED.value,
            eggs_remaining=200,
        )

    def test_sanitation_penalty_pushes_the_lot_past_the_settable_limit(self, api):
        """PRD 3.4: "To the scaled base, add a penalty of 0.75 effective days —
        three-quarters of a day, or 18 hours — for **each** completed sanitation cycle
        recorded in `sanitation_cycle_count`." And PRD 3.5: "exactly 10.00 is allowed,
        10.01 is rejected with `ERR_EGG_TOO_OLD`".

        Design: Difficulty/boundary_precision_check/egg_effective_age_exactly_ten_allowed_then_penalty_rejects
        """
        ctx = self._two_cool_lots(api)
        lot_a = fx.read_lot(api, ctx["lot_a"]["id"])
        fx.draw_eggs(api, ctx["load"]["id"], lot_a["id"], 6000, lot_a["version"])

        lot_b = fx.read_lot(api, ctx["lot_b"]["id"])
        assert_two_dp(lot_b["effective_age_days"], 10.75, "effective_age_days")
        assert lot_b["sanitation_cycle_count"] == 1

        response = api.draw_eggs(
            ctx["load"]["id"],
            f.draw_payload(lot_b["id"], 6000, lot_b["version"]),
            INCUBATION_OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_EGG_TOO_OLD, 422)

        assert_egg_lot(
            fx.read_lot(api, lot_b["id"]),
            status=EggLotStatus.IN_STORAGE.value,
            eggs_remaining=6200,
        )
        assert_setter_load(fx.read_load(api, ctx["load"]["id"]), total_eggs_set=6000)


class TestDeviationOpenThreshold:
    """A segment of exactly 1.500 degree-hours does not open the deviation."""

    def test_segment_of_exactly_the_threshold_leaves_the_dimension_nominal(self, api):
        """PRD 3.5: "If the segment just closed has `segment_degree_hours` strictly
        greater than the deviation-open threshold of 1.50 degree-hours, the load's
        `environment_status` becomes `DEVIATION_OPEN` and its `deviation_opened_at` is
        set to the ingested reading's `recorded_at` — a segment of exactly 1.500
        degree-hours does **not** open a deviation."

        Design: Difficulty/boundary_precision_check/segment_degree_hours_exactly_threshold_does_not_open
        """
        ctx = fx.incubating_load_context(api)
        fx.set_clock(api, "2026-08-02T06:00:00Z")

        first = fx.ingest_reading(api, ctx["load"]["id"], "2026-08-01T18:00:00Z", 38.6)
        second = fx.ingest_reading(api, ctx["load"]["id"], "2026-08-01T21:00:00Z", 38.6)

        assert_environment_reading(first)
        assert_two_dp(first["abs_deviation_c"], 0.80, "abs_deviation_c")
        assert_three_dp(first["segment_degree_hours"], 0.000, "segment_degree_hours")
        assert_three_dp(second["segment_degree_hours"], 1.500, "segment_degree_hours")

        load = fx.read_load(api, ctx["load"]["id"])
        assert_setter_load(
            load,
            status=SetterLoadStatus.INCUBATING.value,
            environment_status=EnvironmentStatus.NOMINAL.value,
        )
        assert load["deviation_opened_at"] is None, (
            "a segment at exactly the threshold must not stamp deviation_opened_at"
        )
        assert_three_dp(load["deviation_degree_hours"], 1.500, "deviation_degree_hours")

    def test_segment_just_above_the_threshold_opens_the_deviation(self, api):
        """PRD 3.5: "The segment's `segment_degree_hours` is the excess multiplied by
        the span, rounded half up to three decimal places. That figure is then added to
        the load's running `deviation_degree_hours`, which accumulates across the entire
        incubation and is never reset." And: "the load's `environment_status` becomes
        `DEVIATION_OPEN` and its `deviation_opened_at` is set to the ingested reading's
        `recorded_at`".

        Design: Difficulty/boundary_precision_check/segment_degree_hours_exactly_threshold_does_not_open
        """
        ctx = fx.incubating_load_context(api)
        fx.set_clock(api, "2026-08-02T06:00:00Z")
        fx.ingest_reading_sequence(
            api,
            ctx["load"]["id"],
            [("2026-08-01T18:00:00Z", 38.6), ("2026-08-01T21:00:00Z", 38.6)],
        )

        third = fx.ingest_reading(api, ctx["load"]["id"], "2026-08-02T00:10:00Z", 37.8)

        assert_three_dp(third["segment_degree_hours"], 1.583, "segment_degree_hours")
        load = fx.read_load(api, ctx["load"]["id"])
        assert_setter_load(
            load,
            status=SetterLoadStatus.INCUBATING.value,
            environment_status=EnvironmentStatus.DEVIATION_OPEN.value,
        )
        assert_instant(
            load["deviation_opened_at"], "2026-08-02T00:10:00Z", "deviation_opened_at"
        )
        assert_three_dp(load["deviation_degree_hours"], 3.083, "deviation_degree_hours")


class TestHatchabilityThreshold:
    """Exactly 82.00 percent is not strictly below the threshold."""

    def test_hatchability_at_exactly_the_threshold_opens_no_action(self, api):
        """PRD 3.9: "Only the set-basis figure gates corrective action, and the
        comparison is strictly less than. When a boxing recomputation leaves
        `hatchability_rolling_pct` strictly below the hatchability threshold of 82.0
        percent, the system automatically opens a **corrective action** against that
        flock."

        Design: Difficulty/boundary_precision_check/hatchability_exactly_threshold_opens_no_action
        """
        ctx = fx.threshold_hatchability_boxed_context(api)

        flock = fx.read_flock(api, ctx["flock"]["id"])
        assert_two_dp(
            flock["hatchability_rolling_pct"], 82.00, "hatchability_rolling_pct"
        )
        assert_two_dp(
            flock["hatchability_fertile_pct"], 91.11, "hatchability_fertile_pct"
        )
        assert flock["corrective_action_count"] == 0, (
            "82.00 is not strictly below 82.0, so no corrective action is opened"
        )

        rows, meta = validate_paginated(
            api.list_corrective_actions(
                fx.HATCHERY_MANAGER, {"flock_id": ctx["flock"]["id"]}
            )
        )
        assert meta["total_count"] == 0, f"expected no corrective actions, got {rows}"

    def test_forecast_is_not_derated_when_hatchability_only_touches_the_threshold(
        self, api
    ):
        """PRD 3.2: "A derate expresses open corrective action: it is 0.95 whenever the
        flock's `corrective_action_count` is 1 or more, and 1.0 when the count is 0."

        Design: Difficulty/boundary_precision_check/hatchability_exactly_threshold_opens_no_action
        """
        ctx = fx.threshold_hatchability_boxed_context(api)

        assert_chick_batch(
            ctx["batch"],
            vaccine_cull_count=33,
            cull_count=133,
            saleable_count=8200,
            box_count=82,
        )
        assert_two_dp(ctx["batch"]["preliminary_yield_pct"], 98.80, "preliminary_yield_pct")
        assert_two_dp(ctx["batch"]["final_yield_pct"], 98.40, "final_yield_pct")
        assert_two_dp(
            ctx["batch"]["quality_score_final"], 98.56, "quality_score_final"
        )

        flock = fx.read_flock(api, ctx["flock"]["id"])
        assert_forecast_chain(flock, settable_forecast=5587)
