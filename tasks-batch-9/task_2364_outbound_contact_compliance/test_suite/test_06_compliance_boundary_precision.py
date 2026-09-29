"""Exact edges of three compliance thresholds.

Each edge is pinned twice: once with the quantity sitting exactly on the stated
threshold, and once one smallest step to the other side of it, so the direction
of the comparison is fixed rather than inferred.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    PHONE_C1,
    ApiErrorId,
    AttemptOutcome,
    CampaignStatus,
    ComplianceWorld,
    DialerProfileStatus,
    ScrubJobStatus,
    SuspensionReason,
    assert_attempt_budget_conserved,
    assert_created,
    assert_decimal_equals,
    assert_error,
    assert_fields_null,
    assert_ok,
    assert_timestamp_equals,
    factories,
)

# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------


def _record_one_live_answer_then_one_abandonment(
    world: ComplianceWorld, base: Dict[str, Any]
) -> Dict[str, Any]:
    """Take one live answer and one abandonment: one drop out of two live answers."""
    first = world.create_attempt(base["campaign"]["id"], base["contact"]["id"])
    world.record_outcome(
        first["id"], outcome=AttemptOutcome.CONNECTED_LIVE, agent_connect_seconds=1
    )
    world.set_clock("2026-08-03T00:31:00Z")
    second = world.create_attempt(base["campaign"]["id"], base["contact"]["id"])
    return world.record_outcome(
        second["id"], outcome=AttemptOutcome.ABANDONED, abandon_message_played=True
    )


def _attempt_response(world: ComplianceWorld, base: Dict[str, Any]):
    """Post a VOICE attempt for the built campaign and consumer, unvalidated."""
    return world.api.create_contact_attempt(
        factories.contact_attempt_payload(
            base["campaign"]["id"], base["contact"]["id"]
        ),
        world.operator,
    )


def _running_campaign_scrubbed_on_2026_08_03_at_2200z(
    world: ComplianceWorld,
) -> Dict[str, Any]:
    """Run a campaign whose scrub was completed at 2026-08-03T22:00:00Z.

    The reassigned-numbers check is refreshed on 2026-09-03 so that the only
    stale thing left at the end of the scrub's life is the scrub itself.
    """
    base = world.build(stop_after="launch", clock="2026-08-03T22:00:00Z")
    world.set_clock("2026-09-03T21:00:00Z")
    base["contact"] = world.number_status_check(base["contact"]["id"])
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAbandonmentLimitComparisonIsStrict:
    """A rate equal to the configured limit is tolerated; a hair over it is not."""

    def test_01_rate_exactly_equal_to_the_limit_does_not_breach(
        self, world: ComplianceWorld
    ):
        """One drop in two live answers is 50.00 against a 50.00 limit, so nothing breaks.

        PRD §3.8: "A breach is declared only when two conditions hold together, both evaluated after the current disposition has been applied: `live_answer_count_today` is at least 2 — the minimum measured volume below which no rate is meaningful — and `regulatory_abandonment_rate_pct` is *strictly* greater than the profile's `abandonment_limit_pct`. The comparison is strict, so a rate exactly equal to the configured limit does not breach."

        Design: Difficulty/boundary_precision_check/abandonment_limit_not_breached_at_exactly_the_limit
        """
        base = world.build(stop_after="launch", abandonment_limit_pct=50.0)

        _record_one_live_answer_then_one_abandonment(world, base)

        campaign = world.read_campaign(base["campaign"]["id"])
        assert campaign["live_answer_count_today"] == 2, (
            "the measured volume should be two live answers, got %s"
            % (campaign.get("live_answer_count_today"),)
        )
        assert campaign["abandoned_count_today"] == 1, (
            "exactly one drop should be counted, got %s"
            % (campaign.get("abandoned_count_today"),)
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)
        assert campaign["status"] == CampaignStatus.ACTIVE, (
            "a rate equal to the limit must leave the campaign running, got %s"
            % (campaign.get("status"),)
        )
        assert_fields_null(campaign, "suspension_reason")

        profile = assert_ok(
            world.api.get_dialer_profile(base["profile"]["id"], world.officer)
        )
        assert profile["status"] == DialerProfileStatus.APPROVED, (
            "the profile must stay approved, got %s" % (profile.get("status"),)
        )
        assert_fields_null(profile, "locked_reason")

    def test_02_rate_one_hundredth_above_the_limit_does_breach(
        self, world: ComplianceWorld
    ):
        """Drop the limit by a single hundredth and the same traffic breaches.

        PRD §3.8: "A breach is declared only when two conditions hold together, both evaluated after the current disposition has been applied: `live_answer_count_today` is at least 2 — the minimum measured volume below which no rate is meaningful — and `regulatory_abandonment_rate_pct` is *strictly* greater than the profile's `abandonment_limit_pct`."
        PRD §3.8: "The campaign moves `ACTIVE → SUSPENDED` with `suspension_reason` `ABANDONMENT_BREACH`, voiding its `PENDING` attempts with `void_reason` `CAMPAIGN_SUSPENDED` and crediting those consumers' attempt budgets, and its `version` increments."

        Design: Difficulty/boundary_precision_check/abandonment_limit_not_breached_at_exactly_the_limit
        """
        base = world.build(stop_after="launch", abandonment_limit_pct=49.99)

        _record_one_live_answer_then_one_abandonment(world, base)

        campaign = world.read_campaign(base["campaign"]["id"])
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)
        assert campaign["status"] == CampaignStatus.SUSPENDED, (
            "50.00 is strictly above 49.99 and must suspend, got %s"
            % (campaign.get("status"),)
        )
        assert campaign["suspension_reason"] == SuspensionReason.ABANDONMENT_BREACH, (
            "suspension_reason should be ABANDONMENT_BREACH, got %s"
            % (campaign.get("suspension_reason"),)
        )


class TestEligibleTargetCountFloor:
    """Launch needs at least one reachable target; zero is refused."""

    def test_03_launch_is_refused_when_every_target_was_suppressed(
        self, world: ComplianceWorld
    ):
        """With the only target on the national list, the eligible count is zero.

        PRD §3.7: "The campaign's newest scrub job must be in `COMPLETED` — a newest job that is `PENDING`, `FAILED`, `SUPERSEDED` or `INVALIDATED` yields `ERR_SCRUB_NOT_CURRENT` — and the campaign's `eligible_target_count` must be at least 1, since a campaign whose every target was suppressed has nobody to call and yields `ERR_EMPTY_TARGET_SET`."
        PRD §3.4: "`eligible_target_count` is `contacts_scrubbed_count` less `contacts_suppressed_count`, and can never be negative because the suppressed contacts are a subset of the examined ones."

        Design: Difficulty/boundary_precision_check/fully_suppressed_target_set_blocks_launch_at_zero
        """
        base = world.build(stop_after="campaign")
        world.create_suppression(PHONE_C1)

        job = world.create_scrub_job(base["campaign"]["id"])
        job = world.execute_scrub_job(job["id"])

        assert job["status"] == ScrubJobStatus.COMPLETED, (
            "the scrub itself should complete, got %s" % (job.get("status"),)
        )
        assert job["contacts_scrubbed_count"] == 1, (
            "the one targeted consumer should have been examined, got %s"
            % (job.get("contacts_scrubbed_count"),)
        )
        assert job["contacts_suppressed_count"] == 1, (
            "that consumer should have been found suppressed, got %s"
            % (job.get("contacts_suppressed_count"),)
        )
        assert job["eligible_target_count"] == 0, (
            "one examined less one suppressed leaves nobody, got %s"
            % (job.get("eligible_target_count"),)
        )

        campaign = world.read_campaign(base["campaign"]["id"])
        assert campaign["status"] == CampaignStatus.PENDING_LAUNCH, (
            "a completed scrub should leave the campaign awaiting certification, got %s"
            % (campaign.get("status"),)
        )
        assert campaign["eligible_target_count"] == 0, (
            "the campaign should carry the zero forward, got %s"
            % (campaign.get("eligible_target_count"),)
        )

        response = world.api.launch_campaign(
            base["campaign"]["id"],
            factories.campaign_launch_payload(
                expected_campaign_version=campaign["version"]
            ),
            world.launcher,
        )
        assert_error(response, ApiErrorId.EMPTY_TARGET_SET)

        after = world.read_campaign(base["campaign"]["id"])
        assert after["status"] == CampaignStatus.PENDING_LAUNCH, (
            "the refused launch must leave the campaign where it was, got %s"
            % (after.get("status"),)
        )
        assert_fields_null(after, "launch_certified_by_user_id")

    def test_04_launch_succeeds_with_a_single_eligible_target(
        self, world: ComplianceWorld
    ):
        """One reachable target is the smallest population the floor admits.

        PRD §3.7: "The campaign's newest scrub job must be in `COMPLETED` — a newest job that is `PENDING`, `FAILED`, `SUPERSEDED` or `INVALIDATED` yields `ERR_SCRUB_NOT_CURRENT` — and the campaign's `eligible_target_count` must be at least 1, since a campaign whose every target was suppressed has nobody to call and yields `ERR_EMPTY_TARGET_SET`."
        PRD §3.7: "A campaign that survives all of that moves `PENDING_LAUNCH → ACTIVE`. Its `launch_certified_by_user_id` records the certifying officer's `X-User-ID`."

        Design: Difficulty/boundary_precision_check/fully_suppressed_target_set_blocks_launch_at_zero
        """
        base = world.build(stop_after="scrub")

        assert base["scrub_job"]["contacts_suppressed_count"] == 0, (
            "nobody should be suppressed in this run, got %s"
            % (base["scrub_job"].get("contacts_suppressed_count"),)
        )
        assert base["scrub_job"]["eligible_target_count"] == 1, (
            "the single unsuppressed consumer should be eligible, got %s"
            % (base["scrub_job"].get("eligible_target_count"),)
        )

        launched = world.launch_campaign(base["campaign"]["id"])

        assert launched["status"] == CampaignStatus.ACTIVE, (
            "one eligible target should clear the floor, got %s"
            % (launched.get("status"),)
        )
        assert launched["launch_certified_by_user_id"] is not None, (
            "the certifying officer must be recorded"
        )


class TestScrubValidityHorizon:
    """A scrub is usable up to, but never at, its expiry instant."""

    def test_05_attempt_at_exactly_the_expiry_instant_is_refused(
        self, world: ComplianceWorld
    ):
        """A scrub completed on 2026-08-03T22:00Z is already expired 31 days later.

        PRD §3.4: "The job's `completed_at` is stamped at the current clock instant and `expires_at` is set to 31 days after `completed_at`."
        PRD §3.4: "A completed scrub is current while the clock is strictly earlier than its `expires_at`; at exactly `expires_at` the scrub has already expired."
        PRD §3.8: "The campaign's newest scrub job must be `COMPLETED`, or the attempt is refused with `ERR_SCRUB_NOT_CURRENT`, and that scrub must not have expired — the clock strictly before its `expires_at` — or the attempt is refused with `ERR_SCRUB_EXPIRED`."

        Design: Difficulty/boundary_precision_check/scrub_validity_expires_exactly_at_expires_at
        """
        base = _running_campaign_scrubbed_on_2026_08_03_at_2200z(world)

        job = assert_ok(
            world.api.get_scrub_job(base["scrub_job"]["id"], world.manager)
        )
        assert_timestamp_equals(job["expires_at"], "2026-09-03T22:00:00.000Z")

        world.set_clock("2026-09-03T22:00:00Z")

        assert_error(_attempt_response(world, base), ApiErrorId.SCRUB_EXPIRED)

        contact = world.read_contact(base["contact"]["id"])
        assert contact["attempts_charged"] == 0, (
            "the refused attempt should charge nothing, got %s"
            % (contact.get("attempts_charged"),)
        )
        assert contact["attempt_budget_remaining"] == 3, (
            "the allowance should be untouched, got %s"
            % (contact.get("attempt_budget_remaining"),)
        )
        assert_attempt_budget_conserved(contact)

        campaign = world.read_campaign(base["campaign"]["id"])
        assert campaign["status"] == CampaignStatus.ACTIVE, (
            "an expired scrub refuses attempts without suspending, got %s"
            % (campaign.get("status"),)
        )

    def test_06_attempt_one_second_before_the_expiry_instant_is_permitted(
        self, world: ComplianceWorld
    ):
        """One second earlier the clock is still strictly before expiry, so the call goes.

        PRD §3.4: "A completed scrub is current while the clock is strictly earlier than its `expires_at`; at exactly `expires_at` the scrub has already expired."
        PRD §3.8: "The campaign's newest scrub job must be `COMPLETED`, or the attempt is refused with `ERR_SCRUB_NOT_CURRENT`, and that scrub must not have expired — the clock strictly before its `expires_at` — or the attempt is refused with `ERR_SCRUB_EXPIRED`."

        Design: Difficulty/boundary_precision_check/scrub_validity_expires_exactly_at_expires_at
        """
        base = _running_campaign_scrubbed_on_2026_08_03_at_2200z(world)

        world.set_clock("2026-09-03T21:59:59Z")

        attempt = assert_created(_attempt_response(world, base))

        assert attempt["outcome"] == AttemptOutcome.PENDING, (
            "a permitted attempt starts out PENDING, got %s"
            % (attempt.get("outcome"),)
        )

        contact = world.read_contact(base["contact"]["id"])
        assert contact["attempts_charged"] == 1, (
            "the permitted attempt should charge exactly one, got %s"
            % (contact.get("attempts_charged"),)
        )
        assert_attempt_budget_conserved(contact)
