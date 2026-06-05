"""Difficulty Rule 3 — non_linear_state_machine.

State machines that revisit a state by design rather than running a linear
A→B→C pipeline:

  • SettlementOffer: PENDING → COUNTERED → (new) PENDING → COUNTERED ... (PRD §3.5)
  • MedicalLien: DISPUTED ↔ NEGOTIATING re-entry cycle (PRD §3.7)
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_lien,
    negotiate_lien,
    dispute_lien,
    resume_lien,
    create_offer,
    get_case,
    setup_case_in_negotiation_with_offer,
)


# =============================================================================
# Instance: settlement_offer_counter_round_chain
# =============================================================================


class TestSettlementOfferCounterRoundChain:
    """Counter offers create a chain that ping-pongs PENDING → COUNTERED →
    (new) PENDING. Each counter resolves the prior offer and creates a new one
    one round higher."""

    def _setup_three_round_chain(self):
        """Build a case in DEMAND_SENT, then post three offers in alternating
        parties — CARRIER, FIRM (counter of #1), CARRIER (counter of #2).
        Returns (case_id, offer1_id, offer2_id, offer3_id)."""
        client, case_in_neg, provider, offer1 = setup_case_in_negotiation_with_offer(
            offer_amount_cents=4_000_000, by_party="CARRIER",
        )
        offer2 = create_offer(case_in_neg["id"], 8_000_000, "FIRM",
                               counter_to_offer_id=offer1["id"])
        offer3 = create_offer(case_in_neg["id"], 6_000_000, "CARRIER",
                               counter_to_offer_id=offer2["id"])
        return case_in_neg["id"], offer1["id"], offer2["id"], offer3["id"]

    def test_each_counter_advances_round_number_and_resolves_prior(self, api):
        """PRD §3.5: "the system pins `round_number` to one more than the prior
        offer's `round_number` and transitions the prior offer `PENDING →
        COUNTERED`, stamping its `responded_at`."

        Design: Difficulty/non_linear_state_machine/settlement_offer_counter_round_chain
        """
        from test_helpers import TEST_USERS
        set_clock("2026-01-01T00:00:00Z")
        case_id, o1, o2, o3 = self._setup_three_round_chain()
        h = TEST_USERS["attorney_headers"]
        d1 = validate_success(api.get_offer(o1, h), 200)
        d2 = validate_success(api.get_offer(o2, h), 200)
        d3 = validate_success(api.get_offer(o3, h), 200)

        # Round numbers form an ascending arithmetic chain.
        assert d1["round_number"] == 1
        assert d2["round_number"] == 2
        assert d3["round_number"] == 3
        # Prior offers transitioned to COUNTERED on counter creation.
        assert d1["status"] == "COUNTERED"
        assert d2["status"] == "COUNTERED"
        # Newest offer remains PENDING — it has not yet been countered.
        assert d3["status"] == "PENDING"

    def test_chain_back_links_via_counter_to_offer_id(self, api):
        """PRD §3.5: "An `Attorney` creating a counter posts a new
        `SettlementOffer` whose `counter_to_offer_id` points at the prior
        `PENDING` offer; the system pins `round_number` to one more than the
        prior offer's `round_number` and transitions the prior offer `PENDING
        → COUNTERED`, stamping its `responded_at`."

        Design: Difficulty/non_linear_state_machine/settlement_offer_counter_round_chain
        """
        from test_helpers import TEST_USERS
        set_clock("2026-01-01T00:00:00Z")
        case_id, o1, o2, o3 = self._setup_three_round_chain()
        h = TEST_USERS["attorney_headers"]
        d2 = validate_success(api.get_offer(o2, h), 200)
        d3 = validate_success(api.get_offer(o3, h), 200)
        # Counter back-links chain back to the previous offer.
        assert d2["counter_to_offer_id"] == o1
        assert d3["counter_to_offer_id"] == o2
        # responded_at must be stamped on the COUNTERED offers.
        d1 = validate_success(api.get_offer(o1, h), 200)
        assert d1["responded_at"] is not None
        assert d2["responded_at"] is not None


# =============================================================================
# Instance: medical_lien_dispute_resume_cycle
# =============================================================================


class TestMedicalLienDisputeResumeCycle:
    """A MedicalLien on a single case can cycle NEGOTIATING ↔ DISPUTED any
    number of times — the cycle is part of the state machine."""

    def _setup_lien_in_negotiating(self):
        set_clock("2026-01-01T00:00:00Z")
        client = register_client(email="lien-cycle@example.com")
        sign_retainer(client["id"])
        case = create_case(client["id"], jurisdiction="CA",
                            accident_date="2024-06-15")
        activate_case(case["id"])
        provider = register_provider()
        lien = create_lien(case["id"], provider["id"], 800_000)
        negotiate_lien(lien["id"])
        return lien

    def test_double_dispute_resume_round_trip_lands_in_negotiating(self, api):
        """PRD §3.7: "The `Attorney` can also resume a disputed negotiation by
        moving the lien `DISPUTED → NEGOTIATING`, which means the same lien
        can cycle `NEGOTIATING → DISPUTED → NEGOTIATING → DISPUTED`
        indefinitely."

        Design: Difficulty/non_linear_state_machine/medical_lien_dispute_resume_cycle
        """
        from test_helpers import TEST_USERS
        lien = self._setup_lien_in_negotiating()
        dispute_lien(lien["id"])     # NEGOTIATING → DISPUTED
        resume_lien(lien["id"])      # DISPUTED → NEGOTIATING
        dispute_lien(lien["id"])     # NEGOTIATING → DISPUTED
        final = resume_lien(lien["id"])  # DISPUTED → NEGOTIATING
        assert final["status"] == "NEGOTIATING"
        assert final["asserted_amount_cents"] == 800_000

    def test_dispute_then_resume_returns_lien_to_negotiating(self, api):
        """PRD §3.7: "The `Attorney` can also resume a disputed negotiation by
        moving the lien `DISPUTED → NEGOTIATING`, which means the same lien
        can cycle `NEGOTIATING → DISPUTED → NEGOTIATING → DISPUTED`
        indefinitely."

        Design: Difficulty/non_linear_state_machine/medical_lien_dispute_resume_cycle
        """
        lien = self._setup_lien_in_negotiating()
        disputed = dispute_lien(lien["id"])
        assert disputed["status"] == "DISPUTED"
        resumed = resume_lien(lien["id"])
        assert resumed["status"] == "NEGOTIATING"
