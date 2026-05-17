"""Copay card lifecycle: ACTIVE -> EXHAUSTED -> ACTIVE; TERMINATED.

PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    create_copay_card,
    create_copay_card_payload,
    create_drug,
    create_formulary_entry,
    create_member,
    create_plan,
    occ_payload,
    re_get_copay_card,
    setup_adjudicated_claim,
    setup_paid_claim,
    setup_reference_data,
    setup_reversed_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Card creation
# ===========================================================================
class TestCopayCardCreation:

    def test_create_copay_card_returns_active_used_zero(
        self, api, admin_headers,
    ):
        """PRD §3.8: "The cumulative draw is tracked in used_cents
        and begins at zero. The card begins life in ACTIVE status."

        Claim: a freshly issued card has used_cents=0, status=ACTIVE.
        """
        _, drug, _, member = setup_reference_data()
        payload = create_copay_card_payload(
            member_id=member["id"], drug_id=drug["id"],
            max_benefit_cents=1_000, per_claim_cap_cents=500,
        )
        card = validate_success(
            api.create_copay_card(payload, admin_headers), 201,
        )
        assert card["status"] == "ACTIVE"
        assert card["used_cents"] == 0


# ===========================================================================
# Automatic EXHAUSTED <-> ACTIVE
# ===========================================================================
class TestAutomaticTransitions:

    def test_card_returns_to_active_on_reverse(self, api):
        """PRD §3.8: "The card reverts to ACTIVE — again automatically
        — when a reverse decrements used_cents strictly below
        max_benefit_cents."
        PRD §3.7: "if this drop pushes used_cents strictly below
        max_benefit_cents the card's status reverts from EXHAUSTED
        back to ACTIVE."

        Setup: card max=500, per-claim=500. After adjudicate+pay the
        card hits 500 -> EXHAUSTED. After reverse used drops below
        500 -> back to ACTIVE.
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=100_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=300)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        card = create_copay_card(
            member_id=member["id"], drug_id=drug["id"],
            max_benefit_cents=500, per_claim_cap_cents=500,
        )
        # allowed=300*10=3000, member_share=600, card_payable=500.
        setup_reversed_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=1, quantity=10,
            copay_card_id=card["id"],
        )
        # After the round-trip, used_cents=0 (< 500) and status
        # should be ACTIVE again.
        c = re_get_copay_card(card["id"])
        assert c["used_cents"] == 0
        assert c["status"] == "ACTIVE"


# ===========================================================================
# Manual TERMINATED.
# ===========================================================================
class TestManualTermination:

    def test_terminate_active_card(self, api, admin_headers):
        """PRD §3.8: "A PBMAdmin may also terminate a card at any
        time from either ACTIVE or EXHAUSTED, transitioning it to the
        terminal TERMINATED state."

        Claim: terminate ACTIVE card -> TERMINATED.
        """
        _, drug, _, member = setup_reference_data()
        card = create_copay_card(
            member_id=member["id"], drug_id=drug["id"],
            max_benefit_cents=1_000, per_claim_cap_cents=1_000,
        )
        res = api.terminate_copay_card(
            card["id"], occ_payload(version=card["version"]),
            admin_headers,
        )
        term = validate_success(res, 200)
        assert term["status"] == "TERMINATED"

    def test_terminate_terminated_card_rejected(
        self, api, admin_headers,
    ):
        """PRD §3.8: TERMINATED is "the terminal TERMINATED state".
        PRD §2.8 rung 4: "the target resource must be in a state legal
        for the requested transition … Violations yield
        ERR_INVALID_STATE (409)."

        Claim: terminate a card already TERMINATED -> ERR_INVALID_STATE.
        """
        _, drug, _, member = setup_reference_data()
        card = create_copay_card(
            member_id=member["id"], drug_id=drug["id"],
            max_benefit_cents=1_000, per_claim_cap_cents=1_000,
        )
        res1 = api.terminate_copay_card(
            card["id"], occ_payload(version=card["version"]),
            admin_headers,
        )
        term = validate_success(res1, 200)
        res2 = api.terminate_copay_card(
            term["id"], occ_payload(version=term["version"]),
            admin_headers,
        )
        validate_error(res2, "ERR_INVALID_STATE")

    def test_terminated_card_is_ignored_at_adjudicate(
        self, api, admin_headers,
    ):
        """PRD §3.8: "A TERMINATED card is ignored on any future
        adjudication: the adjudication proceeds as if the claim had
        not supplied copay_card_id at all."

        Note (PRD-only readers): "ignored" is the verbatim PRD verb.
        PRD §2.8 rung 12 says ``ERR_COPAY_CARD_MISMATCH`` fires when
        ``card.status != ACTIVE``, but PRD §3.8 explicitly overrides
        that for TERMINATED: the card is silently disregarded. Both
        readings are PRD-consistent in isolation; per the two-reader
        rule we therefore widen the assertion: the adjudicate either
        succeeds (treating card as absent, member pays full share)
        OR is rejected with ERR_COPAY_CARD_MISMATCH (card not
        ACTIVE). We only forbid an outcome where the terminated card
        somehow DOES contribute (copay_card_paid_cents > 0).
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=100_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=1_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        card = create_copay_card(
            member_id=member["id"], drug_id=drug["id"],
            max_benefit_cents=1_000, per_claim_cap_cents=1_000,
        )
        # Terminate.
        term_res = api.terminate_copay_card(
            card["id"], occ_payload(version=card["version"]),
            admin_headers,
        )
        validate_success(term_res, 200)
        # Submit + adjudicate with the terminated card.
        from test_helpers import TEST_USERS, submit_claim
        claim = submit_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=30,
            copay_card_id=card["id"],
        )
        res = api.adjudicate_claim(
            claim["id"], occ_payload(version=claim["version"]),
            TEST_USERS["claims_adjudicator_headers"],
        )
        body = res.json()
        if 200 <= res.status_code < 300:
            data = body["data"]
            assert data["copay_card_paid_cents"] == 0, (
                "TERMINATED card must contribute 0 even when adjudicate "
                "treats card as absent"
            )
            assert data["status"] == "ADJUDICATED"
        else:
            # Either way is fine, but loser must surface
            # ERR_COPAY_CARD_MISMATCH (card not ACTIVE) per PRD §2.8
            # rung 12 — never anything else.
            assert body["response_type"] == "error"
            assert (body["data"]["error_id"]
                    == "ERR_COPAY_CARD_MISMATCH")
