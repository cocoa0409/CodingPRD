"""Lifecycle edges: initial states, terminal states, supersession and bounded loops."""

from test_helpers import (
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    api_client,
    assert_age_screen,
    assert_consent_request,
    assert_instant,
    assert_parental_rights_request,
    assert_safe_harbor_assessment,
    child_data_record_payload,
    collected_record,
    create_assessment,
    create_consent,
    create_notice,
    create_program,
    create_rights_request,
    create_age_screen,
    create_service,
    deliver_notice_to_consent,
    grant_consent,
    granted_consent,
    make_assessor_headers,
    make_certifier_headers,
    make_parent_headers,
    mixed_audience_service,
    open_verification,
    publish_notice,
    published_notice,
    read_assessment,
    read_consent,
    read_notice,
    read_record,
    read_rights_request,
    read_service,
    run_compliance,
    set_assessment_status,
    set_clock,
    set_consent_status,
    set_rights_status,
    submit_assessment,
    validate_error,
    validate_paginated,
)


class TestAgeScreenInitialState:
    """A declared screen is not yet a screening capability."""

    def test_01_a_new_screen_is_draft_at_revision_round_zero(self):
        """Declaration alone gives the service no active screen.

        "A new screen is born in `DRAFT` with `revision_round` at 0, `activated_at` null, and
        `neutrality_violation_codes` already computed from the values supplied."

        Design: Corner/state_machines/age_screen_created_starts_in_draft_with_zero_revision_round
        """
        service = mixed_audience_service(name="Draft Screen Service")

        screen = create_age_screen(
            service["id"],
            mechanism="NEUTRAL_DOB_ENTRY",
            retry_allowed_on_fail=False,
            outcome_session_persisted=True,
        )

        assert_age_screen(screen)
        assert screen["status"] == "DRAFT", (
            f"a declared screen is born in DRAFT, got {screen['status']}"
        )
        assert screen["revision_round"] == 0
        assert screen["activated_at"] is None
        assert screen["neutrality_violation_codes"] == [], (
            "a fully neutral screen carries an empty list, got "
            f"{screen['neutrality_violation_codes']}"
        )
        assert screen["version"] == 1

        _, meta = validate_paginated(
            api_client.list_service_age_screens(
                service["id"], ENGINEER_HEADERS, {"status": "ACTIVE", "limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 0, (
            f"the service has no ACTIVE screen yet, got {meta['total_count']}"
        )


class TestNoticePublicationIsNotRepeatable:
    """A service keeps exactly one live notice, and publication never replays."""

    def test_02_publishing_a_superseded_or_published_revision_is_an_invalid_state(self):
        """Neither the superseded revision nor the live one may be published again.

        Publication "moves any other notice of the same service that was `PUBLISHED` to
        `SUPERSEDED`, because a service has at most one live notice at a time." Afterwards
        "Where no more specific code applies the response is `ERR_INVALID_STATE` — publishing
        a notice that is not `DRAFT` ... lands here."

        Design: Corner/state_machines/notice_publish_from_superseded_status_reports_invalid_state
        """
        service = create_service(name="One Live Notice Service")
        first = create_notice(service["id"], notice_label="Notice r1")
        published_first = publish_notice(first["id"])
        assert published_first["status"] == "PUBLISHED"

        second = create_notice(service["id"], notice_label="Notice r2")
        published_second = publish_notice(second["id"])
        assert published_second["status"] == "PUBLISHED"
        assert read_notice(service["id"], first["id"])["status"] == "SUPERSEDED", (
            "publishing the newer revision supersedes the older one"
        )

        validate_error(
            api_client.publish_parental_notice(first["id"], OFFICER_HEADERS),
            "ERR_INVALID_STATE",
        )
        validate_error(
            api_client.publish_parental_notice(second["id"], OFFICER_HEADERS),
            "ERR_INVALID_STATE",
        )

        rows, meta = validate_paginated(
            api_client.list_service_parental_notices(
                service["id"], OFFICER_HEADERS, {"status": "PUBLISHED", "limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"exactly one revision is live, got {meta['total_count']}"
        )
        assert rows[0]["id"] == second["id"], "the live revision is the one published last"


class TestDeniedConsentIsTerminal:
    """A refused parent cannot be walked into consent afterwards."""

    def test_03_a_denied_consent_refuses_both_a_grant_and_a_revocation(self):
        """Denial closes the record and moves no counter.

        "A `ComplianceOfficer` may instead move the request `PENDING_VERIFICATION → DENIED`,
        optionally recording a `denial_reason`. Denial has no preconditions and changes no
        counters, since the consent was never granted." "`DENIED`, `EXPIRED`, `REVOKED` and
        `SUPERSEDED` are all terminal."

        Design: Corner/state_machines/denied_consent_cannot_be_granted_or_revoked_afterwards
        """
        service = mixed_audience_service(name="Denied Consent Service")
        notice = published_notice(service["id"])
        consent = create_consent(
            service["id"], notice["id"], "guardian.d@x.test", "child-600"
        )
        deliver_notice_to_consent(consent["id"])
        open_verification(consent["id"])

        denied = set_consent_status(
            consent["id"],
            "DENIED",
            OFFICER_HEADERS,
            denial_reason="PARENT_REFUSED_VERIFICATION",
        )

        assert_consent_request(denied)
        assert denied["status"] == "DENIED"
        assert denied["granted_at"] is None
        assert denied["revocation_reason"] is None, (
            "a denial is not a revocation, got "
            f"{denied['revocation_reason']}"
        )
        assert read_service(service["id"])["active_consent_count"] == 0, (
            "a denied consent never counted as active"
        )

        validate_error(
            api_client.set_consent_request_status(
                consent["id"],
                {"to_status": "GRANTED", "verification_evidence_code": "PHONE-LOG-9"},
                OFFICER_HEADERS,
            ),
            "ERR_INVALID_STATE",
        )
        validate_error(
            api_client.set_consent_request_status(
                consent["id"],
                {"to_status": "REVOKED", "revocation_reason": "PARENT_REFUSAL"},
                OFFICER_HEADERS,
            ),
            "ERR_INVALID_STATE",
        )

        assert read_consent(consent["id"])["status"] == "DENIED", (
            "two refused transitions left the terminal state intact"
        )


class TestConsentSupersessionOnGrant:
    """A second grant for the same triple demotes the incumbent instead of doubling it."""

    def test_04_granting_a_second_consent_supersedes_the_incumbent_granted_row(self):
        """The count stays at one: one consent in, one consent out.

        "It then supersedes any other `GRANTED` request of the same `service_id`,
        `parent_email` and `child_pseudonym` triple, moving it `GRANTED → SUPERSEDED` with
        `revocation_reason` set to `SUPERSEDED_BY_NEW_CONSENT`." At creation, by contrast,
        only "any prior request of that same triple whose `status` is `INITIATED`,
        `NOTICE_DELIVERED` or `PENDING_VERIFICATION` is moved to `SUPERSEDED`".

        Design: Corner/state_machines/consent_grant_supersedes_the_prior_granted_consent_for_the_same_child
        """
        service = mixed_audience_service(name="Supersession Service")
        notice = published_notice(service["id"])
        first = granted_consent(
            service["id"], notice["id"], "guardian.n@x.test", "child-601"
        )
        assert first["status"] == "GRANTED"
        assert read_service(service["id"])["active_consent_count"] == 1

        second = create_consent(
            service["id"], notice["id"], "guardian.n@x.test", "child-601"
        )
        assert read_consent(first["id"])["status"] == "GRANTED", (
            "creating the successor does not supersede a GRANTED incumbent"
        )

        deliver_notice_to_consent(second["id"])
        open_verification(second["id"])
        granted_second = grant_consent(second["id"], "KBA-N-2")

        assert granted_second["status"] == "GRANTED"
        assert_instant(granted_second["granted_at"], STARTUP_CLOCK, "granted_at")

        demoted = read_consent(first["id"])
        assert demoted["status"] == "SUPERSEDED", (
            f"the grant demotes the incumbent, got {demoted['status']}"
        )
        assert demoted["revocation_reason"] == "SUPERSEDED_BY_NEW_CONSENT", (
            f"the supersession reason is recorded, got {demoted['revocation_reason']}"
        )
        assert read_service(service["id"])["active_consent_count"] == 1, (
            "the count does not double when one consent replaces another"
        )


class TestRightsVerificationLoopIsBounded:
    """Three failures close the loop; only the officer's exit remains."""

    def test_05_a_fourth_submission_is_refused_while_rejection_stays_open(self):
        """The attempt counter survives every re-submission and caps the loop.

        The parent "may move it `VERIFICATION_FAILED → SUBMITTED` to try again, permitted
        only while `verification_attempt_count` is strictly below 3; a fourth attempt is
        refused with `ERR_VERIFICATION_ATTEMPTS_EXHAUSTED` (HTTP 409). Re-submission clears
        `verification_method` back to null". "`REJECTED` and `FULFILLED` are both terminal."

        Design: Corner/state_machines/rights_verification_failures_loop_until_attempts_are_exhausted
        """
        service = mixed_audience_service(name="Bounded Verification Service")
        notice = published_notice(service["id"])
        consent = granted_consent(
            service["id"], notice["id"], "guardian.p@x.test", "child-602"
        )
        parent = make_parent_headers(consent["id"])
        request = create_rights_request(
            service["id"], consent["id"], "REVIEW", "guardian.p@x.test"
        )
        assert_parental_rights_request(request)
        assert request["verification_attempt_count"] == 0

        expected_counts = []
        for _ in range(3):
            verifying = set_rights_status(
                request["id"],
                "VERIFYING",
                OFFICER_HEADERS,
                verification_method="SIGNED_FORM_RETURN",
            )
            assert verifying["verification_method"] == "SIGNED_FORM_RETURN"
            failed = set_rights_status(request["id"], "VERIFICATION_FAILED", OFFICER_HEADERS)
            expected_counts.append(failed["verification_attempt_count"])
            if len(expected_counts) < 3:
                resubmitted = set_rights_status(request["id"], "SUBMITTED", parent)
                assert resubmitted["status"] == "SUBMITTED"
                assert resubmitted["verification_method"] is None, (
                    "a re-submission clears the method, got "
                    f"{resubmitted['verification_method']}"
                )

        assert expected_counts == [1, 2, 3], (
            "the counter moves once per failed verification, got "
            f"{expected_counts}"
        )

        validate_error(
            api_client.set_parental_rights_request_status(
                request["id"], {"to_status": "SUBMITTED"}, parent
            ),
            "ERR_VERIFICATION_ATTEMPTS_EXHAUSTED",
        )

        rejected = set_rights_status(
            request["id"],
            "REJECTED",
            OFFICER_HEADERS,
            rejection_reason="IDENTITY_NEVER_ESTABLISHED",
        )
        assert rejected["status"] == "REJECTED", (
            "the officer's exit remains open from VERIFICATION_FAILED"
        )

        validate_error(
            api_client.set_parental_rights_request_status(
                request["id"], {"to_status": "SUBMITTED"}, parent
            ),
            "ERR_INVALID_STATE",
        )
        assert read_rights_request(request["id"])["status"] == "REJECTED"
        assert read_service(service["id"])["live_child_data_element_count"] == 0, (
            "the verification loop never touched any collected data"
        )


class TestRefusalStopsCollectionWithoutDisposal:
    """Refusing further collection shuts off the tap without emptying the tank."""

    def test_06_refusal_revokes_the_consent_and_leaves_every_record_in_place(self):
        """The scope is resolved and reported, and nothing is destroyed.

        "For `REFUSE_FURTHER_COLLECTION`, the referenced consent is moved `GRANTED →
        REVOKED` with `revocation_reason` set to `PARENT_REFUSAL`, and no record is destroyed
        — the parent is shutting off the tap, not emptying the tank." Afterwards "attempting
        to collect against a revoked consent surfaces here as `ERR_CONSENT_REVOKED` (409)".

        Design: Corner/state_machines/refusal_of_further_collection_revokes_consent_and_keeps_records
        """
        bundle = collected_record(
            consent_method="SIGNED_FORM_RETURN",
            parent_email="guardian.q@x.test",
            child_pseudonym="child-603",
        )
        request = create_rights_request(
            bundle["service_id"],
            bundle["consent_id"],
            "REFUSE_FURTHER_COLLECTION",
            "guardian.q@x.test",
        )
        assert request["right_type"] == "REFUSE_FURTHER_COLLECTION"
        set_rights_status(
            request["id"],
            "VERIFYING",
            OFFICER_HEADERS,
            verification_method="SIGNED_FORM_RETURN",
        )
        set_rights_status(request["id"], "VERIFIED", OFFICER_HEADERS)

        fulfilled = set_rights_status(
            request["id"], "FULFILLED", OFFICER_HEADERS, scope_mode="PARENT_CONSENT_SCOPE"
        )

        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["in_scope_record_count"] == 1, (
            "the scope is still resolved and reported, got "
            f"{fulfilled['in_scope_record_count']}"
        )
        assert_instant(fulfilled["fulfilled_at"], STARTUP_CLOCK, "fulfilled_at")

        consent = read_consent(bundle["consent_id"])
        assert consent["status"] == "REVOKED"
        assert consent["revocation_reason"] == "PARENT_REFUSAL", (
            f"refusal records PARENT_REFUSAL, got {consent['revocation_reason']}"
        )

        record = read_record(bundle["record_id"])
        assert record["status"] == "COLLECTED", (
            f"refusal is forward-looking only, got {record['status']}"
        )
        assert record["disposed_at"] is None

        service = read_service(bundle["service_id"])
        assert service["live_child_data_element_count"] == 1
        assert service["lifetime_collected_element_count"] == 1
        assert service["active_consent_count"] == 0

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    bundle["service_id"], bundle["consent_id"], bundle["activity_id"]
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_CONSENT_REVOKED",
        )


class TestUnverifiedConsentExpiresOnTheRun:
    """The operator's call is refused at the deadline; only the run moves the row."""

    def test_07_the_deadline_closes_the_window_and_the_next_run_expires_the_consent(self):
        """One millisecond before the deadline the consent survives; at it, it does not.

        Opening verification is "permitted only while the current logical-clock instant is
        strictly earlier than `verification_deadline_at`; at or past the deadline the
        transition is refused with `ERR_CONSENT_WINDOW_EXPIRED` (HTTP 409)." Phase one of a
        run expires "every consent request of the service whose `status` is
        `NOTICE_DELIVERED` or `PENDING_VERIFICATION` and whose `verification_deadline_at` has
        been reached or passed ... with no counter changes."

        Design: Corner/state_machines/unverified_consent_expires_on_the_compliance_run_at_its_deadline
        """
        service = mixed_audience_service(name="Consent Window Service")
        notice = published_notice(service["id"])
        consent = create_consent(
            service["id"], notice["id"], "guardian.r@x.test", "child-604"
        )
        delivered = deliver_notice_to_consent(consent["id"])
        assert_instant(delivered["notice_delivered_at"], STARTUP_CLOCK, "notice_delivered_at")
        assert_instant(
            delivered["verification_deadline_at"],
            "2026-08-15T00:00:00Z",
            "verification_deadline_at",
        )

        set_clock("2026-08-14T23:59:59.999Z")
        early_run = run_compliance(service["id"], ENGINEER_HEADERS)
        assert early_run["run_sequence"] == 1
        assert early_run["expired_consent_count"] == 0, (
            "one millisecond before the deadline the consent survives, got "
            f"{early_run['expired_consent_count']}"
        )

        set_clock("2026-08-15T00:00:00Z")
        validate_error(
            api_client.set_consent_request_status(
                consent["id"], {"to_status": "PENDING_VERIFICATION"}, OFFICER_HEADERS
            ),
            "ERR_CONSENT_WINDOW_EXPIRED",
        )
        assert read_consent(consent["id"])["status"] == "NOTICE_DELIVERED", (
            "the refused transition left the consent where it was"
        )

        expiring_run = run_compliance(service["id"])
        assert expiring_run["run_sequence"] == 2
        assert expiring_run["expired_consent_count"] == 1, (
            f"the run performs the transition, got {expiring_run['expired_consent_count']}"
        )
        assert expiring_run["compliance_posture_after"] == "OPEN"

        expired = read_consent(consent["id"])
        assert expired["status"] == "EXPIRED"
        assert expired["granted_at"] is None

        validate_error(
            api_client.set_consent_request_status(
                consent["id"],
                {
                    "to_status": "GRANTED",
                    "verification_evidence_code": "EMAIL-R-1",
                    "secondary_confirmation_code": "SEC-R-1",
                },
                OFFICER_HEADERS,
            ),
            "ERR_INVALID_STATE",
        )
        assert read_service(service["id"])["active_consent_count"] == 0, (
            "the consent was never granted, so no counter moved on expiry"
        )


class TestAssessmentFailureIsTerminal:
    """Failure needs the loop spent, and closes the assessment for good."""

    def test_08_a_failed_assessment_leaves_the_service_due_and_refuses_every_move(self):
        """The certifier's last move is a terminal failure.

        "Once `remediation_round` has reached 2 the loop is closed, and the certifier's
        remaining move from `REMEDIATION_REQUIRED` is to move the assessment to `FAILED`,
        permitted only when `remediation_round` is 2 or more." "If it has assessments but
        none certified, the status is `ASSESSMENT_DUE`." "`CERTIFIED` and `FAILED` are both
        terminal."

        Design: Corner/state_machines/assessment_fails_after_the_second_remediation_round
        """
        assessor = make_assessor_headers("assessor-1")
        certifier = make_certifier_headers("certifier-1")
        service = mixed_audience_service(name="Failed Assessment Service")
        program = create_program(
            program_name="KidTrust Seal",
            regulator_approved=True,
            annual_assessment_required=True,
            assessment_validity_days=365,
            assessment_grace_days=30,
        )
        assessment = create_assessment(service["id"], program["id"], 2026, assessor)
        submit_assessment(assessment["id"], 2, assessor)
        first_round = set_assessment_status(
            assessment["id"], "REMEDIATION_REQUIRED", certifier
        )
        assert first_round["remediation_round"] == 1
        set_assessment_status(
            assessment["id"], "SUBMITTED", assessor, findings_open_count=2
        )
        second_round = set_assessment_status(
            assessment["id"], "REMEDIATION_REQUIRED", certifier
        )
        assert second_round["remediation_round"] == 2, (
            "failure is unreachable until the loop is spent, got "
            f"{second_round['remediation_round']}"
        )

        failed = set_assessment_status(
            assessment["id"],
            "FAILED",
            certifier,
            remediation_note="remediation exhausted",
        )

        assert_safe_harbor_assessment(failed)
        assert failed["status"] == "FAILED"
        assert failed["certified_at"] is None
        assert failed["expires_at"] is None

        after = read_service(service["id"])
        assert after["safe_harbor_status"] == "ASSESSMENT_DUE", (
            "a failed assessment is enrolment without certification, got "
            f"{after['safe_harbor_status']}"
        )
        assert after["safe_harbor_expires_at"] is None
        assert after["compliance_posture"] == "OPEN", (
            "only a LAPSED safe harbor status reaches the posture ladder, got "
            f"{after['compliance_posture']}"
        )

        validate_error(
            api_client.certify_safe_harbor_assessment(
                assessment["id"], make_certifier_headers("certifier-2")
            ),
            "ERR_INVALID_STATE",
        )
        validate_error(
            api_client.set_safe_harbor_assessment_status(
                assessment["id"],
                {"to_status": "SUBMITTED", "findings_open_count": 0},
                assessor,
            ),
            "ERR_INVALID_STATE",
        )
        assert read_assessment(assessment["id"])["findings_open_count"] == 2, (
            "the refused re-submission stored nothing"
        )


class TestSubmissionRequiresTheProgramToDemandIt:
    """Enrolment is accepted; submission under that program is not."""

    def test_09_a_program_that_demands_no_assessment_refuses_the_submission(self):
        """The DRAFT row exists and stays there.

        Submission requires that "the program must actually require an annual assessment: a
        program whose `annual_assessment_required` is false refuses the submission with
        `ERR_ASSESSMENT_NOT_REQUIRED` (HTTP 409)." Certification, in turn, is declared only
        from `SUBMITTED`, so "certifying an assessment that is not `SUBMITTED`" lands on
        `ERR_INVALID_STATE`.

        Design: Corner/state_machines/assessment_submission_under_a_non_required_program_is_refused
        """
        assessor = make_assessor_headers("assessor-2")
        service = create_service(name="No Assessment Owed Service")
        program = create_program(
            program_name="Voluntary Seal",
            regulator_approved=True,
            annual_assessment_required=False,
        )
        assert program["annual_assessment_required"] is False

        assessment = create_assessment(service["id"], program["id"], 2026, assessor)
        assert assessment["status"] == "DRAFT"
        assert assessment["findings_open_count"] == 0
        assert assessment["preparer_user_id"] == "assessor-2"
        assert read_service(service["id"])["safe_harbor_status"] == "ASSESSMENT_DUE", (
            "opening an assessment moves the service off NOT_ENROLLED"
        )

        validate_error(
            api_client.set_safe_harbor_assessment_status(
                assessment["id"],
                {"to_status": "SUBMITTED", "findings_open_count": 0},
                assessor,
            ),
            "ERR_ASSESSMENT_NOT_REQUIRED",
        )
        assert read_assessment(assessment["id"])["status"] == "DRAFT", (
            "the refused submission stored nothing"
        )

        validate_error(
            api_client.certify_safe_harbor_assessment(
                assessment["id"], make_certifier_headers("certifier-3")
            ),
            "ERR_INVALID_STATE",
        )
