"""Difficulty Rule 7 — cross_entity_state_dependency.

Operations that require a coordinated state shape across two related entities:

  • DemandLetter draft requires Case.status==ACTIVE AND a REVIEWED MRR (PRD §3.4)
  • SettlementOffer accept requires NO MedicalLien in DISPUTED on the case (PRD §3.6)
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    negotiate_lien,
    dispute_lien,
    create_offer,
    get_case,
    get_case_version,
    ApiErrorId,
    api_client,
    create_demand_letter_payload,
    accept_offer_payload,
    make_attorney_headers,
    make_managing_partner_headers,
    setup_active_case_with_reviewed_records,
)


# =============================================================================
# Instance: demand_letter_requires_active_case_and_reviewed_records
# =============================================================================


class TestDemandLetterRequiresActiveCaseAndReviewedRecords:
    """A DemandLetter draft is allowed ONLY when both Case.status==ACTIVE and
    at least one MedicalRecordsRequest on the case has status==REVIEWED."""

    def _active_case_with_unreviewed_records(self):
        """Active CA case with a MedicalRecordsRequest still in REQUESTED."""
        set_clock("2026-01-01T00:00:00Z")
        c = register_client(email="ce1@example.com")
        sign_retainer(c["id"])
        case = create_case(c["id"], accident_date="2024-06-15",
                            jurisdiction="CA")
        activate_case(case["id"])
        provider = register_provider()
        # Deliberately do not receive/review.
        create_records_request(case["id"], provider["id"])
        return case["id"]

    def test_demand_draft_without_reviewed_records_returns_demand_prereq(self, api):
        """PRD §3.4: "Once the case is `ACTIVE` and at least one medical
        records request on it is `REVIEWED`, an `Attorney` drafts a demand
        letter, supplying the `case_id` and a `pain_multiplier`."
        PRD §3.4: "If the case is not `ACTIVE` or no `REVIEWED` records
        request is present, the draft is rejected with
        `ERR_DEMAND_PREREQUISITES_NOT_MET`."

        Design: Difficulty/cross_entity_state_dependency/demand_letter_requires_active_case_and_reviewed_records
        """
        case_id = self._active_case_with_unreviewed_records()
        headers = make_attorney_headers("drafter-7a")
        res = api_client.create_demand_letter(
            create_demand_letter_payload(case_id, pain_multiplier=1.5),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_DEMAND_PREREQUISITES_NOT_MET.value)

    def test_demand_draft_on_intake_case_returns_demand_prereq(self, api):
        """PRD §3.4: "If the case is not `ACTIVE` or no `REVIEWED` records
        request is present, the draft is rejected with
        `ERR_DEMAND_PREREQUISITES_NOT_MET`."

        Design: Difficulty/cross_entity_state_dependency/demand_letter_requires_active_case_and_reviewed_records
        """
        # Case in INTAKE (not activated). A reviewed records request exists,
        # but Case.status != ACTIVE.
        set_clock("2026-01-01T00:00:00Z")
        c = register_client(email="ce1b@example.com")
        sign_retainer(c["id"])
        case = create_case(c["id"], accident_date="2024-06-15",
                            jurisdiction="CA")
        # NOT activated — stays INTAKE.
        provider = register_provider()
        mrr = create_records_request(case["id"], provider["id"])
        walk_records_request_to_reviewed(mrr["id"])
        headers = make_attorney_headers("drafter-7b")
        res = api_client.create_demand_letter(
            create_demand_letter_payload(case["id"], pain_multiplier=1.5),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_DEMAND_PREREQUISITES_NOT_MET.value)


# =============================================================================
# Instance: settlement_accept_blocked_by_disputed_lien
# =============================================================================


class TestSettlementAcceptBlockedByDisputedLien:
    """A SettlementOffer cannot be accepted while ANY lien on the case is in
    status DISPUTED. The cross-entity pair is SettlementOffer ↔ MedicalLien."""

    def _build_case_in_negotiation_with_disputed_lien(self):
        """Active CA case in IN_NEGOTIATION; one MedicalLien on the case in
        DISPUTED status (NEGOTIATING → DISPUTED). One CARRIER PENDING offer."""
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
        dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                                   drafter_user_id="drafter-7c")
        send_demand_letter(dl["id"], partner_user_id="partner-7c")
        # Create lien, walk to DISPUTED.
        lien = create_lien(case["id"], provider["id"], 700_000)
        negotiate_lien(lien["id"])
        dispute_lien(lien["id"])
        # First CARRIER offer puts case in IN_NEGOTIATION.
        offer = create_offer(case["id"], 5_000_000, "CARRIER")
        return case["id"], offer["id"], lien["id"]

    def test_accept_with_disputed_lien_returns_disputed_lien_blocks_settlement(self, api):
        """PRD §3.6: "No medical lien on the case may be in `DISPUTED` status
        — the firm refuses to settle on top of an open lien dispute, so an
        attempt is rejected with `ERR_DISPUTED_LIEN_BLOCKS_SETTLEMENT` (this
        is the cross-entity guard that gives `DISPUTED` its operational
        teeth)."

        Design: Difficulty/cross_entity_state_dependency/settlement_accept_blocked_by_disputed_lien
        """
        case_id, offer_id, lien_id = self._build_case_in_negotiation_with_disputed_lien()
        case_v = get_case_version(case_id)
        headers = make_managing_partner_headers("partner-7c")
        res = api_client.accept_offer(
            offer_id, accept_offer_payload(case_v), headers
        )
        validate_error(res, ApiErrorId.ERR_DISPUTED_LIEN_BLOCKS_SETTLEMENT.value)

    def test_accept_blocked_offer_stays_pending_case_stays_in_negotiation(self, api):
        """PRD §3.6: "No medical lien on the case may be in `DISPUTED` status
        — the firm refuses to settle on top of an open lien dispute, so an
        attempt is rejected with `ERR_DISPUTED_LIEN_BLOCKS_SETTLEMENT` (this
        is the cross-entity guard that gives `DISPUTED` its operational
        teeth)."

        Design: Difficulty/cross_entity_state_dependency/settlement_accept_blocked_by_disputed_lien
        """
        from test_helpers import TEST_USERS
        case_id, offer_id, lien_id = self._build_case_in_negotiation_with_disputed_lien()
        case_v = get_case_version(case_id)
        headers = make_managing_partner_headers("partner-7d")
        api_client.accept_offer(offer_id, accept_offer_payload(case_v), headers)
        # Verify the failure left both sides in their pre-call state.
        h = TEST_USERS["attorney_headers"]
        offer_after = validate_success(api.get_offer(offer_id, h), 200)
        case_after = get_case(case_id)
        assert offer_after["status"] == "PENDING"
        assert case_after["status"] == "IN_NEGOTIATION"
