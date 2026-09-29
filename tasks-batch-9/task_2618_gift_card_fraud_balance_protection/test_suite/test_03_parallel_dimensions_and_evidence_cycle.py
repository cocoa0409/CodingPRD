"""Two lifecycles that are not simple linear ladders.

A gift card carries "two independent lifecycle dimensions", and a victim claim's
evidence loop returns the row to its starting state while a monotone counter climbs.
"""

from test_helpers import assert_signed_amount
from test_helpers.assertions import assert_empty
from test_helpers.fixtures import (
    create_rack,
    create_store,
    file_claim,
    funded_physical_card,
    override_posture,
    read_card,
    read_claim,
    redeem,
    request_evidence,
    resubmit_evidence,
    reverse,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_risk_manager_headers,
)


class TestCardDimensionsDiverge:
    """Funding state and fraud posture advance on disjoint triggers."""

    def _depleted_frozen_card(self, client):
        """A 5000-cent card fully redeemed — which drives it DEPLETED — and then frozen
        by a RiskManager override."""
        store = create_store(client, name="Lakeside Mart", region_code="NW")
        rack = create_rack(client, store["id"], rack_label="RACK-L1", expected_card_count=8)
        built = funded_physical_card(client, 5000, store=store, rack=rack)
        card_id = built["card"]["id"]
        event = redeem(client, card_id, 5000, store["id"], memo="drained in one shot")
        frozen = override_posture(client, card_id, "FROZEN", reason="suspected drain")
        return {"card_id": card_id, "event": event, "frozen": frozen, "store": store}

    def test_freezing_a_depleted_card_leaves_the_funding_dimension_alone(self, client):
        """"Whenever an append or a reversal leaves an ACTIVE card's re-derived
        current_balance_cents at exactly zero, the card transitions ACTIVE → DEPLETED",
        and a manual override "leaves the funding state and every balance figure
        completely untouched, which is the plainest demonstration that the two dimensions
        are independent".

        Design: Difficulty/non_linear_state_machine/gift_card_parallel_activation_and_posture_dimensions_diverge
        """
        built = self._depleted_frozen_card(client)

        assert built["frozen"]["activation_state"] == "DEPLETED"
        assert built["frozen"]["risk_posture"] == "FROZEN"
        assert built["frozen"]["current_balance_cents"] == 0
        assert built["frozen"]["total_redeemed_cents"] == 5000

    def test_reversal_revives_the_funding_state_while_the_posture_stays_frozen(self, client):
        """"Whenever an append or a reversal leaves a DEPLETED card's re-derived balance
        above zero, it transitions DEPLETED → ACTIVE", while "Reversal deliberately
        leaves risk_posture completely untouched — a FROZEN card stays FROZEN after its
        fraudulent redemptions have been unwound".

        Design: Difficulty/non_linear_state_machine/gift_card_parallel_activation_and_posture_dimensions_diverge
        """
        built = self._depleted_frozen_card(client)

        reversal = reverse(
            client,
            built["event"]["id"],
            reversal_reason="unauthorized redemption, victim made whole",
        )

        assert reversal["type"] == "REDEMPTION_REVERSAL"
        assert reversal["reverses_event_id"] == built["event"]["id"]
        assert reversal["amount_cents"] == 5000
        assert reversal["signed_amount_cents"] == 5000
        assert_signed_amount(reversal)

        card = read_card(client, built["card_id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["risk_posture"] == "FROZEN"
        assert card["current_balance_cents"] == 5000
        assert card["total_redeemed_cents"] == 0
        assert card["total_loaded_cents"] == 10000
        assert float(card["drawdown_ratio"]) == 0.00

    def test_the_frozen_gate_does_not_block_the_reversal_endpoint(self, client):
        """"reversal is the one value-moving operation that the frozen-card guard does
        not block, because freezing a drained card must never prevent making its victim
        whole."  The card's ledger then holds three rows: the load, the redemption and the
        reversal.

        Design: Difficulty/non_linear_state_machine/gift_card_parallel_activation_and_posture_dimensions_diverge
        """
        built = self._depleted_frozen_card(client)

        response = client.reverse_ledger_event(
            built["event"]["id"],
            {"reversal_reason": "unauthorized redemption"},
            make_risk_manager_headers(),
        )

        assert response.status_code == 201, response.text
        events = client.list_ledger_events(
            make_platform_admin_headers(), {"card_id": built["card_id"]}
        )
        assert events.json()["meta"]["total_count"] == 3


class TestClaimEvidenceCycle:
    """SUBMITTED → EVIDENCE_REQUESTED → SUBMITTED, twice."""

    def _claim(self, client):
        """A 9000-cent card and a claim taken in by pos-9 with no evidence at all —
        "evidence completeness is not checked at intake"."""
        store = create_store(client, name="Old Town Grocers", region_code="SW")
        rack = create_rack(client, store["id"], rack_label="RACK-O1", expected_card_count=6)
        built = funded_physical_card(client, 9000, store=store, rack=rack)
        claim = file_claim(
            client,
            built["card"]["id"],
            disputed_amount_cents=3000,
            purchased_at="2026-08-01T00:00:00Z",
            headers=make_pos_associate_headers("pos-9"),
            claimant_name="Priya Raman",
            claimant_contact="priya@example.com",
        )
        return claim

    def test_each_request_increments_the_round_and_each_resubmission_does_not(self, client):
        """"the claim moves SUBMITTED → EVIDENCE_REQUESTED, evidence_round increments by
        1" on the outbound leg, and on the inbound leg "resubmission does not reset
        evidence_round.  That counter only ever climbs".

        Design: Difficulty/non_linear_state_machine/victim_claim_evidence_cycle_returns_to_submitted_twice
        """
        claim = self._claim(client)
        assert claim["evidence_round"] == 0
        analyst = make_fraud_analyst_headers("analyst-4")
        pos = make_pos_associate_headers("pos-9")

        requested_1 = request_evidence(client, claim["id"], ["PURCHASE_RECEIPT"], headers=analyst)
        resubmitted_1 = resubmit_evidence(
            client, claim["id"], headers=pos, purchase_receipt_ref="RCPT-0001"
        )
        requested_2 = request_evidence(client, claim["id"], ["PACKAGING_PHOTO"], headers=analyst)
        resubmitted_2 = resubmit_evidence(
            client, claim["id"], headers=pos, purchase_receipt_ref=None, packaging_photo_ref="PHOTO-0001"
        )

        assert (requested_1["state"], requested_1["evidence_round"]) == ("EVIDENCE_REQUESTED", 1)
        assert (resubmitted_1["state"], resubmitted_1["evidence_round"]) == ("SUBMITTED", 1)
        assert (requested_2["state"], requested_2["evidence_round"]) == ("EVIDENCE_REQUESTED", 2)
        assert (resubmitted_2["state"], resubmitted_2["evidence_round"]) == ("SUBMITTED", 2)

    def test_the_cycle_returns_the_row_to_submitted_keeping_both_references(self, client):
        """"only the references actually supplied are overwritten — an omitted reference
        retains whatever it already held rather than being cleared", so after two laps the
        claim is back in SUBMITTED holding both references and its original
        intake_user_id.

        Design: Difficulty/non_linear_state_machine/victim_claim_evidence_cycle_returns_to_submitted_twice
        """
        claim = self._claim(client)
        analyst = make_fraud_analyst_headers("analyst-4")
        pos = make_pos_associate_headers("pos-9")
        request_evidence(client, claim["id"], ["PURCHASE_RECEIPT"], headers=analyst)
        resubmit_evidence(client, claim["id"], headers=pos, purchase_receipt_ref="RCPT-0001")
        request_evidence(client, claim["id"], ["PACKAGING_PHOTO"], headers=analyst)
        resubmit_evidence(
            client, claim["id"], headers=pos, purchase_receipt_ref=None, packaging_photo_ref="PHOTO-0001"
        )

        final = read_claim(client, claim["id"])
        assert final["state"] == "SUBMITTED"
        assert final["evidence_round"] == 2
        assert final["purchase_receipt_ref"] == "RCPT-0001"
        assert final["packaging_photo_ref"] == "PHOTO-0001"
        assert final["intake_user_id"] == "pos-9"

    def test_every_leg_of_the_cycle_is_a_mutation_that_bumps_the_version(self, client):
        """A version "starts at 1 on creation and increases by exactly 1 on every
        mutation", so a claim created at 1 and taken through four cycle legs reads 5.

        Design: Difficulty/non_linear_state_machine/victim_claim_evidence_cycle_returns_to_submitted_twice
        """
        claim = self._claim(client)
        assert claim["version"] == 1
        analyst = make_fraud_analyst_headers("analyst-4")
        pos = make_pos_associate_headers("pos-9")

        request_evidence(client, claim["id"], ["PURCHASE_RECEIPT"], headers=analyst)
        resubmit_evidence(client, claim["id"], headers=pos, purchase_receipt_ref="RCPT-0001")
        request_evidence(client, claim["id"], ["PACKAGING_PHOTO"], headers=analyst)
        resubmit_evidence(
            client, claim["id"], headers=pos, purchase_receipt_ref=None, packaging_photo_ref="PHOTO-0001"
        )

        final = read_claim(client, claim["id"])
        assert final["version"] == 5
        assert_empty(final["decided_by_user_id"], "decided_by_user_id")
