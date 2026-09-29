"""The cumulative baseline and the resource-effects analysis: the two variants a
finalisation stores, the ceiling that binds before mitigation, the inclusive
threshold, and the rules guarding creation, finalisation and reopening.
"""
from test_helpers import (
    PUBLIC_COMMENTER_HEADERS,
    RESOURCE_SPECIALIST_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    ApiErrorId,
    approx_score,
    assert_resource_analysis,
    assert_scores_differ,
    entries_with_code,
    finalize_analysis_payload,
    fixtures,
    resource_analysis_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The AIR analysis whose base term plus area tier adder overflows the ceiling.
AIR_ANALYSIS = {
    "resource_area": "AIR",
    "intensity_score": 98.0,
    "context_sensitivity_score": 96.0,
    "affected_area_hectares": 150.0,
    "mitigation_reduction_points": 25.0,
}
#: A water analysis landing exactly on the office significance threshold.
WATER_ANALYSIS = {
    "resource_area": "WATER",
    "intensity_score": 60.0,
    "context_sensitivity_score": 60.0,
    "affected_area_hectares": 0.0,
    "mitigation_reduction_points": None,
}
#: A socioeconomic analysis landing one hundredth below it.
SOCIOECONOMIC_ANALYSIS = {
    "resource_area": "SOCIOECONOMIC",
    "intensity_score": 59.98,
    "context_sensitivity_score": 60.0,
    "affected_area_hectares": 0.0,
    "mitigation_reduction_points": None,
}
#: A cultural analysis created without any mitigation reduction.
CULTURAL_ANALYSIS = {
    "resource_area": "CULTURAL",
    "intensity_score": 50.0,
    "context_sensitivity_score": 40.0,
    "affected_area_hectares": 3.0,
    "mitigation_reduction_points": None,
}
#: A baseline entry in a different resource area from the analysis under test.
CULTURAL_BASELINE_ENTRY = {
    "resource_area": "CULTURAL",
    "label": "Historic ranger cabin rehabilitation",
    "intensity_contribution": 40.0,
    "footprint_hectares": 2.0,
    "distance_km": 5.0,
    "temporal_scope": "PRESENT",
}


def _analysis_stage(**opts):
    """An action carried to ANALYSIS with nothing but the statement and the
    closed scoping period behind it."""
    return fixtures.setup_analysis_stage_action(
        with_issue=False, with_alternatives=False, with_consultation=False, **opts
    )


class TestSignificanceVariants:
    """Both variants are computed and stored on every finalisation."""

    def test_both_variants_are_stored_and_the_unmitigated_one_is_recorded(
        self, client
    ):
        """On one set of stored inputs the unmitigated and mitigated scores differ
        by the analysis's reduction points, and the requested basis decides which
        one is recorded.

        PRD 3.7: "The `unmitigated_score` is the direct term rounded half up to
        two decimal places. The `mitigated_score` is the direct term reduced by the
        analysis's `mitigation_reduction_points`, floored at zero, then rounded
        half up to two decimal places."
        PRD 3.7: "The `variant_applied` is set to the requested `basis`, and
        `significance_score` is set to `unmitigated_score` when the basis is
        `UNMITIGATED` and to `mitigated_score` when it is `MITIGATED`."

        Design: Difficulty/dual_variant_calc/resource_significance_unmitigated_vs_mitigated_divergence
        """
        ctx = _analysis_stage(with_baseline=True)
        analysis = fixtures.open_analysis(ctx["action"]["id"])

        finalized = validate_success(
            client.finalize_resource_analysis(
                analysis["id"], finalize_analysis_payload("UNMITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )
        assert finalized["status"] == "FINAL"
        assert finalized["cumulative_effect_score"] == approx_score(60.04)
        assert finalized["unmitigated_score"] == approx_score(70.21)
        assert finalized["mitigated_score"] == approx_score(58.21), (
            "the mitigated variant is stored even under an unmitigated basis"
        )
        assert finalized["variant_applied"] == "UNMITIGATED"
        assert finalized["significance_score"] == approx_score(70.21)
        assert finalized["significance_determination"] == "SIGNIFICANT"
        assert (finalized["unmitigated_score"] - finalized["mitigated_score"]) == (
            approx_score(12.00)
        ), "the divergence is exactly the recorded reduction points"
        assert_resource_analysis(finalized)

    def test_refinalizing_on_the_mitigated_basis_flips_the_determination(
        self, client
    ):
        """Reopening and finalising again on the other basis changes no input
        field, yet the recorded determination flips.

        PRD 3.7: "Under an `UNMITIGATED` basis, `mitigation_reduction_points` is
        ignored entirely in choosing the recorded score. Under a `MITIGATED` basis
        the recorded score is the reduced one, which on identical stored inputs can
        flip the determination the other way."
        PRD 3.7: "The `significance_determination` is `SIGNIFICANT` when
        `significance_score` is greater than or equal to the office's
        `significance_threshold`, and `NOT_SIGNIFICANT` otherwise; a score exactly
        equal to the threshold is `SIGNIFICANT`."

        Design: Difficulty/dual_variant_calc/resource_significance_unmitigated_vs_mitigated_divergence
        """
        ctx = _analysis_stage(with_baseline=True)
        analysis = fixtures.open_analysis(ctx["action"]["id"])
        first = fixtures.finalize_analysis(analysis["id"], "UNMITIGATED")
        assert first["significance_determination"] == "SIGNIFICANT"

        reopened = validate_success(
            client.reopen_resource_analysis(analysis["id"],
                                            RESOURCE_SPECIALIST_HEADERS)
        )
        assert reopened["status"] == "DRAFT"
        assert reopened["significance_score"] is None
        assert reopened["variant_applied"] is None

        mitigated = validate_success(
            client.finalize_resource_analysis(
                analysis["id"], finalize_analysis_payload("MITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )
        assert mitigated["variant_applied"] == "MITIGATED"
        assert mitigated["significance_score"] == approx_score(58.21)
        assert mitigated["significance_determination"] == "NOT_SIGNIFICANT", (
            "the reduced score falls below the office threshold"
        )
        assert mitigated["intensity_score"] == approx_score(72.0)
        assert mitigated["context_sensitivity_score"] == approx_score(55.0)
        assert mitigated["mitigation_reduction_points"] == approx_score(12.0), (
            "no stored input changed between the two finalisations"
        )

    def test_the_ceiling_clamps_the_direct_term_before_mitigation_is_subtracted(
        self, client
    ):
        """A base term of 97.20 plus the top area tier adder overflows the cap, and
        the cap binds first, so the mitigated score is 75.00.

        PRD 3.7: "The direct term is the sum of the base term, the area tier adder
        and the cumulative uplift, capped at 100.0."
        PRD 3.7: "An area tier adder is selected from `affected_area_hectares`:
        exactly zero hectares adds nothing; more than zero and up to and including
        5 hectares adds 2.0; more than 5 and up to and including 25 adds 4.0; more
        than 25 and up to and including 100 adds 7.0; and anything above 100 adds
        11.0."

        Design: Difficulty/combinatorial_formula/mode_a_significance_score_ceiling_binds_before_mitigation_subtraction
        """
        ctx = _analysis_stage()
        analysis = fixtures.open_analysis(ctx["action"]["id"], **AIR_ANALYSIS)

        finalized = validate_success(
            client.finalize_resource_analysis(
                analysis["id"], finalize_analysis_payload("MITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )
        assert finalized["cumulative_effect_score"] == approx_score(0.00), (
            "no baseline entry exists for the air resource area"
        )
        assert finalized["mitigated_score"] == approx_score(75.00)
        assert_scores_differ(finalized["mitigated_score"], 83.20, "mitigated_score")
        assert finalized["significance_score"] == approx_score(75.00)
        assert finalized["significance_determination"] == "SIGNIFICANT"

    def test_the_unmitigated_variant_of_the_same_analysis_sits_at_the_cap(
        self, client
    ):
        """Under the unmitigated basis the recorded score is the clamped 100.00,
        and the mitigated variant stored alongside it is the same 75.00.

        PRD 3.7: "The significance score is then built in one pass, and both
        variants are computed and stored on every finalisation. The base term is
        the office's `intensity_weight` multiplied by the analysis's
        `intensity_score` plus the office's `context_weight` multiplied by its
        `context_sensitivity_score`."
        PRD 2.8: "Comparisons against configured thresholds are inclusive in the
        direction the threshold is written, and the specific direction is stated
        wherever a threshold is introduced; hectare and kilometre comparisons
        involve no rounding at all."

        Design: Difficulty/combinatorial_formula/mode_a_significance_score_ceiling_binds_before_mitigation_subtraction
        """
        ctx = _analysis_stage()
        analysis = fixtures.open_analysis(ctx["action"]["id"], **AIR_ANALYSIS)

        finalized = validate_success(
            client.finalize_resource_analysis(
                analysis["id"], finalize_analysis_payload("UNMITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )
        assert finalized["unmitigated_score"] == approx_score(100.00), (
            "the uncapped sum of 97.20 and 11.0 is held at the ceiling"
        )
        assert finalized["mitigated_score"] == approx_score(75.00), (
            "the reduction is taken from the clamped direct term"
        )
        assert finalized["significance_score"] == approx_score(100.00)
        assert finalized["variant_applied"] == "UNMITIGATED"
        assert fixtures.read_action(ctx["action"]["id"])[
            "max_unmitigated_score"
        ] == approx_score(100.00)


class TestSignificanceThresholdBoundary:
    """The threshold comparison is inclusive, and rounding happens first."""

    def test_a_score_exactly_at_the_threshold_is_significant(self, client):
        """Sixty against a threshold of sixty is significant.

        PRD 3.7: "The `significance_determination` is `SIGNIFICANT` when
        `significance_score` is greater than or equal to the office's
        `significance_threshold`, and `NOT_SIGNIFICANT` otherwise; a score exactly
        equal to the threshold is `SIGNIFICANT`."

        Design: Difficulty/boundary_precision_check/significance_score_exactly_at_threshold_is_significant
        """
        ctx = _analysis_stage()
        assert ctx["office"]["significance_threshold"] == approx_score(60.0)
        analysis = fixtures.open_analysis(ctx["action"]["id"], **WATER_ANALYSIS)

        finalized = validate_success(
            client.finalize_resource_analysis(
                analysis["id"], finalize_analysis_payload("UNMITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )
        assert finalized["cumulative_effect_score"] == approx_score(0.00)
        assert finalized["significance_score"] == approx_score(60.00), (
            "a zero-hectare footprint adds nothing to the base term"
        )
        assert finalized["significance_determination"] == "SIGNIFICANT"

    def test_a_score_one_hundredth_below_the_threshold_is_not_significant(
        self, client
    ):
        """A direct term of 59.988 rounds half up to 59.99 before the comparison,
        which lands below the threshold.

        PRD 2.8: "Scores, percentages and credit quantities are carried to exactly
        two decimal places and rounded half up."
        PRD 3.7: "its `max_unmitigated_score` becomes the largest
        `unmitigated_score` among those final analyses, or 0.00 when there are
        none; its `cumulative_intensity_index` becomes the mean of
        `cumulative_effect_score` over those final analyses, rounded half up to two
        decimal places, or exactly 0.00 when there are none"

        Design: Difficulty/boundary_precision_check/significance_score_exactly_at_threshold_is_significant
        """
        ctx = _analysis_stage()
        action_id = ctx["action"]["id"]
        water = fixtures.open_analysis(action_id, **WATER_ANALYSIS)
        socioeconomic = fixtures.open_analysis(action_id, **SOCIOECONOMIC_ANALYSIS)

        fixtures.finalize_analysis(water["id"], "UNMITIGATED")
        finalized = validate_success(
            client.finalize_resource_analysis(
                socioeconomic["id"], finalize_analysis_payload("UNMITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )
        assert finalized["significance_score"] == approx_score(59.99)
        assert finalized["significance_determination"] == "NOT_SIGNIFICANT", (
            "one hundredth below the threshold is on the other side of it"
        )

        action = fixtures.read_action(action_id)
        assert action["max_unmitigated_score"] == approx_score(60.00), (
            "the larger of the two final analyses sets the rollup"
        )
        assert action["cumulative_intensity_index"] == approx_score(0.00)
        assert action["finalized_analysis_count"] == 2


class TestAnalysisCreationAndBaseline:
    """What a fresh analysis holds, and which baseline rows feed it."""

    def test_a_new_analysis_carries_no_computed_scores(self, client):
        """Creation stores the supplied inputs and leaves the recorded-variant
        fields null.

        PRD 3.7: "The analysis begins with `status` `DRAFT`, with
        `significance_score`, `significance_determination` and `variant_applied`
        all null, and with `cumulative_effect_score`, `unmitigated_score` and
        `mitigated_score` at 0.00 until finalisation computes them."

        Design: Corner/entities/corner_resource_analysis_computed_scores_are_null_until_finalized
        """
        ctx = _analysis_stage()
        created = validate_success(
            client.create_resource_analysis(
                ctx["action"]["id"], resource_analysis_payload(),
                RESOURCE_SPECIALIST_HEADERS,
            ),
            expected_status=201,
        )
        assert created["status"] == "DRAFT"
        for field in ("significance_score", "significance_determination",
                      "variant_applied"):
            assert created[field] is None, (
                f"{field} cannot be seeded by the client and is null until "
                f"finalisation"
            )
        for field in ("cumulative_effect_score", "unmitigated_score",
                      "mitigated_score"):
            assert created[field] == approx_score(0.00), (
                f"{field} holds 0.00 until finalisation computes it"
            )
        assert created["intensity_score"] == approx_score(72.0)
        assert created["context_sensitivity_score"] == approx_score(55.0)
        assert created["mitigation_reduction_points"] == approx_score(12.0)
        assert created["version"] == 1
        assert fixtures.read_action(ctx["action"]["id"])[
            "finalized_analysis_count"
        ] == 0

    def test_only_included_entries_of_the_same_area_feed_the_aggregation(
        self, client
    ):
        """An entry beyond the inclusion radius and an entry in another resource
        area are both absent from the aggregation and from its crowding count.

        PRD 3.7: "The first quantity recomputed is `cumulative_effect_score`,
        aggregated over the baseline entries belonging to the same action and the
        same `resource_area` whose `inclusion_status` is `INCLUDED`. Excluded
        entries contribute nothing and are not counted anywhere in the
        aggregation."
        PRD 3.7: "The server sets `inclusion_status` to `INCLUDED` when
        `distance_km` is less than or equal to the office's `cumulative_radius_km`
        and to `EXCLUDED` otherwise; an entry sitting exactly on the radius is
        included."

        Design: Corner/calculations/corner_cumulative_effect_score_filters_by_area_radius_and_status
        """
        ctx = _analysis_stage()
        action_id = ctx["action"]["id"]
        ctx = fixtures.setup_biological_baseline(ctx, include_excluded=True)
        cultural_entry = fixtures.add_baseline_entry(action_id,
                                                     **CULTURAL_BASELINE_ENTRY)

        assert all(entry["inclusion_status"] == "INCLUDED"
                   for entry in ctx["baseline"]), (
            "all four biological entries lie inside the office radius"
        )
        assert ctx["baseline_excluded"]["inclusion_status"] == "EXCLUDED", (
            "sixty kilometres is outside the office radius"
        )
        assert cultural_entry["inclusion_status"] == "INCLUDED"
        assert cultural_entry["resource_area"] == "CULTURAL"

        analysis = fixtures.open_analysis(action_id)
        finalized = validate_success(
            client.finalize_resource_analysis(
                analysis["id"], finalize_analysis_payload("UNMITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )
        assert finalized["cumulative_effect_score"] == approx_score(60.04), (
            "only the four included biological entries contribute, and the "
            "crowding multiplier counts only those four"
        )
        assert finalized["unmitigated_score"] == approx_score(70.21)
        assert finalized["significance_determination"] == "SIGNIFICANT"
        assert fixtures.read_action(action_id)[
            "cumulative_intensity_index"
        ] == approx_score(60.04)

    def test_a_second_analysis_for_the_same_resource_area_is_refused(self, client):
        """One analysis per action per resource area; another area is free.

        PRD 3.7: "At most one analysis may exist per action per resource area; a
        second is rejected with `ERR_DUPLICATE_RESOURCE_ANALYSIS`."

        Design: Corner/validations/corner_second_resource_analysis_for_same_area_is_rejected
        """
        ctx = _analysis_stage()
        action_id = ctx["action"]["id"]
        first = fixtures.open_analysis(action_id)

        refused = client.create_resource_analysis(
            action_id,
            resource_analysis_payload(resource_area="BIOLOGICAL",
                                      intensity_score=30.0,
                                      context_sensitivity_score=30.0,
                                      affected_area_hectares=1.0,
                                      mitigation_reduction_points=None),
            RESOURCE_SPECIALIST_HEADERS,
        )
        validate_error(refused, ApiErrorId.DUPLICATE_RESOURCE_ANALYSIS.value,
                       expected_status=409)
        assert fixtures.read_analysis(first["id"])["intensity_score"] == (
            approx_score(72.0)
        ), "the refused creation left the existing analysis untouched"

        accepted = validate_success(
            client.create_resource_analysis(
                action_id,
                resource_analysis_payload(resource_area="CULTURAL",
                                          intensity_score=30.0,
                                          context_sensitivity_score=30.0,
                                          affected_area_hectares=1.0,
                                          mitigation_reduction_points=None),
                RESOURCE_SPECIALIST_HEADERS,
            ),
            expected_status=201,
        )
        assert accepted["status"] == "DRAFT"

        _, meta = validate_paginated(
            client.list_resource_analyses(action_id, RESOURCE_SPECIALIST_HEADERS)
        )
        assert meta["total_count"] == 2


class TestFinalizationAndReopenGuards:
    """The mitigated basis needs a reduction, and reopening needs an open record."""

    def test_a_mitigated_basis_without_reduction_points_is_refused(self, client):
        """A zero reduction cannot support the mitigated variant, and the
        unmitigated basis on the same analysis succeeds.

        PRD 3.7: "A `MITIGATED` basis is admissible only when the analysis's
        `mitigation_reduction_points` is strictly greater than zero; requesting it
        against a zero reduction is rejected with `ERR_MITIGATION_BASIS_REQUIRED`."

        Design: Corner/errors/corner_error_mitigation_basis_required_on_mitigated_finalize
        """
        ctx = _analysis_stage()
        action_id = ctx["action"]["id"]
        analysis = fixtures.open_analysis(action_id, **CULTURAL_ANALYSIS)
        assert analysis["mitigation_reduction_points"] == approx_score(0.0), (
            "the optional reduction defaults to zero"
        )

        refused = client.finalize_resource_analysis(
            analysis["id"], finalize_analysis_payload("MITIGATED"),
            RESOURCE_SPECIALIST_HEADERS,
        )
        validate_error(refused, ApiErrorId.MITIGATION_BASIS_REQUIRED.value,
                       expected_status=409)
        still_draft = fixtures.read_analysis(analysis["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["significance_score"] is None
        assert still_draft["variant_applied"] is None

        accepted = validate_success(
            client.finalize_resource_analysis(
                analysis["id"], finalize_analysis_payload("UNMITIGATED"),
                RESOURCE_SPECIALIST_HEADERS,
            )
        )
        assert accepted["significance_score"] == approx_score(48.00)
        assert accepted["significance_determination"] == "NOT_SIGNIFICANT"
        assert fixtures.read_action(action_id)["finalized_analysis_count"] == 1

    def test_reopening_is_refused_once_a_document_has_been_published(self, client):
        """The same analysis reopens cleanly before publication and is locked
        afterwards.

        PRD 3.7: "A `ResourceSpecialist` may return a `FINAL` analysis `FINAL →
        DRAFT` only while no `NepaDocument` of the action has `publication_status`
        `PUBLISHED` or `FINAL` and no `DecisionDocument` of the action has `status`
        `SIGNED`; once either is true the analysis is frozen and the attempt is
        rejected with `ERR_ANALYSIS_LOCKED`."

        Design: Corner/endpoints/corner_reopen_analysis_after_publication_is_rejected
        """
        ctx = fixtures.setup_publish_ready_action(**fixtures.NO_ISSUE_NO_BASELINE)
        action_id = ctx["action"]["id"]
        analysis_id = ctx["analysis"]["id"]

        reopened = validate_success(
            client.reopen_resource_analysis(analysis_id, RESOURCE_SPECIALIST_HEADERS)
        )
        assert reopened["status"] == "DRAFT"
        assert reopened["significance_score"] is None
        entries, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert len(entries_with_code(entries, "ANALYSIS_REOPENED")) == 1

        fixtures.finalize_analysis(analysis_id, "UNMITIGATED")
        document = fixtures.create_document(action_id)
        fixtures.set_clock(fixtures.PUBLICATION_INSTANT)
        fixtures.publish_document(document["id"], fixtures.COMMENT_PERIOD_END)

        refused = client.reopen_resource_analysis(analysis_id,
                                                 RESOURCE_SPECIALIST_HEADERS)
        validate_error(refused, ApiErrorId.ANALYSIS_LOCKED.value,
                       expected_status=409)

        locked = fixtures.read_analysis(analysis_id)
        assert locked["status"] == "FINAL"
        assert locked["significance_score"] == approx_score(67.20), (
            "with no baseline entries the cumulative uplift is zero"
        )
        assert locked["variant_applied"] == "UNMITIGATED"

        action = fixtures.read_action(action_id)
        assert action["finalized_analysis_count"] == 1
        assert action["review_stage"] == "DRAFT_PUBLISHED"

    def test_a_public_commenter_may_not_list_the_resource_analyses(self, client):
        """The restriction is per endpoint: the same caller reads the document
        while the analysis listing is refused.

        PRD 2.1: "`X-User-ID` identifies the acting principal, and `X-User-Role`
        declares the capacity in which that principal is acting."
        PRD 2.5: "Role authorisation for the target endpoint, on every endpoint —
        `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/corner_public_commenter_cannot_read_resource_analyses
        """
        ctx = _analysis_stage()
        action_id = ctx["action"]["id"]
        fixtures.open_analysis(action_id)
        document = fixtures.create_document(action_id)

        refused = client.list_resource_analyses(action_id, PUBLIC_COMMENTER_HEADERS)
        validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED.value,
                       expected_status=403)

        readable = validate_success(
            client.get_document(document["id"], PUBLIC_COMMENTER_HEADERS)
        )
        assert readable["id"] == document["id"]

        rows, meta = validate_paginated(
            client.list_resource_analyses(action_id, RESOURCE_SPECIALIST_HEADERS)
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
