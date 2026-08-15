"""RBAC, ownership, segregation of duties, and validation-pipeline ordering
(PRD §2.1, §2.8, §2.9)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_approved_model_with_metric,
    create_finding,
    create_model,
    create_model_payload,
    create_model_with_approved_doc,
    create_report_payload,
    get_model,
    make_owner_headers,
    make_risk_officer_headers,
    make_validator_headers,
    record_reading,
    submit_documentation,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OWNER_B = TEST_USERS["model_owner_b_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
REPORTER = TEST_USERS["reporter_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestHeaderContextAndRoleGates:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
        the acting user, and `X-User-Role`, naming the acting role. A request missing
        either header, or whose role header does not name one of the declared roles, is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_rejected
        """
        err = validate_error(api.list_models(headers={}),
                             ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert err["error_id"] == "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"

    def test_forbidden_role_on_exclusive_endpoint(self, api):
        """PRD §2.1: "When the role is valid but not authorized for the target
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /mrm/models/{id}/approve is authorized for `ModelRiskOfficer`.

        Design: Corner/validations/forbidden_role_on_exclusive_endpoint
        """
        model = create_model(name="FR M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        err = validate_error(api.approve_model(model["id"], VALIDATOR), ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert err["error_id"] == "ERR_FORBIDDEN_ROLE"
        assert get_model(model["id"])["status"] == "REGISTERED"

    def test_role_check_precedes_existence_check(self, api):
        """PRD §2.8: "Every request passes through a fixed pipeline of validation
        stages, and a rejection at an earlier stage masks every later stage — the
        caller always sees the earliest applicable error."
        PRD §2.8: "3. **Role authorization.** The role must appear in the endpoint's
        authorized list, else `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.8: "4. **Existence.** Path parameters — the model `id` first, then any
        nested child identifier such as `docId`, `crId`, or `fid` — are resolved
        strictly left to right".

        A forbidden role calling approve on a non-existent model gets
        ERR_FORBIDDEN_ROLE, not ERR_NOT_FOUND.

        Design: Corner/validations/role_check_precedes_existence_check
        """
        err = validate_error(api.approve_model(NON_EXISTENT_UUID, VALIDATOR),
                             ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert err["error_id"] == "ERR_FORBIDDEN_ROLE"


class TestRbacDenials:
    def test_model_validator_cannot_register_models(self, api):
        """PRD §2.1: "`ModelOwner` — a business-unit model developer or owner.
        Registers models (becoming their owner), submits documentation packages and
        change requests, registers monitoring metrics and records readings, and
        resolves breach events — in each write case only on models they own."
        PRD §4: POST /mrm/models is authorized for `ModelOwner` only.

        Design: Corner/rbac/model_validator_cannot_register_models
        """
        err = validate_error(
            api.create_model(create_model_payload(name="RBAC M", declared_complexity="LOW",
                                                  usage_scope="SINGLE_DESK", exposure_amount=100),
                             VALIDATOR),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        assert err["error_id"] == "ERR_FORBIDDEN_ROLE"
        models, _ = validate_paginated(api.list_models(OFFICER))
        assert models == []

    def test_model_owner_cannot_open_engagement(self, api):
        """PRD §4: POST /mrm/models/{id}/validation-engagements is authorized for
        `ModelValidator` only.
        PRD §2.1: "When the role is valid but not authorized for the target endpoint,
        the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/model_owner_cannot_open_engagement
        """
        model, _doc = create_model_with_approved_doc(name="RBACEng M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        err = validate_error(
            api.create_engagement(
                model["id"],
                {"scope_conceptual_soundness": True, "scope_outcomes_analysis": False,
                 "period_start": "2026-08-02T00:00:00Z", "period_end": "2026-08-09T00:00:00Z"},
                OWNER_B,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        assert err["error_id"] == "ERR_FORBIDDEN_ROLE"

    def test_model_validator_cannot_decide_documentation(self, api):
        """PRD §4: POST /mrm/models/{id}/documentations/{docId}/decide is authorized
        for `ModelRiskOfficer` only.

        Design: Corner/rbac/model_validator_cannot_decide_documentation
        """
        model = create_model(name="RBACDoc M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        doc = submit_documentation(model["id"])
        err = validate_error(
            api.decide_documentation(model["id"], doc["id"], {"decision": "APPROVE"}, VALIDATOR),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        assert err["error_id"] == "ERR_FORBIDDEN_ROLE"
        docs, _ = validate_paginated(api.list_documentations(model["id"], OFFICER))
        assert docs[0]["status"] == "SUBMITTED"

    def test_model_owner_cannot_close_findings(self, api):
        """PRD §4: POST /mrm/models/{id}/findings/{fid}/close is authorized for
        `ModelRiskOfficer` only.

        Design: Corner/rbac/model_owner_cannot_close_findings
        """
        model = create_model(name="RBACClose M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        finding = create_finding(model["id"], severity="LOW", title="rbac close")
        err = validate_error(api.close_finding(model["id"], finding["id"], OWNER_A),
                             ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert err["error_id"] == "ERR_FORBIDDEN_ROLE"
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert findings[0]["status"] == "OPEN"

    def test_regulatory_reporter_cannot_create_reports_as_other_role(self, api):
        """PRD §2.1: "`RegulatoryReporter` — the regulatory reporting liaison. Drafts
        and submits board and regulator reports."
        PRD §4: POST /mrm/regulatory-reports is authorized for `RegulatoryReporter`
        only.

        Design: Corner/rbac/regulatory_reporter_cannot_create_reports_as_other_role
        """
        err = validate_error(api.create_report(create_report_payload(), OFFICER),
                             ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert err["error_id"] == "ERR_FORBIDDEN_ROLE"

    def test_platform_admin_cannot_touch_business_endpoints(self, api):
        """PRD §2.1: "All four business roles (`ModelOwner`, `ModelValidator`,
        `ModelRiskOfficer`, `RegulatoryReporter`) may use every read endpoint;
        `PlatformAdmin` has no read or write access to business resources."

        Design: Corner/rbac/platform_admin_cannot_touch_business_endpoints
        """
        err = validate_error(api.list_models(ADMIN), ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert err["error_id"] == "ERR_FORBIDDEN_ROLE"


class TestOwnershipAndSegregation:
    def test_ownership_check_blocks_non_owner_documentation(self, api):
        """PRD §2.9: "Five owner-scoped writes require the caller's `X-User-ID` to
        equal the owning model's `owner_user_id`, failing with `ERR_NOT_MODEL_OWNER`
        (HTTP 403) otherwise: submitting a documentation package, submitting a change
        request, registering a monitoring metric, recording a reading (ownership of the
        metric's model), and resolving a breach event."

        Design: Corner/validations/ownership_check_blocks_non_owner_documentation
        """
        model = create_model(name="Own M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        err = validate_error(
            api.submit_documentation(
                model["id"],
                {"version_label": "1.0", "has_development_evidence": True,
                 "has_testing_evidence": True, "has_data_lineage": True},
                OWNER_B,
            ),
            ApiErrorId.ERR_NOT_MODEL_OWNER,
        )
        assert err["error_id"] == "ERR_NOT_MODEL_OWNER"
        docs, _ = validate_paginated(api.list_documentations(model["id"], OFFICER))
        assert docs == []

    def test_sod_validator_independence_blocks_owner_validator(self, api):
        """PRD §2.9: "A validation engagement may only be opened by a `ModelValidator`
        whose `X-User-ID` differs from the model's `owner_user_id`; a validator acting
        on their own model is rejected with `ERR_SOD_VALIDATION_INDEPENDENCE` (HTTP
        403)."

        Design: Corner/validations/sod_validator_independence_blocks_owner_validator
        """
        model, _doc = create_model_with_approved_doc(name="SoD M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        err = validate_error(
            api.create_engagement(
                model["id"],
                {"scope_conceptual_soundness": True, "scope_outcomes_analysis": False,
                 "period_start": "2026-08-02T00:00:00Z", "period_end": "2026-08-09T00:00:00Z"},
                make_validator_headers("u_own_a"),
            ),
            ApiErrorId.ERR_SOD_VALIDATION_INDEPENDENCE,
        )
        assert err["error_id"] == "ERR_SOD_VALIDATION_INDEPENDENCE"
        engs, _ = validate_paginated(api.list_engagements(model["id"], OFFICER))
        assert engs == []

    def test_sod_documentation_approval_blocks_submitter_deciding(self, api):
        """PRD §2.9: "A documentation package may only be decided by a
        `ModelRiskOfficer` whose `X-User-ID` differs from the package's
        `submitted_by_user_id`; an officer deciding their own submission is rejected
        with `ERR_SOD_DOCUMENTATION_APPROVAL` (HTTP 403)."

        The model is registered by u_cro acting as ModelOwner, so the package's
        submitter is u_cro; a decision by u_cro is rejected.

        Design: Corner/validations/sod_documentation_approval_blocks_submitter_deciding
        """
        model = create_model(name="SoDDoc M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100, owner_headers=make_owner_headers("u_cro"))
        doc = submit_documentation(model["id"], owner_headers=make_owner_headers("u_cro"))
        err = validate_error(
            api.decide_documentation(model["id"], doc["id"], {"decision": "APPROVE"}, OFFICER),
            ApiErrorId.ERR_SOD_DOCUMENTATION_APPROVAL,
        )
        assert err["error_id"] == "ERR_SOD_DOCUMENTATION_APPROVAL"
        docs, _ = validate_paginated(api.list_documentations(model["id"], OFFICER))
        assert docs[0]["status"] == "SUBMITTED"

    def test_breach_event_resolve_requires_owner(self, api):
        """PRD §3.7: "Breach events remain `OPEN` until the model's owner resolves
        them; resolving one that is already `RESOLVED` fails with
        `ERR_BREACH_EVENT_ALREADY_RESOLVED`, and resolution by anyone but the owner
        fails with `ERR_NOT_MODEL_OWNER`."
        PRD §3.7: "The model's `monitoring_posture` is derived from breach events
        alone: it is `BREACHED` while at least one `OPEN` breach event exists on any
        metric of the model, and returns to `NORMAL` only when none remain".

        Design: Corner/rbac/breach_event_resolve_requires_owner
        """
        model, metric, ctx = create_approved_model_with_metric(name="BEOwn M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        record_reading(metric["id"], 0.30, "2026-08-02T00:00:00Z", owner_headers=ctx["owner_headers"])
        events, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A))
        be_id = events[0]["id"]
        err = validate_error(api.resolve_breach_event(be_id, OWNER_B), ApiErrorId.ERR_NOT_MODEL_OWNER)
        assert err["error_id"] == "ERR_NOT_MODEL_OWNER"
        resolved = validate_success(api.resolve_breach_event(be_id, ctx["owner_headers"]))
        assert resolved["status"] == "RESOLVED"
        assert get_model(model["id"])["monitoring_posture"] == "NORMAL"

    def test_findings_raise_shared_between_validator_and_officer(self, api):
        """PRD §3.6: "A `ModelValidator` or `ModelRiskOfficer` raises one on any
        non-retired model by supplying a `severity` (`LOW`, `MEDIUM`, `HIGH`, or
        `CRITICAL`) and a short `title`."
        PRD §3.6: "Raising a finding increments the model's `open_findings_count` —
        defined as the number of findings on the model whose status is `OPEN`,
        `OVERDUE`, or `ESCALATED` — by one and recomputes the model's `risk_score` and
        `risk_tier`, since the findings penalty of §3.1 has grown."

        Both roles raise on the same model: LOW (+1) and MEDIUM (+2) on a base-30 model
        -> open_findings_count 2, risk_score 33.

        Design: Corner/rbac/findings_raise_shared_between_validator_and_officer
        """
        model = create_model(name="Shared M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        f1 = validate_success(api.create_finding(model["id"], {"severity": "LOW", "title": "by validator"},
                                                 VALIDATOR), expected_status=201)
        f2 = validate_success(api.create_finding(model["id"], {"severity": "MEDIUM", "title": "by officer"},
                                                 OFFICER), expected_status=201)
        assert f1["id"] and f2["id"]
        data = get_model(model["id"])
        assert data["open_findings_count"] == 2
        assert data["risk_score"] == 33, f"expected 30 + 1 + 2 = 33, got {data['risk_score']}"

    def test_segregation_of_duties_role_model_enforced(self, api):
        """PRD §2.9: "Two independence rules are enforced as safety gates. A validation
        engagement may only be opened by a `ModelValidator` whose `X-User-ID` differs
        from the model's `owner_user_id`; a validator acting on their own model is
        rejected with `ERR_SOD_VALIDATION_INDEPENDENCE` (HTTP 403). A documentation
        package may only be decided by a `ModelRiskOfficer` whose `X-User-ID` differs
        from the package's `submitted_by_user_id`; an officer deciding their own
        submission is rejected with `ERR_SOD_DOCUMENTATION_APPROVAL` (HTTP 403)."

        Both axes in one flow: the submitter (u_own_a) cannot decide their own package,
        and the owner (u_own_a) cannot validate their own model.

        Design: Corner/rbac/segregation_of_duties_role_model_enforced
        """
        model = create_model(name="SoDModel M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        doc = submit_documentation(model["id"])
        err1 = validate_error(
            api.decide_documentation(model["id"], doc["id"], {"decision": "APPROVE"},
                                     make_risk_officer_headers("u_own_a")),
            ApiErrorId.ERR_SOD_DOCUMENTATION_APPROVAL,
        )
        assert err1["error_id"] == "ERR_SOD_DOCUMENTATION_APPROVAL"
        err2 = validate_error(
            api.create_engagement(
                model["id"],
                {"scope_conceptual_soundness": True, "scope_outcomes_analysis": False,
                 "period_start": "2026-08-02T00:00:00Z", "period_end": "2026-08-09T00:00:00Z"},
                make_validator_headers("u_own_a"),
            ),
            ApiErrorId.ERR_SOD_VALIDATION_INDEPENDENCE,
        )
        assert err2["error_id"] == "ERR_SOD_VALIDATION_INDEPENDENCE"
