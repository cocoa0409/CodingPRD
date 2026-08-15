"""Security (auth/RBAC/segregation), OCC stale-version guards, error-priority
pairs, not-found handling, and pagination envelope.

PRD §2.1 (headers), §2.8 (segregation/ownership), §2.9 (OCC), §2.10
(validation order), §2.3 (pagination), and §2.10 rank 3 (existence).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_staff,
    create_student,
    draft_plan,
    get_case_version,
    get_scheduled_checkin,
    get_success_data,
    order_assessment,
    score_case,
    setup_case_in_intake,
    setup_case_on_leave,
    setup_case_plan_active,
    setup_case_triaged,
    setup_staff_group,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    make_bit_chair_headers,
    make_case_manager_headers,
    make_system_admin_headers,
)


class TestAuthHeaderGate:
    def test_missing_auth_headers_rejected_before_existence(self, api):
        """PRD §2.1: "A request with either header missing, with a role string
        outside this set, or — for an entity-backed role — with an `X-User-ID`
        that does not resolve to an existing staff record is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.10: "1. **Request context** — both headers present, the role
        declared, and entity-backed identities resolving to a real staff
        record; failures yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        # No X-User-ID / X-User-Role at all; the id would 404 if auth passed.
        resp = api.get_student(NON_EXISTENT_UUID, headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:
    def test_reporter_cannot_record_risk_scoring(self, api):
        """PRD §3.2: "Scoring is performed exclusively by a `BITChair`, whose
        `X-User-ID` is recorded as the scoring's `scored_by`"
        PRD §2.10: "2. **Role authorization** — the caller's role listed for
        the endpoint; failures yield `ERR_FORBIDDEN` (403)."

        Design: Corner/validations/reporter_cannot_score_returns_forbidden
        """
        ctx = setup_staff_group(chair=False, case_manager=False)
        resp = api.create_risk_scoring(
            {
                "case_id": NON_EXISTENT_UUID,
                "mode": "INITIAL",
                "harm_to_self": 1,
                "harm_to_others": 1,
                "academic_disruption": 1,
                "substance_involvement": 1,
                "rationale": "x",
            },
            ctx["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_case_manager_cannot_order_assessment(self, api):
        """PRD §3.5: "When the team needs a clinical judgment before it can
        proceed, a `BITChair` orders a mandated assessment, naming the
        `case_id`, the `evaluator_id` of the `CounselingEvaluator` who must
        record the outcome, a `due_at` deadline, and a `rationale` for
        mandating it."
        PRD §2.10: "2. **Role authorization** — the caller's role listed for
        the endpoint; failures yield `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/case_manager_cannot_order_assessment
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_plan_active(ctx, external_ref="S0030", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        resp = api.create_mandated_assessment(
            {
                "case_id": ctx["case_id"],
                "evaluator_id": ctx["ev"]["id"],
                "due_at": "2026-08-10T00:00:00Z",
                "rationale": "cm attempt",
            },
            ctx["cm_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDuties:
    def test_approver_who_is_drafter_rejected(self, api):
        """PRD §2.8: "A plan's approver must differ from its `drafted_by`."
        PRD §2.8: "Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Corner/rbac/segregation_approver_is_drafter_rejected
        """
        admin = make_system_admin_headers()
        hybrid = create_staff("Hybrid Person", "BIT_OFFICE")
        rep = create_staff("Prof Rep", "FACULTY_AFFAIRS")
        hyb_chair = make_bit_chair_headers(hybrid["id"])
        hyb_cm = make_case_manager_headers(hybrid["id"])
        rep_h = {"X-User-ID": rep["id"], "X-User-Role": "Reporter",
                 "Content-Type": "application/json"}
        student = create_student(external_ref="S0033")
        report = get_success_data(
            api.create_concern_report(
                {
                    "student_id": student["id"],
                    "category": "ACADEMIC_DISTRESS",
                    "narrative": "n",
                    "observed_at": "2026-07-31T10:00:00Z",
                },
                rep_h,
            )
        )
        get_success_data(api.start_review_concern_report(report["id"], hyb_chair))
        accepted = get_success_data(
            api.accept_concern_report(report["id"], {"case_manager_id": hybrid["id"]}, hyb_chair)
        )
        case_id = accepted["care_case_id"]
        get_success_data(
            api.create_risk_scoring(
                {
                    "case_id": case_id,
                    "mode": "INITIAL",
                    "harm_to_self": 0,
                    "harm_to_others": 0,
                    "academic_disruption": 0,
                    "substance_involvement": 0,
                    "rationale": "low",
                },
                hyb_chair,
            )
        )
        case = get_success_data(api.get_care_case(case_id, hyb_chair))
        plan = get_success_data(
            api.create_intervention_plan(
                {
                    "case_id": case_id,
                    "expected_case_version": case["version"],
                    "objectives": ["o"],
                    "success_criteria": "s",
                },
                hyb_cm,
            )
        )
        get_success_data(api.submit_intervention_plan(plan["id"], hyb_cm))
        resp = api.approve_intervention_plan(plan["id"], hyb_chair)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        plan_after = get_success_data(api.get_intervention_plan(plan["id"], hyb_chair))
        assert plan_after["status"] == "PENDING_APPROVAL"


class TestSystemAdminOpaqueIdentity:
    def test_opaque_admin_manages_roster_without_staff_record(self, api):
        """PRD §2.1: "When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an
        opaque operator identifier not tied to any persisted entity; the server
        does not compare it to any entity's `id`."

        Design: Corner/rbac/system_admin_opaque_identity_manages_roster
        """
        admin = make_system_admin_headers("operator-not-in-roster")
        staff = validate_success(
            api.create_staff({"full_name": "New Hire", "office": "BIT_OFFICE"}, admin),
            expected_status=201,
        )
        student = validate_success(
            api.create_student({"external_ref": "S0032", "full_name": "Stu New"}, admin),
            expected_status=201,
        )
        assert isinstance(staff["id"], str) and staff["id"]
        assert isinstance(student["id"], str) and student["id"]


class TestNotFound:
    def test_get_unknown_case_id_returns_not_found(self, api):
        """PRD §2.10: "3. **Existence** — path identifiers validated left to
        right, then body foreign-key targets (`student_id`, `case_id`,
        `case_manager_id`, `evaluator_id`, `related_report_id`); failures yield
        `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_unknown_ids_return_not_found
        """
        ctx = setup_staff_group(case_manager=False, reporter=False)
        resp = api.get_care_case(NON_EXISTENT_UUID, ctx["chair_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPaginationEnvelope:
    def test_limit_offset_total_count_has_more(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit`
        parameter caps the number of items returned: it defaults to 10 when
        omitted, accepts a minimum of 1, and rejects values above 100. The
        `offset` parameter states how many items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_pagination_limit_and_has_more
        """
        ctx = setup_staff_group()
        student = create_student(external_ref="S0004")
        submit_report(ctx, student["id"], category="ACADEMIC_DISTRESS", narrative="first")
        submit_report(ctx, student["id"], narrative="second",
                      observed_at="2026-07-31T11:00:00Z")
        page1, meta1 = validate_paginated(
            api.list_concern_reports(
                ctx["chair_headers"],
                params={"student_id": student["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_concern_reports(
                ctx["chair_headers"],
                params={"student_id": student["id"], "limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"]


class TestOccStaleVersion:
    def test_stale_expected_version_rejected_on_plan_create(self, api):
        """PRD §2.9: "Drafting an intervention plan and filing a re-entry
        petition each require the request body to carry
        `expected_case_version`, holding the `version` of the case as the
        client last observed it. If the case's current `version` has advanced
        past that observed value — because any workflow event on the case has
        mutated it since — the write is rejected with `ERR_STALE_CASE_VERSION`
        (HTTP 412), preventing the client from building a plan or petition on a
        state of the case it never saw."

        Design: Corner/cross_cutting_layers/occ_stale_version_plan_create_rejected
        """
        ctx = setup_staff_group(case_manager2=True)
        setup_case_triaged(ctx, external_ref="S0035", category="ACADEMIC_DISTRESS")
        stale_version = get_case_version(ctx, ctx["case_id"])
        # An unrelated mutation (assign-manager) advances the case version.
        get_success_data(
            api.assign_case_manager(
                ctx["case_id"], {"case_manager_id": ctx["cm2"]["id"]},
                ctx["chair_headers"],
            )
        )
        resp = api.create_intervention_plan(
            {
                "case_id": ctx["case_id"],
                "expected_case_version": stale_version,
                "objectives": ["o"],
                "success_criteria": "s",
            },
            ctx["cm2_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

    def test_stale_expected_version_rejected_on_reentry_petition(self, api):
        """PRD §2.9: "Drafting an intervention plan and filing a re-entry
        petition each require the request body to carry
        `expected_case_version`, holding the `version` of the case as the
        client last observed it. If the case's current `version` has advanced
        past that observed value — because any workflow event on the case has
        mutated it since — the write is rejected with `ERR_STALE_CASE_VERSION`
        (HTTP 412), preventing the client from building a plan or petition on a
        state of the case it never saw."

        Design: Corner/cross_cutting_layers/occ_stale_version_reentry_petition_rejected
        """
        ctx = setup_staff_group(evaluator=True, dean=True, case_manager2=True)
        setup_case_on_leave(ctx, external_ref="S0036")
        stale_version = get_case_version(ctx, ctx["case_id"])
        get_success_data(
            api.assign_case_manager(
                ctx["case_id"], {"case_manager_id": ctx["cm2"]["id"]},
                ctx["chair_headers"],
            )
        )
        resp = api.create_reentry_evaluation(
            {
                "case_id": ctx["case_id"],
                "expected_case_version": stale_version,
                "petition_summary": "stale view",
            },
            ctx["cm2_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)


class TestStateVsRubricRangePriority:
    def test_state_error_masks_rubric_range_error(self, api):
        """PRD §2.10: "5. **State-machine preconditions** — the target
        transition's state requirements; failures yield the appropriate member
        of the 409 state family"
        PRD §2.10: "9. **Field and constraint checks** — rubric range,
        scoring-mode consistency, enum and required-field validity, non-empty
        `objectives`, evaluator distinct from orderer, disclosure and trend
        window sanity, non-empty re-entry `conditions`, closure eligibility,
        open-plan exclusion, and pending-petition exclusion; failures yield
        `ERR_RUBRIC_SCORE_OUT_OF_RANGE`, ..."
        PRD §2.10: "When several rules could reject the same request, the
        server evaluates them in a fixed order and reports the first failure; a
        failure at an earlier rank always masks every later rank."

        Design: Difficulty/priority_pair_validation_conflict/triage_state_vs_rubric_range_conflict
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S7001", category="ACADEMIC_DISTRESS")
        resp = api.create_risk_scoring(
            {
                "case_id": ctx["case_id"],
                "mode": "REASSESSMENT",
                "harm_to_self": 30,  # out of range AND state-wrong
                "harm_to_others": 0,
                "academic_disruption": 0,
                "substance_involvement": 0,
                "rationale": "bad dim",
            },
            ctx["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_TRIAGEABLE)

    def test_masked_failure_leaves_case_and_scorings_unchanged(self, api):
        """PRD §2.10: "When several rules could reject the same request, the
        server evaluates them in a fixed order and reports the first failure; a
        failure at an earlier rank always masks every later rank."
        PRD §3.2: "State must agree too: scoring requires the case in `INTAKE`
        (for `INITIAL`) or `TRIAGED` (for `REASSESSMENT`), with anything else
        rejected as `ERR_CASE_NOT_TRIAGEABLE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/triage_state_vs_rubric_range_conflict
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S7001B", category="ACADEMIC_DISTRESS")
        scorings_before, meta_before = validate_paginated(
            api.list_risk_scorings(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        resp = api.create_risk_scoring(
            {
                "case_id": ctx["case_id"],
                "mode": "REASSESSMENT",
                "harm_to_self": 30,
                "harm_to_others": 0,
                "academic_disruption": 0,
                "substance_involvement": 0,
                "rationale": "bad dim",
            },
            ctx["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_TRIAGEABLE)
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["status"] == "PLAN_ACTIVE"
        _, meta_after = validate_paginated(
            api.list_risk_scorings(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        assert meta_after["total_count"] == meta_before["total_count"]


class TestScoringModeGate:
    def test_reassessment_without_prior_scoring_rejected(self, api):
        """PRD §3.2: "Mode must agree with history: `INITIAL` is valid only
        when no prior scoring exists for the case, and `REASSESSMENT` is valid
        only when at least one does; a mismatch is rejected with
        `ERR_SCORING_MODE_INVALID` (HTTP 400)."

        Design: Corner/errors/scoring_mode_invalid_rejected
        """
        ctx = setup_staff_group()
        setup_case_in_intake(ctx, external_ref="S0027", category="ACADEMIC_DISTRESS")
        resp = api.create_risk_scoring(
            {
                "case_id": ctx["case_id"],
                "mode": "REASSESSMENT",
                "harm_to_self": 5,
                "harm_to_others": 5,
                "academic_disruption": 5,
                "substance_involvement": 5,
                "rationale": "no prior",
            },
            ctx["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SCORING_MODE_INVALID)
