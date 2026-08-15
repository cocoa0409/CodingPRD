"""Health assessments: basis input-set filtering, weighted penalty tiers,
band boundaries, adoption side effects, trend reads, and OCC (PRD §3.9, §2.6)."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    create_circuit,
    setup_job_in_progress,
    create_evaluated_vlf_series,
    create_energized_series,
    log_vlf_pd_steps,
    evaluate_series,
    accept_series,
    create_health_assessment,
    review_assessment,
    adopt_assessment,
    get_circuit,
)

ENGINEER = TEST_USERS["asset_engineer_headers"]
SUPERVISOR = TEST_USERS["test_supervisor_headers"]


def _circuit_version(api, circuit_id):
    return get_success_data(api.get_circuit(circuit_id, ENGINEER))["version"]


class TestEmptyAndTrend:
    def test_empty_input_set_scores_100(self, api):
        """PRD §3.9: "The tan-delta penalty takes the maximum of
        `max_tan_delta_e3` over the included series — series whose value is
        null are simply excluded, and if none qualify the metric is treated as
        empty — and maps it: below 5.0 to 0 points; at least 5.0 but below 20
        to 20 points; at least 20 but below 80 to 60 points; 80 or above to
        100 points; an empty set contributes 0." With no series, no faults, and
        an 11-year-old circuit every penalty is 0.

        Design: Corner/calculations/health_empty_input_set_scores_100
        """
        circuit = create_circuit("CKT-C4", installation_year=2015)
        assessment = create_health_assessment(circuit["id"], "FORMAL")
        assert assessment["health_index_score"] == 100.0
        assert assessment["band"] == "GOOD"
        assert assessment["recommended_action"] == "NONE"
        assert assessment["penalty_components"] == {
            "td_pen": 0, "pd_pen": 0, "fault_pen": 0, "age_pen": 0,
        }

    def test_trend_reflects_adopted_assessment(self, api):
        """PRD §3.9: "a `NetworkPlanner` or `AssetEngineer` can read the
        circuit's trend: its adopted assessments ordered oldest to newest as
        `points`, together with the `circuit_id` and the current
        `replacement_recommended` flag."

        Design: Corner/endpoints/trend_computed_read
        """
        circuit = create_circuit("CKT-P5", installation_year=2015)
        assessment = create_health_assessment(circuit["id"], "FORMAL")
        review_assessment(assessment["id"])
        adopt_assessment(assessment["id"])

        trend = validate_success(api.get_circuit_trend(circuit["id"], ENGINEER))
        assert trend["circuit_id"] == circuit["id"]
        assert len(trend["points"]) == 1
        assert trend["points"][0]["health_index_score"] == 100.0
        assert trend["points"][0]["band"] == "GOOD"
        assert trend["replacement_recommended"] is False


class TestBasisVariants:
    def _circuit_with_accepted_and_evaluated_series(self, api):
        """Circuit (installed 1996) with series A ACCEPTED (tan-delta 3.0)
        and series B EVALUATED but not customer-accepted (tan-delta 50.0)."""
        ctx = setup_job_in_progress(
            circuit_ref="CKT-DV3", length_m=2000, installation_year=1996,
            approved_budget_cents=900000,
        )
        # Both series must exist before either is accepted: accepting the only
        # series of a faultless job would satisfy the auto-evaluation gate
        # (PRD §3.3: every series terminal and every fault CLOSED_VERIFIED)
        # and move the job to EVALUATION, after which series creation is
        # illegal. With B still EVALUATED the gate stays closed.
        series_a = create_evaluated_vlf_series(ctx["job"]["id"], (3.0, 3.0, 3.0))
        create_evaluated_vlf_series(ctx["job"]["id"], (50.0, 50.0, 50.0))
        accept_series(series_a["id"])
        return ctx

    def test_formal_basis_counts_accepted_only(self, api):
        """PRD §3.9: "`FORMAL` counts only series in `ACCEPTED`, while
        `PROVISIONAL` counts series in `EVALUATED` or `ACCEPTED`, so identical
        raw data can score lower on the provisional basis — 96.2 formally
        against 75.2 provisionally, for instance, when a tan-delta reading of
        50.0 sits in a still-unevaluated-by-the-customer series."

        Design: Difficulty/dual_variant_calc/health_index_formal_vs_provisional_input_set
        """
        ctx = self._circuit_with_accepted_and_evaluated_series(api)
        assessment = create_health_assessment(ctx["circuit"]["id"], "FORMAL")
        # age 30y -> age_pen 25; all other penalties 0 -> penalty 3.8.
        assert assessment["health_index_score"] == 96.2
        assert assessment["band"] == "GOOD"
        assert assessment["recommended_action"] == "NONE"

    def test_provisional_basis_includes_evaluated_and_supersedes(self, api):
        """PRD §3.9: "any existing assessment of the same circuit in
        `COMPUTED`, `REVIEWED`, or `ADOPTED` is moved to `SUPERSEDED` with the
        new assessment's `supersedes_id` recording which assessment it
        replaced — null when there was none".

        Design: Difficulty/dual_variant_calc/health_index_formal_vs_provisional_input_set
        """
        ctx = self._circuit_with_accepted_and_evaluated_series(api)
        formal = create_health_assessment(ctx["circuit"]["id"], "FORMAL")
        assert formal["supersedes_id"] is None

        provisional = create_health_assessment(ctx["circuit"]["id"], "PROVISIONAL")
        # Provisional adds td_pen 60 over the EVALUATED 50.0 series:
        # 0.35*60 + 0.15*25 = 24.75 -> 24.8 penalty -> 75.2.
        assert provisional["health_index_score"] == 75.2
        assert provisional["band"] == "FAIR"
        assert provisional["recommended_action"] == "MONITOR"
        assert provisional["supersedes_id"] == formal["id"]
        prior = validate_success(api.get_health_assessment(formal["id"], ENGINEER))
        assert prior["status"] == "SUPERSEDED"


class TestWeightedTiers:
    def _monitor_series_with_fault(self, api):
        """Circuit (installed 1991) with one EVALUATED series (tan-delta 50.0,
        PD 600) and one manually raised fault."""
        ctx = setup_job_in_progress(
            circuit_ref="CKT-CF1", length_m=2000, installation_year=1991,
            requested_methods=["VLF_WITH_PD"], approved_budget_cents=900000,
        )
        series = create_energized_series(ctx["job"]["id"], "VLF_WITH_PD")
        log_vlf_pd_steps(series["id"], td=50.0, pd=600)
        evaluated = evaluate_series(series["id"])
        assert evaluated["verdict"] == "MONITOR"
        validate_success(
            api.create_fault({"test_series_id": series["id"]}, SUPERVISOR), 201
        )
        return ctx

    def test_four_inputs_combine_to_score_50(self, api):
        """PRD §3.9: "The aggregate penalty is thirty-five percent of the
        tan-delta penalty plus thirty percent of the partial-discharge penalty
        plus twenty percent of the fault penalty plus fifteen percent of the
        age penalty, summed at full precision and rounded half-up to one
        decimal place exactly once — per-component rounding is never applied."
        and "The score aggregates four penalties into `penalty_components`, an
        object holding `td_pen`, `pd_pen`, `fault_pen`, and `age_pen`."

        Design: Difficulty/combinatorial_formula/health_weighted_tiers_four_input_nonlinear
        """
        ctx = self._monitor_series_with_fault(api)
        assessment = create_health_assessment(ctx["circuit"]["id"], "PROVISIONAL")
        assert assessment["penalty_components"] == {
            "td_pen": 60, "pd_pen": 55, "fault_pen": 25, "age_pen": 50,
        }
        # 0.35*60 + 0.30*55 + 0.20*25 + 0.15*50 = 50.0
        assert assessment["health_index_score"] == 50.0

    def test_score_50_bands_poor(self, api):
        """PRD §3.9: "The `band` is `GOOD` for a score of eighty or above,
        `FAIR` for sixty or above but below eighty, `POOR` for forty or above
        but below sixty, and `CRITICAL` below forty; the `recommended_action`
        is band-mapped — `GOOD` to `NONE`, `FAIR` to `MONITOR`, `POOR` to
        `PLAN_REPLACEMENT`, and `CRITICAL` to `URGENT_REPLACEMENT`."

        Design: Difficulty/combinatorial_formula/health_weighted_tiers_four_input_nonlinear
        """
        ctx = self._monitor_series_with_fault(api)
        assessment = create_health_assessment(ctx["circuit"]["id"], "PROVISIONAL")
        assert assessment["band"] == "POOR"
        assert assessment["recommended_action"] == "PLAN_REPLACEMENT"


class TestScoreFortyBoundary:
    def _two_fail_series_ctx(self, api):
        """Circuit (installed 1991) with two EVALUATED FAIL series
        (tan-delta 90.0, PD 250) and therefore two auto-created faults."""
        ctx = setup_job_in_progress(
            circuit_ref="CKT-BP4", length_m=2000, installation_year=1991,
            requested_methods=["VLF_WITH_PD"], approved_budget_cents=900000,
        )
        for _ in range(2):
            series = create_energized_series(ctx["job"]["id"], "VLF_WITH_PD")
            log_vlf_pd_steps(series["id"], td=90.0, pd=250)
            evaluate_series(series["id"])
        circuit = get_circuit(ctx["circuit"]["id"])
        assert circuit["unresolved_fault_count"] == 2, (
            "each FAIL series auto-creates one fault (PRD §3.6)"
        )
        return ctx

    def test_score_exactly_forty_is_poor_not_critical(self, api):
        """PRD §3.9: "`POOR` for forty or above but below sixty". The four
        penalties (100, 25, 50, 50) weight to 35 + 7.5 + 10 + 7.5 = 60.0, a
        score of exactly 40.0 — POOR, not CRITICAL. "the `recommended_action`
        is band-mapped — `GOOD` to `NONE`, `FAIR` to `MONITOR`, `POOR` to
        `PLAN_REPLACEMENT`, and `CRITICAL` to `URGENT_REPLACEMENT`."

        Design: Difficulty/boundary_precision_check/health_score_exactly_forty_is_poor
        """
        ctx = self._two_fail_series_ctx(api)
        assessment = create_health_assessment(ctx["circuit"]["id"], "PROVISIONAL")
        assert assessment["health_index_score"] == 40.0
        assert assessment["band"] == "POOR"
        assert assessment["recommended_action"] == "PLAN_REPLACEMENT"

    def test_adopted_poor_with_two_faults_recommends_replacement(self, api):
        """PRD §3.9: "Adoption by the `NetworkPlanner` moves `REVIEWED` →
        `ADOPTED` and writes the assessment onto the circuit:
        `current_health_index` takes the score, `current_health_band` takes
        the band, and `replacement_recommended` is recomputed as true exactly
        when the band is `CRITICAL`, or when the band is `POOR` and the
        circuit's `unresolved_fault_count` is at least two."

        Design: Difficulty/boundary_precision_check/health_score_exactly_forty_is_poor
        """
        ctx = self._two_fail_series_ctx(api)
        assessment = create_health_assessment(ctx["circuit"]["id"], "PROVISIONAL")
        review_assessment(assessment["id"])
        adopted = adopt_assessment(assessment["id"])
        assert adopted["status"] == "ADOPTED"
        circuit = get_circuit(ctx["circuit"]["id"])
        assert circuit["current_health_index"] == 40.0
        assert circuit["current_health_band"] == "POOR"
        assert circuit["replacement_recommended"] is True


class TestOptimisticConcurrency:
    def test_stale_circuit_version_rejected(self, api):
        """PRD §2.6: "if the circuit's current `version` has advanced beyond
        what the client observed — including advancement caused by an earlier
        health-assessment creation, which itself bumps the circuit's version —
        the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_circuit_version_rejected
        """
        circuit = create_circuit("CKT-X1")
        observed = _circuit_version(api, circuit["id"])
        first = validate_success(api.create_health_assessment(
            {"circuit_id": circuit["id"], "basis": "FORMAL",
             "expected_circuit_version": observed},
            ENGINEER,
        ), 201)
        assert _circuit_version(api, circuit["id"]) != observed, (
            "creation itself bumps the circuit's version (PRD §3.9)"
        )
        stale = api.create_health_assessment(
            {"circuit_id": circuit["id"], "basis": "PROVISIONAL",
             "expected_circuit_version": observed},
            ENGINEER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assessments = validate_success(
            api.list_circuit_health_assessments(circuit["id"], ENGINEER)
        )
        assert [a["id"] for a in assessments] == [first["id"]]
