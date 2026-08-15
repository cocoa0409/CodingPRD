"""Payment applications: certification math, chain linkage, gates, void."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_project,
    create_report_issued_visit,
    create_performed_visit,
    create_payment_application,
    certify_payment_application,
    create_change_order,
    create_incorporated_change_order,
    set_clock,
    make_firm_admin_headers,
    make_architect_headers,
    make_contractor_headers,
    make_owner_headers,
    USER_ARCH_2,
    USER_ARCH_LEAD,
)

SOV_AB = [
    {"line_code": "A", "description": "Concrete", "scheduled_value_cents": 6000000},
    {"line_code": "B", "description": "Metals", "scheduled_value_cents": 4000000},
]
SOV_A_ONLY = [{"line_code": "A", "description": "Concrete",
               "scheduled_value_cents": 10000000}]


def _project_with_verification_visit(api, retainage_mode="TIERED_MARGINAL",
                                     sov_lines=None, **overrides):
    """ACTIVE project + REPORT_ISSUED PAYMENT_VERIFICATION visit at 2026-08-20."""
    project = create_active_project(
        sov_lines=sov_lines or SOV_AB, retainage_mode=retainage_mode, **overrides,
    )
    set_clock("2026-08-20T09:00:00Z")
    visit, report = create_report_issued_visit(
        project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
    )
    return project, visit, report


class TestRetainageModeTieredVsReductionDivergence:
    """Identical lines certified on two projects differing only in retainage_mode."""

    def _certify_six_million(self, api, retainage_mode):
        project, visit, _ = _project_with_verification_visit(
            api, retainage_mode=retainage_mode, grace_days=5,
        )
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 6000000,
                    "stored_materials_cents": 0}],
        )
        return certify_payment_application(application["id"])

    def test_tiered_marginal_certification_figures(self, api):
        """PRD 3.5: "Under `TIERED_MARGINAL`, the retainage on a gross figure is
        ten percent of the portion of the gross up to the threshold plus five
        percent of the portion above it — work at or below the threshold never
        benefits from the lower rate, so nothing re-bases and there is no cliff."

        Design: Difficulty/dual_variant_calc/retainage_mode_tiered_vs_reduction_divergence
        """
        certified = self._certify_six_million(api, "TIERED_MARGINAL")
        # threshold = 5000000; R(6000000) = 0.10*5000000 + 0.05*1000000 = 550000
        assert certified["retainage_work_cents"] == 550000
        assert certified["certified_current_due_cents"] == 5450000

    def test_reduction_at_halfway_certification_figures(self, api):
        """PRD 3.5: "Under `REDUCTION_AT_HALFWAY`, the retainage is ten percent of
        the entire gross while the gross is below the threshold, and five percent
        of the entire gross once the gross reaches or exceeds the threshold — the
        crossing application re-bases all retainage to the lower rate."

        Design: Difficulty/dual_variant_calc/retainage_mode_tiered_vs_reduction_divergence
        """
        certified = self._certify_six_million(api, "REDUCTION_AT_HALFWAY")
        # gross 6000000 >= threshold 5000000 -> R = 0.05 * 6000000 = 300000
        assert certified["retainage_work_cents"] == 300000
        assert certified["certified_current_due_cents"] == 5700000


class TestRetainageTierBoundaryAtExactHalfway:
    def test_gross_exactly_at_threshold_has_no_low_band(self, api):
        """PRD 3.5: "Under `TIERED_MARGINAL`, the retainage on a gross figure is
        ten percent of the portion of the gross up to the threshold plus five
        percent of the portion above it — work at or below the threshold never
        benefits from the lower rate, so nothing re-bases and there is no cliff."

        Design: Difficulty/boundary_precision_check/retainage_tier_boundary_at_exact_halfway
        """
        project, visit, _ = _project_with_verification_visit(api)
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 5000000,
                    "stored_materials_cents": 0}],
        )
        certified = certify_payment_application(application["id"])
        assert certified["gross_work_completed_cents"] == 5000000
        assert certified["retainage_work_cents"] == 500000
        assert certified["certified_current_due_cents"] == 4500000

    def test_certification_stamps_certifier_and_timestamp(self, api):
        """PRD 3.5: "A successful certification stamps `certified_at` from the
        clock, records the certifier in `certified_by_user_id`, moves the
        application to `CERTIFIED`".

        Design: Difficulty/boundary_precision_check/retainage_tier_boundary_at_exact_halfway
        """
        project, visit, _ = _project_with_verification_visit(api)
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 5000000,
                    "stored_materials_cents": 0}],
        )
        certified = certify_payment_application(application["id"])
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == USER_ARCH_LEAD
        assert certified["certified_at"] is not None
        assert certified["certified_at"].startswith("2026-08-20T09:00:00")


class TestStoredMaterialsPerLineRounding:
    def _certify_three_lines_105(self, api):
        sov_lines = [
            {"line_code": "A", "description": "Concrete", "scheduled_value_cents": 4000000},
            {"line_code": "B", "description": "Metals", "scheduled_value_cents": 3000000},
            {"line_code": "C", "description": "Finishes", "scheduled_value_cents": 3000000},
        ]
        project, visit, _ = _project_with_verification_visit(
            api, sov_lines=sov_lines, grace_days=5,
        )
        lines = [
            {"sov_line_code": code, "work_completed_this_period_cents": 1000000,
             "stored_materials_cents": 105}
            for code in ("A", "B", "C")
        ]
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31", lines=lines,
        )
        return certify_payment_application(application["id"])

    def test_stored_retainage_rounds_per_line_then_sums(self, api):
        """PRD 3.5: "For each line, in lines-array order, the stored-materials
        retainage is that line's `stored_materials_cents` multiplied by ten
        percent and rounded half up to the cent; `retainage_stored_cents` is the
        sum of those per-line figures. Each line is rounded before summing —
        summing first and rounding once is a different, non-conformant result."

        Design: Difficulty/combinatorial_formula/payapp_stored_materials_per_line_rounding_mode_b
        """
        certified = self._certify_three_lines_105(api)
        # round_half_up(105 * 0.10) = round_half_up(10.5) = 11 per line, x 3 = 33
        assert certified["retainage_stored_cents"] == 33

    def test_certified_current_due_includes_stored_materials_net(self, api):
        """PRD 3.5: "The current amount due is the earned work minus
        `retainage_work_cents`, plus the stored-materials total minus
        `retainage_stored_cents`."

        Design: Difficulty/combinatorial_formula/payapp_stored_materials_per_line_rounding_mode_b
        """
        certified = self._certify_three_lines_105(api)
        # retainage_work = 0.10 * 3000000 = 300000 (below 5000000 threshold)
        assert certified["retainage_work_cents"] == 300000
        # 3000000 - 300000 + (315 - 33)
        assert certified["certified_current_due_cents"] == 2700282


class TestRetainageEvalOrderAfterIncorporation:
    def _setup(self, api):
        """Application 1 certified (4000000); +6000000 change order incorporated;
        V2 REPORT_ISSUED for period 2026-09-30."""
        sov_lines = [
            {"line_code": "A", "description": "Concrete", "scheduled_value_cents": 9000000},
            {"line_code": "B", "description": "Metals", "scheduled_value_cents": 1000000},
        ]
        project, visit1, _ = _project_with_verification_visit(
            api, sov_lines=sov_lines, grace_days=5,
        )
        app1 = create_payment_application(
            project["id"], visit1["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 4000000,
                    "stored_materials_cents": 0}],
        )
        app1 = certify_payment_application(app1["id"])
        project, _co = create_incorporated_change_order(
            project, title="Added scope", net_cost_change_cents=6000000,
            time_extension_days=0,
        )
        set_clock("2026-09-15T09:00:00Z")
        visit2, _ = create_report_issued_visit(
            project["id"], visit_date="2026-09-15", purpose="PAYMENT_VERIFICATION",
        )
        return project, app1, visit2

    def test_second_application_chains_to_first_and_reevaluates_threshold(self, api):
        """PRD 3.5: "The retainage held on a gross figure is evaluated under the
        project's current `retainage_mode`, using the current mode and the current
        threshold for both the new gross and the prior gross." and "The halfway
        threshold is one half of the project's `adjusted_contract_sum_cents` as it
        stands at the moment this computation runs, rounded half up to the cent."

        Design: Difficulty/combinatorial_formula/payapp_retainage_eval_order_after_incorporation_mode_c
        """
        project, app1, visit2 = self._setup(api)
        assert app1["certified_current_due_cents"] == 3600000
        assert project["adjusted_contract_sum_cents"] == 16570000
        app2 = create_payment_application(
            project["id"], visit2["id"], period_ending_date="2026-09-30",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 5000000,
                    "stored_materials_cents": 0}],
        )
        certified = certify_payment_application(app2["id"])
        assert certified["gross_work_completed_cents"] == 9000000
        # new threshold = 8285000; R(9000000) = 828500 + 0.05*715000 = 864250;
        # R(4000000) = 400000; delta = 464250
        assert certified["retainage_work_cents"] == 464250
        assert certified["certified_current_due_cents"] == 4535750

    def test_second_application_links_previous_application_id(self, api):
        """PRD 3.5: "`previous_application_id` resolves to the `CERTIFIED`
        application on the same project with the greatest `period_ending_date`
        strictly before this application's, ties broken by the earlier
        `created_at`, with `VOIDED` applications excluded from consideration; it
        is null for the project's first application."

        Design: Difficulty/combinatorial_formula/payapp_retainage_eval_order_after_incorporation_mode_c
        """
        project, app1, visit2 = self._setup(api)
        app2 = create_payment_application(
            project["id"], visit2["id"], period_ending_date="2026-09-30",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 5000000,
                    "stored_materials_cents": 0}],
        )
        assert app2["previous_application_id"] == app1["id"]


class TestProvisionalDiffersFromFinalAfterIncorporation:
    def _setup(self, api):
        """Application created (6000000) under the original threshold, then a
        +6000000 change order is incorporated before certification."""
        sov_lines = [
            {"line_code": "A", "description": "Concrete", "scheduled_value_cents": 9000000},
            {"line_code": "B", "description": "Metals", "scheduled_value_cents": 1000000},
        ]
        project, visit, _ = _project_with_verification_visit(
            api, sov_lines=sov_lines, grace_days=5,
        )
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 6000000,
                    "stored_materials_cents": 0}],
        )
        project, _co = create_incorporated_change_order(
            project, title="Added scope", net_cost_change_cents=6000000,
            time_extension_days=0,
        )
        return project, application

    def test_provisional_snapshot_uses_pre_incorporation_threshold(self, api):
        """PRD 3.5: "The provisional variant, run at creation and at
        resubmission, stores its result in `provisional_current_due_cents`
        alongside snapshots of `gross_work_completed_cents`,
        `earned_work_this_period_cents`, `retainage_work_cents`, and
        `retainage_stored_cents`."

        Design: Corner/calculations/provisional_differs_from_final_after_incorporation
        """
        project, application = self._setup(api)
        # provisional was computed at creation under threshold 5000000:
        # retainage 550000, due 5450000
        assert application["provisional_current_due_cents"] == 5450000

    def test_final_recompute_uses_post_incorporation_threshold(self, api):
        """PRD 3.5: "The final variant, run at certification time, re-executes
        the identical formula and stores its result in
        `certified_current_due_cents`, overwriting the four snapshot fields. The
        two runs legitimately diverge: a change-order incorporation between
        creation and certification changes `adjusted_contract_sum_cents` and
        therefore the halfway threshold (Section 3.6)."

        Design: Corner/calculations/provisional_differs_from_final_after_incorporation
        """
        project, application = self._setup(api)
        certified = certify_payment_application(application["id"])
        # new threshold = 8285000; gross 6000000 < threshold -> R = 600000
        assert certified["retainage_work_cents"] == 600000
        assert certified["certified_current_due_cents"] == 5400000
        # provisional snapshot survives with its original value
        assert certified["provisional_current_due_cents"] == 5450000
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["retainage_held_cents"] == 600000


class TestCertifyThenVoidConservesCertifiedToDate:
    def _submitted_application(self, api):
        project, visit, _ = _project_with_verification_visit(api)
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 2000000,
                    "stored_materials_cents": 0}],
        )
        return project, application

    def test_certify_moves_project_aggregates(self, api):
        """PRD 3.5: "recomputes the project's contract position:
        `certified_to_date_cents` becomes the sum of `certified_current_due_cents`
        over all of the project's applications in `CERTIFIED` (voided ones
        excluded), and `retainage_held_cents` becomes the retainage the current
        mode and current threshold would hold on the `gross_work_completed_cents`
        of the latest certified application by `period_ending_date`, plus the sum
        of `retainage_stored_cents` over all certified applications".

        Design: Difficulty/compensating_invariant/certify_then_void_conserves_certified_to_date
        """
        project, application = self._submitted_application(api)
        certify_payment_application(application["id"])
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["certified_to_date_cents"] == 1800000
        assert project["retainage_held_cents"] == 200000

    def test_void_returns_aggregates_to_baseline(self, api):
        """PRD 3.5: "A successful void moves the application to `VOIDED`,
        recomputes the project's `certified_to_date_cents` and
        `retainage_held_cents` so the certification's contribution is fully
        compensated, and releases the period for the ordering rule."

        Design: Difficulty/compensating_invariant/certify_then_void_conserves_certified_to_date
        """
        project, application = self._submitted_application(api)
        certify_payment_application(application["id"])
        voided = validate_success(
            api.void_payment_application(application["id"], make_firm_admin_headers()), 200)
        assert voided["status"] == "VOIDED"
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["certified_to_date_cents"] == 0
        assert project["retainage_held_cents"] == 0


class TestImmediateConsistency:
    def test_certify_then_project_read_reflects_totals_immediately(self, api):
        """PRD 2.11: "The project's `certified_to_date_cents` and
        `retainage_held_cents` are recomputed from the certified payment chain
        after every certification, void, and change-order incorporation
        (Sections 3.5 and 3.6)." and "every affected resource is updated as part
        of that same request."

        Design: Corner/consistency_model/certify_then_project_read_reflects_totals_immediately
        """
        project, visit, _ = _project_with_verification_visit(api, sov_lines=SOV_A_ONLY)
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 2000000,
                    "stored_materials_cents": 0}],
        )
        certify_payment_application(application["id"])
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["certified_to_date_cents"] == 1800000
        assert project["retainage_held_cents"] == 200000


class TestCertificationGates:
    def test_sod_certifier_equals_visit_performer_rejected(self, api):
        """PRD 2.10: "the CA staff member who certifies a payment application must
        differ from the staff member who performed that application's verification
        visit: the certifier's `X-User-ID` must differ from the verification
        visit's `performed_by_user_id`, or certification fails with
        `ERR_SOD_CERTIFIER_IS_VERIFIER` (HTTP 422)."

        Design: Corner/validations/sod_certifier_equals_visit_performer_rejected
        """
        project, visit, _ = _project_with_verification_visit(api, sov_lines=SOV_A_ONLY)
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
        )
        resp = api.certify_payment_application(
            application["id"], make_architect_headers(USER_ARCH_2),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_CERTIFIER_IS_VERIFIER, 422)
        current = get_success_data(
            api.get_payment_application(application["id"], make_architect_headers()))
        assert current["status"] == "SUBMITTED"

    def test_certify_with_uncleared_nonconformance_returns_409(self, api):
        """PRD 2.10: "Separately, certification is blocked when the verification
        visit's field report flags nonconforming work that has not been cleared,
        returning `ERR_NONCONFORMANCE_NOT_CLEARED` (HTTP 409)."

        Design: Corner/validations/certify_with_uncleared_nonconformance_returns_409
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        set_clock("2026-08-20T09:00:00Z")
        visit, report = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
            conformance_summary="NONCONFORMING", nonconforming_work_flag=True,
        )
        assert report["nonconformance_status"] == "OPEN"
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
        )
        resp = api.certify_payment_application(
            application["id"], make_architect_headers(USER_ARCH_LEAD),
        )
        validate_error(resp, ApiErrorId.ERR_NONCONFORMANCE_NOT_CLEARED, 409)
        current = get_success_data(
            api.get_payment_application(application["id"], make_architect_headers()))
        assert current["status"] == "SUBMITTED"


class TestCertifyRejectedAppStateBeatsFiscal:
    def _rejected_app_then_deduct(self, api):
        """Application (gross 10000000) REJECTED; deduct -2000000 incorporated."""
        project, visit, _ = _project_with_verification_visit(api)
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[
                {"sov_line_code": "A", "work_completed_this_period_cents": 6000000,
                 "stored_materials_cents": 0},
                {"sov_line_code": "B", "work_completed_this_period_cents": 4000000,
                 "stored_materials_cents": 0},
            ],
        )
        resp = api.reject_payment_application(
            application["id"], {"reason": "overstated"}, make_architect_headers(),
        )
        get_success_data(resp)
        project, _co = create_incorporated_change_order(
            project, title="Scope removal", net_cost_change_cents=-2000000,
            time_extension_days=0,
        )
        return project, application

    def test_state_error_wins_over_fiscal_error(self, api):
        """PRD 2.7: "A certification request whose application is no longer in
        `SUBMITTED` reports `ERR_PAYMENT_APPLICATION_INVALID_STATE` from stage 8,
        even if the certifier also performed the verification visit — the state
        gate precedes the segregation gate."

        Design: Difficulty/priority_pair_validation_conflict/certify_rejected_app_state_beats_fiscal
        """
        project, application = self._rejected_app_then_deduct(api)
        assert project["adjusted_contract_sum_cents"] == 8000000
        resp = api.certify_payment_application(
            application["id"], make_architect_headers(USER_ARCH_LEAD),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_APPLICATION_INVALID_STATE, 409)

    def test_rejected_application_unchanged_and_fiscal_not_returned(self, api):
        """PRD 2.7: "When several rules could reject the same request, exactly one
        error is returned: the one from the earliest applicable stage in the
        following fixed evaluation pipeline." (stage 8 target-entity state gates
        precede stage 13 fiscal gate).

        Design: Difficulty/priority_pair_validation_conflict/certify_rejected_app_state_beats_fiscal
        """
        project, application = self._rejected_app_then_deduct(api)
        resp = api.certify_payment_application(
            application["id"], make_architect_headers(USER_ARCH_LEAD),
        )
        error = validate_error(resp, ApiErrorId.ERR_PAYMENT_APPLICATION_INVALID_STATE, 409)
        assert error["error_id"] != ApiErrorId.ERR_CERTIFICATION_EXCEEDS_CONTRACT_BALANCE
        current = get_success_data(
            api.get_payment_application(application["id"], make_architect_headers()))
        assert current["status"] == "REJECTED"


class TestCreateAppPeriodTemporalBeatsVisitReferential:
    def _setup(self, api):
        """App1 CERTIFIED at period 2026-08-31; V2 is PROGRESS_OBSERVATION."""
        project, visit1, _ = _project_with_verification_visit(api)
        app1 = create_payment_application(
            project["id"], visit1["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 1000000,
                    "stored_materials_cents": 0}],
        )
        certify_payment_application(app1["id"])
        set_clock("2026-09-15T09:00:00Z")
        visit2, _ = create_report_issued_visit(
            project["id"], visit_date="2026-09-15", purpose="PROGRESS_OBSERVATION",
        )
        return project, visit2

    def test_temporal_error_wins_over_referential(self, api):
        """PRD 2.7: "When several rules could reject the same request, exactly one
        error is returned: the one from the earliest applicable stage in the
        following fixed evaluation pipeline." — stage 10 (temporal: "payment-period
        ordering") precedes stage 11 (referential: "verification-visit validity").
        PRD 3.5: "the new `period_ending_date` must be strictly later than the
        `period_ending_date` of every other application on the project in
        `SUBMITTED` or `CERTIFIED` — rejection yields
        `ERR_PAY_APP_PERIOD_NOT_AFTER_PREVIOUS` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/create_app_period_temporal_beats_visit_referential
        """
        project, visit2 = self._setup(api)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.create_payment_application(
            {"project_id": project["id"], "period_ending_date": "2026-08-31",
             "verification_visit_id": visit2["id"],
             "lines": [{"sov_line_code": "A", "work_completed_this_period_cents": 500000,
                        "stored_materials_cents": 0}]},
            contractor_headers,
        )
        error = validate_error(resp, ApiErrorId.ERR_PAY_APP_PERIOD_NOT_AFTER_PREVIOUS, 409)
        assert error["error_id"] != ApiErrorId.ERR_VERIFICATION_VISIT_INVALID

    def test_no_application_persisted_after_temporal_rejection(self, api):
        """PRD 3.5: "the new `period_ending_date` must be strictly later than the
        `period_ending_date` of every other application on the project in
        `SUBMITTED` or `CERTIFIED` — rejection yields
        `ERR_PAY_APP_PERIOD_NOT_AFTER_PREVIOUS` (HTTP 409); applications in
        `REJECTED` or `VOIDED` release their period and no longer block."

        Design: Difficulty/priority_pair_validation_conflict/create_app_period_temporal_beats_visit_referential
        """
        project, visit2 = self._setup(api)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        api.create_payment_application(
            {"project_id": project["id"], "period_ending_date": "2026-08-31",
             "verification_visit_id": visit2["id"],
             "lines": [{"sov_line_code": "A", "work_completed_this_period_cents": 500000,
                        "stored_materials_cents": 0}]},
            contractor_headers,
        )
        listing = get_success_data(api.list_payment_applications(
            make_firm_admin_headers(), params={"project_id": project["id"]}))
        assert len(listing) == 1


class TestVerificationVisitGate:
    def test_payapp_create_requires_verification_visit_report_issued(self, api):
        """PRD 3.5: "the referenced visit must have `purpose`
        `PAYMENT_VERIFICATION` and status `REPORT_ISSUED`, and its `visit_date`
        must fall inside the application's period window — ... otherwise
        `ERR_VERIFICATION_VISIT_INVALID` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/payapp_create_requires_verification_visit_report_issued
        """
        project = create_active_project()
        set_clock("2026-08-20T09:00:00Z")
        visit = create_performed_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
        )
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.create_payment_application(
            {"project_id": project["id"], "period_ending_date": "2026-08-31",
             "verification_visit_id": visit["id"],
             "lines": [{"sov_line_code": "A", "work_completed_this_period_cents": 1000000,
                        "stored_materials_cents": 0}]},
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_VISIT_INVALID, 422)

    def test_payapp_create_succeeds_after_report_issued(self, api):
        """PRD 3.3: "On issuance the report's `issued_at` is stamped and the visit
        advances from `PERFORMED` to `REPORT_ISSUED`" and PRD 3.5: "The
        application lands in `SUBMITTED` with `revision_number` 1".

        Design: Difficulty/cross_entity_state_dependency/payapp_create_requires_verification_visit_report_issued
        """
        project = create_active_project()
        set_clock("2026-08-20T09:00:00Z")
        visit = create_performed_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
        )
        from test_helpers import issue_field_report
        issue_field_report(visit["id"])
        visit = get_success_data(api.get_site_visit(visit["id"], make_architect_headers()))
        assert visit["status"] == "REPORT_ISSUED"
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 1000000,
                    "stored_materials_cents": 0}],
        )
        assert application["status"] == "SUBMITTED"


class TestPaymentApplicationRejectResubmitCycle:
    def _rejected_application(self, api):
        project, visit, _ = _project_with_verification_visit(api)
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 2000000,
                    "stored_materials_cents": 0}],
        )
        resp = api.reject_payment_application(
            application["id"], {"reason": "arithmetic error"}, make_architect_headers(),
        )
        rejected = validate_success(resp, 200)
        return project, visit, rejected

    def test_resubmit_increments_revision_and_clears_reason(self, api):
        """PRD 3.5: "A `Contractor` resubmits a `REJECTED` application with
        replacement `period_ending_date`, `verification_visit_id`, and `lines`;
        the replacement values are re-validated exactly as on creation — period
        ordering, verification-visit validity, line-code membership, and the
        per-line cap — `revision_number` increments, `rejection_reason` clears to
        null, and the provisional computation re-runs."

        Design: Difficulty/non_linear_state_machine/payment_application_reject_resubmit_cycle
        """
        project, visit, rejected = self._rejected_application(api)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "arithmetic error"
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.resubmit_payment_application(
            rejected["id"],
            {"period_ending_date": "2026-08-31", "verification_visit_id": visit["id"],
             "lines": [{"sov_line_code": "A", "work_completed_this_period_cents": 2000000,
                        "stored_materials_cents": 0}]},
            contractor_headers,
        )
        resubmitted = validate_success(resp, 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_number"] == 2
        assert resubmitted["rejection_reason"] is None

    def test_certify_after_resubmit_cycle(self, api):
        """PRD 3.5: "`certified_to_date_cents` becomes the sum of
        `certified_current_due_cents` over all of the project's applications in
        `CERTIFIED` (voided ones excluded)".

        Design: Difficulty/non_linear_state_machine/payment_application_reject_resubmit_cycle
        """
        project, visit, rejected = self._rejected_application(api)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        api.resubmit_payment_application(
            rejected["id"],
            {"period_ending_date": "2026-08-31", "verification_visit_id": visit["id"],
             "lines": [{"sov_line_code": "A", "work_completed_this_period_cents": 2000000,
                        "stored_materials_cents": 0}]},
            contractor_headers,
        )
        certified = certify_payment_application(rejected["id"])
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_current_due_cents"] == 1800000
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["certified_to_date_cents"] == 1800000


class TestPaymentApplicationInvalidStates:
    def test_certify_voided_pay_app_returns_invalid_state(self, api):
        """PRD 3.5: "Certifying, rejecting, resubmitting, or voiding against an
        application in the wrong state fails with
        `ERR_PAYMENT_APPLICATION_INVALID_STATE`."

        Design: Corner/state_machines/certify_voided_pay_app_returns_invalid_state
        """
        project, visit, _ = _project_with_verification_visit(api, sov_lines=SOV_A_ONLY)
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
        )
        certify_payment_application(application["id"])
        api.void_payment_application(application["id"], make_firm_admin_headers())
        resp = api.certify_payment_application(
            application["id"], make_architect_headers(USER_ARCH_LEAD),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_APPLICATION_INVALID_STATE, 409)
        current = get_success_data(
            api.get_payment_application(application["id"], make_architect_headers()))
        assert current["status"] == "VOIDED"

    def test_void_with_later_certified_app_returns_409(self, api):
        """PRD 3.5: "a `FirmAdmin` may void a `CERTIFIED` application, but only
        from the tip of the certified chain: if any other application on the same
        project is `CERTIFIED` with a strictly greater `period_ending_date`, the
        void is rejected with `ERR_LATER_CERTIFIED_APPLICATION_EXISTS` (HTTP 409)."

        Design: Corner/validations/void_with_later_certified_app_returns_409
        """
        project, visit1, _ = _project_with_verification_visit(api, sov_lines=SOV_A_ONLY)
        app1 = create_payment_application(
            project["id"], visit1["id"], period_ending_date="2026-08-31",
        )
        certify_payment_application(app1["id"])
        set_clock("2026-09-15T09:00:00Z")
        visit2, _ = create_report_issued_visit(
            project["id"], visit_date="2026-09-15", purpose="PAYMENT_VERIFICATION",
        )
        app2 = create_payment_application(
            project["id"], visit2["id"], period_ending_date="2026-09-30",
        )
        certify_payment_application(app2["id"])
        resp = api.void_payment_application(app1["id"], make_firm_admin_headers())
        validate_error(resp, ApiErrorId.ERR_LATER_CERTIFIED_APPLICATION_EXISTS, 409)
        current = get_success_data(
            api.get_payment_application(app1["id"], make_architect_headers()))
        assert current["status"] == "CERTIFIED"
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["certified_to_date_cents"] == 1800000


class TestLineValidation:
    def test_unknown_sov_line_code_returns_422(self, api):
        """PRD 3.5: "every line's `sov_line_code` must exist in the project's
        `sov_lines`, else `ERR_UNKNOWN_SOV_LINE_CODE` (HTTP 422)."

        Design: Corner/validations/unknown_sov_line_code_returns_422
        """
        project, visit, _ = _project_with_verification_visit(api, sov_lines=SOV_A_ONLY)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.create_payment_application(
            {"project_id": project["id"], "period_ending_date": "2026-08-31",
             "verification_visit_id": visit["id"],
             "lines": [{"sov_line_code": "ZZ", "work_completed_this_period_cents": 1000,
                        "stored_materials_cents": 0}]},
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_SOV_LINE_CODE, 422)
        listing = get_success_data(api.list_payment_applications(
            make_firm_admin_headers(), params={"project_id": project["id"]}))
        assert listing == []

    def test_sov_line_overrun_returns_422(self, api):
        """PRD 3.5: "the per-line schedule cap: for each line, the work previously
        certified against that same schedule-of-values line across the project's
        certified applications plus this line's `work_completed_this_period_cents`
        must not exceed the line's `scheduled_value_cents`, else
        `ERR_SOV_LINE_OVERRUN` (HTTP 422)."

        Design: Corner/validations/sov_line_overrun_returns_422
        """
        project = create_active_project(
            original_contract_sum_cents=1000000,
            sov_lines=[{"line_code": "A", "description": "Concrete",
                        "scheduled_value_cents": 1000000}],
        )
        set_clock("2026-08-20T09:00:00Z")
        visit, _ = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
        )
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        resp = api.create_payment_application(
            {"project_id": project["id"], "period_ending_date": "2026-08-31",
             "verification_visit_id": visit["id"],
             "lines": [{"sov_line_code": "A", "work_completed_this_period_cents": 1000001,
                        "stored_materials_cents": 0}]},
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SOV_LINE_OVERRUN, 422)


class TestCertificationFiscalGate:
    def test_certify_exceeding_adjusted_contract_sum_returns_402(self, api):
        """PRD 3.5: "the recomputed `gross_work_completed_cents` must not exceed
        the project's `adjusted_contract_sum_cents` (else
        `ERR_CERTIFICATION_EXCEEDS_CONTRACT_BALANCE`, HTTP 402)."

        Design: Corner/validations/certify_exceeding_adjusted_contract_sum_returns_402
        """
        project = create_active_project(
            original_contract_sum_cents=1000000,
            sov_lines=[{"line_code": "A", "description": "Concrete",
                        "scheduled_value_cents": 1000000}],
        )
        set_clock("2026-08-20T09:00:00Z")
        visit, _ = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
        )
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 1000000,
                    "stored_materials_cents": 0}],
        )
        project, _co = create_incorporated_change_order(
            project, title="Scope deletion", net_cost_change_cents=-300000,
            time_extension_days=0,
        )
        assert project["adjusted_contract_sum_cents"] == 700000
        resp = api.certify_payment_application(
            application["id"], make_architect_headers(USER_ARCH_LEAD),
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_EXCEEDS_CONTRACT_BALANCE, 402)
        current = get_success_data(
            api.get_payment_application(application["id"], make_architect_headers()))
        assert current["status"] == "SUBMITTED"
