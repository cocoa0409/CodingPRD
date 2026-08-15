"""Interpretation sessions: dual-variant pricing, settlement, ownership gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    adjudicate_complaint,
    complete_request,
    create_active_contract,
    create_assigned_request,
    create_department,
    create_document,
    create_interpreter,
    get_contract,
    get_department,
    get_interpreter,
    make_interpreter_headers,
    make_liaison_headers,
    record_complaint,
    set_clock,
    setup_interpretation_workspace,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


class TestEstimatedVersusFinalVariant:
    def _completed_in_person_session(self):
        ws = setup_interpretation_workspace(
            dept_budget=1_000_000, ceiling_cents=1_000_000, tier="CERTIFIED",
            modalities=("IN_PERSON",), interpreter_name="Iris Cert")
        request = create_assigned_request(
            ws["department"]["id"], modality="IN_PERSON",
            scheduled_start="2026-08-10T10:00:00Z", scheduled_duration_minutes=45)
        completed = complete_request(request["id"], ws["interpreter"]["id"], 130)
        return ws, request, completed

    def test_estimated_and_final_costs_diverge_on_actual_minutes(self, api):
        """PRD §3.6: "First, the session length is rounded up to the next whole
        multiple of six minutes, and the billable minutes are the greater of that
        rounded length and the modality minimum — fifteen minutes for `PHONE`,
        fifteen for `VIDEO`, sixty for `IN_PERSON`."
        PRD §3.6: "The estimated variant runs these five steps over
        `scheduled_duration_minutes` at dispatch; the final variant runs them
        over `actual_minutes` at completion, so identical bookings price
        differently whenever a session runs long or short."

        Design: Difficulty/dual_variant_calc/interpretation_cost_estimated_vs_final
        """
        _, request, completed = self._completed_in_person_session()
        # Estimated: max(60, ceil(45/6)*6=48) = 60 min x 100c x 1.15 + 2500c.
        assert request["estimated_cost_cents"] == 9400
        # Final: ceil(130/6)*6 = 132 min x 100c x 1.15 + 2500c.
        assert completed["final_cost_cents"] == 17680
        assert completed["estimated_cost_cents"] != completed["final_cost_cents"], (
            "the variants diverge whenever the session runs long or short"
        )

    def test_completion_settles_ledgers_and_monthly_minutes(self, api):
        """PRD §3.6: "The request becomes `COMPLETED`; `completed_at` is stamped
        from the logical clock; `final_cost_cents` is computed by the final
        variant and stored, having been null until now; the contract releases
        the estimate from `committed_cents` and adds the final to `spent_cents`;
        the department's `spent_cents` absorbs the final as well"
        PRD §3.5: "`minutes_current_month` sums the `actual_minutes` of the
        interpreter's `COMPLETED`, non-refunded requests whose `completed_at`
        falls inside the calendar month (UTC) of the current logical clock."

        Design: Difficulty/dual_variant_calc/interpretation_cost_estimated_vs_final
        """
        ws, _, completed = self._completed_in_person_session()
        assert completed["status"] == "COMPLETED"
        contract = get_contract(ws["contract"]["id"])
        assert contract["committed_cents"] == 0, "the estimate is released"
        assert contract["spent_cents"] == 17680, "the final settles into spend"
        assert get_department(ws["department"]["id"])["spent_cents"] == 17680
        interpreter = get_interpreter(ws["interpreter"]["id"])
        assert interpreter["minutes_current_month"] == 130


class TestFinalCostRoundingOrder:
    def _completed_video_session(self):
        ws = setup_interpretation_workspace(
            dept_budget=1_000_000, ceiling_cents=1_000_000, tier="REGISTERED",
            modalities=("VIDEO",), interpreter_name="Reg Video")
        request = create_assigned_request(
            ws["department"]["id"], modality="VIDEO",
            scheduled_start="2026-08-10T10:00:00Z", scheduled_duration_minutes=60)
        completed = complete_request(request["id"], ws["interpreter"]["id"], 61)
        return ws, request, completed

    def test_final_cost_quantizes_minutes_before_rating(self, api):
        """PRD §3.6: "First, the session length is rounded up to the next whole
        multiple of six minutes, and the billable minutes are the greater of that
        rounded length and the modality minimum — fifteen minutes for `PHONE`,
        fifteen for `VIDEO`, sixty for `IN_PERSON`. Second, the base is those
        billable minutes multiplied by the per-minute rate for the session's
        modality taken from the selected interpreter's contract rate card."

        Design: Difficulty/combinatorial_formula/interpretation_final_cost_rounding_order_pinned
        """
        _, request, completed = self._completed_video_session()
        assert request["estimated_cost_cents"] == 4500, (
            "60 minutes x 75c with a REGISTERED 1.0 multiplier"
        )
        # 61 raw minutes must first quantize to 66 billable minutes:
        # 66 x 75c = 4950c. Multiplying raw minutes would give 4575c — rejected.
        assert completed["final_cost_cents"] == 4950

    def test_contract_settles_rounded_final_cost(self, api):
        """PRD §3.6: "the contract releases the estimate from `committed_cents`
        and adds the final to `spent_cents`"
        PRD §3.6: "The estimated variant runs these five steps over
        `scheduled_duration_minutes` at dispatch; the final variant runs them
        over `actual_minutes` at completion"

        Design: Difficulty/combinatorial_formula/interpretation_final_cost_rounding_order_pinned
        """
        ws, _, completed = self._completed_video_session()
        assert completed["final_cost_cents"] == 4950
        contract = get_contract(ws["contract"]["id"])
        assert contract["spent_cents"] == 4950
        assert contract["committed_cents"] == 0


class TestNoncompliantDepartmentGate:
    def _noncompliant_department(self):
        dept = create_department(name="Dept Transit", service_area_code="SA-13")
        for i in range(3):
            complaint = record_complaint(
                dept["id"], category="NO_INTERPRETER_AVAILABLE",
                description=f"k{i}")
            adjudicate_complaint(complaint["id"], outcome="SUBSTANTIATED")
        return dept

    def test_noncompliant_department_request_rejected(self, api):
        """PRD §3.1: "a complaint adjudicated `SUBSTANTIATED` costs the
        department 150 points, timed at the complaint's `adjudicated_at`"
        PRD §3.1: "The final score then derives `posture`: at least 800 is
        `GOOD_STANDING`, 600 through 799 is `WATCH`, and below 600 is
        `NONCOMPLIANT`. A `NONCOMPLIANT` department is barred from commissioning
        new translation jobs and from creating interpretation requests — both
        attempts fail with `ERR_DEPARTMENT_NONCOMPLIANT` — until remediation
        restores its standing."

        Design: Difficulty/cross_entity_state_dependency/request_create_blocked_when_department_noncompliant
        """
        dept = self._noncompliant_department()
        dept_after = get_department(dept["id"])
        assert dept_after["compliance_score"] == 550, "1000 - 3 x 150"
        assert dept_after["posture"] == "NONCOMPLIANT"

        resp = api.create_interpretation_request(
            {"department_id": dept["id"], "language_code": "es",
             "modality": "PHONE", "encounter_setting": "GENERAL",
             "scheduled_duration_minutes": 30},
            make_liaison_headers(dept["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPARTMENT_NONCOMPLIANT.value)

    def test_noncompliant_department_job_rejected_and_nothing_persisted(
            self, api, coordinator_headers):
        """PRD §3.1: "A `NONCOMPLIANT` department is barred from commissioning
        new translation jobs and from creating interpretation requests — both
        attempts fail with `ERR_DEPARTMENT_NONCOMPLIANT` — until remediation
        restores its standing."

        Design: Difficulty/cross_entity_state_dependency/request_create_blocked_when_department_noncompliant
        """
        dept = self._noncompliant_department()
        contract = create_active_contract(vendor_name="VendorGate",
                                          ceiling_cents=500000)
        document = create_document(dept["id"], title="Transit Notice",
                                   document_type="NOTICE")
        job_resp = api.create_translation_job(
            {"document_id": document["id"], "vendor_contract_id": contract["id"],
             "target_language_code": "es", "word_count": 100},
            COORDINATOR,
        )
        validate_error(job_resp, ApiErrorId.ERR_DEPARTMENT_NONCOMPLIANT.value)

        req_resp = api.create_interpretation_request(
            {"department_id": dept["id"], "language_code": "es",
             "modality": "PHONE", "encounter_setting": "GENERAL",
             "scheduled_duration_minutes": 30},
            make_liaison_headers(dept["id"]),
        )
        validate_error(req_resp, ApiErrorId.ERR_DEPARTMENT_NONCOMPLIANT.value)
        _, meta = validate_paginated(api.list_interpretation_requests(
            coordinator_headers, params={"department_id": dept["id"]}))
        assert meta["total_count"] == 0


class TestSessionOwnership:
    def test_interpreter_cannot_complete_others_assignment(self, api):
        """PRD §3.6: "Completion belongs to the assigned interpreter alone — any
        other caller is refused with `ERR_FORBIDDEN_ROLE` — and requires a
        strictly positive `actual_minutes` (`ERR_VALIDATION` otherwise)."
        PRD §3.6: "Eligible candidates are ranked by `minutes_current_month`
        ascending, then `created_at` ascending, then `full_name` ascending, and
        the first-ranked candidate is selected."

        Design: Corner/rbac/interpreter_cannot_complete_others_assignment
        """
        dept = create_department(name="Dept Own", service_area_code="SA-C36")
        ws = setup_interpretation_workspace(
            dept_budget=1_000_000, ceiling_cents=500000, tier="CERTIFIED",
            interpreter_name="X Owner")
        owner = ws["interpreter"]
        set_clock("2026-08-01T00:01:00Z")
        other = create_interpreter(ws["contract"]["id"], full_name="Y Other",
                                   tier="CERTIFIED")
        request = create_assigned_request(
            dept["id"], modality="PHONE", scheduled_duration_minutes=30,
            scheduled_start="2026-08-01T10:00:00Z")
        assert request["interpreter_id"] == owner["id"], (
            "setup: equal minutes, earliest created_at wins the tie-break"
        )

        resp = api.complete_interpretation_request(
            request["id"], {"actual_minutes": 30},
            make_interpreter_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        stayed = validate_success(api.get_interpretation_request(
            request["id"], COORDINATOR))
        assert stayed["status"] == "ASSIGNED"
        assert stayed["interpreter_id"] == owner["id"]

    def test_liaison_cannot_act_for_other_department(self, api):
        """PRD §3.6: "A `DepartmentLiaison` requests an interpreter with the
        owning `department_id` (which must be the liaison's own department, else
        `ERR_FORBIDDEN_ROLE`)"
        PRD §2.1: "When `X-User-Role` is `DepartmentLiaison`, `X-User-ID` is the
        `id` of the `Department` the liaison represents: ownership checks on any
        resource that references a department compare the resource's
        `department_id` field to `X-User-ID`, and a liaison acting on another
        department's resources is refused."

        Design: Corner/rbac/liaison_cannot_act_for_other_department
        """
        dept_a = create_department(name="Dept A", service_area_code="SA-C34",
                                   annual_budget_cents=100000)
        dept_b = create_department(name="Dept B", service_area_code="SA-C35",
                                   annual_budget_cents=100000)
        resp = api.create_interpretation_request(
            {"department_id": dept_b["id"], "language_code": "es",
             "modality": "PHONE", "encounter_setting": "GENERAL",
             "scheduled_duration_minutes": 30},
            make_liaison_headers(dept_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        _, meta = validate_paginated(api.list_interpretation_requests(
            COORDINATOR, params={"department_id": dept_b["id"]}))
        assert meta["total_count"] == 0


class TestSessionNotFound:
    def test_get_request_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/errors/get_request_not_found_returns_404
        """
        resp = api.get_interpretation_request(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_FOUND.value)

    def test_get_interpreter_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/errors/get_interpreter_not_found_returns_404
        """
        resp = api.get_interpreter(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INTERPRETER_NOT_FOUND.value)
