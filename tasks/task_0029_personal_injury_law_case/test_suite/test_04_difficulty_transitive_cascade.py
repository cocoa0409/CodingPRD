"""Difficulty Rule 4 — transitive_cascade.

Multi-hop cascades where each hop is caused by the previous one:

  • SettlementOffer accept → Case SETTLED → liens AGREED + court events CANCELLED +
    Disbursement PENDING with all three derived amounts computed (PRD §3.6, §3.7)
  • DemandLetter send → Case ACTIVE → DEMAND_SENT (PRD §3.4)
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
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    negotiate_lien,
    create_offer,
    create_court_event,
    accept_offer,
    get_case_version,
    get_case,
    get_disbursement_for_case,
    setup_active_case_with_reviewed_records,
)


# =============================================================================
# Instance: settlement_accept_three_hop_cascade
# =============================================================================


class TestSettlementAcceptThreeHopCascade:
    """Accepting a settlement offer triggers a depth-3 cascade: offer→case→
    {liens, court events, disbursement} all in the same operation."""

    def _build_settled_case(self):
        """Build the canonical pre-suit settle scenario:
          - Active CA case at 2026-01-01
          - REVIEWED records, INCLUDED damages totalling 4_400_000
          - DemandLetter SENT
          - One SCHEDULED HEARING in 2026-08
          - One MedicalLien NEGOTIATING at 1_500_000
          - One CARRIER PENDING offer at 6_000_000
        """
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
        create_included_damages(case["id"], "LOST_WAGES", 500_000)
        create_included_damages(case["id"], "FUTURE_MEDICAL", 600_000)
        create_included_damages(case["id"], "PROPERTY", 300_000)
        create_included_damages(case["id"], "PAIN_SUFFERING", 2_000_000)
        dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                                   drafter_user_id="drafter-4a")
        send_demand_letter(dl["id"], partner_user_id="partner-4a")
        event = create_court_event(case["id"], "HEARING",
                                    "2026-08-01T14:00:00Z", duration_minutes=60)
        lien = create_lien(case["id"], provider["id"], 1_500_000)
        negotiate_lien(lien["id"])
        offer = create_offer(case["id"], 6_000_000, "CARRIER")
        return case["id"], offer["id"], lien["id"], event["id"]

    def test_accept_settles_case_and_stamps_gross_settlement(self, api):
        """PRD §3.6: "When all guards pass, the offer transitions `PENDING →
        ACCEPTED`, its `responded_at` is stamped, and the parent case
        auto-transitions to `SETTLED` (as a depth-two cascade from either
        `IN_NEGOTIATION → SETTLED` or `LITIGATION → SETTLED` depending on
        where the case was). The accepting offer's `offer_amount_cents` is
        stamped onto the case as `gross_settlement_cents`."

        Design: Difficulty/transitive_cascade/settlement_accept_three_hop_cascade
        """
        from test_helpers import TEST_USERS
        case_id, offer_id, lien_id, event_id = self._build_settled_case()
        case_v = get_case_version(case_id)
        accept_offer(offer_id, case_v, partner_user_id="partner-4a")

        offer_after = validate_success(
            api.get_offer(offer_id, TEST_USERS["attorney_headers"]), 200
        )
        case_after = get_case(case_id)
        assert offer_after["status"] == "ACCEPTED"
        assert offer_after["responded_at"] is not None
        assert case_after["status"] == "SETTLED"
        assert case_after["gross_settlement_cents"] == 6_000_000

    def test_accept_cancels_scheduled_court_events_and_settles_liens(self, api):
        """PRD §3.6: "Three further cascades fire as depth-two effects of the
        case settling. First, every medical lien on the case whose status is
        `ASSERTED` or `NEGOTIATING` is auto-transitioned to `AGREED`, and each
        such lien's `negotiated_amount_cents` is set to the lesser of its
        `asserted_amount_cents` and the proportional cap defined by the lien
        waterfall described in §3.7 (the cap computation is a depth-three
        effect, fanning out across the lien set). Second, every `SCHEDULED`
        court event on the case is moved to `CANCELLED` — the docket is
        cleared."

        Design: Difficulty/transitive_cascade/settlement_accept_three_hop_cascade
        """
        from test_helpers import TEST_USERS
        case_id, offer_id, lien_id, event_id = self._build_settled_case()
        case_v = get_case_version(case_id)
        accept_offer(offer_id, case_v, partner_user_id="partner-4b")
        h = TEST_USERS["attorney_headers"]
        lien_after = validate_success(api.get_lien(lien_id, h), 200)
        event_after = validate_success(api.get_court_event(event_id, h), 200)
        # Lien transitioned to AGREED at its asserted amount (well below distributable).
        assert lien_after["status"] == "AGREED"
        assert lien_after["negotiated_amount_cents"] == 1_500_000
        # Scheduled hearing was cancelled by the case-settling cascade.
        assert event_after["status"] == "CANCELLED"

    def test_accept_creates_disbursement_with_three_amounts_computed(self, api):
        """PRD §3.6: "Third, a `Disbursement` row in `PENDING` status is
        created for the case, and its `contingency_fee_cents`,
        `total_lien_payout_cents`, and `net_to_client_cents` are computed at
        creation per §3.7 (again, depth-three calculations inside the
        depth-two disbursement creation)."

        Design: Difficulty/transitive_cascade/settlement_accept_three_hop_cascade
        """
        case_id, offer_id, lien_id, event_id = self._build_settled_case()
        case_v = get_case_version(case_id)
        accept_offer(offer_id, case_v, partner_user_id="partner-4c")
        disb = get_disbursement_for_case(case_id)
        # Pre-suit (filed_in_court=false): fee=1_999_800.
        # Single lien at 1_500_000 (below distributable=4_000_200) → paid in full.
        # net = 6_000_000 - 1_999_800 - 1_500_000 = 2_500_200.
        assert disb["status"] == "PENDING"
        assert disb["contingency_fee_cents"] == 1_999_800
        assert disb["total_lien_payout_cents"] == 1_500_000
        assert disb["net_to_client_cents"] == 2_500_200


# =============================================================================
# Instance: demand_send_cascade_to_case_demand_sent
# =============================================================================


class TestDemandSendCascadeToCaseDemandSent:
    """Sending a DemandLetter triggers a depth-2 cascade: letter→case.
    The Case ACTIVE→DEMAND_SENT transition has NO direct endpoint — it can
    only be reached through this cascade."""

    def _build_active_case_with_draft_demand(self):
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                                   drafter_user_id="drafter-4d")
        return case["id"], dl["id"]

    def test_send_demand_flips_letter_to_sent_and_stamps_sent_at(self, api):
        """PRD §3.4: "Sending stamps `sent_at` with the current clock and
        enforces three preconditions: the case must be `ACTIVE`, at least one
        `REVIEWED` records request must still be present, and the
        segregation-of-duties guard must hold — the `ManagingPartner`'s
        `X-User-ID` must not equal the letter's stored `drafted_by_user_id`."

        Design: Difficulty/transitive_cascade/demand_send_cascade_to_case_demand_sent
        """
        from test_helpers import TEST_USERS
        case_id, dl_id = self._build_active_case_with_draft_demand()
        send_demand_letter(dl_id, partner_user_id="partner-4d")
        dl_after = validate_success(
            api.get_demand_letter(dl_id, TEST_USERS["attorney_headers"]), 200
        )
        assert dl_after["status"] == "SENT"
        assert dl_after["sent_at"] is not None

    def test_send_demand_cascades_case_active_to_demand_sent(self, api):
        """PRD §3.4: "Sending the letter also cascades up: as a depth-two side
        effect, the parent case auto-transitions `ACTIVE → DEMAND_SENT`,
        refreshing the case's `updated_at` and incrementing `Case.version` by
        one."

        Design: Difficulty/transitive_cascade/demand_send_cascade_to_case_demand_sent
        """
        case_id, dl_id = self._build_active_case_with_draft_demand()
        case_before = get_case(case_id)
        send_demand_letter(dl_id, partner_user_id="partner-4e")
        case_after = get_case(case_id)
        assert case_before["status"] == "ACTIVE"
        assert case_after["status"] == "DEMAND_SENT"
        assert case_after["version"] > case_before["version"]
