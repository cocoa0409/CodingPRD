"""Role authorisation: endpoint exclusivity, consumer ownership and segregation of duties."""

from test_helpers import (
    CAMPAIGN_MANAGER_BUILDER_USER_ID,
    OFFICER_AUDITOR_USER_ID,
    OFFICER_LAUNCHER_USER_ID,
    OFFICER_SCRIPT_APPROVER_USER_ID,
    ApiErrorId,
    AttemptOutcome,
    CampaignStatus,
    ConsentStatus,
    ConsentType,
    VoidReason,
    assert_created,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_status,
    assert_timestamp_equals,
    assert_total_count,
    assert_version_is,
    factories,
    make_campaign_manager_headers,
    make_consumer_headers,
    make_headers,
    validate_error,
    validate_paginated,
)


class TestComplianceOfficerExclusiveOperations:
    """Compliance controls belong to the officer role alone."""

    def test_01_campaign_manager_cannot_certify_a_launch(
        self, api, world, scrubbed_campaign
    ):
        """The manager who built the campaign is refused the launch certification even
        though every business precondition holds, and an officer then certifies it.

        PRD 2.1: "A `CampaignManager` builds campaigns, drafts scripts and dialer
        profiles, queues and runs scrubs, and closes campaigns, but may never approve a
        script, certify a launch or adjudicate a complaint."

        PRD 2.1: "Once the headers are accepted, the acting role must appear on the
        endpoint being called; if it does not, the request is refused with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/campaign_manager_cannot_certify_a_launch
        """
        campaign = scrubbed_campaign["campaign"]
        version = world.campaign_version(campaign["id"])

        refusal = api.launch_campaign(
            campaign["id"],
            factories.campaign_launch_payload(expected_campaign_version=version),
            make_campaign_manager_headers(CAMPAIGN_MANAGER_BUILDER_USER_ID),
        )
        validate_error(refusal, ApiErrorId.FORBIDDEN_ROLE)

        untouched = world.read_campaign(campaign["id"])
        assert_status(untouched, CampaignStatus.PENDING_LAUNCH)
        assert_fields_null(untouched, "launch_certified_by_user_id")

        launched = world.launch_campaign(
            campaign["id"], expected_campaign_version=version
        )
        assert_status(launched, CampaignStatus.ACTIVE)

    def test_02_dialer_operator_cannot_void_the_attempt_they_dispositioned(
        self, api, world, active_campaign
    ):
        """The operator owns the disposition endpoint but not the void endpoint, so their
        recorded no-answer survives the refusal with the budget still charged.

        PRD 2.1: "A `DialerOperator` runs the dialer: requesting attempts, recording
        dispositions, running reassigned-number checks, and logging revocations or
        complaints heard on a call."

        PRD 3.8: "Voiding an attempt is a `ComplianceOfficer`'s compliance correction and
        is admissible from every one of the five recordable states, so that `PENDING →
        VOIDED`, `CONNECTED_LIVE → VOIDED`, `ABANDONED → VOIDED`, `MACHINE_ANSWERED →
        VOIDED` and `NO_ANSWER → VOIDED` are all available so long as `voided_at` is
        still null"

        Design: Corner/rbac/dialer_operator_cannot_void_an_attempt
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        attempt = world.create_attempt(campaign["id"], contact["id"])
        world.record_outcome(attempt["id"], outcome=AttemptOutcome.NO_ANSWER)

        refusal = api.void_contact_attempt(
            attempt["id"],
            factories.attempt_void_payload(void_reason=VoidReason.MISDIAL),
            world.operator,
        )
        validate_error(refusal, ApiErrorId.FORBIDDEN_ROLE)

        preserved = assert_ok(api.get_contact_attempt(attempt["id"], world.officer))
        assert_status(preserved, AttemptOutcome.NO_ANSWER, field="outcome")
        assert_fields_null(preserved, "voided_at", "void_reason")

        still_charged = world.read_contact(contact["id"])
        assert_fields_equal(
            still_charged, attempts_charged=1, attempt_budget_remaining=2
        )

        campaign_after = world.read_campaign(campaign["id"])
        assert_fields_equal(
            campaign_after, no_answer_count_today=1, voided_attempt_count=0
        )


class TestHeaderAuthentication:
    """The header check runs before any authorisation or business rule."""

    def test_03_consent_capture_under_an_undeclared_role_is_unauthenticated(
        self, api, world
    ):
        """A role name outside the five declared ones is refused as unauthenticated rather
        than as a forbidden role, and no consent row is written.

        PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the five
        declared role names, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401).
        This check runs before anything else in the request, including body parsing."

        PRD 2.1: "The five roles are `Consumer`, `CampaignManager`, `ComplianceOfficer`,
        `DialerOperator` and `PlatformAdmin`."

        Design: Corner/rbac/consent_capture_with_an_undeclared_role_is_unauthenticated
        """
        world.set_clock("2026-08-03T00:00:00Z")
        world.create_ca_policy()
        contact = world.create_ca_contact()
        script = world.approved_script()

        refusal = api.create_consent_record(
            factories.consent_record_payload(
                contact_id=contact["id"],
                disclosure_script_id=script["id"],
                expected_contact_version=contact["version"],
            ),
            make_headers(OFFICER_AUDITOR_USER_ID, "Auditor"),
        )
        error = validate_error(refusal, ApiErrorId.UNAUTHENTICATED)
        assert error["error_id"] != ApiErrorId.FORBIDDEN_ROLE

        _, meta = validate_paginated(api.list_consent_records(world.officer))
        assert_total_count(meta, 0)

        unchanged = world.read_contact(contact["id"])
        assert_fields_equal(unchanged, total_consent_count=0)
        assert_version_is(unchanged, 1)


class TestConsumerOwnership:
    """A consumer's user identifier is a contact identifier."""

    def test_04_consumer_cannot_capture_consent_for_another_consumers_record(
        self, api, world
    ):
        """Capturing consent naming somebody else's contact is refused as an ownership
        failure, and neither consumer's census moves.

        PRD 2.1: "Concretely, when a `Consumer` captures a consent record or logs a
        revocation request, the payload `contact_id` must equal `X-User-ID`; a mismatch is
        refused with `ERR_NOT_CONTACT_OWNER` (HTTP 403)."

        PRD 2.1: "When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting
        `Contact`; ownership checks on any resource that references a `Contact` compare
        the resource's `contact_id` field to `X-User-ID`."

        Design: Corner/rbac/consumer_cannot_capture_consent_for_another_contact
        """
        world.set_clock("2026-08-03T00:00:00Z")
        world.create_ca_policy()
        owner = world.create_ca_contact()
        intruder = world.create_second_ca_contact()
        script = world.approved_script()

        refusal = api.create_consent_record(
            factories.consent_record_payload(
                contact_id=owner["id"],
                disclosure_script_id=script["id"],
                expected_contact_version=owner["version"],
            ),
            make_consumer_headers(intruder["id"]),
        )
        validate_error(refusal, ApiErrorId.NOT_CONTACT_OWNER)

        owner_after = world.read_contact(owner["id"])
        assert_fields_equal(owner_after, total_consent_count=0)
        assert_version_is(owner_after, 1)

        intruder_after = world.read_contact(intruder["id"])
        assert_fields_equal(intruder_after, total_consent_count=0)

    def test_05_consumer_may_capture_consent_for_their_own_record(self, api, world):
        """The identical request succeeds when the acting consumer's identifier equals the
        payload contact, which shows the rule is an ownership test and not a role denial.

        PRD 2.1: "They may capture consent for their own record, revoke it by any
        reasonable method, file a complaint, and read their own compliance history."

        PRD 3.2: "Capture stamps `captured_at` with the current logical clock instant,
        sets `status` to `ACTIVE`, and returns the new record with a 201. Its
        `suspended_reason` and `revoked_at` are null and its `reinstatement_count` is 0."

        Design: Corner/rbac/consumer_may_capture_consent_for_their_own_contact
        """
        world.set_clock("2026-08-03T00:00:00Z")
        world.create_ca_policy()
        contact = world.create_ca_contact()
        script = world.approved_script()

        record = assert_created(
            api.create_consent_record(
                factories.consent_record_payload(
                    contact_id=contact["id"],
                    disclosure_script_id=script["id"],
                    expected_contact_version=contact["version"],
                ),
                make_consumer_headers(contact["id"]),
            )
        )
        assert_status(record, ConsentStatus.ACTIVE)
        assert_fields_equal(
            record,
            consent_type=ConsentType.EXPRESS_WRITTEN,
            disclosure_text_version=1,
            reinstatement_count=0,
        )
        assert_timestamp_equals(record["captured_at"], "2026-08-03T00:00:00.000Z")

        counted = world.read_contact(contact["id"])
        assert_fields_equal(counted, active_consent_count=1, total_consent_count=1)
        assert_version_is(counted, 2)


class TestSegregationOfDuties:
    """Two distinct officer identities are needed to put a campaign on the wire."""

    def test_06_script_approver_cannot_certify_the_launch_of_that_campaign(
        self, api, world, scrubbed_campaign
    ):
        """The officer recorded as the pinned script's approver is refused the launch,
        while a different officer certifies the very same campaign.

        PRD 2.1: "The officer whose `X-User-ID` was recorded as `approved_by_user_id` when
        a script was approved is refused the launch certification of any campaign pinned
        to that script, with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD 2.1: "Putting a campaign on the wire therefore requires two distinct
        `ComplianceOfficer` identities."

        Design: Corner/rbac/script_approver_cannot_certify_the_launch_of_that_campaign
        """
        campaign = scrubbed_campaign["campaign"]
        script = scrubbed_campaign["script"]
        assert_fields_equal(
            script, approved_by_user_id=OFFICER_SCRIPT_APPROVER_USER_ID
        )

        version = world.campaign_version(campaign["id"])
        refusal = api.launch_campaign(
            campaign["id"],
            factories.campaign_launch_payload(expected_campaign_version=version),
            world.script_approver,
        )
        validate_error(refusal, ApiErrorId.SEGREGATION_OF_DUTIES)

        untouched = world.read_campaign(campaign["id"])
        assert_status(untouched, CampaignStatus.PENDING_LAUNCH)
        assert_fields_null(
            untouched, "launch_certified_by_user_id", "pinned_script_version"
        )

        launched = world.launch_campaign(
            campaign["id"],
            headers=world.launcher,
            expected_campaign_version=version,
        )
        assert_status(launched, CampaignStatus.ACTIVE)
        assert_fields_equal(
            launched, launch_certified_by_user_id=OFFICER_LAUNCHER_USER_ID
        )
