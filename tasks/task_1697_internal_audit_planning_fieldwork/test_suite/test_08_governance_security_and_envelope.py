"""Rating-config band governance, high-risk coverage aggregation, RBAC and
segregation-of-duties gates, response envelope shape, and the 404 sweep
(PRD §2.1, §2.2, §2.3, §2.7, §3.2, §3.3)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assign_auditor,
    build_user_headers,
    create_active_rating_config,
    create_auditor,
    create_engagement_payload,
    create_entity,
    create_finding_payload,
    create_plan,
    create_rating_criteria_config_payload,
    create_risk_assessment_payload,
    create_signed_off_workpaper,
    create_workpaper_payload,
    get_plan,
    get_success_data,
    is_iso8601_timestamp,
    make_field_auditor_headers,
    make_manager_headers,
    set_clock,
    setup_engagement_in_fieldwork,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRatingConfigGovernance:
    def test_config_band_validation_rejected(self, api, admin_headers):
        """PRD §3.2: "The bands must be strictly increasing within the
        composite-score range: `moderate_min` must be at least 1, `high_min`
        must be strictly greater than `moderate_min`, `critical_min` must be
        strictly greater than `high_min`, and `critical_min` may be at most 25.
        This constraint is enforced both when a config is created and again when
        it is activated; a violation at either point is rejected with
        `ERR_CONFIG_BANDS_INVALID` (HTTP 422)."

        Design: Corner/calculations/config_band_validation_rejected
        """
        resp = api.create_rating_criteria_config(
            create_rating_criteria_config_payload(
                name="bad", critical_min=12, high_min=12, moderate_min=6,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONFIG_BANDS_INVALID, expected_status=422)

    def test_config_band_defaults_and_activation(self, api, admin_headers):
        """PRD §3.2: "A config is created with a `name` and three optional band
        thresholds: `critical_min` defaulting to 20, `high_min` defaulting to
        12, and `moderate_min` defaulting to 6."
        PRD §3.2: "Activation moves a `DRAFT` config to `ACTIVE` — attempting to
        activate a config in any other status fails with
        `ERR_RATING_CONFIG_INVALID_STATE` — and stamps `activated_at` from the
        logical clock."

        Design: Corner/calculations/config_band_validation_rejected
        """
        cfg = get_success_data(api.create_rating_criteria_config(
            create_rating_criteria_config_payload(name="defaults-only"), admin_headers,
        ))
        assert cfg["status"] == "DRAFT"
        assert cfg["critical_min"] == 20
        assert cfg["high_min"] == 12
        assert cfg["moderate_min"] == 6
        activated = get_success_data(api.activate_rating_criteria_config(cfg["id"], admin_headers))
        assert activated["status"] == "ACTIVE"
        assert is_iso8601_timestamp(activated["activated_at"])


class TestHighRiskCoverage:
    def test_plan_high_risk_coverage_aggregation(self, api, cae_headers):
        """PRD §3.3: "The `high_risk_coverage_pct` measures coverage of the
        high-risk universe: take all `ACTIVE` auditable entities whose
        `current_inherent_risk_score` is at least 70, count how many of them are
        referenced by at least one non-`CANCELLED` engagement of this plan, and
        express the share as one hundred times the covered count divided by the
        universe size, rounded half-up to two decimal places."
        PRD §3.3: "When no active entity currently scores at or above 70, the
        universe is empty and the coverage is defined as exactly 100.0."
        PRD §3.3: "Both aggregates are recomputed whenever an engagement is
        created under the plan and whenever one of the plan's engagements is
        cancelled."

        Design: Corner/calculations/plan_high_risk_coverage_aggregation
        """
        set_clock()
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])

        # Entity A scores 72 (WEIGHTED); entity B scores 80 (CONSERVATIVE).
        ent_a = create_entity(name="EA")
        ra_a = get_success_data(api.create_risk_assessment(
            create_risk_assessment_payload(ent_a["id"], ent_a["version"], likelihood=3, impact=4),
            mgr_h,
        ))
        get_success_data(api.finalize_risk_assessment(ra_a["id"], mgr_h))
        ent_b = create_entity(name="EB", regulatory_scrutiny=True)
        ra_b = get_success_data(api.create_risk_assessment(
            create_risk_assessment_payload(ent_b["id"], ent_b["version"], likelihood=3, impact=4),
            mgr_h,
        ))
        get_success_data(api.finalize_risk_assessment(ra_b["id"], mgr_h))

        # Two high-risk entities, none covered yet.
        plan = create_plan()
        assert plan["high_risk_coverage_pct"] == pytest.approx(0.0)

        # Covering one of two high-risk entities yields 50.0.
        eng = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent_a["id"], plan["version"], title="G",
                                      budget_hours=50),
            mgr_h,
        ))
        after_cover = get_plan(plan["id"])
        assert after_cover["high_risk_coverage_pct"] == pytest.approx(50.0)

        # Cancelling the engagement excludes it and returns coverage to 0.0.
        get_success_data(api.cancel_engagement(eng["id"], mgr_h))
        after_cancel = get_plan(plan["id"])
        assert after_cancel["high_risk_coverage_pct"] == pytest.approx(0.0)


class TestRbac:
    def test_rbac_role_denial_matrix(self, api, cae_headers, committee_headers, owner_headers):
        """PRD §2.1: "Each endpoint declares the roles permitted to invoke it; a
        caller whose `X-User-Role` is not in the endpoint's allowed set is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.7: "2. **Role authorization** — the presented role is in the
        endpoint's allowed set, else `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/rbac_role_denial_matrix
        """
        staff = create_auditor(full_name="Sam Staff", grade="STAFF")
        plan = create_plan()

        # FieldAuditor on the committee-only plan approve.
        e1 = api.approve_audit_plan(
            NON_EXISTENT_UUID, make_field_auditor_headers(staff["id"])
        )
        validate_error(e1, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

        # ManagementOwner on the manager-only workpaper sign-off.
        e2 = api.sign_off_workpaper(NON_EXISTENT_UUID, owner_headers)
        validate_error(e2, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

        # AuditCommittee on the manager-only engagement create; role denial
        # precedes existence and OCC checks.
        e3 = api.create_engagement(
            create_engagement_payload(plan["id"], NON_EXISTENT_UUID, plan["version"],
                                      title="G", budget_hours=50),
            committee_headers,
        )
        validate_error(e3, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_rbac_role_grade_mapping_enforced(self, api):
        """PRD §2.1: "a `FieldAuditor` caller's record must carry a `grade` of
        `STAFF`, `SENIOR`, or `MANAGER` (which is what allows a manager-grade
        auditor to also prepare workpapers); and a `QualityAssessor` caller's
        record must carry a `grade` of `MANAGER` or `DIRECTOR`. In all three
        cases the referenced `Auditor` must also have `status` equal to
        `ACTIVE`. A caller failing this grade-or-status mapping is rejected with
        `ERR_ROLE_GRADE_MISMATCH` (HTTP 403)."
        PRD §2.1: "an `AuditManager` caller's `Auditor` record must carry a
        `grade` of `MANAGER` or `DIRECTOR`"

        Design: Corner/rbac/rbac_role_grade_mapping_enforced
        """
        director = create_auditor(full_name="Dana Director", grade="DIRECTOR")
        ent = create_entity(name="E")

        # DIRECTOR is not an eligible FieldAuditor grade; the grade gate fires
        # before existence checks on the bogus engagement id.
        e1 = api.create_workpaper(
            create_workpaper_payload(NON_EXISTENT_UUID, reference="A-1", title="W",
                                     hours_worked=5),
            make_field_auditor_headers(director["id"]),
        )
        validate_error(e1, ApiErrorId.ERR_ROLE_GRADE_MISMATCH, expected_status=403)

        # The same DIRECTOR acting as AuditManager is accepted.
        got = get_success_data(
            api.get_auditable_entity(ent["id"], make_manager_headers(director["id"]))
        )
        assert got["id"] == ent["id"]


class TestWorkpaperSegregation:
    def test_workpaper_self_review_rejected(self, api):
        """PRD §3.5: "Segregation of duties applies: the reviewer's `X-User-ID`
        must differ from `preparer_auditor_id`, and a self-review fails with
        `ERR_WORKPAPER_SELF_REVIEW`."
        PRD §2.1: "a `FieldAuditor` caller's record must carry a `grade` of
        `STAFF`, `SENIOR`, or `MANAGER` (which is what allows a manager-grade
        auditor to also prepare workpapers)"

        Design: Corner/rbac/workpaper_self_review_rejected
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        mgr = ctx["mgr"]
        # mgr (MANAGER) prepares a workpaper acting as FieldAuditor...
        wp = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP", hours_worked=5),
            make_field_auditor_headers(mgr["id"]),
        ))
        get_success_data(api.submit_workpaper(wp["id"], make_field_auditor_headers(mgr["id"])))
        # ...and cannot sign it off acting as AuditManager.
        resp = api.sign_off_workpaper(wp["id"], make_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_WORKPAPER_SELF_REVIEW, expected_status=403)
        assert get_success_data(
            api.get_workpaper(wp["id"], make_manager_headers(mgr["id"]))
        )["status"] == "SUBMITTED"

    def test_workpaper_preparer_ownership_assignment_and_link_gates(self, api):
        """PRD §3.5: "Submitting is the preparer's own action: only the auditor
        whose `id` matches `preparer_auditor_id` may submit, and anyone else is
        rejected with `ERR_NOT_WORKPAPER_PREPARER`"
        PRD §3.5: "Creation captures `preparer_auditor_id` from the caller's
        `X-User-ID`, and the caller must hold an `ACTIVE` assignment on that
        engagement — a preparer without one is rejected with
        `ERR_PREPARER_NOT_ASSIGNED`."
        PRD §3.6: "An optional `workpaper_id` links the finding to its evidence;
        when supplied, the referenced workpaper must belong to the same
        engagement and must already be `SIGNED_OFF`, otherwise creation fails
        with `ERR_WORKPAPER_NOT_SIGNED`."

        Design: Corner/rbac/workpaper_preparer_ownership_assignment_and_link_gates
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        create_active_rating_config()
        staff1, staff2 = ctx["staff"], create_auditor(full_name="Sue Staff2", grade="STAFF")
        wp = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP", hours_worked=5),
            make_field_auditor_headers(staff1["id"]),
        ))

        # Submit by a different auditor fails the ownership check.
        e1 = api.submit_workpaper(wp["id"], make_field_auditor_headers(staff2["id"]))
        validate_error(e1, ApiErrorId.ERR_NOT_WORKPAPER_PREPARER, expected_status=403)

        # Creation by an auditor with no ACTIVE assignment on the engagement.
        e2 = api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-9",
                                     title="WP9", hours_worked=3),
            make_field_auditor_headers(staff2["id"]),
        )
        validate_error(e2, ApiErrorId.ERR_PREPARER_NOT_ASSIGNED, expected_status=422)

        # Linking a DRAFT workpaper at finding creation fails the signing gate.
        e3 = api.create_finding(
            create_finding_payload(ctx["engagement"]["id"], title="F", likelihood=3,
                                   impact=4, workpaper_id=wp["id"]),
            make_field_auditor_headers(staff1["id"]),
        )
        validate_error(e3, ApiErrorId.ERR_WORKPAPER_NOT_SIGNED, expected_status=422)


class TestValidationPriority:
    def test_priority_auth_beats_existence_unauthenticated(self, api):
        """PRD §2.7: "Every request passes through a fixed validation pipeline,
        and the ordering between stages is contractual: when several violations
        are present, the error surfaced is the one belonging to the earliest
        stage. The stages, in evaluation order, are: 1. **Authentication** — the
        `X-User-ID` and `X-User-Role` headers are present and well-formed, else
        `ERR_UNAUTHENTICATED`."
        PRD §2.1: "A request missing either header, or presenting a malformed
        header, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/priority_auth_beats_existence_unauthenticated
        """
        resp = api.get_engagement(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_priority_existence_beats_state(self, api):
        """PRD §2.7: "The stages, in evaluation order, are:"
        PRD §2.7 stage 4: "**Existence** — path identifiers are validated left
        to right, and then body foreign-key fields in their declared input
        order."
        PRD §2.11: "The first reference that does not resolve to an existing
        resource terminates the request with the corresponding 404 error of
        pipeline stage 4, before request-shape, state, or business rules are
        examined."

        Design: Corner/validations/priority_existence_beats_state
        """
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        resp = api.sign_off_workpaper(NON_EXISTENT_UUID, make_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_WORKPAPER_NOT_FOUND, expected_status=404)


class TestEnvelope:
    def test_response_envelope_object_array_error_shapes(self, api, admin_headers):
        """PRD §2.2: "The `response_type` is either \"object\" for a single
        resource or \"array\" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_object_array_error_shapes
        """
        ent = create_entity(name="E")

        obj_resp = api.get_auditable_entity(ent["id"], admin_headers)
        obj_body = obj_resp.json()
        assert obj_body["response_type"] == "object"
        assert obj_body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(obj_body["meta"]["api_request_timestamp"])
        assert obj_body["data"]["id"] == ent["id"]

        data, meta = validate_paginated(api.list_findings(admin_headers))
        assert isinstance(data, list)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        err_resp = api.get_auditable_entity(NON_EXISTENT_UUID, admin_headers)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_AUDITABLE_ENTITY_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"].strip()


class TestNotFoundSweep:
    def test_engagement_get_not_found_returns_404(self, api, admin_headers):
        """PRD §2.11: "The first reference that does not resolve to an existing
        resource terminates the request with the corresponding 404 error of
        pipeline stage 4, before request-shape, state, or business rules are
        examined."
        PRD §3.4: "An optional `supersedes_engagement_id` links the engagement
        to a prior one as a follow-up reference; when supplied, it must resolve
        to an existing engagement or the create fails with
        `ERR_ENGAGEMENT_NOT_FOUND`."

        Design: Corner/entities/engagement_get_not_found_returns_404
        """
        resp = api.get_engagement(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND, expected_status=404)

    def test_not_found_sweep_all_collections(self, api, admin_headers):
        """PRD §2.7 stage 4: "Each missing reference surfaces its own not-found
        error: `ERR_AUDITABLE_ENTITY_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`,
        `ERR_RATING_CONFIG_NOT_FOUND`, `ERR_AUDIT_PLAN_NOT_FOUND`,
        `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_AUDITOR_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WORKPAPER_NOT_FOUND`,
        `ERR_FINDING_NOT_FOUND`, `ERR_MANAGEMENT_RESPONSE_NOT_FOUND`,
        `ERR_ACTION_PLAN_NOT_FOUND`, `ERR_EXTENSION_REQUEST_NOT_FOUND`,
        `ERR_AUDIT_REPORT_NOT_FOUND`, `ERR_QA_REVIEW_NOT_FOUND`, or
        `ERR_COMMITTEE_PACK_NOT_FOUND` — all HTTP 404."

        Design: Corner/errors/not_found_sweep_all_collections
        """
        cases = [
            (api.get_risk_assessment, ApiErrorId.ERR_RISK_ASSESSMENT_NOT_FOUND),
            (api.get_rating_criteria_config, ApiErrorId.ERR_RATING_CONFIG_NOT_FOUND),
            (api.get_audit_plan, ApiErrorId.ERR_AUDIT_PLAN_NOT_FOUND),
            (api.get_auditor, ApiErrorId.ERR_AUDITOR_NOT_FOUND),
            (api.get_engagement_assignment, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.get_workpaper, ApiErrorId.ERR_WORKPAPER_NOT_FOUND),
            (api.get_finding, ApiErrorId.ERR_FINDING_NOT_FOUND),
            (api.get_management_response, ApiErrorId.ERR_MANAGEMENT_RESPONSE_NOT_FOUND),
            (api.get_action_plan, ApiErrorId.ERR_ACTION_PLAN_NOT_FOUND),
            (api.get_extension_request, ApiErrorId.ERR_EXTENSION_REQUEST_NOT_FOUND),
            (api.get_audit_report, ApiErrorId.ERR_AUDIT_REPORT_NOT_FOUND),
            (api.get_qa_review, ApiErrorId.ERR_QA_REVIEW_NOT_FOUND),
            (api.get_committee_pack, ApiErrorId.ERR_COMMITTEE_PACK_NOT_FOUND),
            (api.get_auditable_entity, ApiErrorId.ERR_AUDITABLE_ENTITY_NOT_FOUND),
        ]
        for getter, error_id in cases:
            resp = getter(NON_EXISTENT_UUID, admin_headers)
            validate_error(resp, error_id, expected_status=404)


class TestAuditorRoster:
    def test_auditor_grade_invalid_enum_rejected(self, api, admin_headers):
        """PRD §3.4: "An auditor is registered with a `full_name`, a `grade` of
        `STAFF`, `SENIOR`, `MANAGER`, or `DIRECTOR`, and an optional list of
        `skills` tags"
        PRD §2.7 stage 5: "required fields are present, types are valid, enum
        values are in range, and no unknown or read-only fields were supplied;
        violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/auditor_grade_invalid_enum_rejected
        """
        resp = api.create_auditor({"full_name": "Pat Partner", "grade": "PARTNER"},
                                  admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestImmediateConsistency:
    def test_immediate_consistency_same_response(self, api):
        """PRD §3.5: "A successful sign-off records `reviewer_auditor_id` from
        the caller, stamps `signed_off_at` from the logical clock, moves the
        workpaper to `SIGNED_OFF`, increments the engagement's
        `signed_off_workpaper_count` by one, and recomputes `actual_hours` and
        `provisional_hours`."
        PRD §2.10: "the invariant the implementer must hold is that a reader
        fetching any resource after the operation completes observes every
        consequence of the operation, never an intermediate state."

        Design: Corner/consistency_model/immediate_consistency_same_response
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        wp = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP", hours_worked=5),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp["id"], staff_h))

        # The sign-off response body itself carries the mutation.
        signed = get_success_data(api.sign_off_workpaper(wp["id"], mgr_h))
        assert signed["status"] == "SIGNED_OFF"
        assert signed["reviewer_auditor_id"] == ctx["mgr"]["id"]
        assert is_iso8601_timestamp(signed["signed_off_at"])
