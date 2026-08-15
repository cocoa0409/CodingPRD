"""Verification, dual-variant scoring, labels, trajectory targets, certification (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_verifier,
    certify_report,
    create_and_open_cycle,
    create_owner,
    create_report,
    create_verifier,
    get_report,
    make_owner_headers,
    make_tenant_rep_headers,
    make_verifier_headers,
    set_clock,
    setup_report_scenario,
    setup_submitted_report,
    setup_verified_report,
    submit_report,
    upload_usage,
    validate_error,
    validate_success,
    verify_report,
)

OFFICER = TEST_USERS["officer_headers"]
OFFICER2 = TEST_USERS["officer2_headers"]

FULL_YEAR_2027 = {
    "period_start": "2027-01-01T00:00:00Z",
    "period_end": "2028-01-01T00:00:00Z",
}


class TestDualVariantScoring:
    def _verified_ctx_1200_mwh(self):
        """VERIFIED report: 1200000 kWh -> 4094400 kBtu -> site_eui 81.89 on 50000 sqft."""
        return setup_verified_report(
            usage_records=[dict(FULL_YEAR_2027, consumption_value=1200000)]
        )

    def test_verification_computes_both_score_variants(self, api):
        """PRD §3.6: "Otherwise the as-reported raw score is fifty plus the difference
        between the standard's `median_eui` and the report's `site_eui`, that
        difference multiplied by the standard's `score_slope`; the raw value is
        rounded half-up to a whole integer and then clamped into the inclusive range
        from 1 to 100, yielding `score_as_reported`. The weather-normalized variant
        first multiplies `site_eui` by the cycle's `weather_adjustment_factor`,
        rounded half-up to two decimals, then runs the identical pipeline — fifty
        plus the median-minus-normalized difference times `score_slope`, rounded
        half-up to an integer, clamped between 1 and 100 — yielding
        `score_weather_normalized`."

        Identical aggregates: site_eui 81.89 -> score_as_reported 46; normalized EUI
        73.70 under factor 0.9 -> score_weather_normalized 63.

        Design: Difficulty/dual_variant_calc/weather_normalized_score_diverges_from_as_reported
        """
        ctx = self._verified_ctx_1200_mwh()
        report = ctx["report"]
        assert report["status"] == "VERIFIED"
        assert report["aggregated_kbtu"] == 4094400
        assert report["site_eui"] == pytest.approx(81.89, abs=0.005)
        assert report["score_as_reported"] == 46
        assert report["score_weather_normalized"] == 63

    def test_label_follows_only_as_reported_score(self, api):
        """PRD §3.6: "The label always follows the as-reported variant: `A` when
        `score_as_reported` is at least 90, otherwise `B` at 75 or above, otherwise
        `C` at 50 or above, otherwise `D` at 25 or above, and `E` below that."

        The weather-normalized 63 would be a C; the label must be D because it
        follows only the as-reported 46.

        Design: Difficulty/dual_variant_calc/weather_normalized_score_diverges_from_as_reported
        """
        ctx = self._verified_ctx_1200_mwh()
        report = ctx["report"]
        assert report["score_as_reported"] == 46
        assert report["score_weather_normalized"] == 63
        assert report["label_grade"] == "D", "label follows the as-reported variant only"


class TestScoreClamp:
    def _verified_ctx_4_mwh(self):
        """4000 kWh -> 13648 kBtu -> site_eui 0.27 on 50000 sqft."""
        return setup_verified_report(usage_records=[dict(FULL_YEAR_2027, consumption_value=4000)])

    def test_score_clamped_to_max_100(self, api):
        """PRD §3.6: "Otherwise the as-reported raw score is fifty plus the difference
        between the standard's `median_eui` and the report's `site_eui`, that
        difference multiplied by the standard's `score_slope`; the raw value is
        rounded half-up to a whole integer and then clamped into the inclusive range
        from 1 to 100, yielding `score_as_reported`."

        Raw 50 + (80 - 0.27) * 2 = 209.46 rounds to 209 and clamps to exactly 100.

        Design: Difficulty/combinatorial_formula/score_banding_multi_input_clamp
        """
        ctx = self._verified_ctx_4_mwh()
        report = ctx["report"]
        assert report["site_eui"] == pytest.approx(0.27, abs=0.005)
        assert report["score_as_reported"] == 100, "nested clamp pins the score at the band ceiling"

    def test_clamped_score_bands_to_label_a(self, api):
        """PRD §3.6: "The label always follows the as-reported variant: `A` when
        `score_as_reported` is at least 90, otherwise `B` at 75 or above, otherwise
        `C` at 50 or above, otherwise `D` at 25 or above, and `E` below that."

        Design: Difficulty/combinatorial_formula/score_banding_multi_input_clamp
        """
        ctx = self._verified_ctx_4_mwh()
        report = ctx["report"]
        assert report["score_as_reported"] == 100
        assert report["label_grade"] == "A"


class TestLabelBandBoundary:
    def _verified_ctx_therms(self, therms):
        """50000 sqft, units 20000+10000 both consented -> completeness 100.00."""
        return setup_verified_report(
            unit_specs=[("U1", 20000, "OFFICE"), ("U2", 10000, "RETAIL")],
            consent_indexes=(0, 1),
            usage_records=[dict(FULL_YEAR_2027, consumption_value=therms)],
            account_overrides={"commodity": "NATURAL_GAS"},
        )

    def test_label_boundary_score_90_is_a(self, api):
        """PRD §3.6: "The label always follows the as-reported variant: `A` when
        `score_as_reported` is at least 90, otherwise `B` at 75 or above, otherwise
        `C` at 50 or above, otherwise `D` at 25 or above, and `E` below that."

        30000 therms -> 3000000 kBtu -> site_eui 60.00 -> score 90 -> A (>= inclusive).

        Design: Corner/calculations/c_label_boundary_90_A_89_B
        """
        ctx = self._verified_ctx_therms(30000)
        report = ctx["report"]
        assert report["site_eui"] == pytest.approx(60.00, abs=0.005)
        assert report["score_as_reported"] == 90
        assert report["label_grade"] == "A"

    def test_label_boundary_score_89_is_b(self, api):
        """PRD §3.6: "The label always follows the as-reported variant: `A` when
        `score_as_reported` is at least 90, otherwise `B` at 75 or above, otherwise
        `C` at 50 or above, otherwise `D` at 25 or above, and `E` below that."

        30250 therms -> 3025000 kBtu -> site_eui 60.50 -> score 89 -> B.

        Design: Corner/calculations/c_label_boundary_90_A_89_B
        """
        ctx = self._verified_ctx_therms(30250)
        report = ctx["report"]
        assert report["site_eui"] == pytest.approx(60.50, abs=0.005)
        assert report["score_as_reported"] == 89
        assert report["label_grade"] == "B"


class TestScoreSuppressionAtVerification:
    def test_scores_suppressed_when_completeness_below_floor(self, api):
        """PRD §3.6: "When the report's `data_completeness_pct` is below the
        eligibility floor of 75 percent, both `score_as_reported` and
        `score_weather_normalized` are null and `label_grade` is `INSUFFICIENT_DATA`."
        PRD §3.6: "On sign-off the record moves `PENDING → SIGNED_OFF` with
        `decided_at` stamped, and the report moves `SUBMITTED → VERIFIED`:
        `verified_at` is set to the logical clock, the aggregates and completeness
        are recomputed one final time, the report's `verified_site_eui` freezes the
        then-current `site_eui` as the baseline for all later correction checks, and
        the scoring pipeline runs."

        A mid-review consent revoke drops completeness to 60.00 before sign-off.

        Design: Corner/calculations/c_score_suppressed_when_completeness_below_75
        """
        ctx = setup_submitted_report()
        verifier = create_verifier()
        record = assign_verifier(ctx["report"]["id"], verifier["id"], ctx["owner"]["id"])

        # Mid-review revoke: u2's consent is withdrawn while the report is SUBMITTED.
        validate_success(
            api.revoke_consent(ctx["grants"][1]["id"], make_tenant_rep_headers(ctx["units"][1]["id"]))
        )

        signed = validate_success(
            api.sign_off_verification(record["id"], make_verifier_headers(verifier["id"]))
        )
        assert signed["status"] == "SIGNED_OFF"

        report = get_report(ctx["report"]["id"])
        assert report["status"] == "VERIFIED"
        assert report["data_completeness_pct"] == pytest.approx(60.00, abs=0.005)
        assert report["score_as_reported"] is None
        assert report["score_weather_normalized"] is None
        assert report["label_grade"] == "INSUFFICIENT_DATA"


class TestSignoffStateDependency:
    def _submitted_ctx_with_pending_record(self):
        ctx = setup_submitted_report()
        verifier = create_verifier()
        record = assign_verifier(ctx["report"]["id"], verifier["id"], ctx["owner"]["id"])
        ctx["verifier"] = verifier
        ctx["record"] = record
        return ctx

    def test_signoff_rejected_while_report_flagged(self, api):
        """PRD §3.6: "Sign-off requires the record to be `PENDING` and the report to
        be `SUBMITTED` (violations yield `ERR_INVALID_STATE_TRANSITION`)"

        The PENDING record's own state never changes, but an officer's manual review
        drops the report to FLAGGED and the same record can no longer be signed off.

        Design: Difficulty/cross_entity_state_dependency/signoff_requires_report_submitted
        """
        ctx = self._submitted_ctx_with_pending_record()
        validate_success(
            api.create_anomaly_flag(
                ctx["report"]["id"], {"detail": "Audit hold on reported consumption"}, OFFICER
            ),
            201,
        )
        assert get_report(ctx["report"]["id"])["status"] == "FLAGGED"

        resp = api.sign_off_verification(
            ctx["record"]["id"], make_verifier_headers(ctx["verifier"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        still = validate_success(api.get_verification_record(ctx["record"]["id"], OFFICER))
        assert still["status"] == "PENDING"

    def test_signoff_succeeds_after_report_resubmitted(self, api):
        """PRD §3.6: "Sign-off requires the record to be `PENDING` and the report to
        be `SUBMITTED` (violations yield `ERR_INVALID_STATE_TRANSITION`)"
        PRD §3.6: "On sign-off the record moves `PENDING → SIGNED_OFF` with
        `decided_at` stamped, and the report moves `SUBMITTED → VERIFIED`"

        Once the anomaly is resolved and the report resubmitted, the same record
        signs off.

        Design: Difficulty/cross_entity_state_dependency/signoff_requires_report_submitted
        """
        ctx = self._submitted_ctx_with_pending_record()
        flag = validate_success(
            api.create_anomaly_flag(
                ctx["report"]["id"], {"detail": "Audit hold on reported consumption"}, OFFICER
            ),
            201,
        )
        validate_success(
            api.resolve_anomaly_flag(
                flag["id"],
                {"resolution_note": "Consumption confirmed against utility feed"},
                make_owner_headers(ctx["owner"]["id"]),
            )
        )
        resubmitted = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        assert resubmitted["status"] == "SUBMITTED"

        signed = validate_success(
            api.sign_off_verification(
                ctx["record"]["id"], make_verifier_headers(ctx["verifier"]["id"])
            )
        )
        assert signed["status"] == "SIGNED_OFF"
        assert get_report(ctx["report"]["id"])["status"] == "VERIFIED"


class TestVerificationAssignmentRules:
    def test_second_pending_verification_rejected(self, api):
        """PRD §3.6: "At most one record may be `PENDING` per report; a second
        assignment while one is outstanding is refused with
        `ERR_VERIFIER_ALREADY_ASSIGNED`."

        Design: Corner/validations/v_second_pending_verification_rejected
        """
        ctx = setup_submitted_report()
        v1 = create_verifier()
        v2 = create_verifier()
        assign_verifier(ctx["report"]["id"], v1["id"], ctx["owner"]["id"])

        resp = api.create_verification_record(
            ctx["report"]["id"], {"verifier_id": v2["id"]}, make_owner_headers(ctx["owner"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VERIFIER_ALREADY_ASSIGNED)

    def test_signoff_without_performance_standard_rejected(self, api):
        """PRD §3.6: "it requires the cycle's `performance_standards` to contain an
        entry for the building's `property_type`, without which verification cannot
        proceed and the call fails with `ERR_STANDARD_NOT_DEFINED`."

        The cycle covers OFFICE but declares an empty performance_standards array.

        Design: Corner/validations/v_verify_without_standard_returns_standard_not_defined
        """
        ctx = setup_submitted_report(
            cycle_overrides={"covered_property_types": ["OFFICE"], "performance_standards": []}
        )
        verifier = create_verifier()
        record = assign_verifier(ctx["report"]["id"], verifier["id"], ctx["owner"]["id"])

        resp = api.sign_off_verification(record["id"], make_verifier_headers(verifier["id"]))
        validate_error(resp, ApiErrorId.ERR_STANDARD_NOT_DEFINED)
        assert get_report(ctx["report"]["id"])["status"] == "SUBMITTED"
        still = validate_success(api.get_verification_record(record["id"], OFFICER))
        assert still["status"] == "PENDING"


class TestOfficerFlagAndCertification:
    def test_officer_flag_reopens_verified_report(self, api):
        """PRD §3.6: "A `ComplianceOfficer` may raise a manual review on any report
        in `SUBMITTED`, `VERIFIED`, or `CERTIFIED` by supplying a `detail`; the
        report falls to `FLAGGED` and an `AnomalyFlag` of `anomaly_type`
        `MANUAL_REVIEW` opens with that detail."

        Design: Corner/endpoints/ep_officer_flag_reopens_verified_report
        """
        ctx = setup_verified_report()
        assert ctx["report"]["status"] == "VERIFIED"

        flag = validate_success(
            api.create_anomaly_flag(
                ctx["report"]["id"], {"detail": "Desk audit found meter mismatch"}, OFFICER
            ),
            201,
        )
        assert flag["anomaly_type"] == "MANUAL_REVIEW"
        assert flag["status"] == "OPEN"
        assert get_report(ctx["report"]["id"])["status"] == "FLAGGED"

    def test_cycle_creator_cannot_certify(self, api):
        """PRD §3.6: "Segregation of duties applies: the officer whose `X-User-ID`
        matches the cycle's `created_by_officer_id` may not certify reports in that
        cycle, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        The cycle was created by officer-1; officer-1's certify is denied, and
        officer-2 then certifies the same report.

        Design: Corner/validations/v_sod_cycle_creator_cannot_certify
        """
        ctx = setup_verified_report()
        assert ctx["cycle"]["created_by_officer_id"] == "officer-1"

        resp = api.certify_report(ctx["report"]["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        certified = validate_success(api.certify_report(ctx["report"]["id"], OFFICER2))
        assert certified["status"] == "CERTIFIED"

    def test_other_officer_certifies_verified_report(self, api):
        """PRD §3.6: "A `ComplianceOfficer` certifies a report only while it is
        `VERIFIED` and only while the cycle is `OPEN` or `FILING_CLOSED` (both
        violations yield `ERR_INVALID_STATE_TRANSITION`), moving it
        `VERIFIED → CERTIFIED`."

        Design: Corner/state_machines/s_certify_verified_report_succeeds
        """
        ctx = setup_verified_report()
        certified = certify_report(ctx["report"]["id"], OFFICER2)
        assert certified["status"] == "CERTIFIED"


class TestTrajectoryTarget:
    def _setup_two_cycle_trajectory(self):
        """bA has a VERIFIED 2027 report (site_eui 100.00); bB files first in 2028.
        Both submit 2028 reports; both are signed off by the same verifier."""
        owner = create_owner()
        verifier = create_verifier()
        c27 = create_and_open_cycle()
        c28 = create_and_open_cycle(
            cycle_year=2028,
            filing_deadline_at="2028-06-01T00:00:00Z",
            performance_standards=[
                {
                    "property_type": "OFFICE",
                    "median_eui": 80,
                    "score_slope": 2,
                    "baseline_eui_default": 120,
                    "annual_reduction_pct": 10,
                    "shortfall_tolerance_pct": 5,
                    "fine_rate_cents_per_sqft": 5,
                    "performance_fine_cap_cents": 1000000,
                }
            ],
        )

        # Building A: 40000 sqft, verified 2027 report on 40000 therms (eui 100.00).
        ctx_a = setup_report_scenario(
            owner=owner,
            cycle=c27,
            building_overrides={"address": "5 Main St", "gross_floor_area_sqft": 40000},
            unit_specs=[("A1", 20000, "OFFICE"), ("A2", 10000, "OFFICE")],
            consent_indexes=(0, 1),
            consent_window=("2027-01-01", "2028-12-31"),
            usage_records=[dict(FULL_YEAR_2027, consumption_value=40000)],
            account_overrides={"commodity": "NATURAL_GAS"},
        )
        submit_report(ctx_a["report"]["id"], owner["id"])
        verify_report(ctx_a, verifier)
        assert ctx_a["report"]["verified_site_eui"] == pytest.approx(100.00, abs=0.005)

        # Building A's 2028 usage and report (YoY delta 0 -> no anomaly).
        upload_usage(
            ctx_a["account"]["id"], "2028-01-01T00:00:00Z", "2029-01-01T00:00:00Z", 40000
        )
        ctx_a["report"] = create_report(ctx_a["building"]["id"], c28["id"], owner["id"])
        ctx_a["cycle"] = c28

        # Building B: 30000 sqft, no prior reports, no usage.
        ctx_b = setup_report_scenario(
            owner=owner,
            cycle=c28,
            building_overrides={"address": "6 Main St", "gross_floor_area_sqft": 30000},
            unit_specs=[("B1", 20000, "OFFICE"), ("B2", 10000, "OFFICE")],
            consent_indexes=(0, 1),
            consent_window=("2028-01-01", "2028-12-31"),
        )

        set_clock("2028-05-15T00:00:00Z")
        submit_report(ctx_a["report"]["id"], owner["id"])
        submit_report(ctx_b["report"]["id"], owner["id"])
        verify_report(ctx_a, verifier)
        verify_report(ctx_b, verifier)
        return ctx_a, ctx_b

    def test_target_eui_uses_earliest_prior_verified_report(self, api):
        """PRD §3.6: "First, among this building's reports in `VERIFIED` or
        `CERTIFIED` belonging to cycles with a strictly earlier `cycle_year`, select
        the one from the lowest `cycle_year`; if several qualify, break the tie by
        the reports' `created_at` in ascending order. That report's
        `verified_site_eui` becomes the baseline and its cycle year the baseline
        year."
        PRD §3.6: "The target is the baseline multiplied by the annual retention
        factor — one minus the standard's `annual_reduction_pct` expressed as a
        fraction of one hundred — raised to the power of the elapsed years, rounded
        half-up to two decimal places."

        bA's own 2027 VERIFIED snapshot (100.00) is the baseline, one year back:
        target 100 * 0.9^1 = 90.00 — the current 2028 report never feeds itself.

        Design: Difficulty/combinatorial_formula/trajectory_baseline_evaluation_order
        """
        ctx_a, _ctx_b = self._setup_two_cycle_trajectory()
        report_a = ctx_a["report"]
        assert report_a["status"] == "VERIFIED"
        assert report_a["target_eui"] == pytest.approx(90.00, abs=0.005)

    def test_target_eui_defaults_to_standard_baseline_one_year_back(self, api):
        """PRD §3.6: "When no such earlier report exists, the baseline is the
        standard's `baseline_eui_default` and the elapsed time is pinned to exactly
        one year, treating the default baseline as one year back."

        bB has no prior-cycle report: baseline 120 with years_elapsed pinned to 1,
        target 120 * 0.9^1 = 108.00.

        Design: Difficulty/combinatorial_formula/trajectory_baseline_evaluation_order
        """
        _ctx_a, ctx_b = self._setup_two_cycle_trajectory()
        report_b = ctx_b["report"]
        assert report_b["status"] == "VERIFIED"
        assert report_b["target_eui"] == pytest.approx(108.00, abs=0.005)
