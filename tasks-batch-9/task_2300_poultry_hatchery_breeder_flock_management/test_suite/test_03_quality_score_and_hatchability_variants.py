"""Two numbers computed twice: the chick quality score at pull and at boxing, and
rolling hatchability on the set basis and the fertile basis.

Both pairs share most of their inputs, so the interesting assertion is not either
value alone but the exact, stated difference between them.
"""

from test_helpers import (
    ApiClient,
    CHICK_PROCESSOR,
    INCUBATION_OPERATOR,
    ChickBatchStatus,
    PullClass,
    QualityFlag,
    UnitType,
    assert_chick_batch,
    assert_cull_resolution,
    assert_hatcher_load,
    assert_setter_load,
    assert_three_dp,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_paginated,
    validate_success,
)

#: Two out-of-tolerance excursions separated by a clear run, charging 4.200 degree-hours.
EIGHT_READINGS = [
    ("2026-08-02T00:00:00Z", 37.8),
    ("2026-08-02T02:00:00Z", 38.9),
    ("2026-08-02T05:00:00Z", 37.9),
    ("2026-08-02T06:00:00Z", 37.8),
    ("2026-08-02T08:00:00Z", 37.75),
    ("2026-08-02T10:00:00Z", 39.0),
    ("2026-08-02T12:00:00Z", 37.8),
    ("2026-08-02T15:00:00Z", 37.8),
]


def _transferred_after_deviations(api: ApiClient):
    """A hatcher load carrying 4.200 inherited degree-hours from its setter."""
    ctx = fx.deviation_open_context(
        api, readings=EIGHT_READINGS, clock_after="2026-08-02T16:00:00Z"
    )
    ctx["load"] = get_success_data(
        api.candle_setter_load(ctx["load"]["id"], 9600, INCUBATION_OPERATOR), 200
    )
    ctx["hatcher_unit"] = fx.sanitized_unit(
        api, code="U2", unit_type=UnitType.HATCHER.value, capacity_eggs=20000
    )
    ctx["hatcher_load"] = get_success_data(
        api.transfer_setter_load(
            ctx["load"]["id"], ctx["hatcher_unit"]["id"], INCUBATION_OPERATOR
        ),
        201,
    )
    fx.set_clock(api, "2026-08-22T18:00:00Z")
    return ctx


def _pull_and_process(api: ApiClient, ctx):
    """Pull 9400 chicks and take them as far as VACCINATED."""
    batch = get_success_data(
        api.pull_chicks(ctx["hatcher_load"]["id"], 9400, CHICK_PROCESSOR), 201
    )
    batch = get_success_data(
        api.sex_chick_batch(batch["id"], f.sexing_payload(), CHICK_PROCESSOR), 200
    )
    batch = get_success_data(
        api.vaccinate_chick_batch(batch["id"], "MAREKS_HVT", CHICK_PROCESSOR), 200
    )
    return batch


class TestChickQualityScoreVariants:
    """Provisional at pull, final at boxing, and the exact gap between them."""

    def test_provisional_score_debits_only_timing_and_inherited_deviation(self, api):
        """PRD 3.6: "The **provisional** variant is computed at pull and stored as
        `quality_score_provisional`. Because no culls are known at that point, its cull
        penalty is forced to 0.00, and its flag penalty is forced to 0.00 as well — even
        on the early and late branches, which have already set `quality_flag`. Only the
        pull-timing penalty and the inherited environment penalty apply." And: "The
        environment penalty multiplies 3.00 by `inherited_degree_hours`, rounds half up
        to two decimal places, and then caps the result at 25.00 — a badly deviating
        incubation cannot cost more than a quarter of the score."

        Design: Difficulty/dual_variant_calc/chick_quality_provisional_vs_final_diverge
        """
        ctx = _transferred_after_deviations(api)
        assert_three_dp(
            ctx["hatcher_load"]["inherited_degree_hours"], 4.200, "inherited_degree_hours"
        )

        response = api.pull_chicks(ctx["hatcher_load"]["id"], 9400, CHICK_PROCESSOR)
        batch = validate_success(response, 201)

        pulled_load = fx.read_hatcher_load(api, ctx["hatcher_load"]["id"])
        assert_hatcher_load(
            pulled_load,
            pull_class=PullClass.WINDOW.value,
            quality_flag=QualityFlag.NONE.value,
        )
        assert_two_dp(pulled_load["pull_offset_hours"], 0.00, "pull_offset_hours")
        assert_two_dp(
            batch["quality_score_provisional"], 87.40, "quality_score_provisional"
        )

    def test_final_score_adds_the_resolved_cull_penalty_at_boxing(self, api):
        """PRD 3.6: "The **final** variant is computed at boxing and stored as
        `quality_score_final`. It uses the resolved `cull_count`, meaning sexing culls
        plus vaccine culls, for the cull penalty, and it applies the flag penalty in full
        when `quality_flag` is `UNHEALED_NAVEL` or `DEHYDRATION`." And: "The cull penalty
        multiplies 0.90 by the cull rate expressed as a percentage, that is `cull_count`
        divided by `hatched_count` multiplied by 100, and rounds the product half up to
        two decimal places."

        Design: Difficulty/dual_variant_calc/chick_quality_provisional_vs_final_diverge
        """
        ctx = _transferred_after_deviations(api)
        batch = _pull_and_process(api, ctx)

        boxed = validate_success(api.box_chick_batch(batch["id"], CHICK_PROCESSOR), 200)

        assert_chick_batch(
            boxed,
            status=ChickBatchStatus.BOXED.value,
            cull_count=138,
            saleable_count=9262,
        )
        assert_cull_resolution(boxed)
        assert_two_dp(boxed["quality_score_final"], 86.08, "quality_score_final")

    def test_gap_between_the_scores_is_exactly_the_cull_and_flag_penalties(self, api):
        """PRD 3.6: "Its pull-timing and environment penalties are identical to the
        provisional variant's, so the gap between the two scores is exactly the cull
        penalty plus the flag penalty."

        Design: Difficulty/dual_variant_calc/chick_quality_provisional_vs_final_diverge
        """
        ctx = _transferred_after_deviations(api)
        batch = _pull_and_process(api, ctx)
        provisional = batch["quality_score_provisional"]
        assert_two_dp(provisional, 87.40, "quality_score_provisional")

        boxed = validate_success(api.box_chick_batch(batch["id"], CHICK_PROCESSOR), 200)

        assert_two_dp(
            boxed["quality_score_provisional"],
            87.40,
            "quality_score_provisional after boxing",
        )
        assert_two_dp(
            boxed["quality_score_provisional"] - boxed["quality_score_final"],
            1.32,
            "provisional less final",
        )


class TestRollingHatchabilityBases:
    """The same numerator over two different pooled denominators."""

    def test_set_basis_pools_saleable_over_every_egg_set(self, api):
        """PRD 3.9: "The set-basis variant is stored as `hatchability_rolling_pct`: sum
        `saleable_count` across the window's batches, divide by the sum of
        `total_eggs_set` across the window's setter loads, multiply by 100, and round
        half up to two decimal places. Because its denominator counts every egg set
        whether fertile or not, poor fertility depresses it."

        Design: Difficulty/dual_variant_calc/flock_hatchability_set_vs_fertile_basis
        """
        ctx = fx.boxed_batch_context(api)

        load = fx.read_load(api, ctx["load"]["id"])
        assert_setter_load(load, total_eggs_set=10000, fertile_count=9600)
        assert_two_dp(load["fertility_pct"], 96.00, "fertility_pct")

        flock = fx.read_flock(api, ctx["flock"]["id"])
        assert_two_dp(
            flock["hatchability_rolling_pct"], 92.62, "hatchability_rolling_pct"
        )

    def test_fertile_basis_is_at_least_the_set_basis_figure(self, api):
        """PRD 3.9: "The fertile-basis variant is stored as `hatchability_fertile_pct`:
        the same numerator, divided by the sum of `fertile_count` across the window's
        setter loads from candling, multiplied by 100 and rounded half up to two decimal
        places. It isolates incubation performance from flock fertility, is therefore
        always at least as large as the set-basis figure, and is reported for analytics
        only."

        Design: Difficulty/dual_variant_calc/flock_hatchability_set_vs_fertile_basis
        """
        ctx = fx.boxed_batch_context(api)

        flock = fx.read_flock(api, ctx["flock"]["id"])

        assert_two_dp(
            flock["hatchability_fertile_pct"], 96.48, "hatchability_fertile_pct"
        )
        assert flock["hatchability_fertile_pct"] >= flock["hatchability_rolling_pct"], (
            "the fertile basis can never fall below the set basis"
        )

    def test_hatchability_above_the_threshold_opens_no_corrective_action(self, api):
        """PRD 3.9: "Only the set-basis figure gates corrective action, and the
        comparison is strictly less than."

        Design: Difficulty/dual_variant_calc/flock_hatchability_set_vs_fertile_basis
        """
        ctx = fx.boxed_batch_context(api)

        flock = fx.read_flock(api, ctx["flock"]["id"])
        assert flock["corrective_action_count"] == 0, (
            "92.62 percent is above the threshold, so nothing is opened"
        )

        rows, meta = validate_paginated(
            api.list_corrective_actions(
                fx.HATCHERY_MANAGER, {"flock_id": ctx["flock"]["id"]}
            )
        )
        assert meta["total_count"] == 0, f"expected no corrective actions, got {rows}"
