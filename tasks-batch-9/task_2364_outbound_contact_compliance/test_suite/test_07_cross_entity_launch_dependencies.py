"""Dependencies that reach across resource families.

Each behaviour here is asserted twice: once while the row the operation depends
on is in the wrong state, and once after that other row has been moved into the
state the contract requires.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    AttemptOutcome,
    CampaignPurpose,
    CampaignStatus,
    Channel,
    ComplianceWorld,
    ConsentStatus,
    ConsentType,
    DEFAULT_WAIVER_REFERENCE,
    DialerMode,
    DialerProfileStatus,
    ListType,
    OFFICER_LAUNCHER_USER_ID,
    STATE_CA,
    ScrubFailureReason,
    ScrubJobStatus,
    assert_attempt_budget_conserved,
    assert_consent_census_conserved,
    assert_error,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_status,
    factories,
)

# The canonical working instant: a Monday inside the published CA period.
_WORKDAY_CLOCK = "2026-08-03T00:00:00Z"

# One national row refreshed 49 days before the working instant, and one
# refreshed the day before it.
_STALE_REFRESH = "2026-06-15T00:00:00Z"
_FRESH_REFRESH = "2026-08-02T00:00:00Z"
_SECOND_NATIONAL_NUMBER = "+18005550001"


def _instant(value: str) -> datetime:
    """Parse a UTC timestamp so two instants compare independently of formatting."""
    assert isinstance(value, str) and value, (
        "expected an ISO 8601 timestamp, got %r" % (value,)
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant_equals(actual: str, expected: str) -> None:
    """A derived timestamp lands on exactly the expected instant."""
    assert _instant(actual) == _instant(expected), "expected %s, got %s" % (
        expected,
        actual,
    )


def _campaign_awaiting_certification_with_draft_profile(
    world: ComplianceWorld,
) -> Dict[str, Any]:
    """Build the whole launch chain but leave the pinned dialer profile in DRAFT.

    The campaign ends up awaiting certification with a completed scrub and one
    eligible target, so the only outstanding launch precondition is the state of
    the dialer profile it points at.
    """
    world.set_clock(_WORKDAY_CLOCK)
    policy = world.create_ca_policy()
    contact = world.create_ca_contact(attempt_budget_total=3)
    script = world.approved_script(
        name="CA VOICE Script", channel=Channel.VOICE, covered_state_codes=[STATE_CA]
    )
    contact = world.number_status_check(
        contact["id"], claimed_consent_date="2026-07-15"
    )
    consent = world.create_consent(
        contact["id"],
        script["id"],
        channel=Channel.VOICE,
        consent_type=ConsentType.EXPRESS_WRITTEN,
    )
    national_entry = world.create_fresh_national_list()
    profile = world.create_dialer_profile(
        mode=DialerMode.PREDICTIVE,
        agents_available=5,
        abandonment_limit_pct=50.0,
        amd_enabled=True,
        amd_abandon_on_machine=False,
        abandon_message_seconds=2,
    )
    campaign = world.create_campaign(
        dialer_profile_id=profile["id"],
        agent_script_id=script["id"],
        name="CA Aug Outreach",
        channel=Channel.VOICE,
        campaign_purpose=CampaignPurpose.MARKETING,
        target_state_codes=[STATE_CA],
    )
    world.scrub_campaign(
        campaign["id"], list_types=[ListType.NATIONAL, ListType.INTERNAL]
    )
    return {
        "policy": policy,
        "contact": contact,
        "script": script,
        "consent": consent,
        "national_entry": national_entry,
        "profile": profile,
        "campaign": world.read_campaign(campaign["id"]),
    }


class TestLaunchDependsOnDialerProfileApproval:
    """Certification of a campaign turns on the state of the profile it pins."""

    def test_01_launch_refused_while_pinned_dialer_profile_is_still_draft(
        self, world: ComplianceWorld
    ):
        """A scrubbed campaign cannot be certified while its dialer profile is a draft.

        PRD §3.7: "The pinned dialer profile must have been approved at least once, meaning its
        status is no longer `DRAFT`; a still-`DRAFT` profile yields `ERR_DIALER_PROFILE_NOT_APPROVED`,
        while a profile sitting in `LOCKED` yields `ERR_DIALER_PROFILE_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/campaign_launch_blocked_until_dialer_profile_approved
        """
        built = _campaign_awaiting_certification_with_draft_profile(world)
        campaign = built["campaign"]
        assert_status(campaign, CampaignStatus.PENDING_LAUNCH)
        profile = assert_ok(
            world.api.get_dialer_profile(built["profile"]["id"], world.officer)
        )
        assert_status(profile, DialerProfileStatus.DRAFT)

        response = world.api.launch_campaign(
            campaign["id"],
            factories.campaign_launch_payload(
                expected_campaign_version=campaign["version"]
            ),
            world.launcher,
        )
        assert_error(response, ApiErrorId.DIALER_PROFILE_NOT_APPROVED)

        after = world.read_campaign(campaign["id"])
        assert_status(after, CampaignStatus.PENDING_LAUNCH)
        assert after["version"] == campaign["version"], (
            "a refused certification must not mutate the campaign: version moved from %s to %s"
            % (campaign["version"], after["version"])
        )
        assert_fields_null(after, "launch_certified_by_user_id", "pinned_script_version")

    def test_02_launch_succeeds_once_the_dialer_profile_has_been_approved(
        self, world: ComplianceWorld
    ):
        """Approving the pinned profile is the only change the blocked launch needed.

        PRD §3.6: "Approval moves the profile to `APPROVED`, records the approving officer's
        `X-User-ID` in `approved_by_user_id`, clears `locked_reason` back to null, stores the
        supplied `waiver_reference` (which stays null when `requires_waiver` is false), and
        recomputes `max_lines_last_computed` treating the campaign's regulatory abandonment rate
        as `0.00`, since at approval time the profile may have no campaign at all."
        PRD §3.7: "A campaign that survives all of that moves `PENDING_LAUNCH → ACTIVE`. Its
        `launch_certified_by_user_id` records the certifying officer's `X-User-ID`. Its
        `pinned_script_version` captures the script's `version` at this instant, and it is a genuine
        pin: later edits to that script never change the number recorded here."

        Design: Difficulty/cross_entity_state_dependency/campaign_launch_blocked_until_dialer_profile_approved
        """
        built = _campaign_awaiting_certification_with_draft_profile(world)
        campaign = built["campaign"]

        profile = world.approve_dialer_profile(
            built["profile"]["id"], DEFAULT_WAIVER_REFERENCE
        )
        assert_status(profile, DialerProfileStatus.APPROVED)
        assert_fields_equal(
            profile,
            waiver_reference=DEFAULT_WAIVER_REFERENCE,
            max_lines_last_computed=7,
        )

        launched = world.launch_campaign(campaign["id"])
        assert_status(launched, CampaignStatus.ACTIVE)
        assert_fields_equal(
            launched,
            launch_certified_by_user_id=OFFICER_LAUNCHER_USER_ID,
            pinned_script_version=3,
        )


class TestAttemptDependsOnConsentRecordStatus:
    """An attempt needs a live consent row of its own channel, not merely a row."""

    def test_03_attempt_refused_while_the_only_voice_consent_is_suspended(
        self, world: ComplianceWorld, active_campaign: Dict[str, Any]
    ):
        """Suspending the contact's only VOICE consent leaves the dialer with no basis.

        PRD §3.2: "The candidates are the consent records of that consumer whose `channel` equals
        the requested channel and whose `status` is `ACTIVE`; suspended, revoked and superseded rows
        are invisible to this selection even when they are the newest rows for the channel."
        PRD §3.2: "If there are no candidates the attempt is refused with `ERR_NO_CONSENT_ON_RECORD`."

        Design: Difficulty/cross_entity_state_dependency/attempt_blocked_while_consent_record_suspended
        """
        consent = world.suspend_consent(
            active_campaign["consent"]["id"], reason="Signature evidence under review"
        )
        assert_status(consent, ConsentStatus.SUSPENDED)

        response = world.api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=active_campaign["campaign"]["id"],
                contact_id=active_campaign["contact"]["id"],
                channel=Channel.VOICE,
            ),
            world.operator,
        )
        assert_error(response, ApiErrorId.NO_CONSENT_ON_RECORD)

        contact = world.read_contact(active_campaign["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=0)
        assert_attempt_budget_conserved(contact)

    def test_04_attempt_succeeds_once_the_suspended_consent_is_reinstated(
        self, world: ComplianceWorld, active_campaign: Dict[str, Any]
    ):
        """Reinstating that same row restores the basis and it is named on the attempt.

        PRD §3.2: "Reinstatement is the compensating move, and it serves both `SUSPENDED → ACTIVE`
        and `REVOKED → ACTIVE`."
        PRD §3.2: "Otherwise the candidates are ordered by `captured_at` descending, ties broken by
        `created_at` ascending, and the first one is chosen and recorded on the attempt as
        `consent_record_id`."

        Design: Difficulty/cross_entity_state_dependency/attempt_blocked_while_consent_record_suspended
        """
        consent_id = active_campaign["consent"]["id"]
        world.suspend_consent(consent_id, reason="Signature evidence under review")

        reinstated = world.reinstate_consent(
            consent_id, reinstatement_note="Signature verified"
        )
        assert_status(reinstated, ConsentStatus.ACTIVE)
        assert_fields_equal(reinstated, reinstatement_count=1)
        assert_fields_null(reinstated, "suspended_reason")

        contact = world.read_contact(active_campaign["contact"]["id"])
        assert_fields_equal(
            contact,
            active_consent_count=1,
            suspended_consent_count=0,
            total_consent_count=1,
        )
        assert_consent_census_conserved(contact)

        attempt = world.create_attempt(
            active_campaign["campaign"]["id"], active_campaign["contact"]["id"]
        )
        assert_fields_equal(
            attempt,
            outcome=AttemptOutcome.PENDING,
            consent_record_id=consent_id,
        )

        contact = world.read_contact(active_campaign["contact"]["id"])
        assert_fields_equal(
            contact, attempts_charged=1, attempt_budget_remaining=2
        )
        assert_attempt_budget_conserved(contact)


class TestScrubCompletionDependsOnSuppressionListCurrency:
    """A scrub either completes or fails purely on the freshness of the lists."""

    def test_05_scrub_fails_while_the_only_national_row_is_stale(
        self, world: ComplianceWorld
    ):
        """A national list whose newest refresh is 49 days old cannot support a scrub.

        PRD §3.4: "The currency test covers the two external list families only: for each of
        `NATIONAL` and `STATE` that this job requested, at least one `ACTIVE` suppression entry must
        exist whose `source_refreshed_at` is at or after 31 days before the current clock instant,
        and for `STATE` that entry must additionally carry a `state_code` that appears in the
        campaign's `target_state_codes`."
        PRD §3.4: "When any requested external list fails that test, the job moves
        `PENDING → FAILED`: `failure_reason` is set to `STALE_OR_EMPTY_LIST`, `completed_at` and
        `expires_at` stay null, the campaign's `latest_scrub_status` becomes `FAILED`, the campaign's
        own `status` is left exactly where it was, and the campaign's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/scrub_completion_depends_on_suppression_list_currency
        """
        built = world.build(
            stop_after="campaign", suppression_refreshed_at=_STALE_REFRESH
        )
        campaign_id = built["campaign"]["id"]

        job = world.create_scrub_job(
            campaign_id, list_types=[ListType.NATIONAL, ListType.INTERNAL]
        )
        executed = world.execute_scrub_job(job["id"])

        assert_status(executed, ScrubJobStatus.FAILED)
        assert_fields_equal(
            executed, failure_reason=ScrubFailureReason.STALE_OR_EMPTY_LIST
        )
        assert_fields_null(executed, "completed_at", "expires_at")

        campaign = world.read_campaign(campaign_id)
        assert_status(campaign, CampaignStatus.DRAFT)
        assert_fields_equal(campaign, latest_scrub_status=ScrubJobStatus.FAILED)

    def test_06_scrub_completes_and_promotes_the_campaign_once_a_current_row_exists(
        self, world: ComplianceWorld
    ):
        """Adding one currently refreshed national row is all the identical job needed.

        PRD §3.4: "`contacts_scrubbed_count` is the number of contacts whose `state_code` appears in
        the campaign's `target_state_codes`."
        PRD §3.4: "The job's `completed_at` is stamped at the current clock instant and `expires_at`
        is set to 31 days after `completed_at`."
        PRD §3.4: "Finally the campaign is updated: its `latest_scrub_status` becomes `COMPLETED`,
        its own `eligible_target_count` is overwritten with this job's, its `version` increments and
        its `updated_at` refreshes — and if it was in `DRAFT` it moves `DRAFT → PENDING_LAUNCH`,
        becoming launchable only because a child job completed."

        Design: Difficulty/cross_entity_state_dependency/scrub_completion_depends_on_suppression_list_currency
        """
        built = world.build(
            stop_after="campaign", suppression_refreshed_at=_STALE_REFRESH
        )
        campaign_id = built["campaign"]["id"]

        stale_job = world.create_scrub_job(
            campaign_id, list_types=[ListType.NATIONAL, ListType.INTERNAL]
        )
        assert_status(
            world.execute_scrub_job(stale_job["id"]), ScrubJobStatus.FAILED
        )

        world.create_fresh_national_list(
            phone_number=_SECOND_NATIONAL_NUMBER, source_refreshed_at=_FRESH_REFRESH
        )

        job = world.create_scrub_job(
            campaign_id, list_types=[ListType.NATIONAL, ListType.INTERNAL]
        )
        executed = world.execute_scrub_job(job["id"])

        assert_status(executed, ScrubJobStatus.COMPLETED)
        assert_fields_equal(
            executed,
            contacts_scrubbed_count=1,
            contacts_suppressed_count=0,
            eligible_target_count=1,
        )
        _assert_instant_equals(executed["expires_at"], "2026-09-03T00:00:00Z")

        campaign = world.read_campaign(campaign_id)
        assert_status(campaign, CampaignStatus.PENDING_LAUNCH)
        assert_fields_equal(
            campaign,
            latest_scrub_status=ScrubJobStatus.COMPLETED,
            eligible_target_count=1,
        )
