"""Inspections: payload validation, QA rolling-window scoring, the
remediation loop, the fail-to-suspension cascade, and the ordering of the
segregation screen ahead of caller ownership on record."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_completed_project,
    create_failed_inspection_project,
    create_inspecting_project,
    create_inspector,
    create_lead,
    distribute_lead,
    is_iso8601_timestamp,
    make_inspector_headers,
    record_inspection,
    schedule_inspection,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestInspectionPayloadValidation:
    def test_inspection_record_fail_without_reasons_rejected(self, api, pm_headers):
        """PRD 3.6: "A valid recording payload carries an `outcome` of `PASS`
        or `FAIL`, a `score_bps` between 0 and 10,000 inclusive, and a
        `failure_reasons` list that must be non-empty exactly when the outcome
        is `FAIL` — empty on a failure, or supplied on a pass, is malformed, as
        is any out-of-range score, and all such payloads draw
        `ERR_INVALID_INSPECTION_PAYLOAD` (HTTP 400)."

        Design: Corner/validations/inspection_record_fail_without_reasons_rejected
        """
        set_clock()
        ctx = create_inspecting_project()
        resp = api.record_inspection(
            ctx["inspection"]["id"],
            {"outcome": "FAIL", "score_bps": 5000, "failure_reasons": []},
            make_inspector_headers(ctx["inspector"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INSPECTION_PAYLOAD)


class TestQaScoreRollingWindow:
    def test_qa_score_is_mean_of_recorded_inspections(self, api, pm_headers):
        """PRD 3.6: "recomputes the contractor's `qa_score_bps` as the
        arithmetic mean of `score_bps` across the contractor's ten most recent
        `RECORDED` inspections — passing and failing inspections contribute
        alike, and when fewer than ten recorded inspections exist the mean is
        taken over all of them — rounded half up to integer basis points."
        Two recorded inspections scored 8000 and 6000 yield (8000+6000)/2 =
        7000.

        Design: Corner/calculations/qa_score_rolling_window
        """
        set_clock()
        ctx1 = create_completed_project(pass_score_bps=8000)
        assert ctx1["contractor"]["qa_score_bps"] == 8000
        # Second project for the same contractor, completed with a 6000 score.
        ctx2 = create_completed_project(
            pass_score_bps=6000,
            program_id=ctx1["program"]["id"],
            contractor_id=ctx1["contractor"]["id"],
            customer_id=ctx1["customer"]["id"],
        )
        assert ctx2["contractor"]["qa_score_bps"] == 7000


class TestProjectRemediationLoop:
    def test_fail_routes_project_to_remediation(self, api, pm_headers):
        """PRD 3.6: "On a `FAIL`, the project moves `INSPECTING` →
        `REMEDIATION`, the inspection's `remediation_required_by` is set to the
        current logical clock plus the remediation window — a fixed number of
        days — and the recomputed quality score already includes this failing
        grade."

        Design: Difficulty/non_linear_state_machine/project_remediation_loop
        """
        set_clock()
        ctx = create_failed_inspection_project(
            fail_score_bps=8000, failure_reasons=["WRONG_REFRIGERANT_CHARGE"])
        assert ctx["inspection"]["status"] == "RECORDED"
        assert ctx["inspection"]["outcome"] == "FAIL"
        assert ctx["inspection"]["score_bps"] == 8000
        deadline = ctx["inspection"]["remediation_required_by"]
        assert isinstance(deadline, str) and is_iso8601_timestamp(deadline)
        assert ctx["project"]["status"] == "REMEDIATION"

    def test_reinspection_returns_project_to_inspecting(self, api, pm_headers):
        """PRD 3.6: "When a project sits in `REMEDIATION`, the same scheduling
        act books the re-inspection and returns the project `REMEDIATION` →
        `INSPECTING` — but only on or before the `remediation_required_by`
        deadline recorded on the most recent failed inspection".

        Design: Difficulty/non_linear_state_machine/project_remediation_loop
        """
        set_clock()
        ctx = create_failed_inspection_project(fail_score_bps=8000)
        ins2 = schedule_inspection(
            ctx["work_order"]["id"], ctx["project"]["id"], ctx["inspector"]["id"],
            scheduled_on="2026-08-05T00:00:00Z")
        assert ins2["id"] != ctx["inspection"]["id"]
        assert ins2["status"] == "SCHEDULED"
        assert ins2["outcome"] == "PENDING"
        project = validate_success(api.get_project(ctx["project"]["id"], pm_headers))
        assert project["status"] == "INSPECTING"


class TestInspectionFailCascadesToContractorSuspension:
    def _setup_one_fail_and_offered_lead(self, api):
        """First FAIL (score 6000) keeps qa_score_bps at 6000 (>= 5000, no
        suspension yet — PRD 3.6); then a second OFFERED lead is distributed
        to the still-APPROVED contractor."""
        set_clock()
        ctx = create_failed_inspection_project(fail_score_bps=6000)
        contractor = validate_success(
            api.get_contractor(ctx["contractor"]["id"], PM))
        assert contractor["qa_score_bps"] == 6000
        assert contractor["status"] == "APPROVED"
        lead2 = create_lead(ctx["customer"]["id"], ctx["program"]["id"],
                            estimated_annual_kwh_savings=800)
        offered2 = distribute_lead(lead2["id"], lead2["version"])
        assert offered2["assigned_contractor_id"] == ctx["contractor"]["id"]
        # Re-inspection returns the project to INSPECTING (clock unchanged, so
        # it is on or before the remediation deadline — PRD 3.6).
        ins2 = schedule_inspection(
            ctx["work_order"]["id"], ctx["project"]["id"], ctx["inspector"]["id"],
            scheduled_on="2026-08-05T00:00:00Z")
        ctx["inspection2"] = ins2
        ctx["offered_lead2"] = offered2
        return ctx

    def test_second_fail_suspends_contractor(self, api, pm_headers):
        """PRD 3.6: "Should that recomputed `qa_score_bps` fall below 5,000
        basis points, the contractor is automatically suspended, with the usual
        suspension consequences: removal from lead distribution and automatic
        expiry of the firm's outstanding `OFFERED` leads."
        Window after the second FAIL: (6000 + 3000) / 2 = 4500 < 5000.

        Design: Difficulty/transitive_cascade/inspection_fail_cascades_to_contractor_suspension
        """
        ctx = self._setup_one_fail_and_offered_lead(api)
        record_inspection(ctx["inspection2"]["id"], ctx["inspector"]["id"],
                          outcome="FAIL", score_bps=3000,
                          failure_reasons=["STILL_BAD"])
        project = validate_success(api.get_project(ctx["project"]["id"], pm_headers))
        assert project["status"] == "REMEDIATION"
        contractor = validate_success(
            api.get_contractor(ctx["contractor"]["id"], pm_headers))
        assert contractor["qa_score_bps"] == 4500
        assert contractor["status"] == "SUSPENDED"

    def test_suspension_cascade_expires_offered_lead(self, api, pm_headers):
        """PRD 3.6: "Should that recomputed `qa_score_bps` fall below 5,000
        basis points, the contractor is automatically suspended, with the usual
        suspension consequences: removal from lead distribution and automatic
        expiry of the firm's outstanding `OFFERED` leads."
        PRD 3.2: "every `OFFERED` lead currently assigned to it automatically
        expires (`OFFERED` → `EXPIRED`), clearing the lead's
        `assigned_contractor_id`."

        Design: Difficulty/transitive_cascade/inspection_fail_cascades_to_contractor_suspension
        """
        ctx = self._setup_one_fail_and_offered_lead(api)
        record_inspection(ctx["inspection2"]["id"], ctx["inspector"]["id"],
                          outcome="FAIL", score_bps=3000,
                          failure_reasons=["STILL_BAD"])
        lead_after = validate_success(api.get_lead(ctx["offered_lead2"]["id"], pm_headers))
        assert lead_after["status"] == "EXPIRED"
        assert lead_after["assigned_contractor_id"] is None


class TestSafetyVsReferentialOnInspectionRecord:
    def _setup_with_extra_inspectors(self, api):
        """Project in INSPECTING with inspection scheduled by inspector A.
        Inspector B excludes the contractor (safety conflict) and is not the
        assigned inspector; inspector C has no conflict but is not assigned."""
        set_clock()
        ctx = create_inspecting_project()
        ctr_id = ctx["contractor"]["id"]
        insp_b = create_inspector(excluded_contractor_ids=[ctr_id])
        insp_c = create_inspector()
        ctx["inspector_b"] = insp_b
        ctx["inspector_c"] = insp_c
        return ctx

    def test_excluded_non_owner_inspector_gets_inspector_conflict(self, api, pm_headers):
        """PRD 3.6: "the request is screened in a fixed order before its
        payload is even examined: the inspection must be `SCHEDULED` (otherwise
        `ERR_INVALID_STATE`), the segregation rule is re-checked against the
        work order's contractor (`ERR_INSPECTOR_CONFLICT`), and the caller must
        be the inspection's own `inspector_id` (otherwise
        `ERR_NOT_RESOURCE_OWNER`)."
        Inspector B trips both the segregation screen and the ownership check;
        the segregation screen runs first.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_inspection_record
        """
        ctx = self._setup_with_extra_inspectors(api)
        resp = api.record_inspection(
            ctx["inspection"]["id"],
            {"outcome": "PASS", "score_bps": 8000},
            make_inspector_headers(ctx["inspector_b"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_CONFLICT)

    def test_non_excluded_non_owner_inspector_gets_not_resource_owner(self, api, pm_headers):
        """PRD 3.6: "the caller must be the inspection's own `inspector_id`
        (otherwise `ERR_NOT_RESOURCE_OWNER`)."
        Inspector C has no segregation conflict, so the ownership check is the
        one that fires.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_inspection_record
        """
        ctx = self._setup_with_extra_inspectors(api)
        resp = api.record_inspection(
            ctx["inspection"]["id"],
            {"outcome": "PASS", "score_bps": 8000},
            make_inspector_headers(ctx["inspector_c"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
