"""State that advances without following a single line: the environment dimension
that opens, resolves and reopens; the fumigation loop a lot may run any number of
times; and the early-pull branch that gates boxing behind a hold.
"""

from test_helpers import (
    CHICK_PROCESSOR,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    ApiErrorId,
    ChickBatchStatus,
    EggLotStatus,
    EnvironmentStatus,
    HatcherLoadStatus,
    OccupancyStatus,
    PullClass,
    QualityFlag,
    SetterLoadStatus,
    assert_chick_batch,
    assert_egg_lot,
    assert_hatcher_load,
    assert_incubation_unit,
    assert_instant,
    assert_setter_load,
    assert_three_dp,
    assert_two_dp,
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

#: (recorded_at, temp_c, expected segment, expected environment_status after ingest)
READING_SERIES = [
    ("2026-08-02T00:00:00Z", 37.8, 0.000, EnvironmentStatus.NOMINAL.value),
    ("2026-08-02T02:00:00Z", 38.9, 0.000, EnvironmentStatus.NOMINAL.value),
    ("2026-08-02T05:00:00Z", 37.9, 2.400, EnvironmentStatus.DEVIATION_OPEN.value),
    ("2026-08-02T06:00:00Z", 37.8, 0.000, EnvironmentStatus.DEVIATION_OPEN.value),
    ("2026-08-02T08:00:00Z", 37.75, 0.000, EnvironmentStatus.DEVIATION_RESOLVED.value),
    ("2026-08-02T10:00:00Z", 39.0, 0.000, EnvironmentStatus.DEVIATION_RESOLVED.value),
    ("2026-08-02T12:00:00Z", 37.8, 1.800, EnvironmentStatus.DEVIATION_OPEN.value),
    ("2026-08-02T15:00:00Z", 37.8, 0.000, EnvironmentStatus.DEVIATION_RESOLVED.value),
]


class TestEnvironmentDimension:
    """``environment_status`` opens, resolves and reopens on its own axis."""

    def test_deviation_opens_resolves_and_reopens_across_the_series(self, api):
        """PRD 3.5: "Otherwise, if the load is currently `DEVIATION_OPEN` and the
        uninterrupted run of within-tolerance segments ending at this reading spans at
        least 2.0 hours, the load's `environment_status` becomes `DEVIATION_RESOLVED`; a
        segment counts as within tolerance precisely when its `segment_degree_hours` is
        exactly 0." And: "A resolved load can be re-opened: from `DEVIATION_RESOLVED` a
        further segment above the 1.50 threshold drives it back to `DEVIATION_OPEN` and
        re-stamps `deviation_opened_at`, and the degree-hour total continues to
        accumulate across cycles rather than restarting."

        Design: Difficulty/non_linear_state_machine/setter_load_environment_dimension_parallel
        """
        ctx = fx.incubating_load_context(api)
        fx.set_clock(api, "2026-08-02T16:00:00Z")

        for recorded_at, temp_c, expected_segment, expected_status in READING_SERIES:
            reading = fx.ingest_reading(api, ctx["load"]["id"], recorded_at, temp_c)
            assert_three_dp(
                reading["segment_degree_hours"],
                expected_segment,
                f"segment_degree_hours at {recorded_at}",
            )
            load = fx.read_load(api, ctx["load"]["id"])
            assert load["environment_status"] == expected_status, (
                f"after the reading at {recorded_at} the environment dimension should "
                f"be {expected_status}, got {load['environment_status']}"
            )

        final_load = fx.read_load(api, ctx["load"]["id"])
        assert_instant(
            final_load["deviation_opened_at"],
            "2026-08-02T12:00:00Z",
            "deviation_opened_at re-stamped by the second excursion",
        )
        assert_three_dp(
            final_load["deviation_degree_hours"], 4.200, "deviation_degree_hours"
        )

    def test_environment_dimension_never_moves_the_incubation_status(self, api):
        """PRD 3.5: "A setter load carries `environment_status` — `NOMINAL`,
        `DEVIATION_OPEN` or `DEVIATION_RESOLVED` — that moves without ever affecting the
        load's incubation `status`."

        Design: Difficulty/non_linear_state_machine/setter_load_environment_dimension_parallel
        """
        ctx = fx.incubating_load_context(api)
        fx.set_clock(api, "2026-08-02T16:00:00Z")

        for recorded_at, temp_c, _segment, _status in READING_SERIES:
            fx.ingest_reading(api, ctx["load"]["id"], recorded_at, temp_c)
            load = fx.read_load(api, ctx["load"]["id"])
            assert_setter_load(load, status=SetterLoadStatus.INCUBATING.value)

        assert_three_dp(
            fx.read_load(api, ctx["load"]["id"])["deviation_degree_hours"],
            4.200,
            "deviation_degree_hours",
        )


class TestSanitationCycleLoop:
    """A lot may run the fumigation loop repeatedly, ageing permanently each time."""

    def _stored_lot(self, api):
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        return fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            collected_at="2026-07-28T00:00:00Z",
            collected_count=6500,
        )

    def test_each_completed_cycle_adds_three_quarters_of_a_day(self, api):
        """PRD 3.4: "An `IncubationOperator` returns it, moving it `SANITATION_HOLD →
        IN_STORAGE`, which adds 1 to `sanitation_cycle_count`, recomputes
        `effective_age_days` including the accumulated 18-hour penalty for every
        completed cycle, and increments the lot's `version`." And: "A lot may go round
        this loop any number of times, and each completed cycle ages it permanently —
        three cycles cost it 2.25 effective days on top of its scaled calendar age,
        whether or not it is ever set."

        Design: Difficulty/non_linear_state_machine/egg_lot_sanitation_cycle_repeats
        """
        lot = self._stored_lot(api)
        assert_two_dp(lot["effective_age_days"], 4.50, "effective_age_days")
        assert lot["sanitation_cycle_count"] == 0

        get_success_data(api.sanitation_hold_egg_lot(lot["id"], VETERINARIAN), 200)
        after_first = validate_success(
            api.sanitation_release_egg_lot(lot["id"], INCUBATION_OPERATOR), 200
        )
        assert_egg_lot(
            after_first,
            status=EggLotStatus.IN_STORAGE.value,
            sanitation_cycle_count=1,
        )
        assert_two_dp(after_first["effective_age_days"], 5.25, "effective_age_days")

        get_success_data(api.sanitation_hold_egg_lot(lot["id"], VETERINARIAN), 200)
        after_second = validate_success(
            api.sanitation_release_egg_lot(lot["id"], INCUBATION_OPERATOR), 200
        )
        assert_egg_lot(
            after_second,
            status=EggLotStatus.IN_STORAGE.value,
            sanitation_cycle_count=2,
        )
        assert_two_dp(after_second["effective_age_days"], 6.00, "effective_age_days")

    def test_cycles_leave_the_settable_counts_untouched(self, api):
        """PRD 2.5: "Almost every record additionally carries `updated_at` — an ISO 8601
        UTC timestamp with three fractional digits, refreshed on every mutation — and
        `version`, an integer that starts at 1 on creation and increments by exactly 1 on
        every mutation of that record."

        Design: Difficulty/non_linear_state_machine/egg_lot_sanitation_cycle_repeats
        """
        lot = self._stored_lot(api)
        version_before = lot["version"]

        for _cycle in range(2):
            get_success_data(api.sanitation_hold_egg_lot(lot["id"], VETERINARIAN), 200)
            get_success_data(
                api.sanitation_release_egg_lot(lot["id"], INCUBATION_OPERATOR), 200
            )

        after = fx.read_lot(api, lot["id"])
        assert_egg_lot(after, settable_count=6200, eggs_remaining=6200)
        assert after["version"] == version_before + 4, (
            "two hold-and-release cycles are four mutations, so the version advances "
            f"by exactly 4: expected {version_before + 4}, got {after['version']}"
        )


class TestEarlyPullBranch:
    """The early branch flags the chicks and holds them back from the box."""

    def test_early_pull_sets_the_navel_flag_and_a_four_hour_hold(self, api):
        """PRD 3.6: "When the logical clock is strictly before `pull_window_start_at`,
        the load moves `HATCHING → EARLY_PULLED`, `pull_class` is `EARLY` and
        `pull_offset_hours` is negative, being the hours from the pull instant back to
        `pull_window_start_at`. The `quality_flag` becomes `UNHEALED_NAVEL`, and
        `hold_release_at` is set to `actual_pull_at` advanced by the early hold of 4
        hours; the chicks may not be boxed before that instant."

        Design: Difficulty/non_linear_state_machine/hatcher_early_pull_branch_hold
        """
        ctx = fx.pulled_batch_context(api, pull_at="2026-08-22T07:00:00Z")

        load = fx.read_hatcher_load(api, ctx["hatcher_load"]["id"])
        assert_hatcher_load(
            load,
            status=HatcherLoadStatus.EARLY_PULLED.value,
            pull_class=PullClass.EARLY.value,
            quality_flag=QualityFlag.UNHEALED_NAVEL.value,
            hold_release_at="2026-08-22T11:00:00Z",
        )
        assert_two_dp(load["pull_offset_hours"], -5.00, "pull_offset_hours")
        assert_two_dp(
            ctx["batch"]["quality_score_provisional"], 91.00, "quality_score_provisional"
        )

    def test_boxing_is_blocked_until_the_hold_expires_and_allowed_at_that_instant(
        self, api
    ):
        """PRD 3.7: "It moves the batch `VACCINATED → BOXED` and is gated on one temporal
        rule: if the originating hatcher load has a non-null `hold_release_at` — which
        happens only on the early branch — the current logical clock must be at or after
        that instant, otherwise the request is rejected with `ERR_EARLY_HOLD_ACTIVE`.
        Boxing at exactly `hold_release_at` is allowed."

        Design: Difficulty/non_linear_state_machine/hatcher_early_pull_branch_hold
        """
        ctx = fx.vaccinated_batch_context(api, pull_at="2026-08-22T07:00:00Z")

        fx.set_clock(api, "2026-08-22T10:00:00Z")
        too_early = api.box_chick_batch(ctx["batch"]["id"], CHICK_PROCESSOR)
        validate_error(too_early, ApiErrorId.ERR_EARLY_HOLD_ACTIVE, 422)
        assert_chick_batch(
            fx.read_batch(api, ctx["batch"]["id"]),
            status=ChickBatchStatus.VACCINATED.value,
        )

        fx.set_clock(api, "2026-08-22T11:00:00Z")
        boxed = validate_success(
            api.box_chick_batch(ctx["batch"]["id"], CHICK_PROCESSOR), 200
        )

        assert_chick_batch(boxed, status=ChickBatchStatus.BOXED.value)
        assert_two_dp(boxed["quality_score_final"], 85.68, "quality_score_final")
        assert_hatcher_load(
            fx.read_hatcher_load(api, ctx["hatcher_load"]["id"]),
            status=HatcherLoadStatus.PROCESSED.value,
        )
        assert_incubation_unit(
            fx.read_unit(api, ctx["hatcher_unit"]["id"]),
            occupancy_status=OccupancyStatus.FREE.value,
        )
