"""Listing agreements: one-active-per-vessel window, expiry cascades,
suspension offer block, syndication price discipline, accept visibility."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_version_incremented,
    create_listing_payload,
    create_syndication_event_payload,
    get_success_data,
    listing_headers,
    selling_headers,
    set_clock,
    setup_accepted_offer,
    setup_active_listing,
    submit_offer,
    accept_current_offer,
    validate_error,
    validate_success,
)


class TestOneActiveListingPerVessel:
    def test_second_listing_rejected_while_first_active(self, api):
        """PRD §3.3: "A vessel may carry only one non-terminal listing at a time,
        so drafting a second agreement while one stands in DRAFT, ACTIVE,
        SUSPENDED, or UNDER_CONTRACT is rejected with `ERR_DUPLICATE_RESOURCE`."

        Even a geometrically disjoint future window is rejected: occupancy is
        state-based, not interval-intersection.

        Design: Difficulty/resource_temporal_overlap/one_active_listing_per_vessel_window
        """
        deal = setup_active_listing(list_price_cents=600000000)
        res = api.create_listing(
            create_listing_payload(
                deal["brokerage"]["id"],
                deal["listing_agent"]["id"],
                deal["seller"]["id"],
                deal["vessel"]["id"],
                agreement_type="OPEN",
                list_price_cents=610000000,
                start_date="2027-01-01T00:00:00Z",
                end_date="2027-06-01T00:00:00Z",
            ),
            listing_headers(deal),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    def test_new_listing_allowed_after_first_cancelled(self, api):
        """PRD §3.3: "A seller walking away lets the agent cancel from ACTIVE or
        SUSPENDED, provided no offer on the listing stands ACCEPTED: the listing
        becomes CANCELLED" and "A vessel may carry only one non-terminal listing
        at a time" — once the first listing is terminal, drafting succeeds.

        Design: Difficulty/resource_temporal_overlap/one_active_listing_per_vessel_window
        """
        deal = setup_active_listing(list_price_cents=600000000)
        cancelled = validate_success(
            api.cancel_listing(deal["listing"]["id"], listing_headers(deal)), 200
        )
        assert cancelled["status"] == "CANCELLED"
        res = api.create_listing(
            create_listing_payload(
                deal["brokerage"]["id"],
                deal["listing_agent"]["id"],
                deal["seller"]["id"],
                deal["vessel"]["id"],
                agreement_type="OPEN",
                list_price_cents=610000000,
                start_date="2027-01-01T00:00:00Z",
                end_date="2027-06-01T00:00:00Z",
            ),
            listing_headers(deal),
        )
        validate_success(res, 201)


class TestListingExpiryCascade:
    def test_active_listing_expiry_cascades_to_offer_and_syndication(self, api):
        """PRD §3.3: "When the clock reaches `end_date`, the sweep expires an
        ACTIVE or SUSPENDED listing to EXPIRED with the same WITHDRAWN and
        offer-expiry cascades."
        PRD §3.4: "a listing's expiry or cancellation sweeps every such open
        offer on it to EXPIRED in the same motion."

        Design: Difficulty/transitive_cascade/listing_expiry_cascades_to_offers_and_syndication
        """
        deal = setup_active_listing(
            list_price_cents=150000000,
            listing_overrides={"end_date": "2026-08-15T00:00:00Z"},
        )
        listing_id = deal["listing"]["id"]
        push = validate_success(
            api.create_syndication_event(
                listing_id,
                create_syndication_event_payload(payload_price_cents=150000000),
                listing_headers(deal),
            ),
            201,
        )
        assert push["outcome"] == "ACKED"
        syndicated = get_success_data(api.get_listing(listing_id, listing_headers(deal)))
        assert syndicated["syndication_status"] == "SYNDICATED"

        offer = submit_offer(
            deal, offer_price_cents=140000000,
            acceptance_deadline="2026-08-20T00:00:00Z",
        )
        offer_version_before = offer["version"]

        set_clock("2026-08-16T00:00:00Z")

        listing_after = get_success_data(
            api.get_listing(listing_id, listing_headers(deal))
        )
        assert listing_after["status"] == "EXPIRED", listing_after
        assert listing_after["syndication_status"] == "WITHDRAWN"
        offer_after = get_success_data(
            api.get_offer(offer["id"], selling_headers(deal))
        )
        assert offer_after["status"] == "EXPIRED", (
            "offer deadline 2026-08-20 had not passed; expiry must come from the "
            "listing cascade"
        )
        assert_version_incremented(offer_after["version"], offer_version_before)

    def test_suspended_listing_expiry_cascades_identically(self, api):
        """PRD §3.3: "When the clock reaches `end_date`, the sweep expires an
        ACTIVE or SUSPENDED listing to EXPIRED with the same WITHDRAWN and
        offer-expiry cascades."
        PRD §2.5: "each advance runs the automated expiry sweeps — listing expiry
        at `end_date`, offer expiry past `acceptance_deadline`, and contingency
        expiry past `deadline` or past the objection cure window"

        Design: Difficulty/transitive_cascade/listing_expiry_cascades_to_offers_and_syndication
        """
        deal = setup_active_listing(
            list_price_cents=150000000,
            listing_overrides={"end_date": "2026-08-15T00:00:00Z"},
        )
        listing_id = deal["listing"]["id"]
        validate_success(
            api.create_syndication_event(
                listing_id,
                create_syndication_event_payload(payload_price_cents=150000000),
                listing_headers(deal),
            ),
            201,
        )
        offer = submit_offer(
            deal, offer_price_cents=140000000,
            acceptance_deadline="2026-08-20T00:00:00Z",
        )
        suspended = validate_success(
            api.suspend_listing(listing_id, listing_headers(deal)), 200
        )
        assert suspended["status"] == "SUSPENDED"

        set_clock("2026-08-16T00:00:00Z")

        listing_after = get_success_data(
            api.get_listing(listing_id, listing_headers(deal))
        )
        assert listing_after["status"] == "EXPIRED"
        assert listing_after["syndication_status"] == "WITHDRAWN"
        offer_after = get_success_data(
            api.get_offer(offer["id"], selling_headers(deal))
        )
        assert offer_after["status"] == "EXPIRED"


def test_offer_on_suspended_listing_rejected(api):
    """PRD §3.4: "the listing must be ACTIVE, or UNDER_CONTRACT under the
    kick-out rule, failing which the offer is rejected with
    `ERR_LISTING_NOT_ACCEPTING` (HTTP 409)."

    Design: Corner/validations/offer_on_suspended_listing_rejected
    """
    deal = setup_active_listing()
    validate_success(api.suspend_listing(deal["listing"]["id"], listing_headers(deal)))
    res = api.create_offer(
        {
            "listing_id": deal["listing"]["id"],
            "buyer_id": deal["buyer"]["id"],
            "selling_agent_id": deal["selling_agent"]["id"],
            "offer_price_cents": 95000000,
            "deposit_pct_basis": 1000,
            "acceptance_deadline": "2026-08-10T00:00:00Z",
            "settlement_state_code": "FL",
        },
        selling_headers(deal),
    )
    validate_error(res, ApiErrorId.ERR_LISTING_NOT_ACCEPTING)


def test_syndication_push_at_stale_price_rejected(api):
    """PRD §3.3: "a push at any other price or on a non-active listing is
    rejected with `ERR_SYNDICATION_STALE_PRICE` (HTTP 422)" and "the agent's
    price-change action writes the new `list_price_cents`, flips
    `syndication_status` to STALE until a fresh push goes out, and bumps the
    listing's `version`."

    Design: Corner/validations/syndication_stale_price_rejected
    """
    deal = setup_active_listing(list_price_cents=100000000)
    listing_id = deal["listing"]["id"]
    validate_success(
        api.update_listing_price(
            listing_id, {"list_price_cents": 110000000}, listing_headers(deal)
        ),
        200,
    )
    stale = get_success_data(api.get_listing(listing_id, listing_headers(deal)))
    assert stale["syndication_status"] == "STALE"

    res = api.create_syndication_event(
        listing_id,
        create_syndication_event_payload(payload_price_cents=100000000),
        listing_headers(deal),
    )
    validate_error(res, ApiErrorId.ERR_SYNDICATION_STALE_PRICE)


def test_listing_reflects_accept_immediately(api):
    """PRD §3.4: "Acceptance — guarded by the OCC field `expected_offer_version`
    — moves the offer to ACCEPTED and, in the same breath, the listing from
    ACTIVE to UNDER_CONTRACT"

    Design: Corner/consistency_model/immediate_consistency_listing_reflects_accept
    """
    deal = setup_active_listing()
    offer = submit_offer(deal)
    accepted = accept_current_offer(deal, offer)
    assert accepted["status"] == "ACCEPTED"
    listing = get_success_data(
        api.get_listing(deal["listing"]["id"], listing_headers(deal))
    )
    assert listing["status"] == "UNDER_CONTRACT", (
        "the very next read must show UNDER_CONTRACT — no eventual lag"
    )
