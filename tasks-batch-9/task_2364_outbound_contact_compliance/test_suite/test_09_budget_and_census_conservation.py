"""Quantities that survive a forward move followed by its compensating move.

The attempt budget of a consumer and the consent census of a contact are both
conserved: the forward operation moves the numbers, the compensating operation
puts them back, and neither leaves the totals out of balance.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from test_helpers import (
    AttemptOutcome,
    Channel,
    ComplianceWorld,
    ConsentStatus,
    ConsentType,
    IntakeStatus,
    InternalDncStatus,
    ListType,
    OFFICER_ADJUDICATOR_USER_ID,
    PHONE_C1,
    RemovalReason,
    RevocationChannelReceived,
    RevocationMethod,
    RevocationScope,
    SuppressionStatus,
    VoidReason,
    assert_attempt_budget_conserved,
    assert_consent_census_conserved,
    assert_decimal_equals,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_page,
    assert_status,
    assert_total_count,
    factories,
    make_compliance_officer_headers,
)

_WORKDAY_CLOCK = "2026-08-03T00:00:00Z"


def _connected_attempt_on_running_campaign(
    world: ComplianceWorld,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Place one attempt on a running campaign and record it as a live answer."""
    built = world.build()
    attempt = world.create_attempt(
        built["campaign"]["id"], built["contact"]["id"], channel=Channel.VOICE
    )
    recorded = world.record_outcome(
        attempt["id"],
        outcome=AttemptOutcome.CONNECTED_LIVE,
        agent_connect_seconds=1,
    )
    return built, recorded


def _void_as_adjudicating_officer(
    world: ComplianceWorld, attempt_id: str
) -> Dict[str, Any]:
    """Void one attempt as the compliance correction the contract reserves for officers."""
    return assert_ok(
        world.api.void_contact_attempt(
            attempt_id,
            factories.attempt_void_payload(
                void_reason=VoidReason.COMPLIANCE_CORRECTION
            ),
            make_compliance_officer_headers(OFFICER_ADJUDICATOR_USER_ID),
        )
    )


def _revoked_consent_on_one_contact(world: ComplianceWorld) -> Dict[str, Any]:
    """Capture one VOICE consent and revoke it through a validated withdrawal."""
    world.set_clock(_WORKDAY_CLOCK)
    world.create_ca_policy()
    contact = world.create_ca_contact()
    script = world.approved_script()
    consent = world.create_consent(
        contact["id"],
        script["id"],
        channel=Channel.VOICE,
        consent_type=ConsentType.EXPRESS_WRITTEN,
    )
    world.create_fresh_national_list()
    revocation = world.create_revocation(
        contact["id"],
        channel_received=RevocationChannelReceived.WEB,
        method=RevocationMethod.WEB_PORTAL,
        scope=RevocationScope.ALL_CHANNELS,
        received_note="Consumer submitted the opt-out form",
    )
    revocation = world.validate_revocation(
        revocation["id"], validation_note="Identity verified against the account"
    )
    return {"contact": contact, "consent": consent, "revocation": revocation}


def _internal_entries_for(
    world: ComplianceWorld, phone_number: str, status: str
) -> Tuple[list, Dict[str, Any]]:
    """List the internal-list suppression entries standing against one number."""
    return assert_page(
        world.api.list_suppression_entries(
            world.officer,
            params={
                "list_type": ListType.INTERNAL,
                "phone_number": phone_number,
                "status": status,
            },
        )
    )


class TestAttemptBudgetConservation:
    """One attempt takes exactly one unit of budget, and a void gives it back."""

    def test_01_recording_a_live_answer_leaves_exactly_one_attempt_charged(
        self, world: ComplianceWorld
    ):
        """The forward move charges the consumer once and the sum still holds.

        PRD §2.10: "For any contact, `attempts_charged` counts that consumer's contact attempts whose
        `voided_at` is still null, `attempt_budget_remaining` is `attempt_budget_total` minus that
        count, and the two always sum back to `attempt_budget_total`."
        PRD §3.8: "The consumer's `attempts_charged` increases by one, `attempt_budget_remaining`
        decreases by one and the contact's `version` increments; the campaign's
        `permitted_attempt_count` increases by one."

        Design: Difficulty/compensating_invariant/attempt_budget_conserved_across_create_and_void
        """
        built, recorded = _connected_attempt_on_running_campaign(world)
        assert_fields_equal(recorded, outcome=AttemptOutcome.CONNECTED_LIVE)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(
            contact,
            attempts_charged=1,
            attempt_budget_remaining=2,
            attempt_budget_total=3,
        )
        assert_attempt_budget_conserved(contact)

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(
            campaign,
            permitted_attempt_count=1,
            voided_attempt_count=0,
            live_answer_count_today=1,
        )

    def test_02_voiding_that_attempt_credits_exactly_one_unit_back(
        self, world: ComplianceWorld
    ):
        """The compensating move returns the consumer to the numbers they started with.

        PRD §2.10: "Creating an attempt charges exactly one; voiding an attempt — whether an officer
        voided it by hand or a campaign suspension voided it as a cascade — credits exactly one back."
        PRD §2.10: "A create-then-void round trip therefore returns the consumer to the numbers they
        started with, and `attempt_budget_remaining` is never negative, because a create is refused
        with `ERR_ATTEMPT_BUDGET_EXHAUSTED` while the remainder is already zero."

        Design: Difficulty/compensating_invariant/attempt_budget_conserved_across_create_and_void
        """
        built, recorded = _connected_attempt_on_running_campaign(world)

        voided = _void_as_adjudicating_officer(world, recorded["id"])
        assert_fields_equal(
            voided,
            outcome=AttemptOutcome.VOIDED,
            void_reason=VoidReason.COMPLIANCE_CORRECTION,
        )
        assert voided["voided_at"] is not None, "a void must stamp voided_at"

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(
            contact,
            attempts_charged=0,
            attempt_budget_remaining=3,
            attempt_budget_total=3,
        )
        assert_attempt_budget_conserved(contact)

    def test_03_voiding_a_live_answer_returns_the_campaign_counters_to_zero(
        self, world: ComplianceWorld
    ):
        """The campaign gives back exactly the counter the live answer had taken.

        PRD §3.8: "In every case `voided_at` is stamped at the current clock instant, the reason is
        stored, the attempt's `outcome` becomes `VOIDED`, the consumer's `attempts_charged` decreases
        by one and `attempt_budget_remaining` increases by one with the contact's `version`
        incrementing, and the campaign's `permitted_attempt_count` decreases by one while
        `voided_attempt_count` increases by one."
        PRD §3.8: "voiding from `CONNECTED_LIVE` decreases `live_answer_count_today` by one and
        recomputes both measures"

        Design: Difficulty/compensating_invariant/attempt_budget_conserved_across_create_and_void
        """
        built, recorded = _connected_attempt_on_running_campaign(world)
        _void_as_adjudicating_officer(world, recorded["id"])

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(
            campaign,
            live_answer_count_today=0,
            permitted_attempt_count=0,
            voided_attempt_count=1,
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 0.00)
        assert_decimal_equals(campaign["internal_abandonment_rate_pct"], 0.00)


class TestConsentCensusConservation:
    """Status movements shuffle the four buckets without changing the total."""

    def test_04_a_validated_revocation_moves_the_row_into_the_revoked_bucket(
        self, world: ComplianceWorld
    ):
        """The forward move empties the active bucket and fills the revoked one.

        PRD §2.10: "For any contact, `total_consent_count` always equals the sum of
        `active_consent_count`, `suspended_consent_count`, `revoked_consent_count` and
        `superseded_consent_count`."
        PRD §3.2: "Every consent record of that consumer whose status is `ACTIVE` or `SUSPENDED` and
        whose `channel` is covered by the request's `scope` — every channel when the scope is
        `ALL_CHANNELS`, otherwise only the channel the scope names — moves to `REVOKED` with
        `revoked_at` stamped at the current clock instant."

        Design: Difficulty/compensating_invariant/consent_census_conserved_across_revoke_and_reinstate
        """
        built = _revoked_consent_on_one_contact(world)
        assert_fields_equal(built["revocation"], consent_records_revoked_count=1)

        consent = assert_ok(
            world.api.get_consent_record(built["consent"]["id"], world.officer)
        )
        assert_status(consent, ConsentStatus.REVOKED)
        assert consent["revoked_at"] is not None, "a revocation must stamp revoked_at"

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(
            contact,
            total_consent_count=1,
            active_consent_count=0,
            suspended_consent_count=0,
            revoked_consent_count=1,
            superseded_consent_count=0,
            internal_dnc_status=InternalDncStatus.SUPPRESSED,
        )
        assert_consent_census_conserved(contact)

    def test_05_reinstatement_restores_the_original_bucket_distribution(
        self, world: ComplianceWorld
    ):
        """The compensating move puts the single row back where it began.

        PRD §2.10: "No consent row is ever deleted, so the total only grows — by exactly one per
        captured record — while every status movement merely shuffles the four buckets."
        PRD §2.10: "Revoke-then-reinstate and suspend-then-reinstate both restore the original bucket
        distribution exactly."

        Design: Difficulty/compensating_invariant/consent_census_conserved_across_revoke_and_reinstate
        """
        built = _revoked_consent_on_one_contact(world)

        reinstated = world.reinstate_consent(
            built["consent"]["id"], reinstatement_note="Withdrawal retracted in writing"
        )
        assert_status(reinstated, ConsentStatus.ACTIVE)
        assert_fields_equal(reinstated, reinstatement_count=1)
        assert_fields_null(reinstated, "revoked_at")

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(
            contact,
            total_consent_count=1,
            active_consent_count=1,
            suspended_consent_count=0,
            revoked_consent_count=0,
            superseded_consent_count=0,
            internal_dnc_status=InternalDncStatus.CLEAR,
        )
        assert_consent_census_conserved(contact)

    def test_06_reinstatement_withdraws_the_suppression_entry_the_revocation_created(
        self, world: ComplianceWorld
    ):
        """The internal-list entry raised by the withdrawal is stood down again.

        PRD §3.2: "The branch out of `REVOKED` carries one extra consequence: when the consumer is
        left with no `REVOKED` consent record at all *and* their `risk_tier` is not `CRITICAL`, their
        `internal_dnc_status` returns to `CLEAR` and every `ACTIVE` internal-list suppression entry
        standing against their `phone_number` moves `ACTIVE → REMOVED` with `removal_reason` set to
        `CONSENT_REINSTATED`."

        Design: Difficulty/compensating_invariant/consent_census_conserved_across_revoke_and_reinstate
        """
        built = _revoked_consent_on_one_contact(world)
        _, raised_meta = _internal_entries_for(
            world, PHONE_C1, SuppressionStatus.ACTIVE
        )
        assert_total_count(raised_meta, 1)

        world.reinstate_consent(
            built["consent"]["id"], reinstatement_note="Withdrawal retracted in writing"
        )

        _, active_meta = _internal_entries_for(
            world, PHONE_C1, SuppressionStatus.ACTIVE
        )
        assert_total_count(active_meta, 0)

        removed_rows, removed_meta = _internal_entries_for(
            world, PHONE_C1, SuppressionStatus.REMOVED
        )
        assert_total_count(removed_meta, 1)
        assert_fields_equal(
            removed_rows[0], removal_reason=RemovalReason.CONSENT_REINSTATED
        )

        revocation = assert_ok(
            world.api.get_revocation_request(
                built["revocation"]["id"], world.officer
            )
        )
        assert_status(revocation, IntakeStatus.VALIDATED, field="intake_status")
