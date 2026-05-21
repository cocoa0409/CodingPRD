"""DisputeCase lifecycle — PRD §3.7.

Covers filing (PROVISIONAL → DISPUTED + DisputeCase=OPEN), claim
(OPEN → INVESTIGATING), cycle back via request-evidence
(INVESTIGATING → OPEN), and resolve with REFUND or REJECT.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    assert_dispute_case,
    create_dispute_payload,
    file_dispute,
    claim_dispute,
    get_trip,
    make_rider_headers,
    resolve_dispute,
    resolve_dispute_payload,
    setup_dispute_in_investigating,
    setup_rider_with_funded_card,
    tap_in_and_out,
    validate_error,
    validate_success,
)


class TestDisputeFiling:

    def test_file_dispute_creates_open_case_and_flips_fare_status(
            self, api):
        """PRD §3.7: "A rider may file a dispute on any trip whose
        `fare_status` is `PROVISIONAL` and whose owning card belongs
        to them. Filing creates a `DisputeCase` with the trip's
        `trip_id` and the filing rider's `rider_id`, starting in
        `status` `OPEN`; the trip's `fare_status` transitions from
        `PROVISIONAL` to `DISPUTED`."

        Claim: filing creates an OPEN DisputeCase and the trip's
        fare_status moves PROVISIONAL → DISPUTED."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        assert trip["fare_status"] == "PROVISIONAL"
        dispute = file_dispute(
            trip_id=trip["id"], rider_id=rider["id"],
        )
        assert_dispute_case(dispute)
        assert dispute["status"] == "OPEN"
        assert dispute["trip_id"] == trip["id"]
        # Trip fare_status must now be DISPUTED.
        re_read = get_trip(trip["id"])
        assert re_read["fare_status"] == "DISPUTED", (
            "Trip fare_status must move PROVISIONAL → DISPUTED on "
            f"file; got {re_read['fare_status']}"
        )


class TestDisputeClaimAndCycle:

    def test_claim_moves_open_to_investigating(
            self, api, agency_officer_headers):
        """PRD §3.7: "An `AgencyOfficer` may claim the dispute,
        transitioning `status` from `OPEN` to `INVESTIGATING`, only
        while the dispute is in `OPEN`."

        Claim: claim on an OPEN dispute moves it to INVESTIGATING."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        dispute = file_dispute(trip_id=trip["id"], rider_id=rider["id"])
        resp = api.claim_dispute(dispute["id"], agency_officer_headers)
        claimed = validate_success(resp, expected_status=200)
        assert claimed["status"] == "INVESTIGATING"

    def test_claim_on_non_open_rejected_invalid_state(
            self, api, agency_officer_headers):
        """PRD §3.7: "An `AgencyOfficer` may claim the dispute,
        transitioning `status` from `OPEN` to `INVESTIGATING`, only
        while the dispute is in `OPEN`; an attempt against any other
        state is rejected with `ERR_INVALID_STATE`."

        Claim: claim on an already-INVESTIGATING dispute →
        ERR_INVALID_STATE."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card, trip, dispute = setup_dispute_in_investigating()
        # Try to claim again.
        resp = api.claim_dispute(dispute["id"], agency_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_request_evidence_cycles_back_to_open(
            self, api, agency_officer_headers):
        """PRD §3.7: "From `INVESTIGATING` the officer has three
        options: request more evidence, which transitions `status`
        back to `OPEN` so the case can cycle".

        Claim: request-evidence on an INVESTIGATING dispute moves it
        back to OPEN."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card, trip, dispute = setup_dispute_in_investigating()
        resp = api.request_evidence_dispute(
            dispute["id"], agency_officer_headers,
        )
        cycled = validate_success(resp, expected_status=200)
        assert cycled["status"] == "OPEN"


class TestDisputeResolve:

    def test_resolve_refund_zeros_settled_and_refunds_wallet(
            self, api, agency_officer_headers):
        """PRD §3.7: "A REFUND resolution sets `refund_amount_cents`
        to the trip's `provisional_fare_cents`, transitions the trip's
        `fare_status` from `DISPUTED` to `SETTLED` with
        `settled_fare_cents` set to zero, splits the refund
        proportionally back to the `CommuterBenefitAccount.balance_cents`
        (in proportion to `paid_from_fsa_cents` over
        `provisional_fare_cents`) and back to the card's
        `wallet_balance_cents` (taking the difference)".

        Claim: REFUND on an INVESTIGATING dispute (no FSA, all from
        wallet) sets settled_fare_cents=0, refund_amount_cents=275,
        and credits the wallet by 275."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card, trip, dispute = setup_dispute_in_investigating(
            topup_cents=1000,
        )
        # Trip provisional was 275 (STANDARD card). Wallet now = 725.
        resp = api.resolve_dispute(
            dispute["id"],
            resolve_dispute_payload(decision="REFUND"),
            agency_officer_headers,
        )
        resolved = validate_success(resp, expected_status=200)
        assert resolved["status"] == "RESOLVED_REFUNDED"
        assert resolved["refund_amount_cents"] == 275
        # Trip fare_status → SETTLED, settled_fare_cents=0.
        from test_helpers import get_trip, get_card
        t_after = get_trip(trip["id"])
        assert t_after["fare_status"] == "SETTLED"
        assert t_after["settled_fare_cents"] == 0
        # Wallet restored.
        c_after = get_card(card["id"])
        assert c_after["wallet_balance_cents"] == 1000, (
            "Wallet must be restored to pre-tap amount after refund; "
            f"got {c_after['wallet_balance_cents']}"
        )

    def test_resolve_reject_writes_settled_equal_to_provisional(
            self, api, agency_officer_headers):
        """PRD §3.7: "A REJECT resolution simply transitions the
        trip's `fare_status` from `DISPUTED` to `SETTLED` with
        `settled_fare_cents` set equal to `provisional_fare_cents` and
        writes no refund."

        Claim: REJECT moves trip to SETTLED with settled_fare_cents ==
        provisional_fare_cents and the wallet unchanged."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card, trip, dispute = setup_dispute_in_investigating(
            topup_cents=1000,
        )
        resp = api.resolve_dispute(
            dispute["id"],
            resolve_dispute_payload(decision="REJECT"),
            agency_officer_headers,
        )
        resolved = validate_success(resp, expected_status=200)
        assert resolved["status"] == "RESOLVED_REJECTED"
        from test_helpers import get_trip, get_card
        t_after = get_trip(trip["id"])
        assert t_after["fare_status"] == "SETTLED"
        assert t_after["settled_fare_cents"] == t_after[
            "provisional_fare_cents"
        ], (
            "REJECT must leave settled_fare_cents == provisional_fare_cents"
        )
        c_after = get_card(card["id"])
        # Wallet still at pre-tap minus 275 (no refund).
        assert c_after["wallet_balance_cents"] == 1000 - 275

    def test_resolve_from_open_rejected_invalid_state(
            self, api, agency_officer_headers):
        """PRD §3.7: "Both terminal resolutions require the dispute to
        be in `INVESTIGATING`."

        Claim: resolve from OPEN (not yet claimed) → ERR_INVALID_STATE."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        dispute = file_dispute(trip_id=trip["id"], rider_id=rider["id"])
        assert dispute["status"] == "OPEN"
        resp = api.resolve_dispute(
            dispute["id"],
            resolve_dispute_payload(decision="REFUND"),
            agency_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
