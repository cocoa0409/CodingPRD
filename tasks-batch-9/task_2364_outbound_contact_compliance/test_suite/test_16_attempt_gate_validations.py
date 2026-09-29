"""Refusals reached through the compliance gate ladder: intake guards, attempt
channel agreement, outcome admission rules, the abandonment waiver and the three
attempt throttles.
"""

from test_helpers import (
    DEFAULT_CLOCK,
    DEFAULT_WAIVER_REFERENCE,
    OFFICER_PROFILE_APPROVER_USER_ID,
    PHONE_C1,
    STATE_CA,
    STATE_NV,
    TZ_LOS_ANGELES,
    ApiErrorId,
    AttemptOutcome,
    CampaignPurpose,
    CampaignStatus,
    CaptureMethod,
    Channel,
    ConsentStatus,
    ConsentType,
    DialerMode,
    DialerProfileStatus,
    IntakeStatus,
    PhoneType,
    PolicyStatus,
    RevocationChannelReceived,
    RevocationMethod,
    RevocationScope,
    assert_decimal_equals,
    assert_error,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_page,
    assert_status,
    assert_total_count,
    assert_version_is,
    factories,
)


def _over_ceiling_predictive_profile(world):
    """Draft one PREDICTIVE profile configured above the 3.00 percent ceiling."""
    world.set_clock(DEFAULT_CLOCK)
    return world.create_dialer_profile(
        mode=DialerMode.PREDICTIVE,
        agents_available=5,
        abandonment_limit_pct=5.0,
        amd_enabled=True,
        amd_abandon_on_machine=False,
        abandon_message_seconds=2,
    )


class TestContactImportUniqueness:
    """Phone-number uniqueness on contact import."""

    def test_01_second_contact_reusing_a_number_is_refused(
        self, world, platform_admin_headers, api
    ):
        """A second import of a number already held is refused even though its state,
        offset and phone type all differ, and the first contact is untouched.

        PRD: No two contacts may hold the same `phone_number`; a collision is refused
        with `ERR_DUPLICATE_PHONE_NUMBER`.

        Design: Corner/validations/contact_create_with_duplicate_phone_number_rejected
        """
        world.set_clock(DEFAULT_CLOCK)
        first = world.create_ca_contact(
            phone_number=PHONE_C1, phone_type=PhoneType.WIRELESS, attempt_budget_total=3
        )

        response = api.create_contact(
            factories.contact_payload(
                phone_number=PHONE_C1,
                state_code=STATE_NV,
                utc_offset_minutes=-480,
                time_zone_label=TZ_LOS_ANGELES,
                phone_type=PhoneType.LANDLINE,
                attempt_budget_total=2,
            ),
            platform_admin_headers,
        )
        assert_error(response, ApiErrorId.DUPLICATE_PHONE_NUMBER)

        reread = world.read_contact(first["id"])
        assert_fields_equal(reread, state_code=STATE_CA)
        assert_version_is(reread, 1)


class TestRevocationIntakeGuards:
    """The two intake guards on recording a withdrawal of consent."""

    def test_02_second_pending_revocation_for_the_same_consumer_is_refused(
        self, world, compliance_officer_headers, api
    ):
        """While one withdrawal is still sitting at intake, a second withdrawal for the
        same consumer is refused and the first row keeps its own scope.

        PRD: A consumer may also have only one unadjudicated withdrawal outstanding at a
        time: if another revocation request for the same consumer is still sitting in
        `intake_status` `RECEIVED`, the new intake is refused with
        `ERR_DUPLICATE_REVOCATION_PENDING`.

        Design: Corner/validations/second_pending_revocation_for_the_same_contact_rejected
        """
        world.set_clock("2026-08-03T14:00:00Z")
        world.create_ca_policy()
        contact = world.create_ca_contact()
        script = world.approved_script()
        world.create_consent(
            contact["id"],
            script["id"],
            channel=Channel.VOICE,
            consent_type=ConsentType.EXPRESS_WRITTEN,
        )
        first = world.create_revocation(
            contact["id"],
            channel_received=RevocationChannelReceived.SMS,
            method=RevocationMethod.REPLY_STOP,
            scope=RevocationScope.ALL_CHANNELS,
            received_note="Consumer replied STOP",
        )
        assert_status(first, IntakeStatus.RECEIVED, field="intake_status")

        response = api.create_revocation_request(
            factories.revocation_request_payload(
                contact_id=contact["id"],
                channel_received=RevocationChannelReceived.EMAIL,
                method=RevocationMethod.EMAIL_REQUEST,
                scope=RevocationScope.VOICE,
                received_note="Please stop calling me",
            ),
            compliance_officer_headers,
        )
        assert_error(response, ApiErrorId.DUPLICATE_REVOCATION_PENDING)

        reread = assert_ok(
            api.get_revocation_request(first["id"], compliance_officer_headers)
        )
        assert_status(reread, IntakeStatus.RECEIVED, field="intake_status")
        assert_fields_equal(reread, scope=RevocationScope.ALL_CHANNELS)

        _rows, meta = assert_page(
            api.list_contact_revocation_requests(
                contact["id"], compliance_officer_headers
            )
        )
        assert_total_count(meta, 1)

    def test_03_reply_stop_arriving_on_email_is_refused(
        self, world, compliance_officer_headers, api
    ):
        """A STOP reply claimed to have arrived by email pairs a method with the wrong
        channel, so no withdrawal is recorded at all.

        PRD: The five accepted methods each belong to exactly one arrival channel, and
        the pairing is checked at intake: `REPLY_STOP` is reasonable only on `SMS`,
        `VERBAL_REQUEST` only on `VOICE`, `EMAIL_REQUEST` only on `EMAIL`, `WEB_PORTAL`
        only on `WEB`, and `POSTAL_MAIL` only on `MAIL`.

        Design: Corner/validations/reply_stop_on_a_non_sms_channel_rejected
        """
        world.set_clock("2026-08-03T14:00:00Z")
        world.create_ca_policy()
        contact = world.create_ca_contact()
        script = world.approved_script()
        consent = world.create_consent(
            contact["id"],
            script["id"],
            channel=Channel.VOICE,
            consent_type=ConsentType.EXPRESS_WRITTEN,
        )

        response = api.create_revocation_request(
            factories.revocation_request_payload(
                contact_id=contact["id"],
                channel_received=RevocationChannelReceived.EMAIL,
                method=RevocationMethod.REPLY_STOP,
                scope=RevocationScope.ALL_CHANNELS,
                received_note="Consumer replied STOP",
            ),
            compliance_officer_headers,
        )
        assert_error(response, ApiErrorId.METHOD_CHANNEL_MISMATCH)

        _rows, meta = assert_page(
            api.list_contact_revocation_requests(
                contact["id"], compliance_officer_headers
            )
        )
        assert_total_count(meta, 0)

        reread = assert_ok(
            api.get_consent_record(consent["id"], compliance_officer_headers)
        )
        assert_status(reread, ConsentStatus.ACTIVE)


class TestAttemptChannelAgreement:
    """Channel agreement on attempt creation, and its place in the ladder."""

    def test_04_texting_a_voice_campaign_is_refused(
        self, world, dialer_operator_headers, api
    ):
        """With live consent on both channels, a text placed against a voice campaign
        still fails on channel agreement and charges nothing.

        PRD: The campaign must be `ACTIVE`, or the request is refused with
        `ERR_CAMPAIGN_STATE_INVALID`, and the attempt's `channel` must equal the
        campaign's own `channel`, or it is refused with `ERR_ATTEMPT_CHANNEL_MISMATCH`.

        Design: Corner/validations/attempt_channel_must_equal_the_campaign_channel
        """
        built = world.build(stop_after="launch")
        sms_script = world.approved_script(
            name="CA SMS Script", channel=Channel.SMS, covered_state_codes=[STATE_CA]
        )
        world.create_consent(
            built["contact"]["id"],
            sms_script["id"],
            channel=Channel.SMS,
            consent_type=ConsentType.EXPRESS_WRITTEN,
            capture_method=CaptureMethod.SMS_DOUBLE_OPT_IN,
        )

        response = api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.SMS,
            ),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.ATTEMPT_CHANNEL_MISMATCH)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=0, attempt_budget_remaining=3)
        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(campaign, permitted_attempt_count=0)

    def test_05_missing_consent_outranks_channel_disagreement(
        self, world, dialer_operator_headers, api
    ):
        """A text to a consumer who only ever consented to voice fails on the absent
        consent basis, not on the campaign's channel, because the safety block is
        evaluated first.

        PRD: Checks are evaluated in the following order, and the first failing check
        ends the request.

        PRD: The attempt-time safety block, in this exact order on
        `POST /compliance/contact-attempts`: suppression-list coverage —
        `ERR_SUPPRESSED_NUMBER`; existence of a consent basis —
        `ERR_NO_CONSENT_ON_RECORD`; the express-written requirement for marketing —
        `ERR_NO_EXPRESS_WRITTEN_CONSENT`; reassigned-number check currency —
        `ERR_RND_CHECK_REQUIRED`; the reassigned verdict itself —
        `ERR_REASSIGNED_NUMBER`.

        Design: Corner/validations/no_consent_error_outranks_attempt_channel_mismatch
        """
        built = world.build(stop_after="launch")

        response = api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.SMS,
            ),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.NO_CONSENT_ON_RECORD)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=0, attempt_budget_remaining=3)
        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(campaign, permitted_attempt_count=0)


class TestOutcomeAdmissionRules:
    """The admission rule attached to each recordable disposition."""

    def test_06_abandonment_without_the_recorded_message_is_refused(
        self, world, dialer_operator_headers, api
    ):
        """An abandonment claimed without the mandatory recorded message leaves the
        attempt pending and moves no campaign counter.

        PRD: `PENDING → ABANDONED` requires `abandon_message_played` to be true, because
        the recorded abandonment message is mandatory; an abandonment recorded without it
        is refused with `ERR_ABANDON_MESSAGE_REQUIRED`.

        Design: Corner/validations/abandoned_outcome_without_the_recorded_message_rejected
        """
        built = world.build(stop_after="launch")
        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], channel=Channel.VOICE
        )

        response = api.record_attempt_outcome(
            attempt["id"],
            factories.attempt_outcome_payload(
                outcome=AttemptOutcome.ABANDONED, abandon_message_played=False
            ),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.ABANDON_MESSAGE_REQUIRED)

        reread = assert_ok(
            api.get_contact_attempt(attempt["id"], dialer_operator_headers)
        )
        assert_status(reread, AttemptOutcome.PENDING, field="outcome")
        assert_fields_null(reread, "outcome_recorded_at")

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(campaign, abandoned_count_today=0)
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 0.00)

    def test_07_live_connect_beyond_two_seconds_is_refused(
        self, world, dialer_operator_headers, api
    ):
        """A live-connect claim whose agent connect time exceeds the two-second
        abandonment threshold is refused, and no live answer is counted.

        PRD: `PENDING → CONNECTED_LIVE` requires `agent_connect_seconds` to be present
        and no greater than the two-second abandonment threshold; a live-connect claim
        above two seconds is refused with `ERR_ABANDON_CLASSIFICATION_INVALID`.

        Design: Corner/validations/connected_live_beyond_the_abandon_threshold_rejected
        """
        built = world.build(stop_after="launch")
        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], channel=Channel.VOICE
        )

        response = api.record_attempt_outcome(
            attempt["id"],
            factories.attempt_outcome_payload(
                outcome=AttemptOutcome.CONNECTED_LIVE, agent_connect_seconds=5
            ),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.ABANDON_CLASSIFICATION_INVALID)

        reread = assert_ok(
            api.get_contact_attempt(attempt["id"], dialer_operator_headers)
        )
        assert_status(reread, AttemptOutcome.PENDING, field="outcome")
        assert_fields_null(reread, "agent_connect_seconds", "outcome_recorded_at")

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(campaign, live_answer_count_today=0)

    def test_08_machine_answer_is_refused_when_detection_is_off(
        self, world, dialer_operator_headers, api
    ):
        """A machine answer cannot be asserted on a campaign whose dialer profile runs no
        answering-machine detection.

        PRD: `PENDING → MACHINE_ANSWERED` requires the campaign's dialer profile to have
        `amd_enabled` true, since a machine answer can only be asserted where
        answering-machine detection actually runs; otherwise the call is refused with
        `ERR_AMD_NOT_ENABLED`.

        Design: Corner/validations/machine_answered_rejected_when_amd_is_disabled
        """
        built = world.build(stop_after="launch", amd_enabled=False)
        assert_fields_equal(built["profile"], amd_enabled=False)
        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], channel=Channel.VOICE
        )

        response = api.record_attempt_outcome(
            attempt["id"],
            factories.attempt_outcome_payload(outcome=AttemptOutcome.MACHINE_ANSWERED),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.AMD_NOT_ENABLED)

        reread = assert_ok(
            api.get_contact_attempt(attempt["id"], dialer_operator_headers)
        )
        assert_status(reread, AttemptOutcome.PENDING, field="outcome")
        assert_fields_null(reread, "outcome_recorded_at")

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(campaign, machine_count_today=0)
        assert_decimal_equals(campaign["internal_abandonment_rate_pct"], 0.00)


class TestAbandonmentWaiverApproval:
    """Approving a dialer profile configured above the regulatory ceiling."""

    def test_09_over_ceiling_profile_cannot_be_approved_without_a_waiver(
        self, world, compliance_officer_headers, api
    ):
        """An approval that omits the waiver reference on a profile above the ceiling is
        refused, leaving the profile drafted and unapproved.

        PRD: A profile whose `requires_waiver` is true — that is, one configured above
        the 3.00 percent regulatory ceiling — may only be approved when the payload
        supplies a non-empty `waiver_reference` documenting the exception; omitting it,
        or supplying an empty string, is refused with
        `ERR_ABANDONMENT_LIMIT_WAIVER_REQUIRED`.

        Design: Corner/validations/profile_above_the_regulatory_ceiling_needs_a_waiver_reference
        """
        profile = _over_ceiling_predictive_profile(world)
        assert_fields_equal(profile, requires_waiver=True)

        response = api.approve_dialer_profile(
            profile["id"],
            factories.dialer_profile_approve_payload(),
            compliance_officer_headers,
        )
        assert_error(response, ApiErrorId.ABANDONMENT_LIMIT_WAIVER_REQUIRED)

        reread = assert_ok(
            api.get_dialer_profile(profile["id"], compliance_officer_headers)
        )
        assert_status(reread, DialerProfileStatus.DRAFT)
        assert_fields_equal(reread, requires_waiver=True)
        assert_fields_null(reread, "approved_by_user_id", "waiver_reference")

    def test_10_over_ceiling_profile_approves_once_a_waiver_is_supplied(self, world):
        """The same over-ceiling profile approves cleanly with a waiver reference, and
        the approval recomputes the pacing ceiling from a regulatory rate of zero.

        PRD: Approval moves the profile to `APPROVED`, records the approving officer's
        `X-User-ID` in `approved_by_user_id`, clears `locked_reason` back to null, stores
        the supplied `waiver_reference` (which stays null when `requires_waiver` is
        false), and recomputes `max_lines_last_computed` treating the campaign's
        regulatory abandonment rate as `0.00`, since at approval time the profile may
        have no campaign at all.

        Design: Corner/validations/profile_above_the_ceiling_approved_once_a_waiver_is_supplied
        """
        profile = _over_ceiling_predictive_profile(world)

        approved = world.approve_dialer_profile(
            profile["id"], waiver_reference=DEFAULT_WAIVER_REFERENCE
        )
        assert_status(approved, DialerProfileStatus.APPROVED)
        assert_fields_equal(
            approved,
            requires_waiver=True,
            waiver_reference=DEFAULT_WAIVER_REFERENCE,
            approved_by_user_id=OFFICER_PROFILE_APPROVER_USER_ID,
            max_lines_last_computed=7,
        )
        assert_fields_null(approved, "locked_reason")


class TestAttemptThrottles:
    """The pacing ceiling and the per-consumer frequency cap."""

    def test_11_pending_attempts_may_not_exceed_the_preview_line_ceiling(
        self, world, dialer_operator_headers, api
    ):
        """A preview profile paces at exactly its staffed agent count, so a second
        simultaneous dial to a different consumer is refused on capacity.

        PRD: Fifth and last, a profile in `PREVIEW` mode never over-dials: its line
        ceiling is simply `agents_available`, regardless of everything computed before.

        Design: Corner/validations/pending_attempts_may_not_exceed_the_preview_line_ceiling
        """
        built = world.build(
            stop_after="campaign", mode=DialerMode.PREVIEW, agents_available=1
        )
        second = world.create_second_ca_contact()
        world.number_status_check(second["id"], claimed_consent_date="2026-07-15")
        world.create_consent(
            second["id"],
            built["script"]["id"],
            channel=Channel.VOICE,
            consent_type=ConsentType.EXPRESS_WRITTEN,
            signature_evidence="evidence-c2",
        )
        world.scrub_campaign(built["campaign"]["id"])
        world.launch_campaign(built["campaign"]["id"])

        world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], channel=Channel.VOICE
        )

        response = api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=second["id"],
                channel=Channel.VOICE,
            ),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.PACING_CAPACITY_EXCEEDED)

        profile = assert_ok(
            api.get_dialer_profile(built["profile"]["id"], dialer_operator_headers)
        )
        assert_fields_equal(profile, max_lines_last_computed=1)

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(
            campaign, permitted_attempt_count=1, eligible_target_count=2
        )

        reread = world.read_contact(second["id"])
        assert_fields_equal(reread, attempts_charged=0, attempt_budget_remaining=3)

    def test_12_attempt_refused_once_the_consumer_budget_is_exhausted(
        self, world, dialer_operator_headers, api
    ):
        """With the cooldown already elapsed and pacing capacity to spare, a consumer
        whose budget is spent still cannot be dialled again.

        PRD: Finally the frequency cap: the consumer's `attempt_budget_remaining` must be
        at least 1, or the attempt is refused with `ERR_ATTEMPT_BUDGET_EXHAUSTED`.

        Design: Corner/validations/attempt_refused_once_the_contact_budget_is_exhausted
        """
        built = world.build(stop_after="launch", attempt_budget_total=1)
        world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], channel=Channel.VOICE
        )
        world.set_clock("2026-08-03T00:31:00Z")

        response = api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.VOICE,
            ),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.ATTEMPT_BUDGET_EXHAUSTED)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=1, attempt_budget_remaining=0)

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(campaign, permitted_attempt_count=1)

        profile = assert_ok(
            api.get_dialer_profile(built["profile"]["id"], dialer_operator_headers)
        )
        assert_fields_equal(profile, max_lines_last_computed=7)


class TestAttemptTimeGovernance:
    """The governing policy and the consent basis a marketing dial demands."""

    def test_13_attempt_refused_when_no_policy_covers_the_clock_instant(
        self, world, dialer_operator_headers, api
    ):
        """A campaign launched under a policy whose period has since elapsed loses its
        governing policy, and the dial fails before any window arithmetic happens.

        PRD: If there are no candidates, the operation is refused with
        `ERR_CALLING_WINDOW_POLICY_MISSING`.

        Design: Corner/validations/attempt_refused_when_no_policy_covers_the_clock_instant
        """
        built = world.build(
            clock="2026-07-20T17:00:00Z",
            policy_effective_from="2026-07-01T00:00:00Z",
            policy_effective_to="2026-08-01T00:00:00Z",
            stop_after="launch",
        )
        world.set_clock("2026-08-03T00:00:00Z")

        response = api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.VOICE,
            ),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.CALLING_WINDOW_POLICY_MISSING)

        policy = assert_ok(
            api.get_calling_window_policy(
                built["policy"]["id"], dialer_operator_headers
            )
        )
        assert_status(policy, PolicyStatus.ACTIVE)

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_status(campaign, CampaignStatus.ACTIVE)

        _rows, meta = assert_page(
            api.list_contact_attempts(dialer_operator_headers)
        )
        assert_total_count(meta, 0)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempt_budget_remaining=3)

    def test_14_marketing_dial_demands_express_written_consent(
        self, world, compliance_officer_headers, dialer_operator_headers, api
    ):
        """Oral consent is a live legal basis, yet it is not enough for a marketing
        campaign, so the dial is refused while the consent stays active.

        PRD: One further test then applies: when the campaign's `campaign_purpose` is
        `MARKETING`, the chosen record's `consent_type` must be `EXPRESS_WRITTEN`, and an
        attempt relying on oral consent or an established business relationship for a
        marketing campaign is refused with `ERR_NO_EXPRESS_WRITTEN_CONSENT`.

        Design: Corner/validations/marketing_attempt_requires_express_written_consent
        """
        built = world.build(
            stop_after="launch",
            consent_type=ConsentType.EXPRESS_ORAL,
            capture_method=CaptureMethod.IVR_RECORDING,
            campaign_purpose=CampaignPurpose.MARKETING,
        )

        response = api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.VOICE,
            ),
            dialer_operator_headers,
        )
        assert_error(response, ApiErrorId.NO_EXPRESS_WRITTEN_CONSENT)

        consent = assert_ok(
            api.get_consent_record(built["consent"]["id"], compliance_officer_headers)
        )
        assert_status(consent, ConsentStatus.ACTIVE)
        assert_fields_equal(consent, consent_type=ConsentType.EXPRESS_ORAL)

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(
            campaign,
            campaign_purpose=CampaignPurpose.MARKETING,
            permitted_attempt_count=0,
        )
