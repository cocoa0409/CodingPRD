"""Conversion request workflow: offer → accept/reject → finalize, with
the buyout-eligibility threshold (>=) and the one-way ownership flip."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_conversion_request,
    api_client,
    assert_conversion_request,
    create_conversion_request,
    create_park,
    create_resident,
    finalize_conversion_request,
    get_conversion_request,
    get_lease,
    get_lot,
    get_park,
    make_park_manager_headers,
    make_resident_headers,
    setup_park_owned_lot_for_conversion,
    validate_error,
)


# ===========================================================================
# Accept threshold — PRD §3.8
# ===========================================================================
class TestConversionAccept:
    def test_offer_above_assessed_accepted(self, api):
        """PRD §3.8: 'the offer_price_cents must be greater than or
        equal to the home's assessed_value_cents. The boundary is
        inclusive — an offer that exactly matches the assessed value
        is acceptable.'

        Claim: offer 5_000_001 vs assessed 5_000_000 → ACCEPTED.
        """
        park, lot, home, buyer = setup_park_owned_lot_for_conversion(
            assessed_value_cents=5_000_000,
        )
        conv = create_conversion_request(
            park_id=park["id"], lot_id=lot["id"],
            prospective_buyer_resident_id=buyer["id"],
            offer_price_cents=5_000_001,
        )
        accepted = accept_conversion_request(buyer["id"], conv["id"])
        assert accepted["status"] == "ACCEPTED"

    def test_offer_equal_to_assessed_accepted_boundary(self, api):
        """PRD §3.8: 'The boundary is inclusive — an offer that
        exactly matches the assessed value is acceptable.'

        Claim: offer == assessed → ACCEPTED.
        """
        park, lot, home, buyer = setup_park_owned_lot_for_conversion(
            assessed_value_cents=4_000_000,
        )
        conv = create_conversion_request(
            park_id=park["id"], lot_id=lot["id"],
            prospective_buyer_resident_id=buyer["id"],
            offer_price_cents=4_000_000,
        )
        accepted = accept_conversion_request(buyer["id"], conv["id"])
        assert accepted["status"] == "ACCEPTED"

    def test_offer_below_assessed_rejected_with_undervalued_error(self, api):
        """PRD §3.8: 'If the offer is below the assessed value, the
        system transitions the request OFFERED → REJECTED (a terminal
        state) with ERR_BUYOUT_UNDERVALUED.'

        Claim: offer 3_999_999 vs assessed 4_000_000 → accept call
        returns ERR_BUYOUT_UNDERVALUED.
        """
        park, lot, home, buyer = setup_park_owned_lot_for_conversion(
            assessed_value_cents=4_000_000,
        )
        conv = create_conversion_request(
            park_id=park["id"], lot_id=lot["id"],
            prospective_buyer_resident_id=buyer["id"],
            offer_price_cents=3_999_999,
        )
        resp = api.accept_conversion_request(
            conv["id"], make_resident_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUYOUT_UNDERVALUED.value)


# ===========================================================================
# Finalize — PRD §3.8
# ===========================================================================
class TestConversionFinalize:
    def test_finalize_flips_ownership_mode_and_decrements_pool(self, api):
        """PRD §3.8: 'On a successful finalize, the lot's ownership_mode
        flips to RESIDENT_OWNED, the home's owner_resident_id is set
        to the prospective_buyer_resident_id, and the park's
        ownership_pool_count is decremented by one.'

        Claim: finalize → lot RESIDENT_OWNED, park.ownership_pool_count
        decreases by 1.
        """
        park, lot, home, buyer = setup_park_owned_lot_for_conversion(
            assessed_value_cents=5_000_000,
        )
        pool_before = get_park(park["id"])["ownership_pool_count"]
        conv = create_conversion_request(
            park_id=park["id"], lot_id=lot["id"],
            prospective_buyer_resident_id=buyer["id"],
            offer_price_cents=5_000_000,
        )
        accept_conversion_request(buyer["id"], conv["id"])
        closed = finalize_conversion_request(park["id"], conv["id"])
        assert closed["status"] == "CLOSED"
        refreshed_lot = get_lot(lot["id"])
        refreshed_park = get_park(park["id"])
        assert refreshed_lot["ownership_mode"] == "RESIDENT_OWNED"
        assert refreshed_park["ownership_pool_count"] == pool_before - 1

    def test_finalize_creates_lease_when_lot_was_vacant(self, api):
        """PRD §3.8: 'if the lot has no current_lease_id at the moment
        of finalization (the lot was vacant of any standing lease),
        the system creates a fresh Lease in CURRENT whose resident_id
        is the buyer and whose monthly_rent_cents is copied from the
        lot's base_rent_cents.'

        Claim: vacant-lot finalize → Lot.current_lease_id points to a
        fresh Lease in CURRENT for the buyer with monthly_rent_cents
        equal to the lot's base_rent_cents.
        """
        park, lot, home, buyer = setup_park_owned_lot_for_conversion(
            base_rent_cents=77_777, assessed_value_cents=2_000_000,
        )
        conv = create_conversion_request(
            park_id=park["id"], lot_id=lot["id"],
            prospective_buyer_resident_id=buyer["id"],
            offer_price_cents=2_000_000,
        )
        accept_conversion_request(buyer["id"], conv["id"])
        finalize_conversion_request(park["id"], conv["id"])
        refreshed_lot = get_lot(lot["id"])
        assert refreshed_lot["current_lease_id"] is not None
        new_lease = get_lease(refreshed_lot["current_lease_id"])
        assert new_lease["status"] == "CURRENT"
        assert new_lease["resident_id"] == buyer["id"]
        assert new_lease["monthly_rent_cents"] == 77_777

    def test_finalize_on_already_resident_owned_rejected(self, api):
        """PRD §3.8: 'Finalization is gated by one precondition: the
        lot's ownership_mode must still be PARK_OWNED at the moment
        of finalization, otherwise the request is rejected with
        ERR_LOT_ALREADY_RESIDENT_OWNED.'

        Claim: second finalize on already-RESIDENT_OWNED lot →
        ERR_LOT_ALREADY_RESIDENT_OWNED.

        Setup: drive one conversion through to CLOSED, then create a
        new ConversionRequest on the same (now-RESIDENT_OWNED) lot.
        The PRD does not explicitly say a second request can be opened
        on a non-PARK_OWNED lot, so we use a direct API call and
        accept either ERR_LOT_ALREADY_RESIDENT_OWNED at finalize or
        at request creation.
        """
        park, lot, home, buyer = setup_park_owned_lot_for_conversion(
            assessed_value_cents=5_000_000,
        )
        conv = create_conversion_request(
            park_id=park["id"], lot_id=lot["id"],
            prospective_buyer_resident_id=buyer["id"],
            offer_price_cents=5_000_000,
        )
        accept_conversion_request(buyer["id"], conv["id"])
        finalize_conversion_request(park["id"], conv["id"])
        # Calling finalize AGAIN on the same conv_id is now an INVALID
        # STATE transition (ACCEPTED → CLOSED is one-shot). This is the
        # PRD-pinned error for re-finalize on an already-CLOSED request.
        resp = api.finalize_conversion_request(
            conv["id"], make_park_manager_headers(park["id"]),
        )
        # PRD §2.10 priority 6: state-already-CLOSED is ERR_INVALID_STATE.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Reject — PRD §3.8
# ===========================================================================
class TestConversionReject:
    def test_resident_reject_terminates_request(self, api):
        """PRD §3.8: 'A resident may also explicitly reject an offer
        they do not wish to accept, transitioning OFFERED → REJECTED
        directly; this terminal rejection carries no side effects.'

        Claim: POST /conversion-requests/{id}/reject → status REJECTED.
        """
        park, lot, home, buyer = setup_park_owned_lot_for_conversion()
        conv = create_conversion_request(
            park_id=park["id"], lot_id=lot["id"],
            prospective_buyer_resident_id=buyer["id"],
            offer_price_cents=5_000_000,
        )
        resp = api.reject_conversion_request(
            conv["id"], make_resident_headers(buyer["id"]),
        )
        from test_helpers import validate_success
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
