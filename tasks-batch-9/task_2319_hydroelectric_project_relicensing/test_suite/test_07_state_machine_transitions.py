"""Lifecycle transitions: guarded moves, terminal states and cross-entity cascades."""
import pytest

from test_helpers import (
    U_AGENCY,
    U_LICENSEE_A,
    U_LICENSEE_REPORT,
    U_TRIBE,
    advance_environmental_review,
    api_client,
    assert_postures,
    certify_obligation,
    deny_certification,
    file_application,
    file_pad,
    leave_comment,
    list_obligations,
    make_agency_reviewer_headers,
    make_licensee_headers,
    new_measure,
    new_project,
    new_settlement,
    new_study,
    new_study_plan,
    patch_project,
    project_version,
    read_application,
    read_comment,
    read_measure,
    read_obligation,
    read_order,
    read_project,
    read_study,
    read_study_plan,
    register_party,
    request_certification,
    run_sweep,
    schedule_obligation,
    set_clock,
    setup_agency_party,
    setup_application_under_review,
    setup_approved_study_plan,
    setup_licensed_project,
    setup_plan_under_agency_review,
    setup_study_phase_project,
    submit_plan,
    TEST_USERS,
    validate_error,
    validate_success,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
REPORTER_HEADERS = make_licensee_headers(U_LICENSEE_REPORT)
AGENCY_HEADERS = make_agency_reviewer_headers(U_AGENCY)
SMALL_PROJECT = dict(
    installed_capacity_mw=9.0,
    base_annual_generation_mwh=50000,
    license_expiration_date="2035-06-30",
)
DAM_NO_EAP = dict(
    dam_code="D1",
    hazard_class="HIGH",
    inspection_interval_months=12,
    eap_exercise_required=False,
    max_concurrent_field_activities=2,
)
FULL_HEIGHT_LADDER = dict(
    measure_name="Full-height fish ladder",
    resource_category="FISH_PASSAGE",
    capital_cost_usd=4000000.00,
    annual_om_cost_usd=100000.00,
    construction_start_year=2026,
    implementation_months=24,
    flow_release_cfs=300,
    gross_head_ft=90,
    release_days=200,
)


class TestStudyPlanSubmission:
    def test_submitting_a_populated_plan_opens_the_agency_review(self):
        """One study is enough to move the plan into review and stamp the clock.

        PRD §3.3: "Submitting a plan for agency review moves it `DRAFT → UNDER_AGENCY_REVIEW` or, on a later cycle, `REVISION_REQUIRED → UNDER_AGENCY_REVIEW`."
        PRD §3.3: "Submission stamps `submitted_at` with the logical clock and increments the plan's `version`."

        Design: Corner/state_machines/study_plan_submit_moves_to_under_agency_review
        """
        ctx = setup_study_phase_project(
            sites=[dict(site_code="S1", river_mile=1.0)],
            project_name="Submit Reach",
            **SMALL_PROJECT,
        )
        assert ctx["plan"]["status"] == "DRAFT"
        assert ctx["plan"]["version"] == 1
        new_study(
            ctx["plan"]["id"],
            ctx["sites"][0]["id"],
            resource_category="RECREATION",
            study_title="Recreation use survey",
        )

        submitted = submit_plan(ctx["plan"]["id"], submission_note="ready for review")

        assert submitted["status"] == "UNDER_AGENCY_REVIEW"
        assert submitted["submitted_at"].startswith("2026-08-01T00:00:00")
        assert submitted["attached_study_count"] == 1
        assert submitted["approved_at"] is None
        project = read_project(ctx["project"]["id"])
        assert project["stage"] == "STUDY_PHASE"
        assert_postures(project, regulatory_posture="OPEN")

    def test_an_empty_plan_cannot_be_submitted_at_all(self):
        """With no study attached the submission is a bad request and the plan stays DRAFT.

        PRD §3.3: "Both paths carry the same requirements and the same effects: an optional `submission_note` is the only body input, the plan must have `attached_study_count` of at least 1 — an empty plan is rejected with `ERR_INVALID_REQUEST` — and the project's `regulatory_posture` must not be `FROZEN`."

        Design: Corner/state_machines/plan_submit_with_no_attached_studies_rejected
        """
        ctx = setup_study_phase_project(project_name="Empty Plan Reach", **SMALL_PROJECT)
        assert ctx["plan"]["attached_study_count"] == 0

        response = api_client.submit_study_plan(
            ctx["plan"]["id"], {"submission_note": "nothing attached"}, LICENSEE_HEADERS
        )

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        plan = read_study_plan(ctx["plan"]["id"])
        assert plan["status"] == "DRAFT"
        assert plan["submitted_at"] is None
        assert plan["version"] == ctx["plan"]["version"]

    def test_a_determination_on_a_draft_plan_is_refused(self):
        """APPROVE is defined only from review, so a draft plan never reaches approval.

        PRD §3.3: "Either determination requires the plan to be in `UNDER_AGENCY_REVIEW`; a determination on any other status is rejected with `ERR_STUDY_PLAN_STATE_INVALID`."
        PRD §3.3: "On success it stamps `approved_at` with the logical clock, recomputes the project's `unresolved_mandatory_comment_count` and then `regulatory_posture`, and increments the plan's `version`."

        Design: Corner/state_machines/plan_determination_from_draft_rejected
        """
        ctx = setup_study_phase_project(project_name="Invalid From Reach", **SMALL_PROJECT)
        setup_agency_party(ctx["project"]["id"])

        response = api_client.decide_study_plan(
            ctx["plan"]["id"], {"determination": "APPROVE"}, AGENCY_HEADERS
        )

        validate_error(response, "ERR_STUDY_PLAN_STATE_INVALID", 409)
        plan = read_study_plan(ctx["plan"]["id"])
        assert plan["status"] == "DRAFT"
        assert plan["approved_at"] is None
        assert plan["revision_round"] == 0


class TestStudyReportCoupling:
    def test_the_report_waits_for_the_field_effort_to_finish(self):
        """The same call is refused mid-fieldwork and accepted once the work completes.

        PRD §3.4: "Either way it requires `fieldwork_status` to be `COMPLETED`: a report filed while the field effort is still `PLANNED`, `IN_PROGRESS` or `SUSPENDED` is rejected with `ERR_STUDY_STATE_INVALID`, and so is a report filed while `review_status` is already `UNDER_REVIEW` or `ACCEPTED`."
        PRD §3.4: "Submission stamps `report_submitted_at` with the logical clock, records `report_submitted_by_user_id` from the acting `X-User-ID`, and increments the study's `version`."

        Design: Corner/state_machines/study_report_before_fieldwork_completed_rejected
        """
        ctx = setup_plan_under_agency_review(
            study_overrides=dict(
                resource_category="WATER_QUALITY", study_title="Temperature study"
            ),
            site_overrides=dict(site_code="S1", river_mile=1.0),
            project_name="Report Order Reach",
            **SMALL_PROJECT,
        )
        study_id = ctx["study"]["id"]
        started = validate_success(
            api_client.study_fieldwork(study_id, {"action": "START"}, LICENSEE_HEADERS)
        )
        assert started["fieldwork_status"] == "IN_PROGRESS"

        premature = api_client.submit_study_report(
            study_id, {"report_note": "premature report"}, REPORTER_HEADERS
        )

        validate_error(premature, "ERR_STUDY_STATE_INVALID", 409)
        refused = read_study(study_id)
        assert refused["review_status"] == "NOT_SUBMITTED"
        assert refused["report_submitted_at"] is None

        validate_success(
            api_client.study_fieldwork(study_id, {"action": "COMPLETE"}, LICENSEE_HEADERS)
        )
        reported = validate_success(
            api_client.submit_study_report(
                study_id, {"report_note": "final report"}, REPORTER_HEADERS
            )
        )

        assert reported["review_status"] == "UNDER_REVIEW"
        assert reported["report_submitted_by_user_id"] == U_LICENSEE_REPORT


class TestPreApplicationDocumentIsFiledOnce:
    def test_a_second_filing_cannot_overwrite_the_first_timestamp(self):
        """The stage guard makes the filing deliberately non-idempotent.

        PRD §3.2: "The operation is permitted only while `stage` is `PRE_FILING`, so a second filing attempt is rejected with `ERR_PROJECT_STAGE_INVALID`, and only while the logical clock's date is on or before the pre-application deadline — 66 months before `license_expiration_date` — with a late attempt rejected as `ERR_FILING_DEADLINE_PASSED`."
        PRD §3.2: "Filing stamps `pad_filed_at` with the logical clock and derives `pad_year` as the calendar year of that instant."

        Design: Corner/state_machines/second_pre_application_document_filing_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(project_name="Double PAD Dam", **SMALL_PROJECT)
        filed = file_pad(project["id"])
        assert filed["stage"] == "PAD_FILED"
        assert filed["pad_filed_at"].startswith("2026-08-01T00:00:00")
        assert filed["pad_year"] == 2026
        assert filed["version"] == 2
        set_clock("2026-09-01T00:00:00Z")

        response = api_client.file_pre_application_document(
            project["id"], {"filing_note": "PAD again"}, LICENSEE_HEADERS
        )

        validate_error(response, "ERR_PROJECT_STAGE_INVALID", 409)
        after = read_project(project["id"])
        assert after["pad_filed_at"].startswith("2026-08-01T00:00:00")
        assert after["pad_year"] == 2026
        assert after["version"] == filed["version"]


class TestSettlementOpening:
    def test_a_new_settlement_opens_in_negotiation_at_round_one(self):
        """The tally fields read empty until the first round is actually tallied.

        PRD §3.5: "The settlement starts in `NEGOTIATING` with `round_number` 1, unset `circulated_at`, `executed_at` and `withdrawn_at`, and `support_pct`, `total_vote_weight` and `included_measure_count` all zero."
        PRD §3.5: "The create also increments the project's `version`."

        Design: Corner/state_machines/settlement_starts_in_negotiating_round_one
        """
        ctx = setup_study_phase_project(project_name="Initial State Reach", **SMALL_PROJECT)
        project_id = ctx["project"]["id"]
        setup_agency_party(project_id)
        register_party(
            project_id,
            party_name="River Tribe",
            party_type="TRIBE",
            vote_weight=1,
            contact_user_id=U_TRIBE,
        )
        version_before = project_version(project_id)

        settlement = new_settlement(
            project_id, expected_project_version=version_before, title="First settlement"
        )

        assert settlement["status"] == "NEGOTIATING"
        assert settlement["round_number"] == 1
        assert settlement["included_measure_count"] == 0
        assert settlement["support_pct"] == pytest.approx(0.00, abs=0.01)
        assert settlement["total_vote_weight"] == 0
        assert settlement["circulated_at"] is None
        assert settlement["executed_at"] is None
        assert settlement["withdrawn_at"] is None
        assert settlement["version"] == 1
        assert project_version(project_id) == version_before + 1


class TestObligationTerminalState:
    def test_a_certified_obligation_keeps_the_window_it_was_certified_under(self):
        """Rescheduling is defined from PENDING and OVERDUE only, never from CERTIFIED.

        PRD §3.9: "Scheduling moves an obligation `PENDING → SCHEDULED` or, on a reschedule, `OVERDUE → SCHEDULED`; from any other status it is rejected with `ERR_OBLIGATION_STATE_INVALID`."
        PRD §3.9: "Where the obligation's `obligation_type` is `PME_IMPLEMENTATION`, its linked measure moves `INCLUDED → IMPLEMENTED`; the measure remains economically live, since `IMPLEMENTED` counts in the ledger exactly as `INCLUDED` does, but the project burden ledger is nonetheless re-run."

        Design: Corner/state_machines/certified_obligation_cannot_be_rescheduled
        """
        ctx = setup_licensed_project(
            order_number="ORD-9021",
            site_overrides=dict(site_code="S1", river_mile=1.0),
            project_name="Terminal Obligation Dam",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        obligation = ctx["obligations"][0]
        assert obligation["obligation_type"] == "PME_IMPLEMENTATION"
        assert obligation["due_date"] == "2027-02-01"
        schedule_obligation(obligation["id"], "2027-02-01", "2027-02-28")
        set_clock("2027-02-01T00:00:00Z")
        certified = certify_obligation(obligation["id"])
        assert certified["status"] == "CERTIFIED"

        response = api_client.schedule_obligation(
            obligation["id"],
            {"activity_window_start": "2027-05-01", "activity_window_end": "2027-05-31"},
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_OBLIGATION_STATE_INVALID", 409)
        unchanged = read_obligation(obligation["id"])
        assert unchanged["activity_window_start"] == "2027-02-01"
        assert unchanged["activity_window_end"] == "2027-02-28"
        assert read_measure(ctx["condition_measures"][0]["id"])["status"] == "IMPLEMENTED"
        assert read_order(ctx["order"]["id"])["open_violation_count"] == 0


class TestCertificationDenialCascade:
    def test_a_denial_freezes_the_project_and_suspends_the_application_under_review(self):
        """The state certifier never names the application the denial suspends.

        PRD §3.6: "The project's `wqc_status` becomes `DENIED`, which by itself drives `regulatory_posture` to `FROZEN`."
        PRD §3.6: "That freeze does not stop at the project: every license application of the project whose `filing_status` is `FILED`, `UNDER_REVIEW` or `DEFICIENT` is moved to `SUSPENDED`, each such application incrementing its own `version`."

        Design: Corner/state_machines/wqc_denial_cascades_freeze_and_suspends_filed_application
        """
        ctx = setup_approved_study_plan(
            study_overrides=dict(
                resource_category="WATER_QUALITY", study_title="Temperature study"
            ),
            site_overrides=dict(site_code="S1", river_mile=1.0),
            project_name="Denied Reach",
            installed_capacity_mw=12.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        wqc = request_certification(ctx["project"]["id"])
        assert wqc["status"] == "REQUESTED"
        assert wqc["statutory_waiver_date"] == "2027-08-01"
        application = file_application(ctx["project"]["id"])
        application = advance_environmental_review(application["id"], "SCOPING")
        assert application["filing_status"] == "UNDER_REVIEW"

        denied = deny_certification(
            wqc["id"], denial_reason="Thermal criteria cannot be met"
        )

        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Thermal criteria cannot be met"
        project = read_project(ctx["project"]["id"])
        assert project["wqc_status"] == "DENIED"
        assert_postures(project, regulatory_posture="FROZEN")
        assert project["stage"] == "UNDER_ENVIRONMENTAL_REVIEW"
        suspended = read_application(application["id"])
        assert suspended["filing_status"] == "SUSPENDED"
        assert suspended["ea_stage"] == "SCOPING"


class TestStudyPlanSupersede:
    def test_a_second_plan_supersedes_the_first_and_releases_its_mandatory_comment(self):
        """The comment stays OPEN on the superseded plan yet stops restricting the project.

        PRD §3.3: "When a new plan is created for a project that already has a plan in `DRAFT`, `UNDER_AGENCY_REVIEW` or `REVISION_REQUIRED`, that prior plan's status becomes `SUPERSEDED` and its `version` is incremented."
        PRD §3.3: "Its comments keep their own `resolution_status` untouched but stop counting toward the project's `unresolved_mandatory_comment_count`, which is recomputed, followed by `regulatory_posture` — so superseding a plan burdened with open mandatory comments can move a project out of `RESTRICTED`."

        Design: Corner/state_machines/new_study_plan_supersedes_prior_plan_and_releases_its_comments
        """
        ctx = setup_study_phase_project(project_name="Supersede Reach", **SMALL_PROJECT)
        project_id = ctx["project"]["id"]
        party = setup_agency_party(project_id)
        comment = leave_comment(
            ctx["plan"]["id"],
            party,
            resource_category="FISH_PASSAGE",
            comment_text="Add a downstream passage study",
        )
        before = read_project(project_id)
        assert before["unresolved_mandatory_comment_count"] == 1
        assert_postures(before, regulatory_posture="RESTRICTED")

        second_plan = new_study_plan(project_id, plan_title="Study Plan 2")

        assert second_plan["status"] == "DRAFT"
        assert second_plan["revision_round"] == 0
        assert second_plan["id"] != ctx["plan"]["id"]
        superseded = read_study_plan(ctx["plan"]["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["open_comment_count"] == 1
        retained = read_comment(comment["id"])
        assert retained["resolution_status"] == "OPEN"
        assert retained["is_mandatory_condition"] is True
        after = read_project(project_id)
        assert after["unresolved_mandatory_comment_count"] == 0
        assert_postures(after, regulatory_posture="OPEN")
        assert after["stage"] == "STUDY_PHASE"


class TestObligationCertificationBubblesUp:
    def test_clearing_the_last_violation_lifts_both_the_order_and_the_project(self):
        """Three overdue articles are cured and the final certify unfreezes the project.

        PRD §3.9: "The logical clock's date must have reached the obligation's `activity_window_start`, and an earlier attempt is rejected with `ERR_CERTIFICATION_TOO_EARLY`."
        PRD §3.9: "The owning order's `open_violation_count` is recomputed, and when it reaches zero an order sitting in `COMPLIANCE_FLAGGED` moves back to `EFFECTIVE`, which recomputes the project's `compliance_flag_count` and then `regulatory_posture` — the two-tier jump described in §2.8."

        Design: Corner/state_machines/obligation_certification_bubbles_order_and_project_out_of_flagged
        """
        ctx = setup_licensed_project(
            order_number="ORD-9024",
            dams=[DAM_NO_EAP],
            site_overrides=dict(site_code="S1", river_mile=1.0),
            project_name="Bubble Up Dam",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        assert ctx["order"]["article_count"] == 3
        set_clock("2029-02-01T00:00:00Z")
        assert_postures(run_sweep(ctx["project"]["id"]), regulatory_posture="FROZEN")
        inspection = [
            o for o in ctx["obligations"] if o["obligation_type"] == "DAM_SAFETY_INSPECTION"
        ][0]

        rescheduled = schedule_obligation(inspection["id"], "2029-06-01", "2029-06-30")
        too_early = api_client.certify_obligation(
            inspection["id"], {"certification_note": "too early"}, LICENSEE_HEADERS
        )

        assert rescheduled["status"] == "SCHEDULED"
        validate_error(too_early, "ERR_CERTIFICATION_TOO_EARLY", 409)

        set_clock("2029-06-01T00:00:00Z")
        for obligation in ctx["obligations"]:
            if obligation["id"] != inspection["id"]:
                schedule_obligation(obligation["id"], "2029-06-01", "2029-06-30")
            certified = certify_obligation(obligation["id"])
            assert certified["status"] == "CERTIFIED"
            assert certified["certified_by_user_id"] == U_LICENSEE_A

        order = read_order(ctx["order"]["id"])
        assert order["open_violation_count"] == 0
        assert order["compliance_state"] == "EFFECTIVE"
        project = read_project(ctx["project"]["id"])
        assert project["compliance_flag_count"] == 0
        assert_postures(project, regulatory_posture="OPEN")
        assert read_measure(ctx["condition_measures"][0]["id"])["status"] == "IMPLEMENTED"
        assert project["total_pme_annual_cost_usd"] == pytest.approx(53000.00, abs=0.01)


class TestOrderIssuanceIsGuardedByTheProjectPosture:
    def test_an_infeasible_ledger_blocks_issuance_until_generation_is_restored(self):
        """The guard lives on the parent project, so restoring generation reopens issuance.

        PRD §2.8: "Under `RESTRICTED`, study work, settlement work and application filing all proceed normally — application filing carries its own explicit economic check rather than relying on the posture — but order issuance is rejected with `ERR_PROJECT_POSTURE_RESTRICTED` (HTTP 409)."
        PRD §3.8: "The project's `regulatory_posture` must not be `FROZEN`, rejected with `ERR_PROJECT_POSTURE_FROZEN`, and must not be `RESTRICTED` either, rejected with `ERR_PROJECT_POSTURE_RESTRICTED` — order issuance is the one operation the restricted tier blocks."

        Design: Corner/state_machines/order_issuance_rejected_while_posture_restricted
        """
        ctx = setup_application_under_review(
            ea_stage="FINAL_EA",
            site_overrides=dict(site_code="S1", river_mile=1.0),
            project_name="Restricted Order Dam",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        project_id = ctx["project"]["id"]
        application_id = ctx["application"]["id"]
        assert ctx["application"]["ea_stage"] == "FINAL_EA"
        assert ctx["application"]["filing_status"] == "UNDER_REVIEW"
        ladder = new_measure(project_id, source="AGENCY_PRESCRIPTION", **FULL_HEIGHT_LADDER)
        restricted = patch_project(project_id, base_annual_generation_mwh=60000)
        assert restricted["administrative_annual_charge_usd"] == pytest.approx(
            6393.33, abs=0.01
        )
        assert restricted["total_annual_burden_usd"] == pytest.approx(467931.80, abs=0.01)
        assert restricted["burden_ratio_pct"] == pytest.approx(18.57, abs=0.01)
        assert_postures(restricted, regulatory_posture="RESTRICTED")

        refused = api_client.issue_order(
            application_id, {"order_number": "ORD-9025"}, REGULATOR_HEADERS
        )

        validate_error(refused, "ERR_PROJECT_POSTURE_RESTRICTED", 409)
        assert read_application(application_id)["filing_status"] == "UNDER_REVIEW"
        assert read_project(project_id)["stage"] == "UNDER_ENVIRONMENTAL_REVIEW"

        restored = patch_project(project_id, base_annual_generation_mwh=250000)
        order = validate_success(
            api_client.issue_order(
                application_id, {"order_number": "ORD-9025"}, REGULATOR_HEADERS
            ),
            201,
        )

        assert restored["burden_ratio_pct"] == pytest.approx(4.46, abs=0.01)
        assert_postures(restored, regulatory_posture="OPEN")
        assert order["compliance_state"] == "EFFECTIVE"
        assert order["article_count"] == 2
        assert read_project(project_id)["stage"] == "LICENSED"
        obligations = list_obligations(order["id"])
        due_by_measure = {o["pme_measure_id"]: o["due_date"] for o in obligations}
        assert due_by_measure[ctx["condition_measures"][0]["id"]] == "2027-02-01"
        assert due_by_measure[ladder["id"]] == "2028-08-01"
