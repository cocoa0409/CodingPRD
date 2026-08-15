"""FPPE/OPPE reviews: metric intake, rounding order, outcome thresholds, SoD."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_metric,
    assert_performance_metric,
    create_approved_member,
    get_success_data,
    open_review,
    refresh_review,
    review_to_final,
    review_to_provisional,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]


def _approved_ws(name="Dr. Perf", npdb="NPDB-PERF"):
    return create_approved_member(name, npdb)


def _oppe_review(ws, period_start="2026-09-01T00:00:00Z",
                 period_end="2026-10-01T00:00:00Z"):
    return open_review(ws["member"]["id"], ws["grant"]["id"], "OPPE",
                       period_start, period_end)


class TestMetricIntakeWindow:
    def test_metric_collected_outside_review_window_rejected(self, api):
        """PRD §3.5: "Two structural guards apply at intake: `collected_at` must
        fall inside the review's measurement window `[period_start, period_end)`
        (`ERR_METRIC_OUTSIDE_WINDOW`), and all metrics of the review that share
        a domain must carry the same `domain_weight`
        (`ERR_METRIC_WEIGHT_DOMAIN_MISMATCH`)."

        Design: Corner/validations/metric_collected_outside_review_window_rejected
        """
        ws = _approved_ws("Dr. Win", "NPDB-WIN")
        review = _oppe_review(ws)

        accepted = validate_success(api.create_performance_metric(
            {"review_id": review["id"], "metric_domain": "CITIZENSHIP",
             "raw_value": 90.0, "domain_weight": 1.0,
             "collected_at": "2026-09-01T00:00:00Z"}, COORD), 201)
        assert_performance_metric(accepted)
        assert accepted["metric_status"] == "ACTIVE", (
            "collected_at == period_start is inside the half-open window")

        resp = api.create_performance_metric(
            {"review_id": review["id"], "metric_domain": "CITIZENSHIP",
             "raw_value": 90.0, "domain_weight": 1.0,
             "collected_at": "2026-10-01T00:00:00Z"}, COORD)
        validate_error(resp, ApiErrorId.ERR_METRIC_OUTSIDE_WINDOW, 409)


class TestCompositeRoundingOrder:
    def _documentation_review(self):
        ws = _approved_ws("Dr. Round", "NPDB-RND")
        review = _oppe_review(ws)
        m1 = add_metric(review["id"], "DOCUMENTATION", 91.005, 1.0,
                        "2026-09-05T00:00:00Z")
        m2 = add_metric(review["id"], "DOCUMENTATION", 92.335, 1.0,
                        "2026-09-06T00:00:00Z")
        return review, m1, m2

    def test_fppe_metrics_round_individually_before_averaging(self, api):
        """PRD §2.6: "For metric normalization, the normalized value is rounded
        half-up to 2 decimal places first and only then clamped into the range
        from 0.00 to 100.00 inclusive — the clamp is applied after rounding, not
        before."
        PRD §3.5: "for `DOCUMENTATION` and `CITIZENSHIP`, the raw value passes
        through unchanged".

        Design: Difficulty/combinatorial_formula/fppe_per_domain_rounding_order_pinned
        """
        _review, m1, m2 = self._documentation_review()
        assert m1["normalized_value"] == 91.01, (
            "DOCUMENTATION passes raw through, then rounds half-up to 2dp")
        assert m2["normalized_value"] == 92.34

    def test_fppe_per_domain_rounding_order_pinned(self, api):
        """PRD §2.6: "For review composites, rounding happens per domain first:
        each domain's average is rounded half-up to 2 decimal places before the
        weighted cross-domain sum is taken and rounded again."
        PRD §3.5: "first, within each domain, the `normalized_value`s of the
        review's `ACTIVE` metrics are averaged and the average is rounded half-up
        to 2 decimal places; then the composite is the sum over domains of each
        rounded domain score multiplied by that domain's `domain_weight`, itself
        rounded half-up to 2 decimal places."

        Per-metric rounding yields 91.01 and 92.34; the domain average rounds to
        91.68 — not 91.67, which averaging the raw values first would give.

        Design: Difficulty/combinatorial_formula/fppe_per_domain_rounding_order_pinned
        """
        review, _m1, _m2 = self._documentation_review()
        get_success_data(api.close_review_collection(review["id"], COORD))
        computed = validate_success(
            api.compute_review_provisional(review["id"], COORD))
        assert computed["provisional_composite_score"] == 91.68


class TestOutcomeThresholds:
    def _finalized_review(self, ps_raw_value):
        ws = _approved_ws("Dr. Bnd", "NPDB-B1")
        review = _oppe_review(ws)
        add_metric(review["id"], "CLINICAL_QUALITY", 2.0, 0.5,
                   "2026-09-05T00:00:00Z")
        add_metric(review["id"], "PATIENT_SAFETY", ps_raw_value, 0.5,
                   "2026-09-06T00:00:00Z")
        review_to_provisional(review["id"])
        return review_to_final(review["id"])

    def test_oppe_outcome_exactly_70_is_satisfactory(self, api):
        """PRD §3.5: "a final composite of at least 70.00 is `SATISFACTORY`;
        at least 50.00 but below 70.00 is `MARGINAL`; below 50.00 is
        `UNSATISFACTORY`. The boundary is inclusive upward — exactly 70.00 is
        `SATISFACTORY` — and the comparison always reads the rounded value".

        CQ raw 2.0 normalizes to 90.00 and PS raw 6.25 to 50.00, so the
        composite is exactly 70.00.

        Design: Difficulty/boundary_precision_check/oppe_outcome_threshold_exactly_70_vs_69_99
        """
        finalized = self._finalized_review(6.25)
        assert finalized["final_composite_score"] == 70.00
        assert finalized["outcome"] == "SATISFACTORY"

    def test_oppe_outcome_69_99_is_marginal(self, api):
        """PRD §3.5: "a final composite of at least 70.00 is `SATISFACTORY`;
        at least 50.00 but below 70.00 is `MARGINAL`; below 50.00 is
        `UNSATISFACTORY`."

        PS raw 6.2525 normalizes to 49.98, so the composite is 69.99 — one
        hundredth below the SATISFACTORY boundary.

        Design: Difficulty/boundary_precision_check/oppe_outcome_threshold_exactly_70_vs_69_99
        """
        finalized = self._finalized_review(6.2525)
        assert finalized["final_composite_score"] == 69.99
        assert finalized["outcome"] == "MARGINAL"


class TestMetricRetractionInvariant:
    def _three_metric_review(self):
        ws = _approved_ws("Dr. Inv2", "NPDB-INV2")
        review = open_review(ws["member"]["id"], ws["grant"]["id"], "FPPE",
                             "2026-08-02T00:00:00Z", "2026-09-01T00:00:00Z")
        add_metric(review["id"], "CLINICAL_QUALITY", 1.0, 0.4,
                   "2026-08-05T00:00:00Z", passed_fppe_case=True)
        add_metric(review["id"], "PATIENT_SAFETY", 2.0, 0.3,
                   "2026-08-06T00:00:00Z")
        doc = add_metric(review["id"], "DOCUMENTATION", 80.0, 0.3,
                         "2026-08-07T00:00:00Z")
        return review, doc

    def test_metric_retract_updates_review_counters(self, api):
        """PRD §3.5: "Each attachment computes the metric's `normalized_value`
        and recomputes the review's counters; retraction by a coordinator flips
        a metric from `ACTIVE` to `RETRACTED` and recomputes `metric_count` and
        `retracted_metric_count` again."

        Design: Difficulty/compensating_invariant/metric_retract_preserves_review_total_count
        """
        review, doc = self._three_metric_review()
        validate_success(api.retract_performance_metric(doc["id"], COORD))

        refreshed = refresh_review(review["id"])
        assert refreshed["metric_count"] == 2
        assert refreshed["retracted_metric_count"] == 1
        assert refreshed["metric_count"] + refreshed["retracted_metric_count"] == 3, (
            "metric_count + retracted_metric_count is conserved at the total "
            "ever attached")
        retracted = validate_success(
            api.get_performance_metric(doc["id"], COORD))
        assert retracted["metric_status"] == "RETRACTED"

    def test_retracted_metric_excluded_from_provisional_composite(self, api):
        """PRD §3.5: "The provisional variant is boundary-inclusive: a metric
        whose `collected_at` equals `period_end` exactly is included, while
        retracted metrics are always excluded."

        With the DOCUMENTATION metric retracted, the composite aggregates only
        CLINICAL_QUALITY (95.00 x 0.4) and PATIENT_SAFETY (84.00 x 0.3):
        38.00 + 25.20 = 63.20.

        Design: Difficulty/compensating_invariant/metric_retract_preserves_review_total_count
        """
        review, doc = self._three_metric_review()
        validate_success(api.retract_performance_metric(doc["id"], COORD))
        review_to_provisional_step = validate_success(
            api.close_review_collection(review["id"], COORD))
        assert review_to_provisional_step["review_status"] == "EVALUATION"
        computed = validate_success(
            api.compute_review_provisional(review["id"], COORD))
        assert computed["provisional_composite_score"] == 63.20


class TestNormalizationClamp:
    def test_normalization_clamp_at_zero_floor(self, api):
        """PRD §3.5: "For `CLINICAL_QUALITY`, the normalized value is one hundred
        minus five times the raw value".
        PRD §2.6: "the normalized value is rounded half-up to 2 decimal places
        first and only then clamped into the range from 0.00 to 100.00 inclusive
        — the clamp is applied after rounding, not before."
        PRD §3.5: "When an `OPPE` review lands `UNSATISFACTORY`, the system
        auto-proposes an **AdverseActionCase** of `case_kind` `RESTRICTION` whose
        `linked_review_id` references this review — the first cascade link from
        performance data into the adverse-action track."

        Raw 25.0 normalizes to -25.00, clamped to 0.00; the review finalizes at
        0.00 -> UNSATISFACTORY.

        Design: Corner/calculations/normalization_clamp_at_zero_floor
        """
        ws = _approved_ws("Dr. Clamp", "NPDB-CL1")
        review = _oppe_review(ws)
        metric = add_metric(review["id"], "CLINICAL_QUALITY", 25.0, 1.0,
                            "2026-09-05T00:00:00Z")
        assert metric["normalized_value"] == 0.00, (
            "100 - 5*25 = -25 clamps to the 0.00 floor")

        review_to_provisional(review["id"])
        finalized = review_to_final(review["id"])
        assert finalized["final_composite_score"] == 0.00
        assert finalized["outcome"] == "UNSATISFACTORY"

        cases, _meta = validate_paginated(
            api.list_adverse_action_cases(
                COORD, params={"linked_review_id": review["id"]}))
        restriction_cases = [c for c in cases if c["case_kind"] == "RESTRICTION"]
        assert len(restriction_cases) == 1, (
            "An UNSATISFACTORY OPPE review auto-proposes exactly one "
            "RESTRICTION case linked to the review")


class TestWeightSumGate:
    def test_finalize_with_weight_sum_not_one_rejected(self, api):
        """PRD §3.5: "One structural gate stands in front of it: the
        `domain_weight`s of the review's active metrics must sum to exactly
        1.000, else `ERR_WEIGHT_SUM_INVALID`."

        Design: Corner/validations/finalize_with_weight_sum_not_one_rejected
        """
        ws = _approved_ws("Dr. Weights", "NPDB-WTS")
        review = _oppe_review(ws)
        add_metric(review["id"], "CLINICAL_QUALITY", 2.0, 0.5,
                   "2026-09-05T00:00:00Z")
        add_metric(review["id"], "PATIENT_SAFETY", 2.0, 0.3,
                   "2026-09-06T00:00:00Z")
        review_to_provisional(review["id"])

        resp = api.finalize_performance_review(review["id"], CHAIR)
        validate_error(resp, ApiErrorId.ERR_WEIGHT_SUM_INVALID, 409)
        assert refresh_review(review["id"])["review_status"] == "PROVISIONAL_RESULT"


class TestFinalizationRole:
    def test_rbac_coordinator_cannot_finalize_review(self, api):
        """PRD §2.1: "A request whose declared role is not authorized for the
        target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: POST /mso/performance-reviews/{id}/finalize is authorized for
        CredentialsCommitteeChair only.

        Design: Corner/roles/rbac_coordinator_cannot_finalize_review
        """
        ws = _approved_ws("Dr. Fin", "NPDB-FIN")
        review = _oppe_review(ws)
        add_metric(review["id"], "CITIZENSHIP", 90.0, 1.0,
                   "2026-09-05T00:00:00Z")
        review_to_provisional(review["id"])

        resp = api.finalize_performance_review(review["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
        assert refresh_review(review["id"])["review_status"] == "PROVISIONAL_RESULT"
