"""Validation precedence: which of several simultaneous violations is reported."""

from test_helpers import (
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    active_age_screen,
    add_design_factor,
    api_client,
    assert_audience_child_share,
    assert_design_score,
    assert_instant,
    child_data_record_payload,
    child_directed_primary_service,
    collect_record,
    consent_request_payload,
    create_activity,
    create_consent,
    create_program,
    create_retention_schedule,
    create_rights_request,
    create_service,
    granted_consent,
    make_assessor_headers,
    make_certifier_headers,
    make_parent_headers,
    mixed_audience_service,
    published_notice,
    read_consent,
    read_rights_request,
    read_service,
    retention_schedule_payload,
    run_determination,
    safe_harbor_assessment_payload,
    service_version,
    set_assessment_status,
    set_posture_override,
    set_rights_status,
    submitted_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


def _collection_surroundings_without_a_determination() -> dict:
    """Everything collection needs except the determination itself.

    An `ACTIVE` neutral screen, an activity requiring `SCREEN_NAME`, a schedule in
    force for that element and purpose, a `PUBLISHED` notice and a granted consent.
    """
    service = create_service(name="Undetermined Club")
    service_id = service["id"]
    active_age_screen(service_id)
    activity = create_activity(service_id, participation_required_elements=["SCREEN_NAME"])
    create_retention_schedule(
        service_id,
        data_element_code="SCREEN_NAME",
        purpose_code="PARTICIPATION_CORE",
        retention_days=30,
        disposal_method="ANONYMIZE",
    )
    notice = published_notice(service_id)
    consent = granted_consent(
        service_id,
        notice["id"],
        "guardian.aa@x.test",
        "child-601",
        consent_method="KNOWLEDGE_BASED_AUTH",
    )
    return {
        "service_id": service_id,
        "activity_id": activity["id"],
        "consent_id": consent["id"],
        "notice_id": notice["id"],
    }


class TestDeterminationGateSplitsIntoTwoCodes:
    """The same endpoint reports a different code before and after the analysis."""

    def test_01_never_assessed_and_general_audience_report_different_codes(self):
        """Two determination states, two errors, then collection finally opens.

        "A service whose `determination_status` is still `NOT_ASSESSED` has not established
        the basis for collecting from children at all, and collection is refused with
        `ERR_DETERMINATION_NOT_MADE`. A service determined `GENERAL_AUDIENCE` is outside this
        regime's child-data surface entirely, and collection is refused with
        `ERR_SERVICE_NOT_CHILD_DIRECTED`. Only `MIXED_AUDIENCE` and `CHILD_DIRECTED_PRIMARY`
        services may proceed."

        Design: Corner/validations/collection_refused_before_determination_and_on_general_audience
        """
        fixture = _collection_surroundings_without_a_determination()
        service_id = fixture["service_id"]
        payload = child_data_record_payload(
            service_id, fixture["consent_id"], fixture["activity_id"]
        )

        assert read_service(service_id)["determination_status"] == "NOT_ASSESSED", (
            "a newly registered service starts at NOT_ASSESSED"
        )
        validate_error(
            api_client.create_child_data_record(payload, ENGINEER_HEADERS),
            "ERR_DETERMINATION_NOT_MADE",
            409,
        )

        add_design_factor(service_id, "LANGUAGE", "INCIDENTAL")
        first_run = run_determination(service_id)
        assert_design_score(first_run, 0.25)
        assert first_run["determination_variant_applied"] == "DESIGN_FIRST", (
            "no verified panel sample exists, so design evidence decides alone, got "
            f"{first_run['determination_variant_applied']}"
        )
        assert first_run["determination_status"] == "GENERAL_AUDIENCE", (
            "0.25 is below the design-first mixed threshold of 0.45, got "
            f"{first_run['determination_status']}"
        )

        validate_error(
            api_client.create_child_data_record(payload, ENGINEER_HEADERS),
            "ERR_SERVICE_NOT_CHILD_DIRECTED",
            409,
        )

        add_design_factor(service_id, "SUBJECT_MATTER", "MODERATE")
        second_run = run_determination(service_id)
        assert_design_score(second_run, 0.51)
        assert second_run["determination_status"] == "MIXED_AUDIENCE", (
            "0.51 is at or above the mixed threshold, got "
            f"{second_run['determination_status']}"
        )
        assert_instant(
            second_run["determination_evaluated_at"], STARTUP_CLOCK, "determination_evaluated_at"
        )

        record = validate_success(
            api_client.create_child_data_record(payload, ENGINEER_HEADERS), 201
        )
        assert record["status"] == "COLLECTED"
        assert record["retention_days_applied"] == 30
        assert_instant(record["disposal_due_at"], "2026-08-31T00:00:00Z", "disposal_due_at")

        after = read_service(service_id)
        assert after["live_child_data_element_count"] == 1
        assert after["lifetime_collected_element_count"] == 1


def _two_consents_over_one_core_schedule() -> dict:
    """A mixed-audience service whose only schedule covers `PARTICIPATION_CORE`.

    Consent A consented to participation alone; consent B additionally consented to
    the `CONTESTS_PRIZES` use, so the two differ only in the minimization branch.
    """
    service = mixed_audience_service(name="Minimization Order Club")
    service_id = service["id"]
    active_age_screen(service_id)
    activity = create_activity(service_id, participation_required_elements=["SCREEN_NAME"])
    create_retention_schedule(
        service_id,
        data_element_code="SCREEN_NAME",
        purpose_code="PARTICIPATION_CORE",
        retention_days=30,
        disposal_method="ANONYMIZE",
    )
    notice = published_notice(service_id)
    consent_a = granted_consent(
        service_id,
        notice["id"],
        "guardian.ba@x.test",
        "child-610",
        intended_uses=["PARTICIPATION_CORE"],
        consent_method="KNOWLEDGE_BASED_AUTH",
    )
    consent_b = granted_consent(
        service_id,
        notice["id"],
        "guardian.bb@x.test",
        "child-611",
        intended_uses=["PARTICIPATION_CORE", "CONTESTS_PRIZES"],
        consent_method="KNOWLEDGE_BASED_AUTH",
    )
    return {
        "service": read_service(service_id),
        "service_id": service_id,
        "activity_id": activity["id"],
        "consent_a": consent_a,
        "consent_b": consent_b,
    }


class TestMinimizationPrecedesTheScheduleCheck:
    """Both minimization branches are reported ahead of a missing schedule."""

    def test_02_the_unconsented_purpose_and_the_unnecessary_element_outrank_the_schedule(self):
        """Priority 20 in the ladder is reached before priority 25.

        The precedence list places "20. **Data minimization**, else
        `ERR_ELEMENT_NOT_REASONABLY_NECESSARY` or `ERR_PURPOSE_NOT_CONSENTED` (422)" ahead of
        "25. **Retention-schedule availability at collection**, else
        `ERR_NO_RETENTION_SCHEDULE` (409)", and "A later check never masks an earlier one."
        "`CONTESTS` maps to `CONTESTS_PRIZES`" and "A purpose whose mapped use is absent from
        `intended_uses` is refused with `ERR_PURPOSE_NOT_CONSENTED`."

        Design: Corner/validations/minimization_checks_run_before_the_retention_schedule_check
        """
        fixture = _two_consents_over_one_core_schedule()
        service_id = fixture["service_id"]
        activity_id = fixture["activity_id"]
        assert fixture["service"]["determination_status"] == "MIXED_AUDIENCE"
        assert fixture["consent_b"]["required_tier_at_creation"] == 2, (
            "the contests use requires tier 2, which the chosen method exactly meets, got "
            f"{fixture['consent_b']['required_tier_at_creation']}"
        )

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    service_id,
                    fixture["consent_a"]["id"],
                    activity_id,
                    purpose_code="CONTESTS",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_PURPOSE_NOT_CONSENTED",
            422,
        )

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    service_id,
                    fixture["consent_b"]["id"],
                    activity_id,
                    purpose_code="CONTESTS",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_NO_RETENTION_SCHEDULE",
            409,
        )

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    service_id,
                    fixture["consent_b"]["id"],
                    activity_id,
                    data_element_code="GEOLOCATION_PRECISE",
                    purpose_code="PARTICIPATION_CORE",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_ELEMENT_NOT_REASONABLY_NECESSARY",
            422,
        )

    def test_03_a_purpose_scoped_schedule_is_accepted_and_is_the_one_pinned(self):
        """The overlap partition includes the purpose, and the narrower schedule governs.

        "Schedules for different elements, different purposes or different services never
        conflict." "The governing schedule's `retention_days` and `disposal_method` are copied
        onto the record as `retention_days_applied` and `disposal_method_applied` — pinned
        copies ... and `disposal_due_at` is set to `collected_at` plus
        `retention_days_applied` days."

        Design: Corner/validations/minimization_checks_run_before_the_retention_schedule_check
        """
        fixture = _two_consents_over_one_core_schedule()
        service_id = fixture["service_id"]

        contests_schedule = validate_success(
            api_client.create_retention_schedule(
                retention_schedule_payload(
                    service_id,
                    data_element_code="SCREEN_NAME",
                    purpose_code="CONTESTS",
                    retention_days=7,
                    disposal_method="OVERWRITE",
                    effective_from="2026-01-01T00:00:00Z",
                    effective_to="2026-12-31T00:00:00Z",
                    defined_purpose_statement="Contest entry nickname, 7 days.",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert contests_schedule["purpose_code"] == "CONTESTS"

        record = collect_record(
            service_id,
            fixture["consent_b"]["id"],
            fixture["activity_id"],
            purpose_code="CONTESTS",
        )

        assert record["retention_days_applied"] == 7, (
            "the contests schedule governs, not the 30-day participation one, got "
            f"{record['retention_days_applied']}"
        )
        assert record["disposal_method_applied"] == "OVERWRITE"
        assert_instant(record["disposal_due_at"], "2026-08-08T00:00:00Z", "disposal_due_at")

        _, meta = validate_paginated(
            api_client.list_service_retention_schedules(
                service_id, OFFICER_HEADERS, {"data_element_code": "SCREEN_NAME"}
            )
        )
        assert meta["total_count"] == 2, (
            f"both purpose-scoped schedules are stored, got {meta['total_count']}"
        )


class TestPostureOverrideNarrowsThenFreezes:
    """Clause 1 of the ladder decides the posture on its own, in both directions."""

    def test_04_restriction_spares_participation_and_freezing_spares_nothing(self):
        """A manual lock gates collection, then consent intake, then releases both.

        "If `posture_override` is not null, the posture is exactly that override value."
        "When the posture is `FROZEN`, collecting a child data element, creating a consent
        request, and approving a third-party integration are all refused with
        `ERR_POSTURE_FROZEN` (HTTP 409). When the posture is `RESTRICTED`, collecting a child
        data element is refused with `ERR_POSTURE_RESTRICTED` (HTTP 409) unless the
        collection's `purpose_code` is `PARTICIPATION_CORE`; consent creation and integration
        approval are unaffected by `RESTRICTED`."

        Design: Corner/validations/posture_override_narrows_then_freezes_collection_and_consent_intake
        """
        service = mixed_audience_service(name="Override Ladder Club")
        service_id = service["id"]
        active_age_screen(service_id)
        activity = create_activity(service_id, participation_required_elements=["SCREEN_NAME"])
        create_retention_schedule(
            service_id,
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
            retention_days=30,
            disposal_method="ANONYMIZE",
        )
        create_retention_schedule(
            service_id,
            data_element_code="SCREEN_NAME",
            purpose_code="CONTESTS",
            retention_days=7,
            disposal_method="OVERWRITE",
        )
        notice = published_notice(service_id)
        consent = granted_consent(
            service_id,
            notice["id"],
            "guardian.bc@x.test",
            "child-613",
            intended_uses=["PARTICIPATION_CORE", "CONTESTS_PRIZES"],
            consent_method="KNOWLEDGE_BASED_AUTH",
        )
        contests_payload = child_data_record_payload(
            service_id, consent["id"], activity["id"], purpose_code="CONTESTS"
        )
        core_payload = child_data_record_payload(
            service_id, consent["id"], activity["id"], purpose_code="PARTICIPATION_CORE"
        )

        restricted = set_posture_override(service_id, "RESTRICTED")
        assert restricted["compliance_posture"] == "RESTRICTED"
        assert restricted["posture_override"] == "RESTRICTED"
        assert restricted["determination_status"] == "MIXED_AUDIENCE", (
            "the posture submission never touches the determination axis, got "
            f"{restricted['determination_status']}"
        )

        validate_error(
            api_client.create_child_data_record(contests_payload, ENGINEER_HEADERS),
            "ERR_POSTURE_RESTRICTED",
            409,
        )
        core_record = validate_success(
            api_client.create_child_data_record(core_payload, ENGINEER_HEADERS), 201
        )
        assert core_record["status"] == "COLLECTED", (
            "participation remains collectible under restriction, got "
            f"{core_record['status']}"
        )

        frozen = set_posture_override(service_id, "FROZEN")
        assert frozen["compliance_posture"] == "FROZEN"
        validate_error(
            api_client.create_child_data_record(core_payload, ENGINEER_HEADERS),
            "ERR_POSTURE_FROZEN",
            409,
        )
        validate_error(
            api_client.create_consent_request(
                consent_request_payload(
                    service_id,
                    notice["id"],
                    "guardian.bz@x.test",
                    "child-612",
                    service_version(service_id),
                    intended_uses=["PARTICIPATION_CORE"],
                    consent_method="KNOWLEDGE_BASED_AUTH",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_POSTURE_FROZEN",
            409,
        )

        cleared = set_posture_override(service_id, None)
        assert cleared["compliance_posture"] == "OPEN", (
            "with the override gone the computation governs again, got "
            f"{cleared['compliance_posture']}"
        )
        assert cleared["posture_override"] is None
        assert cleared["third_party_exposure_points"] == 0
        assert cleared["open_audit_count"] == 0

        contests_record = validate_success(
            api_client.create_child_data_record(contests_payload, ENGINEER_HEADERS), 201
        )
        assert_instant(
            contests_record["disposal_due_at"], "2026-08-08T00:00:00Z", "disposal_due_at"
        )
        assert read_service(service_id)["live_child_data_element_count"] == 2


class TestChildDirectedPrimaryInvertsTheScreenGate:
    """No screen is demanded, yet a thirteen-plus outcome is a category error."""

    def test_05_a_thirteen_plus_outcome_is_refused_where_no_screen_exists_at_all(self):
        """The primary determination needs no screen and admits no adult.

        "On a `CHILD_DIRECTED_PRIMARY` service the logic inverts: every visitor is treated as
        a child, so no active screen is demanded, but presenting an `age_screen_outcome` of
        `THIRTEEN_PLUS` is a category error and is refused outright with
        `ERR_AGE_SCREEN_NOT_PERMITTED`." "A `design_score` of 0.75 or more makes the service
        `CHILD_DIRECTED_PRIMARY`."

        Design: Corner/validations/child_directed_primary_service_refuses_a_thirteen_plus_outcome
        """
        service = child_directed_primary_service(name="Primary Only Club")
        service_id = service["id"]
        assert_design_score(service, 1.00)
        assert_audience_child_share(service, None)
        assert service["determination_variant_applied"] == "DESIGN_FIRST"
        assert service["determination_status"] == "CHILD_DIRECTED_PRIMARY"

        activity = create_activity(service_id, participation_required_elements=["SCREEN_NAME"])
        create_retention_schedule(
            service_id,
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
            retention_days=30,
            disposal_method="CRYPTO_ERASE",
        )
        notice = published_notice(service_id)
        consent = granted_consent(
            service_id,
            notice["id"],
            "guardian.bd@x.test",
            "child-614",
            consent_method="SIGNED_FORM_RETURN",
        )

        _, meta = validate_paginated(
            api_client.list_service_age_screens(service_id, ENGINEER_HEADERS)
        )
        assert meta["total_count"] == 0, (
            f"the service has no age screen row whatsoever, got {meta['total_count']}"
        )

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    service_id,
                    consent["id"],
                    activity["id"],
                    age_screen_outcome="THIRTEEN_PLUS",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_AGE_SCREEN_NOT_PERMITTED",
            422,
        )

        record = collect_record(service_id, consent["id"], activity["id"])

        assert record["status"] == "COLLECTED", (
            f"collection succeeds with no screen at all, got {record['status']}"
        )
        assert record["disposal_method_applied"] == "CRYPTO_ERASE"
        assert_instant(record["disposal_due_at"], "2026-08-31T00:00:00Z", "disposal_due_at")


class TestRightsVerificationClauseOrder:
    """Three requests, each breaking one clause, produce three different codes."""

    def test_06_undelivered_notice_then_tier_then_email(self):
        """The declared clause order decides which single code is reported.

        "Moving the request `VERIFYING → VERIFIED` applies three cross-checks against the
        referenced consent, in this order. The consent's `notice_delivered_at` must be
        non-null, otherwise `ERR_DIRECT_NOTICE_NOT_DELIVERED` ... The assurance tier of the
        request's `verification_method` must be greater than or equal to the tier of the
        consent's own `consent_method` ... otherwise
        `ERR_RIGHTS_VERIFICATION_TIER_INSUFFICIENT` ... And `requester_email` must equal the
        consent's `parent_email`, otherwise `ERR_REQUESTER_EMAIL_MISMATCH`."

        Design: Corner/validations/rights_verification_clauses_fire_one_at_a_time_in_declared_order
        """
        service = mixed_audience_service(name="Rights Clause Club")
        service_id = service["id"]
        notice = published_notice(service_id)

        undelivered = create_consent(
            service_id,
            notice["id"],
            "guardian.bb@x.test",
            "child-614b",
            consent_method="EMAIL_PLUS",
        )
        assert undelivered["notice_delivered_at"] is None, (
            "a consent still in INITIATED has never had its notice delivered"
        )
        weak_email = granted_consent(
            service_id,
            notice["id"],
            "guardian.cc@x.test",
            "child-615",
            consent_method="EMAIL_PLUS",
            grant_body={"secondary_confirmation_code": "SEC-CC-1"},
        )
        strong_card = granted_consent(
            service_id,
            notice["id"],
            "guardian.dd@x.test",
            "child-616",
            consent_method="CREDIT_CARD_TRANSACTION",
        )

        first = create_rights_request(
            service_id, undelivered["id"], "REVIEW", "guardian.bb@x.test"
        )
        set_rights_status(
            first["id"], "VERIFYING", OFFICER_HEADERS, verification_method="SIGNED_FORM_RETURN"
        )
        validate_error(
            api_client.set_parental_rights_request_status(
                first["id"], {"to_status": "VERIFIED"}, OFFICER_HEADERS
            ),
            "ERR_DIRECT_NOTICE_NOT_DELIVERED",
            422,
        )

        second = create_rights_request(
            service_id, weak_email["id"], "REVIEW", "stranger@x.test"
        )
        set_rights_status(
            second["id"], "VERIFYING", OFFICER_HEADERS, verification_method="SIGNED_FORM_RETURN"
        )
        validate_error(
            api_client.set_parental_rights_request_status(
                second["id"], {"to_status": "VERIFIED"}, OFFICER_HEADERS
            ),
            "ERR_REQUESTER_EMAIL_MISMATCH",
            422,
        )

        third = create_rights_request(
            service_id, strong_card["id"], "REVIEW", "guardian.dd@x.test"
        )
        set_rights_status(
            third["id"], "VERIFYING", OFFICER_HEADERS, verification_method="EMAIL_PLUS"
        )
        validate_error(
            api_client.set_parental_rights_request_status(
                third["id"], {"to_status": "VERIFIED"}, OFFICER_HEADERS
            ),
            "ERR_RIGHTS_VERIFICATION_TIER_INSUFFICIENT",
            422,
        )

        failed = set_rights_status(third["id"], "VERIFICATION_FAILED", OFFICER_HEADERS)
        assert failed["verification_attempt_count"] == 1, (
            f"the single failure advanced the counter to 1, got {failed['verification_attempt_count']}"
        )
        set_rights_status(third["id"], "SUBMITTED", make_parent_headers(strong_card["id"]))
        set_rights_status(
            third["id"], "VERIFYING", OFFICER_HEADERS, verification_method="GOVT_ID_MATCH"
        )
        verified = set_rights_status(third["id"], "VERIFIED", OFFICER_HEADERS)
        assert verified["status"] == "VERIFIED", (
            "a tier-3 method matches the tier the parent consented with, got "
            f"{verified['status']}"
        )

        fulfilled = set_rights_status(
            third["id"], "FULFILLED", OFFICER_HEADERS, scope_mode="PARENT_CONSENT_SCOPE"
        )
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["in_scope_record_count"] == 0, (
            "the consent holds no collected records, got "
            f"{fulfilled['in_scope_record_count']}"
        )

        assert read_rights_request(first["id"])["status"] == "VERIFYING", (
            "the refused transition left the first request where it was"
        )
        assert read_rights_request(second["id"])["status"] == "VERIFYING", (
            "the refused transition left the second request where it was"
        )


class TestFulfilmentBeforeVerification:
    """Premature fulfilment has its own code, and only becomes generic once terminal."""

    def test_07_submitted_and_verifying_both_report_the_dedicated_code(self):
        """The dedicated 409 gives way to a 422 body check, and returns once terminal.

        "Fulfilment moves a verified request `VERIFIED → FULFILLED` and requires a
        `scope_mode` in the body, otherwise `ERR_INVALID_REQUEST`. Attempting fulfilment from
        any status other than `VERIFIED` is refused with `ERR_RIGHTS_REQUEST_NOT_VERIFIED`
        (HTTP 409)." "`REJECTED` and `FULFILLED` are both terminal." For `DELETE`, "if every
        child data record whose `consent_request_id` equals this rights request's
        `consent_request_id` now has `status` of `DISPOSED`, that consent is moved
        `GRANTED → REVOKED` with `revocation_reason` set to `DELETION_FULFILLED`".

        Design: Corner/validations/fulfilment_attempted_before_verification_reports_a_dedicated_error
        """
        service = mixed_audience_service(name="Premature Fulfilment Club")
        service_id = service["id"]
        notice = published_notice(service_id)
        consent = granted_consent(
            service_id,
            notice["id"],
            "guardian.ee@x.test",
            "child-617",
            consent_method="SIGNED_FORM_RETURN",
        )
        request = create_rights_request(
            service_id, consent["id"], "DELETE", "guardian.ee@x.test"
        )
        request_id = request["id"]
        assert request["status"] == "SUBMITTED"

        validate_error(
            api_client.set_parental_rights_request_status(
                request_id,
                {"to_status": "FULFILLED", "scope_mode": "PARENT_CONSENT_SCOPE"},
                OFFICER_HEADERS,
            ),
            "ERR_RIGHTS_REQUEST_NOT_VERIFIED",
            409,
        )

        set_rights_status(
            request_id, "VERIFYING", OFFICER_HEADERS, verification_method="SIGNED_FORM_RETURN"
        )
        validate_error(
            api_client.set_parental_rights_request_status(
                request_id,
                {"to_status": "FULFILLED", "scope_mode": "PARENT_CONSENT_SCOPE"},
                OFFICER_HEADERS,
            ),
            "ERR_RIGHTS_REQUEST_NOT_VERIFIED",
            409,
        )

        set_rights_status(request_id, "VERIFIED", OFFICER_HEADERS)
        validate_error(
            api_client.set_parental_rights_request_status(
                request_id, {"to_status": "FULFILLED"}, OFFICER_HEADERS
            ),
            "ERR_INVALID_REQUEST",
            422,
        )
        assert read_rights_request(request_id)["status"] == "VERIFIED", (
            "the refused fulfilment left the request verified"
        )

        fulfilled = set_rights_status(
            request_id, "FULFILLED", OFFICER_HEADERS, scope_mode="PARENT_CONSENT_SCOPE"
        )
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["in_scope_record_count"] == 0
        assert_instant(fulfilled["fulfilled_at"], STARTUP_CLOCK, "fulfilled_at")

        validate_error(
            api_client.set_parental_rights_request_status(
                request_id,
                {"to_status": "FULFILLED", "scope_mode": "PARENT_CONSENT_SCOPE"},
                OFFICER_HEADERS,
            ),
            "ERR_RIGHTS_REQUEST_NOT_VERIFIED",
            409,
        )

        spent = read_consent(consent["id"])
        assert spent["status"] == "REVOKED", (
            "a consent with nothing left to authorise is spent, got " f"{spent['status']}"
        )
        assert spent["revocation_reason"] == "DELETION_FULFILLED", (
            f"the deletion drove the revocation, got {spent['revocation_reason']}"
        )


class TestAssessmentYearUniquenessTriple:
    """The uniqueness key is the service, the program and the year together."""

    def test_08_the_year_repeats_freely_across_programs_and_services(self):
        """One duplicate is refused; three near-duplicates are accepted.

        "A `SafeHarborAssessor` opens an assessment against a `service_id` and a `program_id`
        for a given `assessment_year`, and at most one assessment may exist for any
        combination of those three; a duplicate is refused with
        `ERR_ASSESSMENT_YEAR_DUPLICATE` (HTTP 409). The new assessment is `DRAFT`, with
        `preparer_user_id` set to the acting assessor's `X-User-ID`". "If it has assessments
        but none certified, the status is `ASSESSMENT_DUE`."

        Design: Corner/validations/assessment_year_uniqueness_is_scoped_to_service_and_program
        """
        first_service = create_service(name="Uniqueness Club A")
        second_service = create_service(name="Uniqueness Club B")
        first_program = create_program(program_name="Seal One", regulator_approved=True)
        second_program = create_program(program_name="Seal Two", regulator_approved=True)
        assessor_four = make_assessor_headers("assessor-4")
        assessor_five = make_assessor_headers("assessor-5")

        validate_success(
            api_client.create_safe_harbor_assessment(
                safe_harbor_assessment_payload(
                    first_service["id"], first_program["id"], 2026
                ),
                assessor_four,
            ),
            201,
        )
        validate_error(
            api_client.create_safe_harbor_assessment(
                safe_harbor_assessment_payload(
                    first_service["id"], first_program["id"], 2026
                ),
                assessor_four,
            ),
            "ERR_ASSESSMENT_YEAR_DUPLICATE",
            409,
        )

        later_year = validate_success(
            api_client.create_safe_harbor_assessment(
                safe_harbor_assessment_payload(
                    first_service["id"], first_program["id"], 2027
                ),
                assessor_four,
            ),
            201,
        )
        assert later_year["assessment_year"] == 2027
        other_program = validate_success(
            api_client.create_safe_harbor_assessment(
                safe_harbor_assessment_payload(
                    first_service["id"], second_program["id"], 2026
                ),
                assessor_four,
            ),
            201,
        )
        assert other_program["program_id"] == second_program["id"]
        other_service = validate_success(
            api_client.create_safe_harbor_assessment(
                safe_harbor_assessment_payload(
                    second_service["id"], first_program["id"], 2026
                ),
                assessor_five,
            ),
            201,
        )
        assert other_service["preparer_user_id"] == "assessor-5", (
            "the preparer is stamped from the acting X-User-ID, got "
            f"{other_service['preparer_user_id']}"
        )
        assert other_service["status"] == "DRAFT"

        _, first_meta = validate_paginated(
            api_client.list_safe_harbor_assessments(
                OFFICER_HEADERS, {"service_id": first_service["id"], "limit": 100, "offset": 0}
            )
        )
        assert first_meta["total_count"] == 3, (
            "the first service holds three accepted assessments, got "
            f"{first_meta['total_count']}"
        )
        _, second_meta = validate_paginated(
            api_client.list_safe_harbor_assessments(
                OFFICER_HEADERS,
                {
                    "service_id": second_service["id"],
                    "program_id": first_program["id"],
                    "assessment_year": 2026,
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        assert second_meta["total_count"] == 1, (
            f"the triple filter selects exactly one row, got {second_meta['total_count']}"
        )

        assert read_service(first_service["id"])["safe_harbor_status"] == "ASSESSMENT_DUE"
        assert read_service(second_service["id"])["safe_harbor_status"] == "ASSESSMENT_DUE"


class TestOpenFindingsOutrankSegregationOfDuties:
    """One attempt breaks two rules, and the earlier clause is the one reported."""

    def test_09_the_findings_clause_hides_the_segregation_clause_until_it_is_satisfied(self):
        """The 409 is reported first; only then does the 403 surface.

        "Moving an assessment `SUBMITTED → CERTIFIED` requires, in this clause order:
        `findings_open_count` equal to 0, otherwise `ERR_OPEN_FINDINGS_PRESENT` (HTTP 409);
        the referenced program's `regulator_approved` to be true ...; and the acting
        `X-User-ID` to differ from the assessment's `preparer_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). That order is normative: an attempt that both
        leaves findings open and is made by the preparer reports `ERR_OPEN_FINDINGS_PRESENT`,
        never `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/open_findings_outrank_segregation_of_duties_on_certification
        """
        service = create_service(name="Dual Duty Club")
        program = create_program(
            program_name="Dual Duty Seal",
            regulator_approved=True,
            annual_assessment_required=True,
            assessment_validity_days=365,
            assessment_grace_days=30,
        )
        submitted = submitted_assessment(service["id"], program["id"], 2026, 3, "dual-1")
        assessment_id = submitted["id"]
        assert submitted["preparer_user_id"] == "dual-1"
        assert submitted["findings_open_count"] == 3

        validate_error(
            api_client.certify_safe_harbor_assessment(
                assessment_id, make_certifier_headers("dual-1")
            ),
            "ERR_OPEN_FINDINGS_PRESENT",
            409,
        )

        sent_back = set_assessment_status(
            assessment_id,
            "REMEDIATION_REQUIRED",
            make_certifier_headers("certifier-6"),
            remediation_note="three findings must close",
        )
        assert sent_back["remediation_round"] == 1
        resubmitted = set_assessment_status(
            assessment_id,
            "SUBMITTED",
            make_assessor_headers("dual-1"),
            findings_open_count=0,
        )
        assert resubmitted["findings_open_count"] == 0

        validate_error(
            api_client.certify_safe_harbor_assessment(
                assessment_id, make_certifier_headers("dual-1")
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        certified = validate_success(
            api_client.certify_safe_harbor_assessment(
                assessment_id, make_certifier_headers("certifier-6")
            )
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["certifier_user_id"] == "certifier-6", (
            "a genuinely different user defeats the segregation clause, got "
            f"{certified['certifier_user_id']}"
        )
        assert_instant(certified["certified_at"], STARTUP_CLOCK, "certified_at")
        assert_instant(certified["expires_at"], "2027-08-01T00:00:00Z", "expires_at")

        after = read_service(service["id"])
        assert after["safe_harbor_status"] == "CERTIFIED"
        assert_instant(
            after["safe_harbor_expires_at"], "2027-08-01T00:00:00Z", "safe_harbor_expires_at"
        )
        assert after["compliance_posture"] == "OPEN"
