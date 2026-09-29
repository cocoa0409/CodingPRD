"""Recipient-local time, the effective calling window, list currency and the
abandonment measures — the arithmetic the attempt ladder and the revocation
clock are built from.

Every precondition is built through the documented endpoints against an empty
database, and every instant comes from the logical clock.
"""

from __future__ import annotations

from test_helpers import (
    STATE_CA,
    ComplianceWorld,
    ConsentType,
    CampaignPurpose,
    CaptureMethod,
    Channel,
    IntakeStatus,
    PHONE_C1,
    PropagationStatus,
    RecordingConsentRegime,
    RevocationChannelReceived,
    RevocationMethod,
    RevocationScope,
    RndResult,
    AttemptOutcome,
    CampaignStatus,
    assert_decimal_equals,
    assert_fields_equal,
    assert_ok,
    assert_status,
    assert_timestamp_equals,
)


class TestRecipientLocalTimeAndTheEffectiveWindow:
    """Recipient-local time and the five-step permitted window."""

    def test_01_local_minutes_wrap_backwards_when_the_utc_date_has_rolled_over(
        self, world: ComplianceWorld
    ):
        """A UTC-420 consumer dialled at 03:50 UTC on 2026-08-04 is at 20:50 on
        their own previous local day, and the attempt is admitted.

        PRD 3.8: "add the consumer's `utc_offset_minutes`, and reduce the sum
        modulo 1440 minutes per day"
        PRD 3.8: "That value is recorded on the attempt as
        `recipient_local_minutes`, and its zero-padded `HH:MM` rendering is
        recorded as `recipient_local_time`."
        PRD 3.8: "`cooldown_until` set to 30 minutes after the current clock
        instant"

        Design: Corner/calculations/recipient_local_minutes_wraps_backwards_across_utc_midnight
        """
        built = world.build(clock="2026-08-04T03:50:00Z")

        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], Channel.VOICE
        )

        assert attempt["recipient_local_minutes"] == 1250, (
            "230 UTC minutes plus a -420 offset must wrap to 1250, got %s"
            % (attempt.get("recipient_local_minutes"),)
        )
        assert_fields_equal(
            attempt,
            recipient_local_time="20:50",
            effective_window_start_minutes=480,
            effective_window_end_minutes=1260,
            outcome=AttemptOutcome.PENDING,
        )
        assert_timestamp_equals(
            attempt["cooldown_until"], "2026-08-04T04:20:00.000Z"
        )

    def test_02_express_written_voice_attempt_uses_the_policy_bounds_unchanged(
        self, world: ComplianceWorld
    ):
        """With express written consent on the voice channel neither adjustment
        applies, so the effective window is exactly the policy's 480 to 1260.

        PRD 3.5: "the server derives `window_start_minutes` and
        `window_end_minutes` by parsing the two `HH:MM` inputs into minutes
        after local midnight"
        PRD 3.8: "when the selected consent record's `consent_type` is anything
        other than `EXPRESS_WRITTEN`, a consent extension of 60 minutes applies,
        and when it is `EXPRESS_WRITTEN` the extension is zero."
        PRD 3.8: "when the attempt's `channel` is `SMS` a channel shift of 30
        minutes applies, and for `VOICE` it is zero."
        PRD 3.8: "A recipient-local time exactly at the start is inside the
        window; a recipient-local time exactly at the end is outside it."

        Design: Corner/calculations/express_written_voice_window_equals_the_policy_bounds
        """
        built = world.build(
            clock="2026-08-03T15:00:00Z",
            consent_type=ConsentType.EXPRESS_WRITTEN,
            capture_method=CaptureMethod.WEB_FORM,
            window_start_local="08:00",
            window_end_local="21:00",
        )

        policy = assert_ok(
            world.api.get_calling_window_policy(built["policy"]["id"], world.admin)
        )
        assert_fields_equal(policy, window_start_minutes=480, window_end_minutes=1260)

        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], Channel.VOICE
        )

        assert_fields_equal(
            attempt,
            effective_window_start_minutes=480,
            effective_window_end_minutes=1260,
            recipient_local_minutes=480,
            outcome=AttemptOutcome.PENDING,
        )

    def test_03_governing_policy_selection_ignores_a_period_that_has_ended(
        self, world: ComplianceWorld
    ):
        """A CA policy whose period ended on 2026-07-01 is not a candidate, so
        the attempt is authorised under its exactly-adjacent successor.

        PRD 3.5: "The candidates are the policies whose `state_code` equals the
        relevant state, whose `status` is `ACTIVE`, and whose effective period
        contains the current clock instant on a half-open basis"
        PRD 3.5: "Otherwise the candidates are ordered by `effective_from`
        descending with ties broken by `created_at` ascending, and the first is
        chosen; an attempt records it as `calling_window_policy_id`."

        Design: Corner/calculations/policy_selector_ignores_policies_whose_period_has_ended
        """
        world.set_clock("2026-08-03T00:00:00Z")
        ended_policy = world.create_policy(
            state_code=STATE_CA,
            window_start_local="09:00",
            window_end_local="20:00",
            recording_consent_regime=RecordingConsentRegime.ONE_PARTY,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-07-01T00:00:00Z",
        )

        built = world.build(
            clock="2026-08-03T00:00:00Z",
            policy_effective_from="2026-07-01T00:00:00Z",
            policy_effective_to="2027-01-01T00:00:00Z",
            window_start_local="08:00",
            window_end_local="21:00",
        )
        current_policy = built["policy"]

        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], Channel.VOICE
        )

        assert attempt["calling_window_policy_id"] == current_policy["id"], (
            "the in-period policy must be pinned, got %s"
            % (attempt.get("calling_window_policy_id"),)
        )
        assert attempt["calling_window_policy_id"] != ended_policy["id"], (
            "the policy whose period ended must never be selected"
        )
        assert attempt["effective_window_start_minutes"] == 480, (
            "the successor policy's 08:00 start must govern, got %s"
            % (attempt.get("effective_window_start_minutes"),)
        )

        ended_read = assert_ok(
            world.api.get_calling_window_policy(ended_policy["id"], world.admin)
        )
        assert_status(ended_read, "ACTIVE")

    def test_04_consent_basis_is_the_active_record_matching_the_attempt_channel(
        self, world: ComplianceWorld
    ):
        """With an older voice consent and a newer text consent on file, a voice
        attempt pins the voice record and ignores the newer text one.

        PRD 3.2: "The candidates are the consent records of that consumer whose
        `channel` equals the requested channel and whose `status` is `ACTIVE`;
        suspended, revoked and superseded rows are invisible to this selection
        even when they are the newest rows for the channel."
        PRD 3.2: "Otherwise the candidates are ordered by `captured_at`
        descending, ties broken by `created_at` ascending, and the first one is
        chosen and recorded on the attempt as `consent_record_id`."

        Design: Corner/calculations/consent_basis_selector_picks_the_record_matching_the_attempt_channel
        """
        built = world.build(
            clock="2026-08-03T00:00:00Z",
            channel=Channel.VOICE,
            campaign_purpose=CampaignPurpose.MARKETING,
            consent_type=ConsentType.EXPRESS_WRITTEN,
        )
        voice_consent = built["consent"]

        sms_script = world.approved_script(
            name="CA SMS Script",
            channel=Channel.SMS,
            covered_state_codes=[STATE_CA],
        )
        sms_consent = world.create_consent(
            built["contact"]["id"],
            sms_script["id"],
            channel=Channel.SMS,
            consent_type=ConsentType.EXPRESS_WRITTEN,
            capture_method=CaptureMethod.SMS_DOUBLE_OPT_IN,
            signature_evidence="evidence-c1-sms",
        )

        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], Channel.VOICE
        )

        assert attempt["consent_record_id"] == voice_consent["id"], (
            "the VOICE consent must be the selected basis, got %s"
            % (attempt.get("consent_record_id"),)
        )
        assert attempt["consent_record_id"] != sms_consent["id"], (
            "the newer SMS consent must not authorise a VOICE attempt"
        )
        assert_fields_equal(attempt, outcome=AttemptOutcome.PENDING, channel=Channel.VOICE)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, active_consent_count=2, total_consent_count=2)


class TestAbandonmentMeasurement:
    """The two abandonment measures over one measurement day."""

    def test_05_regulatory_abandonment_rate_rounds_half_up_to_two_decimals(
        self, world: ComplianceWorld
    ):
        """One abandonment among three live answers is 33.333...%, stored as
        exactly 33.33 on both measures with no machine answers on the day.

        PRD 3.8: "the campaign's `live_answer_count_today` and
        `abandoned_count_today` each increase by one"
        PRD 3.8: "`regulatory_abandonment_rate_pct` is `0.00` when
        `live_answer_count_today` is zero, and otherwise 100 multiplied by
        `abandoned_count_today`, divided by `live_answer_count_today`, rounded
        half up to two decimal places"
        PRD 3.8: "`internal_abandonment_rate_pct` is `0.00` when
        `live_answer_count_today` plus `machine_count_today` is zero, and
        otherwise 100 multiplied by `abandoned_count_today`, divided by the sum
        of `live_answer_count_today` and `machine_count_today`, rounded half up
        to two decimal places."

        Design: Corner/calculations/abandonment_rate_rounds_half_up_to_two_decimals
        """
        built = world.build(
            clock="2026-08-03T00:00:00Z",
            attempt_budget_total=6,
            abandonment_limit_pct=60.0,
        )
        campaign_id = built["campaign"]["id"]
        contact_id = built["contact"]["id"]

        world.connected_attempt(campaign_id, contact_id)

        world.set_clock("2026-08-03T00:31:00Z")
        second = world.create_attempt(campaign_id, contact_id)
        world.record_outcome(
            second["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=2,
        )

        world.set_clock("2026-08-03T01:02:00Z")
        third = world.create_attempt(campaign_id, contact_id)
        world.record_outcome(
            third["id"],
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )

        campaign = world.read_campaign(campaign_id)
        assert_fields_equal(
            campaign,
            live_answer_count_today=3,
            abandoned_count_today=1,
            machine_count_today=0,
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 33.33)
        assert_decimal_equals(campaign["internal_abandonment_rate_pct"], 33.33)
        assert_status(campaign, CampaignStatus.ACTIVE)


class TestPropagationDeadlineAndListCurrency:
    """The ten-business-day revocation clock and reassigned-number verdicts."""

    def test_06_propagation_deadline_skips_weekends_with_an_empty_holiday_list(
        self, world: ComplianceWorld
    ):
        """Ten business days from Monday 2026-08-03T14:00Z over an empty holiday
        calendar lands on Monday 2026-08-17T14:00Z, time of day preserved.

        PRD 3.3: "`propagation_deadline_at` is ten business days after
        `received_at`, counted as follows."
        PRD 3.3: "A cursor begins at `received_at` and keeps its time of day
        unchanged throughout."
        PRD 3.3: "the cursor advances by one whole day at a time, and each day
        the cursor lands on reduces the remaining count by one only if that
        day's UTC date falls Monday through Friday and is not listed in the
        governing policy's `holiday_dates`."
        PRD 3.3: "When the remaining count reaches zero, the cursor's instant is
        `propagation_deadline_at`."

        Design: Corner/calculations/propagation_deadline_skips_weekends_when_no_holiday_is_declared
        """
        world.set_clock("2026-08-03T14:00:00Z")
        world.create_ca_policy(holiday_dates=[])
        contact = world.create_ca_contact()
        script = world.approved_script()
        world.create_consent(contact["id"], script["id"], channel=Channel.VOICE)

        revocation = world.create_revocation(
            contact["id"],
            channel_received=RevocationChannelReceived.EMAIL,
            method=RevocationMethod.EMAIL_REQUEST,
            scope=RevocationScope.ALL_CHANNELS,
            received_note="Emailed opt-out",
        )

        assert_timestamp_equals(revocation["received_at"], "2026-08-03T14:00:00.000Z")
        assert_timestamp_equals(
            revocation["propagation_deadline_at"], "2026-08-17T14:00:00.000Z"
        )
        assert_fields_equal(
            revocation,
            intake_status=IntakeStatus.RECEIVED,
            propagation_status=PropagationStatus.NOT_STARTED,
        )

    def test_07_number_status_check_with_no_seeded_record_confers_safe_harbour(
        self, world: ComplianceWorld
    ):
        """A number the reassigned-number database has never heard of yields
        NO_DATA, which is the only verdict granting the safe harbour.

        PRD 3.1: "If the database holds no record for the number at all, the
        result is `NO_DATA`, and it is precisely this outcome that confers the
        statutory safe harbour: `rnd_safe_harbor_eligible` is true when and only
        when `rnd_result` is `NO_DATA`, and false for every other value."
        PRD 3.1: "The check also stamps `rnd_checked_at` with the current
        logical clock instant and stores the submitted date in
        `rnd_claimed_consent_date`"

        Design: Corner/calculations/rnd_check_with_no_seeded_record_yields_no_data_safe_harbor
        """
        world.set_clock("2026-08-03T00:00:00Z")
        contact = world.create_ca_contact()

        checked = world.number_status_check(
            contact["id"], claimed_consent_date="2026-07-15"
        )

        assert_fields_equal(
            checked,
            rnd_result=RndResult.NO_DATA,
            rnd_safe_harbor_eligible=True,
            rnd_claimed_consent_date="2026-07-15",
        )
        assert_timestamp_equals(checked["rnd_checked_at"], "2026-08-03T00:00:00.000Z")

    def test_08_number_status_check_is_no_match_when_reassignment_predates_consent(
        self, world: ComplianceWorld
    ):
        """A reassignment dated 2026-07-01 against a claimed consent date of
        2026-07-15 is irrelevant history, so the verdict is NO_MATCH without the
        safe harbour.

        PRD 3.1: "If a record exists but its `reassigned_on` date falls on or
        before the claimed date, the result is `NO_MATCH`: the reassignment
        predates the consent and is irrelevant."
        PRD 3.1: "`rnd_safe_harbor_eligible` is true when and only when
        `rnd_result` is `NO_DATA`, and false for every other value"

        Design: Corner/calculations/rnd_check_returns_no_match_when_reassignment_predates_claimed_consent
        """
        world.set_clock("2026-08-03T00:00:00Z")
        contact = world.create_ca_contact(phone_number=PHONE_C1)
        world.seed_rnd(PHONE_C1, "2026-07-01")

        checked = world.number_status_check(
            contact["id"], claimed_consent_date="2026-07-15"
        )

        assert_fields_equal(
            checked,
            rnd_result=RndResult.NO_MATCH,
            rnd_safe_harbor_eligible=False,
            rnd_claimed_consent_date="2026-07-15",
        )
