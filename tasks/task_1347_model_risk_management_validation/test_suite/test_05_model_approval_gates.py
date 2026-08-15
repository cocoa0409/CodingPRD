"""Approval-for-use gates and vendor transparency (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    approve_model,
    create_approvable_model,
    create_approved_model,
    create_finding,
    create_model,
    create_model_with_approved_doc,
    create_vendor_assessment,
    get_model,
    open_engagement,
    complete_engagement,
    set_clock,
    submit_documentation,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]


class TestApprovalHappyPath:
    def test_approve_happy_path_transitions_registered_to_approved(self, api):
        """PRD §3.5: "Approving a model moves it from `REGISTERED` to
        `APPROVED_FOR_USE` and is the most heavily gated transition in the system."

        All gates satisfied: APPROVED doc, COMPLETED EFFECTIVE engagement, no critical
        findings, validation current at the default clock.

        Design: Corner/state_machines/approve_happy_path_transitions_registered_to_approved
        """
        ctx = create_approvable_model(name="Appr M", declared_complexity="LOW",
                                      usage_scope="SINGLE_DESK", exposure_amount=100,
                                      assessed_complexity="LOW")
        approved = validate_success(api.approve_model(ctx["model"]["id"], OFFICER))
        assert approved["status"] == "APPROVED_FOR_USE"

    def test_approve_on_approved_model_returns_not_approvable(self, api):
        """PRD §3.5: "the gates fire in the pipeline order of §2.8: first the state
        gate — the model must be `REGISTERED`, else `ERR_MODEL_NOT_APPROVABLE`".

        Design: Corner/state_machines/approve_on_approved_model_returns_not_approvable
        """
        ctx = create_approved_model(name="Twice M", declared_complexity="LOW",
                                    usage_scope="SINGLE_DESK", exposure_amount=100,
                                    assessed_complexity="LOW")
        err = validate_error(api.approve_model(ctx["model"]["id"], OFFICER),
                             ApiErrorId.ERR_MODEL_NOT_APPROVABLE)
        assert err["error_id"] == "ERR_MODEL_NOT_APPROVABLE"


class TestApprovalGates:
    def test_approve_without_approved_documentation_rejected(self, api):
        """PRD §3.5: "and finally the referential evidence gates — at least one
        `APPROVED` documentation package must exist, else `ERR_NO_APPROVED_DOCUMENTATION`".

        A merely SUBMITTED package does not satisfy the gate.

        Design: Corner/validations/approve_without_approved_documentation_rejected
        """
        model = create_model(name="NoDoc M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        submit_documentation(model["id"])
        err = validate_error(api.approve_model(model["id"], OFFICER),
                             ApiErrorId.ERR_NO_APPROVED_DOCUMENTATION)
        assert err["error_id"] == "ERR_NO_APPROVED_DOCUMENTATION"

    def test_error_catalog_fully_triggerable(self, api):
        """PRD §3.5: "at least one `COMPLETED` validation engagement whose `outcome` is
        not `INEFFECTIVE` must exist, else `ERR_NO_COMPLETED_VALIDATION`."

        APPROVED documentation but zero engagements -> ERR_NO_COMPLETED_VALIDATION.

        Design: Corner/errors/error_catalog_fully_triggerable
        """
        model, _doc = create_model_with_approved_doc(name="ErrCat M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        err = validate_error(api.approve_model(model["id"], OFFICER),
                             ApiErrorId.ERR_NO_COMPLETED_VALIDATION)
        assert err["error_id"] == "ERR_NO_COMPLETED_VALIDATION"

    def test_approve_blocked_by_open_critical_findings(self, api):
        """PRD §3.5: "then the safety gates — no finding on the model may be open
        (status `OPEN`, `OVERDUE`, or `ESCALATED`) with severity `CRITICAL`, else
        `ERR_OPEN_CRITICAL_FINDINGS`".

        Design: Corner/validations/approve_blocked_by_open_critical_findings
        """
        ctx = create_approvable_model(name="CritBlock M", declared_complexity="LOW",
                                      usage_scope="SINGLE_DESK", exposure_amount=100,
                                      assessed_complexity="LOW")
        create_finding(ctx["model"]["id"], severity="CRITICAL", title="blocker")
        err = validate_error(api.approve_model(ctx["model"]["id"], OFFICER),
                             ApiErrorId.ERR_OPEN_CRITICAL_FINDINGS)
        assert err["error_id"] == "ERR_OPEN_CRITICAL_FINDINGS"
        assert get_model(ctx["model"]["id"])["status"] == "REGISTERED"

    def test_approve_blocked_by_validation_overdue(self, api):
        """PRD §3.5: "then the temporal gate — the model's validation must still be
        current, meaning the logical clock reads on or before `validation_due_at`, else
        `ERR_VALIDATION_OVERDUE`".
        PRD §3.1: "A model's validation is overdue when the logical clock reads
        strictly after `validation_due_at`; at the exact due instant it is not yet
        overdue."

        TIER_3 model (LOW/SINGLE_DESK/100) completed at 2026-08-01 -> due 2028-08-01;
        approving at 2028-08-02 fails.

        Design: Corner/validations/approve_blocked_by_validation_overdue
        """
        ctx = create_approvable_model(name="Overdue M", declared_complexity="LOW",
                                      usage_scope="SINGLE_DESK", exposure_amount=100,
                                      assessed_complexity="LOW")
        set_clock("2028-08-02T00:00:00Z")
        err = validate_error(api.approve_model(ctx["model"]["id"], OFFICER),
                             ApiErrorId.ERR_VALIDATION_OVERDUE)
        assert err["error_id"] == "ERR_VALIDATION_OVERDUE"
        assert get_model(ctx["model"]["id"])["status"] == "REGISTERED"


class TestApprovalValidationGate:
    def test_ineffective_validation_fails_approval_gate(self, api):
        """PRD §3.5: "at least one `COMPLETED` validation engagement whose `outcome` is
        not `INEFFECTIVE` must exist, else `ERR_NO_COMPLETED_VALIDATION`."

        An INEFFECTIVE completion leaves the gate shut.

        Design: Difficulty/cross_entity_state_dependency/approve_requires_completed_engagement_on_model
        """
        ctx = create_approvable_model(name="Gated M", declared_complexity="LOW",
                                      usage_scope="SINGLE_DESK", exposure_amount=100,
                                      assessed_complexity="LOW", outcome="INEFFECTIVE")
        err = validate_error(api.approve_model(ctx["model"]["id"], OFFICER),
                             ApiErrorId.ERR_NO_COMPLETED_VALIDATION)
        assert err["error_id"] == "ERR_NO_COMPLETED_VALIDATION"
        assert get_model(ctx["model"]["id"])["status"] == "REGISTERED"

    def test_effective_retest_completion_opens_approval_gate(self, api):
        """PRD §3.5: "at least one `COMPLETED` validation engagement whose `outcome` is
        not `INEFFECTIVE` must exist, else `ERR_NO_COMPLETED_VALIDATION`."
        PRD §3.4: "Retesting is a first-class cycle rather than an exception."

        The same model approves once the INEFFECTIVE engagement is reopened and
        completed EFFECTIVE.

        Design: Difficulty/cross_entity_state_dependency/approve_requires_completed_engagement_on_model
        """
        ctx = create_approvable_model(name="Gated M", declared_complexity="LOW",
                                      usage_scope="SINGLE_DESK", exposure_amount=100,
                                      assessed_complexity="LOW", outcome="INEFFECTIVE")
        eng = ctx["engagement"]
        validate_success(api.reopen_engagement(eng["id"], VALIDATOR))
        complete_engagement(eng["id"], outcome="EFFECTIVE", assessed_complexity="LOW")
        approved = validate_success(api.approve_model(ctx["model"]["id"], OFFICER))
        assert approved["status"] == "APPROVED_FOR_USE"


class TestVendorTransparencyGate:
    def test_vendor_approval_requires_current_assessment_above_threshold(self, api):
        """PRD §3.5: "The approval gate above is satisfied only by an assessment that
        is both `CURRENT` and carries a `completeness_score` of at least 70."

        A vendor model with a CURRENT assessment scoring 69 (< 70) is blocked; a
        non-vendor model with no assessment at all approves fine.

        Design: Corner/validations/vendor_approval_requires_current_assessment_above_threshold
        """
        v_ctx = create_approvable_model(name="Vend69 V", business_unit="Trading",
                                        declared_complexity="LOW", usage_scope="SINGLE_DESK",
                                        exposure_amount=100, is_vendor_model=True,
                                        assessed_complexity="LOW", vendor_completeness=69)
        err = validate_error(api.approve_model(v_ctx["model"]["id"], OFFICER),
                             ApiErrorId.ERR_VENDOR_ASSESSMENT_NOT_CURRENT)
        assert err["error_id"] == "ERR_VENDOR_ASSESSMENT_NOT_CURRENT"

        n_ctx = create_approvable_model(name="NoVend N", declared_complexity="LOW",
                                        usage_scope="SINGLE_DESK", exposure_amount=100,
                                        is_vendor_model=False, assessed_complexity="LOW")
        approved = validate_success(api.approve_model(n_ctx["model"]["id"], OFFICER))
        assert approved["status"] == "APPROVED_FOR_USE"

    def test_vendor_gate_fires_before_temporal_gate(self, api):
        """PRD §3.5: "then the safety gates — no finding on the model may be open
        (status `OPEN`, `OVERDUE`, or `ESCALATED`) with severity `CRITICAL`, else
        `ERR_OPEN_CRITICAL_FINDINGS`, and a vendor model must hold a current
        transparency assessment of sufficient completeness, else
        `ERR_VENDOR_ASSESSMENT_NOT_CURRENT`; then the temporal gate — the model's
        validation must still be current, meaning the logical clock reads on or before
        `validation_due_at`, else `ERR_VALIDATION_OVERDUE`".

        At 2027-03-01 the vendor model's assessment (valid_until 2026-09-01) is EXPIRED
        and its validation (due 2027-02-01) is overdue: both gates fail, and the
        reported error is ERR_VENDOR_ASSESSMENT_NOT_CURRENT, never
        ERR_VALIDATION_OVERDUE.

        Design: Difficulty/priority_pair_validation_conflict/approve_vendor_gate_beats_validation_overdue
        """
        ctx = create_approvable_model(name="Vendor V", business_unit="Trading",
                                      declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                                      exposure_amount=100, is_vendor_model=True,
                                      assessed_complexity="HIGH", vendor_completeness=80,
                                      vendor_valid_months=1)
        assert ctx["model"]["risk_tier"] == "TIER_1"
        set_clock("2027-03-01T00:00:00Z")
        assessments, _ = validate_paginated(
            api.list_vendor_assessments(ctx["model"]["id"], OFFICER)
        )
        assert assessments[0]["status"] == "EXPIRED", "sweep flipped the assessment past valid_until"

        resp = api.approve_model(ctx["model"]["id"], OFFICER)
        err = validate_error(resp, ApiErrorId.ERR_VENDOR_ASSESSMENT_NOT_CURRENT)
        assert err["error_id"] == "ERR_VENDOR_ASSESSMENT_NOT_CURRENT"
        assert err["error_id"] != "ERR_VALIDATION_OVERDUE"
        assert get_model(ctx["model"]["id"])["status"] == "REGISTERED"

    def test_temporal_gate_surfaces_once_vendor_gate_satisfied(self, api):
        """PRD §3.5: "and a vendor model must hold a current transparency assessment of
        sufficient completeness, else `ERR_VENDOR_ASSESSMENT_NOT_CURRENT`; then the
        temporal gate — the model's validation must still be current, meaning the
        logical clock reads on or before `validation_due_at`, else
        `ERR_VALIDATION_OVERDUE`".

        Same doubly-failing setup, but a freshly recorded CURRENT assessment satisfies
        the vendor gate, so the next gate in the pipeline — the temporal gate —
        surfaces ERR_VALIDATION_OVERDUE.

        Design: Difficulty/priority_pair_validation_conflict/approve_vendor_gate_beats_validation_overdue
        """
        ctx = create_approvable_model(name="Vendor V", business_unit="Trading",
                                      declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                                      exposure_amount=100, is_vendor_model=True,
                                      assessed_complexity="HIGH", vendor_completeness=80,
                                      vendor_valid_months=1)
        set_clock("2027-03-01T00:00:00Z")
        # Satisfy the vendor gate with a fresh CURRENT assessment recorded now.
        create_vendor_assessment(ctx["model"]["id"], completeness_score=80, valid_months=1)
        err = validate_error(api.approve_model(ctx["model"]["id"], OFFICER),
                             ApiErrorId.ERR_VALIDATION_OVERDUE)
        assert err["error_id"] == "ERR_VALIDATION_OVERDUE"
        assert get_model(ctx["model"]["id"])["status"] == "REGISTERED"
