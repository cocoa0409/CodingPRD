"""Which single diagnosis an attempt request earns when several gates fail at once.

Attempt creation runs a fixed sequence of checks and stops at the first failure,
so a request that trips two gates is answered by the earlier one alone. Each
winning diagnosis is paired with a companion case that removes the earlier
condition and shows the later one surfacing on its own.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    PHONE_C1,
    ApiErrorId,
    CampaignStatus,
    ComplianceWorld,
    ScrubJobStatus,
    assert_attempt_budget_conserved,
    assert_error,
    factories,
)

# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------


def _attempt_response(world: ComplianceWorld, base: Dict[str, Any]):
    """Post a VOICE attempt for the built campaign and consumer, unvalidated."""
    return world.api.create_contact_attempt(
        factories.contact_attempt_payload(
            base["campaign"]["id"], base["contact"]["id"]
        ),
        world.operator,
    )


def _running_campaign_with_one_attempt_at_2050_local(
    world: ComplianceWorld,
) -> Dict[str, Any]:
    """Run a campaign and take one attempt at 20:50 recipient-local time.

    The consumer sits at UTC-07:00 under an 08:00-21:00 window, so the clock
    instant 2026-08-04T03:50:00Z is 20:50 locally: inside the window, and the
    start of a 30-minute cooldown that runs to 2026-08-04T04:20:00Z.
    """
    base = world.build(stop_after="launch", clock="2026-08-04T03:50:00Z")
    base["attempt"] = world.create_attempt(
        base["campaign"]["id"], base["contact"]["id"]
    )
    return base


def _running_campaign_with_its_only_attempt_spent(
    world: ComplianceWorld,
) -> Dict[str, Any]:
    """Run a campaign for a consumer whose entire allowance is a single attempt."""
    base = world.build(stop_after="launch", attempt_budget_total=1)
    base["attempt"] = world.create_attempt(
        base["campaign"]["id"], base["contact"]["id"]
    )
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCallingWindowOutranksContactCooldown:
    """A late attempt inside the cooldown is diagnosed as a window violation."""

    def test_01_attempt_past_the_window_end_inside_the_cooldown_reports_the_window(
        self, world: ComplianceWorld
    ):
        """Both gates fail; the earlier temporal check is the one reported.

        PRD §2.8: "When a request violates several rules at once, exactly one diagnosis is returned, and which one is fully determined. Checks are evaluated in the following order, and the first failing check ends the request."
        PRD §2.8: "13. The temporal block: no emergency restriction in force, on `POST /compliance/contact-attempts` and `POST /compliance/campaigns/{id}/launch` — `ERR_EMERGENCY_RESTRICTION`; the recipient's local date not being a holiday, on attempts — `ERR_HOLIDAY_RESTRICTION`; the recipient's local time falling inside the effective window, on attempts — `ERR_OUTSIDE_CALLING_WINDOW`; the scrub not having expired, on attempts and launch — `ERR_SCRUB_EXPIRED`."
        PRD §2.8: "15. The contact cooldown on attempt creation — `ERR_CONTACT_COOLDOWN_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/calling_window_error_wins_over_cooldown_error
        """
        base = _running_campaign_with_one_attempt_at_2050_local(world)

        # 21:05 recipient-local: past the window end, and 15 minutes into the
        # cooldown that runs to 04:20Z.
        world.set_clock("2026-08-04T04:05:00Z")

        assert_error(
            _attempt_response(world, base), ApiErrorId.OUTSIDE_CALLING_WINDOW
        )

    def test_02_attempt_still_inside_the_window_reports_the_cooldown_instead(
        self, world: ComplianceWorld
    ):
        """With the window respected, the same cooldown violation is what surfaces.

        PRD §3.8: "If such an attempt exists and the current clock instant falls at or before 30 minutes after its `requested_at`, the new attempt is refused with `ERR_CONTACT_COOLDOWN_ACTIVE`."
        PRD §3.8: "Admission is half-open: the attempt is permitted when `recipient_local_minutes` is greater than or equal to `effective_window_start_minutes` and strictly less than `effective_window_end_minutes`."

        Design: Difficulty/priority_pair_validation_conflict/calling_window_error_wins_over_cooldown_error
        """
        base = _running_campaign_with_one_attempt_at_2050_local(world)

        # 20:55 recipient-local: still inside the window, still inside the
        # cooldown that runs to 04:20Z.
        world.set_clock("2026-08-04T03:55:00Z")

        assert_error(
            _attempt_response(world, base), ApiErrorId.CONTACT_COOLDOWN_ACTIVE
        )

    def test_03_the_refused_attempt_charges_nothing_against_the_consumer(
        self, world: ComplianceWorld
    ):
        """A refusal leaves the consumer's ledger and the campaign counter untouched.

        PRD §2.10: "For any contact, `attempts_charged` counts that consumer's contact attempts whose `voided_at` is still null, `attempt_budget_remaining` is `attempt_budget_total` minus that count, and the two always sum back to `attempt_budget_total`."
        PRD §2.10: "Creating an attempt charges exactly one; voiding an attempt — whether an officer voided it by hand or a campaign suspension voided it as a cascade — credits exactly one back."

        Design: Difficulty/priority_pair_validation_conflict/calling_window_error_wins_over_cooldown_error
        """
        base = _running_campaign_with_one_attempt_at_2050_local(world)
        world.set_clock("2026-08-04T04:05:00Z")

        assert_error(
            _attempt_response(world, base), ApiErrorId.OUTSIDE_CALLING_WINDOW
        )

        contact = world.read_contact(base["contact"]["id"])
        assert contact["attempts_charged"] == 1, (
            "only the one permitted attempt should be charged, got %s"
            % (contact.get("attempts_charged"),)
        )
        assert contact["attempt_budget_remaining"] == 2, (
            "the refused attempt must not spend allowance, got %s"
            % (contact.get("attempt_budget_remaining"),)
        )
        assert_attempt_budget_conserved(contact)

        campaign = world.read_campaign(base["campaign"]["id"])
        assert campaign["permitted_attempt_count"] == 1, (
            "the refused attempt should not be counted as permitted, got %s"
            % (campaign.get("permitted_attempt_count"),)
        )


class TestSuppressionOutranksAttemptBudget:
    """A suppressed consumer with nothing left in the budget is reported suppressed."""

    def test_04_suppressed_consumer_with_an_exhausted_budget_reports_suppression(
        self, world: ComplianceWorld
    ):
        """Both gates fail; the suppression check comes first and ends the request.

        PRD §2.8: "When a request violates several rules at once, exactly one diagnosis is returned, and which one is fully determined. Checks are evaluated in the following order, and the first failing check ends the request."
        PRD §3.8: "The consumer's number must not be covered by any `ACTIVE` suppression entry — a `NATIONAL` or `INTERNAL` entry matching the number, or a `STATE` entry matching both the number and the consumer's own `state_code` — and the consumer's `internal_dnc_status` must be `CLEAR`; either condition failing is refused with `ERR_SUPPRESSED_NUMBER`."
        PRD §3.8: "Finally the frequency cap: the consumer's `attempt_budget_remaining` must be at least 1, or the attempt is refused with `ERR_ATTEMPT_BUDGET_EXHAUSTED`."

        Design: Difficulty/priority_pair_validation_conflict/suppression_error_wins_over_attempt_budget_error
        """
        base = _running_campaign_with_its_only_attempt_spent(world)
        world.create_suppression(PHONE_C1)

        # Past the 30-minute cooldown from the first attempt.
        world.set_clock("2026-08-03T01:00:00Z")

        assert_error(_attempt_response(world, base), ApiErrorId.SUPPRESSED_NUMBER)

        contact = world.read_contact(base["contact"]["id"])
        assert contact["attempts_charged"] == 1, (
            "the refused attempt should charge nothing further, got %s"
            % (contact.get("attempts_charged"),)
        )
        assert contact["attempt_budget_remaining"] == 0, (
            "the single-attempt allowance is already spent, got %s"
            % (contact.get("attempt_budget_remaining"),)
        )
        assert_attempt_budget_conserved(contact)

    def test_05_unsuppressed_consumer_with_the_same_empty_budget_reports_the_cap(
        self, world: ComplianceWorld
    ):
        """Remove the suppression and the frequency cap is the diagnosis that surfaces.

        PRD §3.8: "Finally the frequency cap: the consumer's `attempt_budget_remaining` must be at least 1, or the attempt is refused with `ERR_ATTEMPT_BUDGET_EXHAUSTED`."
        PRD §2.10: "For any contact, `attempts_charged` counts that consumer's contact attempts whose `voided_at` is still null, `attempt_budget_remaining` is `attempt_budget_total` minus that count, and the two always sum back to `attempt_budget_total`."

        Design: Difficulty/priority_pair_validation_conflict/suppression_error_wins_over_attempt_budget_error
        """
        base = _running_campaign_with_its_only_attempt_spent(world)

        world.set_clock("2026-08-03T01:00:00Z")

        assert_error(
            _attempt_response(world, base), ApiErrorId.ATTEMPT_BUDGET_EXHAUSTED
        )

        contact = world.read_contact(base["contact"]["id"])
        assert contact["attempt_budget_remaining"] == 0, (
            "the allowance stays at zero, got %s"
            % (contact.get("attempt_budget_remaining"),)
        )

    def test_06_a_national_entry_leaves_the_campaign_running_on_its_completed_scrub(
        self, world: ComplianceWorld
    ):
        """Only internal-list entries disturb scrubs, so the campaign keeps running.

        PRD §3.4: "Adding an internal-list entry is not inert. When the `phone_number` on a new `ACTIVE` internal entry belongs to an existing contact, the same two hops that close §3.3 run here as well: the current completed scrub jobs that requested `INTERNAL` and cover that consumer's state move to `INVALIDATED` with `invalidation_reason` `NEW_INTERNAL_SUPPRESSION`, and their `ACTIVE` campaigns move to `SUSPENDED` with `suspension_reason` `SCRUB_STALE`, voiding pending attempts and crediting budgets."
        PRD §3.4: "Removed entries do not suppress, and an internal entry is simply ignored by a job that did not request `INTERNAL`."

        Design: Difficulty/priority_pair_validation_conflict/suppression_error_wins_over_attempt_budget_error
        """
        base = _running_campaign_with_its_only_attempt_spent(world)

        world.create_suppression(PHONE_C1)

        campaign = world.read_campaign(base["campaign"]["id"])
        assert campaign["status"] == CampaignStatus.ACTIVE, (
            "a national entry must not suspend the campaign, got %s"
            % (campaign.get("status"),)
        )
        assert campaign["latest_scrub_status"] == ScrubJobStatus.COMPLETED, (
            "a national entry must not invalidate the scrub, got %s"
            % (campaign.get("latest_scrub_status"),)
        )
