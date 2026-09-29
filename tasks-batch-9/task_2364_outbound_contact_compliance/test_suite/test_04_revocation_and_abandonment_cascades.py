"""Multi-hop compliance cascades.

Two chains are exercised here: honouring a revocation, which walks consent
revocation to internal suppression to scrub invalidation to campaign
suspension, and recording an abandonment, which walks a campaign suspension to
a dialer-profile lock to the suspension of a sibling campaign that never dialled
anybody.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    PHONE_C1,
    AttemptOutcome,
    CampaignStatus,
    ComplianceWorld,
    ConsentStatus,
    DialerLockedReason,
    DialerProfileStatus,
    IntakeStatus,
    InternalDncStatus,
    ListType,
    PropagationStatus,
    ScrubInvalidationReason,
    ScrubJobStatus,
    SuppressionStatus,
    SuspensionReason,
    VoidReason,
    assert_attempt_budget_conserved,
    assert_consent_census_conserved,
    assert_decimal_equals,
    assert_ok,
    assert_page,
    assert_total_count,
)

# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------


def _launched_campaign_with_pending_attempt_and_revocation(
    world: ComplianceWorld,
) -> Dict[str, Any]:
    """Run a campaign, charge one pending attempt, and log a withdrawal.

    Leaves the logical clock on the canonical working instant with an ACTIVE
    campaign whose newest scrub covered the internal list, one ACTIVE VOICE
    consent for the consumer, one PENDING attempt charged against a budget of
    three, and one revocation request still at intake covering every channel.
    """
    base = world.build(stop_after="launch")
    base["attempt"] = world.create_attempt(
        base["campaign"]["id"], base["contact"]["id"]
    )
    base["revocation"] = world.create_revocation(base["contact"]["id"])
    return base


def _two_campaigns_sharing_one_dialer_profile(
    world: ComplianceWorld, abandonment_limit_pct: float = 40.0
) -> Dict[str, Any]:
    """Run two campaigns off one approved dialer profile and one approved script."""
    base = world.build(
        stop_after="launch", abandonment_limit_pct=abandonment_limit_pct
    )
    sibling = world.create_campaign(
        dialer_profile_id=base["profile"]["id"],
        agent_script_id=base["script"]["id"],
        name="CA Aug Outreach B",
    )
    sibling_job = world.create_scrub_job(sibling["id"])
    base["sibling_scrub_job"] = world.execute_scrub_job(sibling_job["id"])
    base["sibling"] = world.launch_campaign(sibling["id"])
    return base


def _record_one_live_answer_then_one_abandonment(
    world: ComplianceWorld, base: Dict[str, Any]
) -> Dict[str, Any]:
    """Take one live answer and one abandonment, so one of two live answers dropped."""
    first = world.create_attempt(base["campaign"]["id"], base["contact"]["id"])
    world.record_outcome(
        first["id"], outcome=AttemptOutcome.CONNECTED_LIVE, agent_connect_seconds=1
    )
    world.set_clock("2026-08-03T00:31:00Z")
    second = world.create_attempt(base["campaign"]["id"], base["contact"]["id"])
    return world.record_outcome(
        second["id"], outcome=AttemptOutcome.ABANDONED, abandon_message_played=True
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRevocationValidationCascade:
    """Validating a withdrawal settles every downstream consequence at once."""

    def test_01_validation_revokes_consent_and_suppresses_the_consumer(
        self, world: ComplianceWorld
    ):
        """The near hops: the in-scope consent is revoked and the consumer is suppressed.

        PRD §3.3: "A `ComplianceOfficer` accepts the withdrawal as genuine, supplying a `validation_note`, and the request's `intake_status` moves `RECEIVED → VALIDATED` with `validated_at` stamped at the current clock instant, while the propagation dimension moves `NOT_STARTED → IN_PROGRESS` in the same request."
        PRD §3.3: "Every consent record of that consumer whose status is `ACTIVE` or `SUSPENDED` and whose `channel` is covered by the request's `scope` — every channel when the scope is `ALL_CHANNELS`, otherwise only the channel the scope names — moves to `REVOKED` with `revoked_at` stamped at the current clock instant."
        PRD §3.3: "The second hop, caused by the first, puts the consumer on the internal do-not-call list: `internal_dnc_status` becomes `SUPPRESSED`, the consent census counters are recomputed, the contact's `version` increments, and an `ACTIVE` internal-list suppression entry is created for the consumer's `phone_number` if no such entry already exists."

        Design: Difficulty/transitive_cascade/revocation_validate_cascades_four_hops_to_campaign_suspension
        """
        base = _launched_campaign_with_pending_attempt_and_revocation(world)

        validated = world.validate_revocation(base["revocation"]["id"])

        assert validated["intake_status"] == IntakeStatus.VALIDATED, (
            "intake_status should be VALIDATED, got %s"
            % (validated.get("intake_status"),)
        )
        assert validated["propagation_status"] == PropagationStatus.IN_PROGRESS, (
            "propagation_status should be IN_PROGRESS, got %s"
            % (validated.get("propagation_status"),)
        )
        assert validated["consent_records_revoked_count"] == 1, (
            "exactly the one ACTIVE VOICE consent should have been revoked, got %s"
            % (validated.get("consent_records_revoked_count"),)
        )

        consent = assert_ok(
            world.api.get_consent_record(base["consent"]["id"], world.officer)
        )
        assert consent["status"] == ConsentStatus.REVOKED, (
            "hop 1 should have revoked the consent, got %s" % (consent.get("status"),)
        )
        assert consent["revoked_at"] is not None, "revoked_at must be stamped"

        contact = world.read_contact(base["contact"]["id"])
        assert contact["internal_dnc_status"] == InternalDncStatus.SUPPRESSED, (
            "hop 2 should have suppressed the consumer, got %s"
            % (contact.get("internal_dnc_status"),)
        )
        assert contact["active_consent_count"] == 0, (
            "no consent should remain active, got %s"
            % (contact.get("active_consent_count"),)
        )
        assert contact["revoked_consent_count"] == 1, (
            "one consent should sit in the revoked bucket, got %s"
            % (contact.get("revoked_consent_count"),)
        )
        assert_consent_census_conserved(contact)

        entries, meta = assert_page(
            world.api.list_suppression_entries(
                world.officer,
                {"list_type": ListType.INTERNAL, "phone_number": PHONE_C1},
            )
        )
        assert_total_count(meta, 1)
        assert entries[0]["status"] == SuppressionStatus.ACTIVE, (
            "the internal entry should be ACTIVE, got %s" % (entries[0].get("status"),)
        )
        assert entries[0]["phone_number"] == PHONE_C1, (
            "the internal entry should cover the consumer's number, got %s"
            % (entries[0].get("phone_number"),)
        )

    def test_02_suppression_invalidates_the_scrub_and_suspends_the_campaign(
        self, world: ComplianceWorld
    ):
        """The far hops: the new suppression invalidates the scrub, which stops the campaign.

        PRD §3.3: "The third hop, caused by the second, invalidates the scrubs that were computed before this suppression existed: every scrub job whose status is `COMPLETED`, whose `expires_at` is still later than the current clock instant, whose `list_types` includes `INTERNAL`, and whose campaign's `target_state_codes` contains the consumer's `state_code`, moves `COMPLETED → INVALIDATED` with `invalidation_reason` set to `NEW_INTERNAL_SUPPRESSION`."
        PRD §3.3: "The fourth hop, caused by the third, stops the traffic: every `ACTIVE` campaign whose `latest_scrub_status` has just become `INVALIDATED` moves `ACTIVE → SUSPENDED` with `suspension_reason` set to `SCRUB_STALE`, voiding each of its pending attempts and crediting the affected consumers' attempt budgets as §3.8 describes, and incrementing its own `version`."

        Design: Difficulty/transitive_cascade/revocation_validate_cascades_four_hops_to_campaign_suspension
        """
        base = _launched_campaign_with_pending_attempt_and_revocation(world)

        world.validate_revocation(base["revocation"]["id"])

        job = assert_ok(
            world.api.get_scrub_job(base["scrub_job"]["id"], world.manager)
        )
        assert job["status"] == ScrubJobStatus.INVALIDATED, (
            "hop 3 should have invalidated the completed scrub, got %s"
            % (job.get("status"),)
        )
        assert (
            job["invalidation_reason"]
            == ScrubInvalidationReason.NEW_INTERNAL_SUPPRESSION
        ), (
            "invalidation_reason should be NEW_INTERNAL_SUPPRESSION, got %s"
            % (job.get("invalidation_reason"),)
        )

        campaign = world.read_campaign(base["campaign"]["id"])
        assert campaign["status"] == CampaignStatus.SUSPENDED, (
            "hop 4 should have suspended the campaign, got %s"
            % (campaign.get("status"),)
        )
        assert campaign["suspension_reason"] == SuspensionReason.SCRUB_STALE, (
            "suspension_reason should be SCRUB_STALE, got %s"
            % (campaign.get("suspension_reason"),)
        )
        assert campaign["latest_scrub_status"] == ScrubJobStatus.INVALIDATED, (
            "latest_scrub_status should be INVALIDATED, got %s"
            % (campaign.get("latest_scrub_status"),)
        )

    def test_03_campaign_suspension_voids_the_pending_attempt_and_credits_the_budget(
        self, world: ComplianceWorld
    ):
        """The final side effect: the pending attempt is voided and the budget restored.

        PRD §3.3: "The fourth hop, caused by the third, stops the traffic: every `ACTIVE` campaign whose `latest_scrub_status` has just become `INVALIDATED` moves `ACTIVE → SUSPENDED` with `suspension_reason` set to `SCRUB_STALE`, voiding each of its pending attempts and crediting the affected consumers' attempt budgets as §3.8 describes, and incrementing its own `version`."
        PRD §2.10: "Creating an attempt charges exactly one; voiding an attempt — whether an officer voided it by hand or a campaign suspension voided it as a cascade — credits exactly one back."

        Design: Difficulty/transitive_cascade/revocation_validate_cascades_four_hops_to_campaign_suspension
        """
        base = _launched_campaign_with_pending_attempt_and_revocation(world)

        charged = world.read_contact(base["contact"]["id"])
        assert charged["attempts_charged"] == 1, (
            "the pending attempt should already be charged, got %s"
            % (charged.get("attempts_charged"),)
        )

        world.validate_revocation(base["revocation"]["id"])

        attempt = assert_ok(
            world.api.get_contact_attempt(base["attempt"]["id"], world.operator)
        )
        assert attempt["outcome"] == AttemptOutcome.VOIDED, (
            "the pending attempt should have been voided, got %s"
            % (attempt.get("outcome"),)
        )
        assert attempt["void_reason"] == VoidReason.CAMPAIGN_SUSPENDED, (
            "void_reason should be CAMPAIGN_SUSPENDED, got %s"
            % (attempt.get("void_reason"),)
        )
        assert attempt["voided_at"] is not None, "voided_at must be stamped"

        contact = world.read_contact(base["contact"]["id"])
        assert contact["attempts_charged"] == 0, (
            "the cascade void should have credited the charge back, got %s"
            % (contact.get("attempts_charged"),)
        )
        assert contact["attempt_budget_remaining"] == 3, (
            "the consumer should be back at their full allowance, got %s"
            % (contact.get("attempt_budget_remaining"),)
        )
        assert_attempt_budget_conserved(contact)


class TestAbandonmentBreachCascade:
    """One abandonment past the ceiling stops the profile and every campaign on it."""

    def test_04_breach_suspends_the_campaign_that_abandoned_the_call(
        self, world: ComplianceWorld
    ):
        """Hop one: the breaching campaign is suspended for ABANDONMENT_BREACH.

        PRD §3.8: "A breach is declared only when two conditions hold together, both evaluated after the current disposition has been applied: `live_answer_count_today` is at least 2 — the minimum measured volume below which no rate is meaningful — and `regulatory_abandonment_rate_pct` is *strictly* greater than the profile's `abandonment_limit_pct`."
        PRD §3.8: "The campaign moves `ACTIVE → SUSPENDED` with `suspension_reason` `ABANDONMENT_BREACH`, voiding its `PENDING` attempts with `void_reason` `CAMPAIGN_SUSPENDED` and crediting those consumers' attempt budgets, and its `version` increments."

        Design: Difficulty/transitive_cascade/abandonment_breach_cascades_three_hops_to_sibling_campaign
        """
        base = _two_campaigns_sharing_one_dialer_profile(world)

        abandoned = _record_one_live_answer_then_one_abandonment(world, base)

        assert abandoned["outcome"] == AttemptOutcome.ABANDONED, (
            "the disposition should be ABANDONED, got %s" % (abandoned.get("outcome"),)
        )
        assert abandoned["abandon_message_played"] is True, (
            "abandon_message_played should be stored as true, got %r"
            % (abandoned.get("abandon_message_played"),)
        )

        campaign = world.read_campaign(base["campaign"]["id"])
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)
        assert campaign["live_answer_count_today"] == 2, (
            "one live connect plus one abandonment make two live answers, got %s"
            % (campaign.get("live_answer_count_today"),)
        )
        assert campaign["status"] == CampaignStatus.SUSPENDED, (
            "a rate of 50.00 against a 40.00 ceiling must suspend, got %s"
            % (campaign.get("status"),)
        )
        assert campaign["suspension_reason"] == SuspensionReason.ABANDONMENT_BREACH, (
            "suspension_reason should be ABANDONMENT_BREACH, got %s"
            % (campaign.get("suspension_reason"),)
        )

    def test_05_breach_locks_the_dialer_profile_the_campaign_pointed_at(
        self, world: ComplianceWorld
    ):
        """Hop two: the profile the breaching campaign pointed at is locked.

        PRD §3.8: "The dialer profile it points at then moves `APPROVED → LOCKED` with `locked_reason` `ABANDONMENT_BREACH` and its own `version` increments."
        PRD §3.6: "The reverse move, `APPROVED → LOCKED`, is never requested by a client: it is the second hop of the abandonment cascade in §3.8, sets `locked_reason` to `ABANDONMENT_BREACH`, and is undone only by a fresh approval — which is exactly what makes a campaign suspended for a locked profile resumable again."

        Design: Difficulty/transitive_cascade/abandonment_breach_cascades_three_hops_to_sibling_campaign
        """
        base = _two_campaigns_sharing_one_dialer_profile(world)

        _record_one_live_answer_then_one_abandonment(world, base)

        profile = assert_ok(
            world.api.get_dialer_profile(base["profile"]["id"], world.officer)
        )
        assert profile["status"] == DialerProfileStatus.LOCKED, (
            "hop 2 should have locked the dialer profile, got %s"
            % (profile.get("status"),)
        )
        assert profile["locked_reason"] == DialerLockedReason.ABANDONMENT_BREACH, (
            "locked_reason should be ABANDONMENT_BREACH, got %s"
            % (profile.get("locked_reason"),)
        )

    def test_06_profile_lock_suspends_the_sibling_campaign_that_dialled_nobody(
        self, world: ComplianceWorld
    ):
        """Hop three: a sibling campaign on the same profile goes down as PROFILE_LOCKED.

        PRD §3.8: "And every *other* `ACTIVE` campaign pointing at that same profile then moves `ACTIVE → SUSPENDED` with `suspension_reason` `PROFILE_LOCKED`, likewise voiding its `PENDING` attempts, crediting those consumers' budgets and incrementing its own `version`."
        PRD §3.8: "The sibling campaigns are suspended because the profile was locked, not because they abandoned anything themselves."

        Design: Difficulty/transitive_cascade/abandonment_breach_cascades_three_hops_to_sibling_campaign
        """
        base = _two_campaigns_sharing_one_dialer_profile(world)

        _record_one_live_answer_then_one_abandonment(world, base)

        sibling = world.read_campaign(base["sibling"]["id"])
        assert sibling["status"] == CampaignStatus.SUSPENDED, (
            "hop 3 should have suspended the sibling campaign, got %s"
            % (sibling.get("status"),)
        )
        assert sibling["suspension_reason"] == SuspensionReason.PROFILE_LOCKED, (
            "suspension_reason should be PROFILE_LOCKED, got %s"
            % (sibling.get("suspension_reason"),)
        )
        assert sibling["live_answer_count_today"] == 0, (
            "the sibling dialled nobody, got %s"
            % (sibling.get("live_answer_count_today"),)
        )
        assert_decimal_equals(sibling["regulatory_abandonment_rate_pct"], 0.00)

        sibling_job = assert_ok(
            world.api.get_scrub_job(base["sibling_scrub_job"]["id"], world.manager)
        )
        assert sibling_job["status"] == ScrubJobStatus.COMPLETED, (
            "this chain never touches scrub state, got %s"
            % (sibling_job.get("status"),)
        )
