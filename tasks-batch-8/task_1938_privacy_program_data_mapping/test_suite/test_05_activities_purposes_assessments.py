"""Processing activities, purposes, privacy impact assessments: lifecycle
cycles, gating, reclassification cascade, segregation of duties (PRD §3.4-3.5)."""
from test_helpers import (
    ApiErrorId,
    BO1,
    BO2,
    DS,
    LC1,
    LC2,
    LC9,
    PA,
    assert_assessment,
    create_activity_payload,
    create_activity_with_manual_assessment,
    create_element,
    create_published_notice,
    create_purpose_payload,
    create_retention_policy,
    get_success_data,
    publish_superseding_notice,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAssessmentReviewCycle:
    def test_assessment_review_cycle(self, api):
        """PRD §3.5: "A BusinessOwner submits an assessment in TRIGGERED or
        CHANGES_REQUESTED status; the assessment moves to IN_REVIEW and its
        submitted_by_user_id is set to the caller's X-User-ID."
        PRD §3.5: "Request-changes moves the assessment to CHANGES_REQUESTED,
        from which the business owner may submit again."
        PRD §3.5: "the element values are summed rather than maxed, round-half-up
        is applied to the sum term, the vendor exposure is added as in the
        screening variant, a consent adjustment of 50 is added when any purpose
        of the activity has status DOCUMENTED and legal_basis CONSENT, and the
        result is capped at 1000. The computed value is written to the
        assessment's final_score, the assessment moves to the terminal APPROVED
        status"

        Design: Difficulty/non_linear_state_machine/assessment_review_cycle
        """
        element = create_element(element_key="email", category="BASIC_CONTACT",
                                 classification="INTERNAL")                         # 50
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        pia = get_success_data(api.create_assessment(activity["id"], DS))
        assert pia["status"] == "TRIGGERED"

        st1 = get_success_data(api.submit_assessment(pia["id"], BO1))
        assert st1["status"] == "IN_REVIEW"
        assert st1["submitted_by_user_id"] == "bo-1"

        st2 = get_success_data(api.request_changes_assessment(pia["id"], LC1))
        assert st2["status"] == "CHANGES_REQUESTED"

        # the cycle re-enters IN_REVIEW from CHANGES_REQUESTED
        st3 = get_success_data(api.submit_assessment(pia["id"], BO1))
        assert st3["status"] == "IN_REVIEW"
        assert st3["submitted_by_user_id"] == "bo-1", (
            "resubmission refreshes submitted_by_user_id to the latest submitter"
        )

        st4 = get_success_data(api.approve_assessment(pia["id"], LC1))
        assert st4["status"] == "APPROVED"
        # comprehensive: sum 50, no vendor, no CONSENT purpose
        assert st4["final_score"] == 50
        assert_assessment(st4)

    def test_assessment_changes_requested_resubmit_by_another_owner(self, api):
        """PRD §3.5: "A BusinessOwner submits an assessment in TRIGGERED or
        CHANGES_REQUESTED status; the assessment moves to IN_REVIEW and its
        submitted_by_user_id is set to the caller's X-User-ID. From IN_REVIEW, a
        LegalCounsel reviewer may request changes, approve, or reject. All three
        reviewer actions require that the reviewer's X-User-ID differ from the
        assessment's submitted_by_user_id"

        Design: Difficulty/non_linear_state_machine/assessment_review_cycle
        """
        _activity, pia = create_activity_with_manual_assessment(
            activity_overrides={"activity_name": "Newsletter"})
        assert pia["status"] == "IN_REVIEW"
        assert pia["submitted_by_user_id"] == "bo-1"

        changed = get_success_data(api.request_changes_assessment(pia["id"], LC1))
        assert changed["status"] == "CHANGES_REQUESTED"

        resubmitted = get_success_data(api.submit_assessment(pia["id"], BO2))
        assert resubmitted["status"] == "IN_REVIEW"
        assert resubmitted["submitted_by_user_id"] == "bo-2"

        # lc-1 (who never submitted) may now reject
        rejected = get_success_data(api.reject_assessment(pia["id"], LC1))
        assert rejected["status"] == "REJECTED"


class TestElementReclassifyCascade:
    def test_element_reclassify_cascade_depth3(self, api):
        """PRD §3.4: "In hop 1, every ProcessingActivity whose data_element_ids
        contains this element and whose status is DRAFT, ACTIVE, or
        COMPLIANCE_HOLD has its risk_score and pia_required recomputed using the
        screening variant, processed in created_at ascending order. In hop 2, any
        such activity whose pia_required flips from false to true gets a
        PrivacyImpactAssessment auto-created in TRIGGERED status with
        trigger_reason set to RECLASSIFICATION, but only when no open assessment
        — one in TRIGGERED, IN_REVIEW, or CHANGES_REQUESTED — already exists for
        that activity. In hop 3, any such activity in ACTIVE status transitions
        to COMPLIANCE_HOLD."

        Design: Difficulty/transitive_cascade/element_reclassify_cascade_depth3
        """
        element = create_element(element_key="email", category="BASIC_CONTACT",
                                 classification="INTERNAL")                         # 50
        policy = create_retention_policy()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        assert activity["risk_score"] == 50
        assert activity["pia_required"] is False
        get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="MARKETING",
                                   legal_basis="LEGITIMATE_INTEREST",
                                   retention_policy_id=policy["id"]), DS))
        get_success_data(api.activate_activity(activity["id"], DS))

        # BIOMETRIC/CONFIDENTIAL: 400 * 1.5 = 600
        get_success_data(api.reclassify_data_element(
            element["id"],
            {"category": "BIOMETRIC", "classification": "CONFIDENTIAL",
             "expected_element_version": element["version"]}, DS))

        after = get_success_data(api.get_activity(activity["id"], DS))
        assert after["risk_score"] == 600, "hop 1: screening recompute 400*1.5 = 600"
        assert after["pia_required"] is True, "hop 1b: 600 >= 500 flips pia_required"
        assert after["status"] == "COMPLIANCE_HOLD", "hop 3: ACTIVE -> COMPLIANCE_HOLD"

        assessments, _ = validate_paginated(
            api.list_activity_assessments(activity["id"], DS))
        assert len(assessments) == 1
        assert assessments[0]["trigger_reason"] == "RECLASSIFICATION"
        assert assessments[0]["status"] == "TRIGGERED"
        assert assessments[0]["screening_score"] == 600

    def test_element_reclassify_no_second_pia_when_open_exists(self, api):
        """PRD §3.4: "In hop 2, any such activity whose pia_required flips from
        false to true gets a PrivacyImpactAssessment auto-created in TRIGGERED
        status with trigger_reason set to RECLASSIFICATION, but only when no open
        assessment — one in TRIGGERED, IN_REVIEW, or CHANGES_REQUESTED — already
        exists for that activity."
        PRD §3.4: "In hop 1, every ProcessingActivity whose data_element_ids
        contains this element and whose status is DRAFT, ACTIVE, or
        COMPLIANCE_HOLD has its risk_score and pia_required recomputed using the
        screening variant"

        Design: Difficulty/transitive_cascade/element_reclassify_cascade_depth3
        """
        element = create_element(element_key="email", category="BASIC_CONTACT",
                                 classification="INTERNAL")                         # 50
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        manual = get_success_data(api.create_assessment(activity["id"], DS))
        assert manual["status"] == "TRIGGERED"

        # Reclassify across the threshold while the manual PIA is still open.
        get_success_data(api.reclassify_data_element(
            element["id"],
            {"category": "BIOMETRIC", "classification": "CONFIDENTIAL",
             "expected_element_version": element["version"]}, DS))

        after = get_success_data(api.get_activity(activity["id"], DS))
        assert after["risk_score"] == 600, "hop 1 still recomputes the risk score"
        assert after["pia_required"] is True

        assessments, _ = validate_paginated(
            api.list_activity_assessments(activity["id"], DS))
        assert len(assessments) == 1, (
            "hop 2 is suppressed: an open assessment already exists for the activity"
        )
        assert assessments[0]["id"] == manual["id"]
        assert assessments[0]["trigger_reason"] == "MANUAL"

        # activity was DRAFT, so hop 3 does not move it
        assert after["status"] == "DRAFT"


class TestActivationGating:
    def test_activity_activate_requires_approved_pia(self, api):
        """PRD §3.4: "Activation by a DataSteward requires that the activity be
        in DRAFT, that any pia_required activity already have an APPROVED
        assessment — otherwise ERR_PIA_NOT_APPROVED — and that at least one
        Purpose with status DOCUMENTED exist for the activity — otherwise
        ERR_NO_DOCUMENTED_PURPOSE."
        PRD §3.5: "the element values are summed rather than maxed, round-half-up
        is applied to the sum term, the vendor exposure is added as in the
        screening variant, a consent adjustment of 50 is added when any purpose
        of the activity has status DOCUMENTED and legal_basis CONSENT, and the
        result is capped at 1000."

        Design: Difficulty/cross_entity_state_dependency/activity_activate_requires_approved_pia
        """
        element = create_element(element_key="bio_fp", category="BIOMETRIC",
                                 classification="RESTRICTED")                       # 800
        policy = create_retention_policy()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Access control", business_unit="Security",
                                    notice_scope="EMPLOYEE",
                                    data_element_ids=[element["id"]]), DS))
        assert activity["pia_required"] is True
        get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="EMPLOYMENT", legal_basis="CONTRACT",
                                   retention_policy_id=policy["id"]), DS))
        assessments, _ = validate_paginated(
            api.list_activity_assessments(activity["id"], DS))
        assert len(assessments) == 1
        pia = assessments[0]
        assert pia["trigger_reason"] == "RISK_THRESHOLD"

        resp = api.activate_activity(activity["id"], DS)
        validate_error(resp, ApiErrorId.ERR_PIA_NOT_APPROVED)

        get_success_data(api.submit_assessment(pia["id"], BO1))
        approved = get_success_data(api.approve_assessment(pia["id"], LC1))
        # comprehensive: single element 800, no vendor, no CONSENT purpose
        assert approved["final_score"] == 800

        activated = get_success_data(api.activate_activity(activity["id"], DS))
        assert activated["status"] == "ACTIVE"

    def test_activity_activate_rejected_while_pia_in_review(self, api):
        """PRD §3.4: "Activation by a DataSteward requires that the activity be
        in DRAFT, that any pia_required activity already have an APPROVED
        assessment — otherwise ERR_PIA_NOT_APPROVED — and that at least one
        Purpose with status DOCUMENTED exist for the activity — otherwise
        ERR_NO_DOCUMENTED_PURPOSE."

        Design: Difficulty/cross_entity_state_dependency/activity_activate_requires_approved_pia
        """
        element = create_element(element_key="bio_fp", category="BIOMETRIC",
                                 classification="RESTRICTED")                       # 800
        policy = create_retention_policy()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Access control", business_unit="Security",
                                    notice_scope="EMPLOYEE",
                                    data_element_ids=[element["id"]]), DS))
        get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="EMPLOYMENT", legal_basis="CONTRACT",
                                   retention_policy_id=policy["id"]), DS))
        assessments, _ = validate_paginated(
            api.list_activity_assessments(activity["id"], DS))
        pia = assessments[0]

        # IN_REVIEW is not APPROVED: the gate still blocks activation
        get_success_data(api.submit_assessment(pia["id"], BO1))
        resp = api.activate_activity(activity["id"], DS)
        validate_error(resp, ApiErrorId.ERR_PIA_NOT_APPROVED)
        after = get_success_data(api.get_activity(activity["id"], DS))
        assert after["status"] == "DRAFT"

    def test_err_no_documented_purpose_on_activate(self, api):
        """PRD §3.4: "Activation by a DataSteward requires that the activity be
        in DRAFT, that any pia_required activity already have an APPROVED
        assessment — otherwise ERR_PIA_NOT_APPROVED — and that at least one
        Purpose with status DOCUMENTED exist for the activity — otherwise
        ERR_NO_DOCUMENTED_PURPOSE."

        Design: Corner/errors/err_no_documented_purpose_on_activate
        """
        element = create_element(element_key="email", category="BASIC_CONTACT",
                                 classification="INTERNAL")                         # 50
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        assert activity["pia_required"] is False

        resp = api.activate_activity(activity["id"], DS)
        validate_error(resp, ApiErrorId.ERR_NO_DOCUMENTED_PURPOSE)
        after = get_success_data(api.get_activity(activity["id"], DS))
        assert after["status"] == "DRAFT"

    def test_err_open_assessment_exists_on_second_pia(self, api):
        """PRD §3.5: "the manual route is blocked with ERR_OPEN_ASSESSMENT_EXISTS
        when the activity already has an open assessment in TRIGGERED, IN_REVIEW,
        or CHANGES_REQUESTED."

        Design: Corner/errors/err_open_assessment_exists_on_second_pia
        """
        element = create_element(element_key="bio_fp", category="BIOMETRIC",
                                 classification="RESTRICTED")                       # 800
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Access control", business_unit="Security",
                                    notice_scope="EMPLOYEE",
                                    data_element_ids=[element["id"]]), DS))
        assert activity["pia_required"] is True  # auto-PIA sits TRIGGERED

        resp = api.create_assessment(activity["id"], DS)
        validate_error(resp, ApiErrorId.ERR_OPEN_ASSESSMENT_EXISTS)


class TestSegregationOfDuties:
    def test_sod_reject_by_submitter_forbidden(self, api):
        """PRD §3.5: "All three reviewer actions require that the reviewer's
        X-User-ID differ from the assessment's submitted_by_user_id; a reviewer
        who is also the most recent submitter is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/validations/sod_reject_by_submitter_forbidden
        """
        _activity, pia = create_activity_with_manual_assessment(submitter_headers=BO2)
        assert pia["submitted_by_user_id"] == "bo-2"

        from test_helpers import make_legal_counsel_headers
        resp = api.reject_assessment(pia["id"], make_legal_counsel_headers("bo-2"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api.get_assessment(pia["id"], LC1))
        assert after["status"] == "IN_REVIEW"

    def test_sod_request_changes_by_submitter_forbidden(self, api):
        """PRD §3.5: "All three reviewer actions require that the reviewer's
        X-User-ID differ from the assessment's submitted_by_user_id; a reviewer
        who is also the most recent submitter is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/validations/sod_reject_by_submitter_forbidden
        """
        _activity, pia = create_activity_with_manual_assessment(submitter_headers=BO2)
        assert pia["submitted_by_user_id"] == "bo-2"

        from test_helpers import make_legal_counsel_headers
        resp = api.request_changes_assessment(pia["id"], make_legal_counsel_headers("bo-2"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api.get_assessment(pia["id"], LC1))
        assert after["status"] == "IN_REVIEW"


class TestActivityTerminalAndRetiredGates:
    def test_retire_retired_activity_returns_invalid_state(self, api):
        """PRD §3.4: "Retirement by a DataSteward is valid from either ACTIVE or
        COMPLIANCE_HOLD and moves the activity to the terminal RETIRED status"
        PRD §2.9: "A state machine's terminal state is a lockdown: once a
        resource reaches a terminal state, no further trigger is valid against
        it, and any attempt is rejected with ERR_INVALID_STATE_TRANSITION."

        Design: Corner/state_machines/retire_retired_activity_returns_invalid_state
        """
        from test_helpers import create_active_activity
        activity, _purpose = create_active_activity()
        retired = get_success_data(api.retire_activity(activity["id"], DS))
        assert retired["status"] == "RETIRED"

        resp = api.retire_activity(activity["id"], DS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_activity(activity["id"], DS))
        assert after["status"] == "RETIRED"

    def test_err_activity_retired_blocks_purpose_create(self, api):
        """PRD §3.4: "A DataSteward creates a purpose against an activity that is
        not RETIRED — attempting it against a retired activity is rejected with
        ERR_ACTIVITY_RETIRED"

        Design: Corner/errors/err_activity_retired_blocks_purpose_create
        """
        from test_helpers import create_active_activity
        activity, _purpose = create_active_activity()
        get_success_data(api.retire_activity(activity["id"], DS))

        policy = create_retention_policy(policy_code="RP-2YR", duration_days=730)
        resp = api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="ANALYTICS", legal_basis="CONTRACT",
                                   retention_policy_id=policy["id"]), DS)
        validate_error(resp, ApiErrorId.ERR_ACTIVITY_RETIRED)

    def test_err_element_retired_on_activity_link(self, api):
        """PRD §3.1: "Retired elements are rejected by ERR_ELEMENT_RETIRED when a
        new processing activity attempts to link them, but activities that
        already link the element are not modified — links are immutable once
        created."

        Design: Corner/errors/err_element_retired_on_activity_link
        """
        element = create_element(element_key="email", category="BASIC_CONTACT",
                                 classification="INTERNAL")
        retired = get_success_data(api.retire_data_element(element["id"], DS))
        assert retired["status"] == "RETIRED"

        resp = api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS)
        validate_error(resp, ApiErrorId.ERR_ELEMENT_RETIRED)


class TestPurposeNoticeGate:
    def test_purpose_requires_published_notice(self, api):
        """PRD §3.4: "When the legal basis is CONSENT, the server also pins
        pinned_notice_id to a PUBLISHED notice in the activity's notice_scope; if
        no such published notice exists the create is rejected with
        ERR_NO_PUBLISHED_NOTICE."
        PRD §3.4: "The new purpose is created in DOCUMENTED status."

        Design: Difficulty/cross_entity_state_dependency/purpose_requires_published_notice
        """
        policy = create_retention_policy()
        element = create_element()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="HR analytics", business_unit="HR",
                                    notice_scope="EMPLOYEE",
                                    data_element_ids=[element["id"]]), DS))

        resp = api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="ANALYTICS", legal_basis="CONSENT",
                                   retention_policy_id=policy["id"]), DS)
        validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_NOTICE)

        notice = create_published_notice(scope="EMPLOYEE", title="Emp v1")
        purpose = get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="ANALYTICS", legal_basis="CONSENT",
                                   retention_policy_id=policy["id"]), DS))
        assert purpose["status"] == "DOCUMENTED"
        assert purpose["pinned_notice_id"] == notice["id"], (
            "success version-pins the in-scope PUBLISHED notice"
        )

    def test_non_consent_purpose_pins_nothing_without_notice(self, api):
        """PRD §3.4: "For non-consent bases, pinned_notice_id stays null."
        PRD §3.4: "The new purpose is created in DOCUMENTED status."

        Design: Difficulty/cross_entity_state_dependency/purpose_requires_published_notice
        """
        policy = create_retention_policy()
        element = create_element()
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="HR analytics", business_unit="HR",
                                    notice_scope="EMPLOYEE",
                                    data_element_ids=[element["id"]]), DS))
        # No notice exists anywhere; a CONTRACT basis must not require one.
        purpose = get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="EMPLOYMENT", legal_basis="CONTRACT",
                                   retention_policy_id=policy["id"]), DS))
        assert purpose["status"] == "DOCUMENTED"
        assert purpose["pinned_notice_id"] is None


class TestPurposeRelink:
    def test_purpose_relink_restores_documented_and_resumes_activity(self, api):
        """PRD §3.4: "When a DataSteward relinks a purpose in CONSENT_STALE
        status, the server requires that a PUBLISHED notice exist in the
        purpose's activity's notice_scope — otherwise ERR_NO_PUBLISHED_NOTICE —
        and re-pins pinned_notice_id to the current published notice in scope."
        PRD §3.4: "If the owning activity is in COMPLIANCE_HOLD and now has zero
        remaining CONSENT_STALE purposes and zero assessments in TRIGGERED,
        IN_REVIEW, or CHANGES_REQUESTED, the activity auto-resumes to ACTIVE,
        reinstating its ACTIVITY_HOLD-suspended transfers as in the resume
        transition."

        Design: Corner/state_machines/purpose_relink_restores_documented_and_resumes_activity
        """
        policy = create_retention_policy()
        element = create_element()
        n1 = create_published_notice(scope="WEBSITE", title="v1")
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="CRM", business_unit="Sales",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        purpose = get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="MARKETING", legal_basis="CONSENT",
                                   retention_policy_id=policy["id"]), DS))
        assert purpose["pinned_notice_id"] == n1["id"]
        get_success_data(api.activate_activity(activity["id"], DS))

        n2 = publish_superseding_notice(n1["id"])
        assert get_success_data(api.get_purpose(purpose["id"], DS))["status"] == "CONSENT_STALE"
        assert get_success_data(api.get_activity(activity["id"], DS))["status"] == "COMPLIANCE_HOLD"

        relinked = get_success_data(api.relink_purpose(purpose["id"], DS))
        assert relinked["status"] == "DOCUMENTED"
        assert relinked["pinned_notice_id"] == n2["id"], (
            "relink re-pins the scope's current PUBLISHED notice"
        )

        a_after = get_success_data(api.get_activity(activity["id"], DS))
        assert a_after["status"] == "ACTIVE", (
            "no stale purposes and no open assessments remain: auto-resume fires"
        )
