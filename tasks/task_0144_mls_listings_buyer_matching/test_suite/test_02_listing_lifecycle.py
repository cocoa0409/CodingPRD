"""Listing CRUD, fiscal validation, withdraw/close paths, ownership
enforcement on listing_agent_id == X-User-ID.

Cites PRD §3.2 (Bringing a Listing to Market) and §2.6 (OCC).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_listing,
    create_listing,
    create_listing_agent,
    create_listing_payload,
    create_buyer_agent,
    make_listing_agent_headers,
    patch_listing_payload,
    validate_error,
    validate_success,
    withdraw_listing,
)


class TestCreateListing:
    """PRD §3.2."""

    def test_create_listing_succeeds_with_valid_inputs(self, api):
        """PRD §3.2: 'On success the listing is created in ACTIVE
        status with no accepted offer (accepted_offer_id is null) and
        a showing_count of zero.'

        Claim: POST /listings returns a Listing with status=ACTIVE,
        accepted_offer_id null, showing_count 0.
        """
        la = create_listing_agent()
        res = api.create_listing(
            create_listing_payload(listing_agent_id=la["id"]),
            make_listing_agent_headers(la["id"]),
        )
        listing = validate_success(res, 201)
        assert_listing(listing)
        assert listing["status"] == "ACTIVE"
        assert listing.get("accepted_offer_id") is None
        assert listing["showing_count"] == 0
        assert listing["version"] == 1

    def test_listing_agent_id_must_equal_x_user_id(self, api):
        """PRD §3.2: 'The server requires that listing_agent_id equal
        X-User-ID; a ListingAgent cannot list property on behalf of
        another agent.'

        Claim: POST /listings with a listing_agent_id different from
        X-User-ID → ERR_FORBIDDEN_NOT_OWNER.
        """
        la1 = create_listing_agent()
        la2 = create_listing_agent()
        payload = create_listing_payload(listing_agent_id=la2["id"])
        # Submit as la1; payload's listing_agent_id is la2.
        res = api.create_listing(
            payload, make_listing_agent_headers(la1["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)


class TestListingFiscalBounds:
    """PRD §3.2 fiscal validation."""

    def test_list_price_below_min_rejected(self, api):
        """PRD §3.2: 'the asking price must be at least 1,000,000 cents
        (ten thousand US dollars), ... If any of these is violated the
        listing is rejected with ERR_INVALID_LISTING_FIELDS.'

        Claim: list_price_cents = 999_999 → ERR_INVALID_LISTING_FIELDS.
        """
        la = create_listing_agent()
        res = api.create_listing(
            create_listing_payload(
                listing_agent_id=la["id"], list_price_cents=999_999,
            ),
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_LISTING_FIELDS.value)

    def test_list_price_at_min_accepted(self, api):
        """PRD §3.2: 'the asking price must be at least 1,000,000
        cents'. Boundary inclusive.

        Claim: list_price_cents = exactly 1_000_000 → success.
        """
        la = create_listing_agent()
        res = api.create_listing(
            create_listing_payload(
                listing_agent_id=la["id"], list_price_cents=1_000_000,
            ),
            make_listing_agent_headers(la["id"]),
        )
        listing = validate_success(res, 201)
        assert listing["list_price_cents"] == 1_000_000

    def test_co_op_pct_above_006_rejected(self, api):
        """PRD §3.2: 'the buyer-side co-op fraction must lie between 0
        and 0.06 inclusive ... If any of these is violated the listing
        is rejected with ERR_INVALID_LISTING_FIELDS.'

        Claim: co_op_pct = 0.07 → ERR_INVALID_LISTING_FIELDS.
        """
        la = create_listing_agent()
        res = api.create_listing(
            create_listing_payload(
                listing_agent_id=la["id"],
                co_op_pct=0.07, total_commission_pct=0.08,
            ),
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_LISTING_FIELDS.value)

    def test_total_commission_below_co_op_rejected(self, api):
        """PRD §3.2: 'the combined commission fraction must be at least
        as large as the co-op fraction and no greater than 0.10.'

        Claim: total_commission_pct < co_op_pct →
        ERR_INVALID_LISTING_FIELDS.
        """
        la = create_listing_agent()
        res = api.create_listing(
            create_listing_payload(
                listing_agent_id=la["id"],
                co_op_pct=0.025, total_commission_pct=0.020,
            ),
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_LISTING_FIELDS.value)

    def test_total_commission_above_010_rejected(self, api):
        """PRD §3.2: 'the combined commission fraction must be ... no
        greater than 0.10.'

        Claim: total_commission_pct = 0.11 → ERR_INVALID_LISTING_FIELDS.
        """
        la = create_listing_agent()
        res = api.create_listing(
            create_listing_payload(
                listing_agent_id=la["id"],
                co_op_pct=0.025, total_commission_pct=0.11,
            ),
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_LISTING_FIELDS.value)

    def test_zip_code_not_five_digits_rejected(self, api):
        """PRD §3.2: 'The zip_code must be exactly 5 digits.'

        Claim: zip_code='9411' (4 digits) → ERR_INVALID_LISTING_FIELDS.
        """
        la = create_listing_agent()
        res = api.create_listing(
            create_listing_payload(
                listing_agent_id=la["id"], zip_code="9411",
            ),
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_LISTING_FIELDS.value)


class TestListingPatchOcc:
    """PRD §3.2 listing edit + §2.6 OCC."""

    def test_patch_listing_updates_price_and_version(self, api):
        """PRD §2.6: 'Every successful mutation refreshes updated_at
        and increments version by 1 on the directly mutated row.'

        Claim: PATCH /listings/{id} with version match increments
        version by 1 and writes new price.
        """
        la = create_listing_agent()
        listing = create_listing(la, list_price_cents=50_000_000)
        v0 = listing["version"]
        res = api.patch_listing(
            listing["id"],
            patch_listing_payload(
                version=v0, list_price_cents=51_000_000,
            ),
            make_listing_agent_headers(la["id"]),
        )
        updated = validate_success(res, 200)
        assert updated["list_price_cents"] == 51_000_000
        assert updated["version"] == v0 + 1

    def test_patch_listing_stale_version_rejected(self, api):
        """PRD §2.6: 'If the supplied version does not equal the stored
        version of the target row, the request is rejected with
        ERR_VERSION_CONFLICT and HTTP 409.'

        Claim: PATCH /listings/{id} with a stale `version` →
        ERR_VERSION_CONFLICT.
        """
        la = create_listing_agent()
        listing = create_listing(la)
        # First PATCH bumps version.
        api.patch_listing(
            listing["id"],
            patch_listing_payload(
                version=listing["version"], list_price_cents=52_000_000,
            ),
            make_listing_agent_headers(la["id"]),
        )
        # Re-use the stale version.
        res = api.patch_listing(
            listing["id"],
            patch_listing_payload(
                version=listing["version"], list_price_cents=53_000_000,
            ),
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestListingWithdraw:
    """PRD §3.2 withdraw + cascade."""

    def test_withdraw_active_listing_with_no_offers_succeeds(self, api):
        """PRD §3.2: 'Withdrawing transitions the listing from ACTIVE
        to WITHDRAWN, cancels every open showing on the listing ... and
        disarms the attached lockbox.'

        Claim: Withdraw of ACTIVE listing with no SUBMITTED offers →
        listing.status == WITHDRAWN.
        """
        from test_helpers import create_listing_with_armed_lockbox
        la, listing, lockbox = create_listing_with_armed_lockbox()
        res = api.withdraw_listing(
            listing["id"], {"version": listing["version"]},
            make_listing_agent_headers(la["id"]),
        )
        withdrawn = validate_success(res, 200)
        assert withdrawn["status"] == "WITHDRAWN"

    def test_withdraw_lockbox_cascades_to_disarmed(self, api):
        """PRD §3.5: 'when a listing transitions from ACTIVE to
        WITHDRAWN, or from ACTIVE to EXPIRED via the sweep, the
        attached lockbox is disarmed by cascade.'

        Claim: After withdrawing a listing, the attached lockbox is
        DISARMED.
        """
        from test_helpers import create_listing_with_armed_lockbox
        la, listing, lockbox = create_listing_with_armed_lockbox()
        assert lockbox["status"] == "ARMED"
        withdraw_listing(listing, la)
        # Re-fetch the lockbox indirectly by re-arming: arm requires
        # DISARMED, so arming should now succeed indicating the cascade
        # disarmed the lockbox. But arm on a non-ACTIVE listing is
        # disallowed (PRD §3.5: arming requires the listing be ACTIVE).
        # So instead, fetch listing and check the showing_count is 0
        # and assert lockbox transition through a fresh GET path.
        # Use a side-channel: requesting a showing on a WITHDRAWN
        # listing should fail with ERR_INVALID_STATE. Skip — directly
        # assert via test-friendly read: list lockbox is not exposed as
        # GET. Instead, attempt to disarm again — disarm of DISARMED
        # box must return ERR_LOCKBOX_STATE.
        res = api.disarm_lockbox(
            listing["id"], make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOCKBOX_STATE.value)

    def test_withdraw_with_submitted_offer_rejected_invalid_state(
        self, api,
    ):
        """PRD §3.2: 'A listing in ACTIVE status may be withdrawn from
        the market — but only if no offer on it is currently in
        SUBMITTED status; submitted offers must first be either
        rejected or allowed to expire, otherwise the withdraw is
        rejected as an invalid state.'

        Claim: Withdraw on a listing with a SUBMITTED offer →
        ERR_INVALID_STATE.
        """
        from test_helpers import setup_listing_and_buyer, submit_offer
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        submit_offer(listing, buyer, ba)
        res = api.withdraw_listing(
            listing["id"], {"version": listing["version"]},
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestListingClosePreconditions:
    """PRD §3.7 close requires all contingencies SATISFIED or WAIVED."""

    def test_close_active_listing_rejected(self, api):
        """PRD §3.7: 'Closing a listing is the listing agent's explicit
        move from UNDER_CONTRACT to SOLD.'

        Claim: Close on a listing still in ACTIVE → ERR_INVALID_STATE.
        """
        la = create_listing_agent()
        listing = create_listing(la)
        res = api.close_listing(
            listing["id"], {"version": listing["version"]},
            make_listing_agent_headers(la["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
