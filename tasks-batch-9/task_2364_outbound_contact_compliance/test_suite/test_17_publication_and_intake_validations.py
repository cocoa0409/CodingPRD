"""Launch-readiness, reassigned-number and recipient-local refusals.

Every test builds its own world through the documented endpoints, because the
database is empty when the test starts. The logical clock is moved explicitly;
nothing here reads wall-clock time.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    DEFAULT_CLOCK,
    PHONE_C1,
    REGULATORY_ABANDONMENT_CEILING_PCT,
    STATE_CA,
    STATE_NV,
    AgentScriptStatus,
    ApiErrorId,
    AttemptOutcome,
    CampaignPurpose,
    CampaignStatus,
    Channel,
    ComplianceWorld,
    ConsentStatus,
    ConsentType,
    DialerLockedReason,
    DialerProfileStatus,
    EmergencyStatus,
    PolicyStatus,
    RecordingConsentMode,
    RecordingConsentRegime,
    RndResult,
    ScrubJobStatus,
    SuspensionReason,
    assert_consent_census_conserved,
    assert_created,
    assert_decimal_equals,
    assert_error,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_page,
    assert_status,
    assert_timestamp_equals,
    assert_total_count,
    factories,
    make_campaign_manager_headers,
    make_officer_launcher_headers,
)


# ---------------------------------------------------------------------------
# Private setup helpers (local to this file)
# ---------------------------------------------------------------------------


def _refused_launch(world: ComplianceWorld, campaign_id: str):
    """Attempt a launch certification that is expected to be refused."""
    return world.api.launch_campaign(
        campaign_id,
        factories.campaign_launch_payload(
            expected_campaign_version=world.campaign_version(campaign_id)
        ),
        make_officer_launcher_headers(),
    )


def _scrubbed_campaign_with_a_draft_script(world: ComplianceWorld) -> Dict[str, Any]:
    """Build the whole chain but never send the pinned script to review."""
    world.set_clock(DEFAULT_CLOCK)
    policy = world.create_ca_policy()
    contact = world.create_ca_contact()
    script = world.create_script(
        name="CA VOICE Script",
        channel=Channel.VOICE,
        covered_state_codes=[STATE_CA],
    )
    contact = world.number_status_check(contact["id"], claimed_consent_date="2026-07-15")
    consent = world.create_consent(
        contact["id"],
        script["id"],
        channel=Channel.VOICE,
        consent_type=ConsentType.EXPRESS_WRITTEN,
    )
    profile = world.approved_dialer_profile()
    world.create_fresh_national_list()
    campaign = world.create_campaign(
        dialer_profile_id=profile["id"],
        agent_script_id=script["id"],
        channel=Channel.VOICE,
        campaign_purpose=CampaignPurpose.MARKETING,
        target_state_codes=[STATE_CA],
    )
    world.scrub_campaign(campaign["id"])
    return {
        "policy": policy,
        "contact": contact,
        "script": script,
        "consent": consent,
        "profile": profile,
        "campaign": world.read_campaign(campaign["id"]),
    }


def _breach_the_shared_dialer_profile(world: ComplianceWorld) -> Dict[str, Any]:
    """Run one campaign into an abandonment breach so its profile ends LOCKED.

    One live connect followed by one abandonment gives two live answers and a
    regulatory rate of 50.00 percent against a 3.00 percent ceiling.
    """
    built = world.build(
        stop_after="launch",
        abandonment_limit_pct=REGULATORY_ABANDONMENT_CEILING_PCT,
        waiver_reference=None,
    )
    first = world.create_attempt(built["campaign"]["id"], built["contact"]["id"])
    world.record_outcome(
        first["id"], outcome=AttemptOutcome.CONNECTED_LIVE, agent_connect_seconds=1
    )
    world.set_clock("2026-08-03T00:31:00Z")
    second = world.create_attempt(built["campaign"]["id"], built["contact"]["id"])
    world.record_outcome(
        second["id"], outcome=AttemptOutcome.ABANDONED, abandon_message_played=True
    )
    return built


# ---------------------------------------------------------------------------
# The reassigned-number gate
# ---------------------------------------------------------------------------


class TestReassignedNumberGate:
    """The two ordered halves of the reassigned-number gate on attempt creation."""

    def test_01_wireless_number_never_checked_is_refused_before_dialling(self, world):
        """A WIRELESS consumer with no number-status check at all cannot be dialled.

        PRD §3.8: "A check must exist and still be current — the clock strictly
        earlier than 31 days after `rnd_checked_at` — or the attempt is refused
        with `ERR_RND_CHECK_REQUIRED`; a consumer never checked at all, whose
        `rnd_result` is still `NOT_CHECKED`, fails here too."

        Design: Corner/validations/wireless_number_requires_a_reassigned_number_check
        """
        built = world.build(stop_after="launch", run_number_status_check=False)

        response = world.api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.VOICE,
            ),
            world.operator,
        )
        assert_error(response, ApiErrorId.RND_CHECK_REQUIRED)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(
            contact,
            rnd_result=RndResult.NOT_CHECKED,
            rnd_safe_harbor_eligible=False,
            attempts_charged=0,
        )
        assert_fields_null(contact, "rnd_checked_at", "rnd_claimed_consent_date")

        attempts, meta = assert_page(
            world.api.list_contact_attempts(
                world.operator, {"contact_id": built["contact"]["id"]}
            )
        )
        assert_total_count(meta, 0)
        assert attempts == [], "a refused dial must not persist an attempt row"

    def test_02_reassigned_number_is_refused_even_with_a_current_check(self, world):
        """A verdict of REASSIGNED blocks the dial although the check is current.

        PRD §3.1: "If a seeded record exists for that number and its
        `reassigned_on` date falls strictly after the submitted claimed date, the
        result is `REASSIGNED` — the number changed hands after the consent was
        supposedly given."
        PRD §3.8: "Only then is the verdict read: an `rnd_result` of `REASSIGNED`
        refuses the attempt with `ERR_REASSIGNED_NUMBER`, because a reassigned
        number may not be dialled at all, safe harbour or no safe harbour."

        Design: Corner/validations/reassigned_number_may_not_be_dialed_even_with_a_current_check
        """
        world.seed_rnd(PHONE_C1, "2026-07-15")
        built = world.build(stop_after="launch", claimed_consent_date="2026-07-01")

        response = world.api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.VOICE,
            ),
            world.operator,
        )
        assert_error(response, ApiErrorId.REASSIGNED_NUMBER)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(
            contact,
            rnd_result=RndResult.REASSIGNED,
            rnd_safe_harbor_eligible=False,
            rnd_claimed_consent_date="2026-07-01",
            attempts_charged=0,
        )


# ---------------------------------------------------------------------------
# Recording-consent adequacy, state coverage and script approval at launch
# ---------------------------------------------------------------------------


class TestScriptAdequacyAtLaunchCertification:
    """The script-facing refusals a launch certification can raise."""

    def test_03_all_party_state_requires_an_all_party_recording_script(self, world):
        """An ALL_PARTY state paired with a ONE_PARTY script cannot be certified.

        PRD §3.7: "Where any of those policies has an `ALL_PARTY`
        `recording_consent_regime`, the pinned script's `recording_consent_mode`
        must also be `ALL_PARTY`, or the launch is refused with
        `ERR_RECORDING_CONSENT_DISCLOSURE_MISSING`."

        Design: Corner/validations/all_party_state_requires_an_all_party_recording_script
        """
        built = world.build(
            stop_after="scrub",
            recording_consent_regime=RecordingConsentRegime.ALL_PARTY,
            recording_consent_mode=RecordingConsentMode.ONE_PARTY,
        )

        assert_error(
            _refused_launch(world, built["campaign"]["id"]),
            ApiErrorId.RECORDING_CONSENT_DISCLOSURE_MISSING,
        )

        policy = assert_ok(
            world.api.get_calling_window_policy(built["policy"]["id"], world.admin)
        )
        assert_fields_equal(
            policy, recording_consent_regime=RecordingConsentRegime.ALL_PARTY
        )
        script = assert_ok(
            world.api.get_agent_script(built["script"]["id"], world.manager)
        )
        assert_fields_equal(
            script, recording_consent_mode=RecordingConsentMode.ONE_PARTY
        )

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_status(campaign, CampaignStatus.PENDING_LAUNCH)
        assert_fields_null(
            campaign, "launch_certified_by_user_id", "pinned_script_version"
        )

    def test_04_launch_requires_the_script_to_cover_every_targeted_state(self, world):
        """A script cleared only for NV cannot certify a campaign targeting CA.

        PRD §3.7: "The pinned script's `covered_state_codes` must include every
        one of the campaign's target states, or the launch is refused with
        `ERR_SCRIPT_STATE_NOT_COVERED`."

        Design: Corner/validations/launch_requires_the_script_to_cover_every_targeted_state
        """
        built = world.build(stop_after="scrub", covered_state_codes=[STATE_NV])
        version_before = world.campaign_version(built["campaign"]["id"])

        assert_error(
            _refused_launch(world, built["campaign"]["id"]),
            ApiErrorId.SCRIPT_STATE_NOT_COVERED,
        )

        script = assert_ok(
            world.api.get_agent_script(built["script"]["id"], world.manager)
        )
        assert_status(script, AgentScriptStatus.APPROVED)
        assert_fields_equal(script, covered_state_codes=[STATE_NV])

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_status(campaign, CampaignStatus.PENDING_LAUNCH)
        assert campaign["version"] == version_before, (
            "a refused certification must not mutate the campaign: %s -> %s"
            % (version_before, campaign["version"])
        )

    def test_05_launch_requires_an_approved_script(self, world):
        """A scrub promotes the campaign, so a DRAFT script is caught at launch.

        PRD §3.7: "The script must be `APPROVED` — a `DRAFT` or `IN_REVIEW`
        script yields `ERR_SCRIPT_NOT_APPROVED` — and its channel must still
        match."

        Design: Corner/validations/launch_requires_an_approved_script
        """
        built = _scrubbed_campaign_with_a_draft_script(world)
        assert_status(built["campaign"], CampaignStatus.PENDING_LAUNCH)

        assert_error(
            _refused_launch(world, built["campaign"]["id"]),
            ApiErrorId.SCRIPT_NOT_APPROVED,
        )

        script = assert_ok(
            world.api.get_agent_script(built["script"]["id"], world.manager)
        )
        assert_status(script, AgentScriptStatus.DRAFT)
        assert_fields_null(script, "approved_by_user_id", "approved_at")

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_status(campaign, CampaignStatus.PENDING_LAUNCH)
        assert_fields_null(campaign, "pinned_script_version")


class TestScriptChannelPairing:
    """A campaign may only ever pin a script written for its own channel."""

    def test_06_campaign_create_rejected_when_the_script_channel_differs(self, world):
        """A VOICE campaign cannot be persisted pointing at an SMS script.

        PRD §3.7: "The pinned script's `channel` must equal the campaign's
        `channel`, at creation and again at launch; a mismatch is refused with
        `ERR_SCRIPT_CHANNEL_MISMATCH`."

        Design: Corner/validations/campaign_create_rejected_when_the_script_channel_differs
        """
        world.set_clock(DEFAULT_CLOCK)
        world.create_ca_policy()
        script = world.approved_script(
            name="CA SMS Script", channel=Channel.SMS, covered_state_codes=[STATE_CA]
        )
        profile = world.approved_dialer_profile()

        response = world.api.create_campaign(
            factories.campaign_payload(
                dialer_profile_id=profile["id"],
                agent_script_id=script["id"],
                name="CA Aug Outreach",
                channel=Channel.VOICE,
                campaign_purpose=CampaignPurpose.MARKETING,
                target_state_codes=[STATE_CA],
            ),
            make_campaign_manager_headers(),
        )
        assert_error(response, ApiErrorId.SCRIPT_CHANNEL_MISMATCH)

        stored_script = assert_ok(
            world.api.get_agent_script(script["id"], world.manager)
        )
        assert_fields_equal(stored_script, channel=Channel.SMS)
        assert_status(stored_script, AgentScriptStatus.APPROVED)

        campaigns, meta = assert_page(world.api.list_campaigns(world.manager))
        assert_total_count(meta, 0)
        assert campaigns == [], "the refused create must not persist a campaign"


# ---------------------------------------------------------------------------
# A locked dialer profile: launch refusal and resume refusal
# ---------------------------------------------------------------------------


class TestLockedDialerProfile:
    """A profile locked by one campaign's breach constrains every campaign on it."""

    def test_07_launch_refused_while_the_profile_is_locked_by_a_sibling_breach(
        self, world
    ):
        """A second campaign on a LOCKED profile cannot be certified.

        PRD §3.8: "The dialer profile it points at then moves `APPROVED →
        LOCKED` with `locked_reason` `ABANDONMENT_BREACH` and its own `version`
        increments."
        PRD §3.7: "The pinned dialer profile must have been approved at least
        once, meaning its status is no longer `DRAFT`; a still-`DRAFT` profile
        yields `ERR_DIALER_PROFILE_NOT_APPROVED`, while a profile sitting in
        `LOCKED` yields `ERR_DIALER_PROFILE_LOCKED`."

        Design: Corner/validations/launch_refused_while_the_profile_is_locked_by_a_sibling_breach
        """
        built = _breach_the_shared_dialer_profile(world)

        sibling = world.create_campaign(
            dialer_profile_id=built["profile"]["id"],
            agent_script_id=built["script"]["id"],
            name="CA Aug Overflow",
            channel=Channel.VOICE,
            campaign_purpose=CampaignPurpose.MARKETING,
            target_state_codes=[STATE_CA],
        )
        world.scrub_campaign(sibling["id"])
        assert_status(world.read_campaign(sibling["id"]), CampaignStatus.PENDING_LAUNCH)

        assert_error(
            _refused_launch(world, sibling["id"]), ApiErrorId.DIALER_PROFILE_LOCKED
        )

        profile = assert_ok(
            world.api.get_dialer_profile(built["profile"]["id"], world.operator)
        )
        assert_status(profile, DialerProfileStatus.LOCKED)
        assert_fields_equal(profile, locked_reason=DialerLockedReason.ABANDONMENT_BREACH)

        breached = world.read_campaign(built["campaign"]["id"])
        assert_status(breached, CampaignStatus.SUSPENDED)
        assert_fields_equal(
            breached, suspension_reason=SuspensionReason.ABANDONMENT_BREACH
        )

        refused = world.read_campaign(sibling["id"])
        assert_status(refused, CampaignStatus.PENDING_LAUNCH)
        assert_fields_null(refused, "launch_certified_by_user_id")

    def test_08_resume_refused_while_the_locked_profile_has_not_been_re_approved(
        self, world
    ):
        """A breach-suspended campaign cannot resume while its profile is LOCKED.

        PRD §3.7: "A campaign suspended for `PROFILE_LOCKED` or for
        `ABANDONMENT_BREACH` may resume only once its dialer profile is back in
        `APPROVED`."
        PRD §3.7: "Where the applicable guard still fails, resumption is refused
        with `ERR_RESUME_BLOCKED`; where it holds, `suspension_reason` is cleared
        back to null and the campaign's `version` increments."

        Design: Corner/validations/resume_refused_while_the_locked_profile_has_not_been_re_approved
        """
        built = _breach_the_shared_dialer_profile(world)

        response = world.api.resume_campaign(
            built["campaign"]["id"],
            factories.campaign_resume_payload(resume_note="Pacing retuned"),
            world.officer,
        )
        assert_error(response, ApiErrorId.RESUME_BLOCKED)

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_status(campaign, CampaignStatus.SUSPENDED)
        assert_fields_equal(
            campaign,
            suspension_reason=SuspensionReason.ABANDONMENT_BREACH,
            measurement_date="2026-08-03",
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)

        profile = assert_ok(
            world.api.get_dialer_profile(built["profile"]["id"], world.operator)
        )
        assert_status(profile, DialerProfileStatus.LOCKED)


# ---------------------------------------------------------------------------
# Scrub currency and emergency restrictions at launch
# ---------------------------------------------------------------------------


class TestScrubCurrencyAndEmergencyAtLaunch:
    """Two launch refusals that turn on the state of another row entirely."""

    def test_09_launch_refused_when_the_newest_scrub_is_still_pending(self, world):
        """Queueing a fresh scrub makes an already-promoted campaign unlaunchable.

        PRD §3.4: "A campaign's `latest_scrub_status` always reflects the newest
        job of that campaign ordered by `requested_at` descending with ties
        broken by `created_at` ascending, and takes one of `PENDING`,
        `COMPLETED`, `FAILED`, `SUPERSEDED` or `INVALIDATED`."
        PRD §3.7: "The campaign's newest scrub job must be in `COMPLETED` — a
        newest job that is `PENDING`, `FAILED`, `SUPERSEDED` or `INVALIDATED`
        yields `ERR_SCRUB_NOT_CURRENT` — and the campaign's
        `eligible_target_count` must be at least 1, since a campaign whose every
        target was suppressed has nobody to call and yields
        `ERR_EMPTY_TARGET_SET`."

        Design: Corner/validations/launch_refused_when_the_newest_scrub_is_still_pending
        """
        built = world.build(stop_after="scrub")
        completed_job = built["scrub_job"]
        pending_job = world.create_scrub_job(built["campaign"]["id"])

        assert_error(
            _refused_launch(world, built["campaign"]["id"]),
            ApiErrorId.SCRUB_NOT_CURRENT,
        )

        first = assert_ok(world.api.get_scrub_job(completed_job["id"], world.manager))
        assert_status(first, ScrubJobStatus.COMPLETED)
        second = assert_ok(world.api.get_scrub_job(pending_job["id"], world.manager))
        assert_status(second, ScrubJobStatus.PENDING)

        assert_status(
            world.read_campaign(built["campaign"]["id"]), CampaignStatus.PENDING_LAUNCH
        )

        _, meta = assert_page(
            world.api.list_campaign_scrub_jobs(built["campaign"]["id"], world.manager)
        )
        assert_total_count(meta, 2)

    def test_10_launch_refused_while_an_emergency_covers_a_targeted_state(self, world):
        """A declared emergency blocks certification without suspending the draft.

        PRD §3.7: "No targeted state's policy may have `emergency_status`
        `ACTIVE`, or the launch is refused with `ERR_EMERGENCY_RESTRICTION`."
        PRD §3.7: "In `DRAFT`, `PENDING_LAUNCH`, `ACTIVE` and `CLOSED`,
        `suspension_reason` is null."

        Design: Corner/validations/launch_refused_while_an_emergency_covers_a_targeted_state
        """
        built = world.build(stop_after="scrub")
        assert_ok(
            world.api.declare_policy_emergency(
                built["policy"]["id"],
                factories.declare_emergency_payload(
                    emergency_note="Statewide wildfire evacuation"
                ),
                world.admin,
            )
        )

        assert_error(
            _refused_launch(world, built["campaign"]["id"]),
            ApiErrorId.EMERGENCY_RESTRICTION,
        )

        policy = assert_ok(
            world.api.get_calling_window_policy(built["policy"]["id"], world.admin)
        )
        assert_status(policy, PolicyStatus.ACTIVE)
        assert_fields_equal(policy, emergency_status=EmergencyStatus.ACTIVE)

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_status(campaign, CampaignStatus.PENDING_LAUNCH)
        assert_fields_null(campaign, "suspension_reason")


# ---------------------------------------------------------------------------
# Recipient-local temporal guards
# ---------------------------------------------------------------------------


class TestRecipientLocalTemporalGuards:
    """The holiday test is read in the recipient's own local calendar."""

    def test_11_attempt_refused_on_a_recipient_local_holiday(self, world):
        """A holiday blocks a dial that would otherwise fall inside the window.

        PRD §3.8: "The recipient's local calendar date is the date reached by
        adding `utc_offset_minutes` to the current clock instant, which may well
        differ from the UTC date."
        PRD §3.8: "If that local date appears in the governing policy's
        `holiday_dates`, the attempt is refused with `ERR_HOLIDAY_RESTRICTION`."

        Design: Corner/validations/attempt_refused_on_a_recipient_local_holiday
        """
        built = world.build(
            clock="2026-08-03T17:00:00Z",
            holiday_dates=["2026-08-03"],
            stop_after="launch",
        )

        response = world.api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.VOICE,
            ),
            world.operator,
        )
        assert_error(response, ApiErrorId.HOLIDAY_RESTRICTION)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=0, attempt_budget_remaining=3)

        _, meta = assert_page(
            world.api.list_contact_attempts(
                world.operator, {"campaign_id": built["campaign"]["id"]}
            )
        )
        assert_total_count(meta, 0)

        assert_status(
            world.read_campaign(built["campaign"]["id"]), CampaignStatus.ACTIVE
        )


# ---------------------------------------------------------------------------
# One live consent per channel
# ---------------------------------------------------------------------------


class TestConsentChannelUniqueness:
    """Reinstatement is guarded by the one-live-consent-per-channel rule."""

    def test_12_reinstate_refused_when_a_newer_active_consent_holds_the_channel(
        self, clocked_world
    ):
        """A suspended record cannot come back while a newer record holds the channel.

        PRD §3.2: "Because a consumer may hold at most one live consent per
        channel, reinstatement is refused with `ERR_CONSENT_CHANNEL_CONFLICT`
        when another `ACTIVE` record already covers the same contact-and-channel
        pair."
        PRD §2.10: "For any contact, `total_consent_count` always equals the sum
        of `active_consent_count`, `suspended_consent_count`,
        `revoked_consent_count` and `superseded_consent_count`."

        Design: Corner/validations/reinstate_refused_when_a_newer_active_consent_holds_the_channel
        """
        world = clocked_world
        contact = world.create_ca_contact()
        script = world.approved_script(
            name="CA VOICE Script", channel=Channel.VOICE, covered_state_codes=[STATE_CA]
        )
        first = world.create_consent(
            contact["id"],
            script["id"],
            channel=Channel.VOICE,
            consent_type=ConsentType.EXPRESS_WRITTEN,
        )
        world.suspend_consent(first["id"], reason="Evidence handle under audit")
        second = world.create_consent(
            contact["id"],
            script["id"],
            channel=Channel.VOICE,
            consent_type=ConsentType.EXPRESS_WRITTEN,
            signature_evidence="evidence-c1-b",
        )

        response = world.api.reinstate_consent_record(
            first["id"],
            factories.consent_reinstate_payload(
                reinstatement_note="Audit cleared the original signature"
            ),
            world.officer,
        )
        assert_error(response, ApiErrorId.CONSENT_CHANNEL_CONFLICT)

        stored_first = assert_ok(
            world.api.get_consent_record(first["id"], world.officer)
        )
        assert_status(stored_first, ConsentStatus.SUSPENDED)
        assert_fields_equal(
            stored_first,
            suspended_reason="Evidence handle under audit",
            reinstatement_count=0,
        )
        stored_second = assert_ok(
            world.api.get_consent_record(second["id"], world.officer)
        )
        assert_status(stored_second, ConsentStatus.ACTIVE)

        refreshed = world.read_contact(contact["id"])
        assert_fields_equal(
            refreshed,
            active_consent_count=1,
            suspended_consent_count=1,
            revoked_consent_count=0,
            superseded_consent_count=0,
            total_consent_count=2,
        )
        assert_consent_census_conserved(refreshed)


# ---------------------------------------------------------------------------
# The satisfied dial
# ---------------------------------------------------------------------------


class TestAdmittedAttempt:
    """What a dial that clears every gate actually writes."""

    def test_13_attempt_admitted_when_every_guard_is_satisfied(self, world):
        """A satisfied dial lands PENDING, charges one unit and arms the cooldown.

        PRD §3.8: "An accepted attempt is created with `requested_at` stamped at
        the current clock instant and `outcome` `PENDING`."
        PRD §3.8: "It records the `consent_record_id` and
        `calling_window_policy_id` the server selected, the four window and
        local-time fields already described, `cooldown_until` set to 30 minutes
        after the current clock instant — the closed interval from `requested_at`
        through `cooldown_until` is what blocks the next attempt to this consumer
        — and `max_lines_snapshot`, the line ceiling as computed from state
        persisted before this attempt."
        PRD §3.8: "The consumer's `attempts_charged` increases by one,
        `attempt_budget_remaining` decreases by one and the contact's `version`
        increments; the campaign's `permitted_attempt_count` increases by one."

        Design: Corner/validations/attempt_admitted_when_every_guard_is_satisfied
        """
        built = world.build(stop_after="launch")

        attempt = assert_created(
            world.api.create_contact_attempt(
                factories.contact_attempt_payload(
                    campaign_id=built["campaign"]["id"],
                    contact_id=built["contact"]["id"],
                    channel=Channel.VOICE,
                ),
                world.operator,
            )
        )

        assert_fields_equal(
            attempt,
            outcome=AttemptOutcome.PENDING,
            consent_record_id=built["consent"]["id"],
            calling_window_policy_id=built["policy"]["id"],
        )
        assert_fields_null(attempt, "voided_at", "void_reason")
        assert_timestamp_equals(attempt["requested_at"], "2026-08-03T00:00:00.000Z")
        assert_timestamp_equals(attempt["cooldown_until"], "2026-08-03T00:30:00.000Z")

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=1, attempt_budget_remaining=2)

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(campaign, permitted_attempt_count=1, voided_attempt_count=0)
        assert_status(campaign, CampaignStatus.ACTIVE)
