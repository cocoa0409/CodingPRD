"""Optimistic concurrency control on offer accept and meetup create.

Translates the Corner cross_cutting OCC instances and the Corner error row for
stale offer version. (The concurrency_rules themselves are exercised
sequentially; OCC's version check at commit time makes the outcome
deterministic without a race.)
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_seller_headers, make_buyer_headers, make_member_headers,
    TEST_USERS, fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestAcceptOCC:
    # NOTE: test_second_accept_with_stale_listing_version_rejected was removed.
    # PRD does not uniquely determine the asserted outcome (STEP 1b / ERROR
    # PRECEDENCE collapse). The scenario (accept a sibling offer after a first
    # accept) puts the sibling in REJECTED via the §3.5 acceptance cascade
    # ("every sibling offer on that listing still in PROPOSED or COUNTERED is
    # cascaded to REJECTED"). §2.8's controlling ordering rule then applies the
    # state check (priority 5) before the OCC check (priority 6) — "a request
    # against a resource in the wrong state never reaches the concurrency check"
    # — so a faithful implementer surfaces ERR_INVALID_STATE, not the asserted
    # ERR_STALE_LISTING_VERSION. The §2.7 sibling-accept narrative is an
    # illustrative aside that conflicts with §2.8+§3.5; the two faithful readings
    # diverge, so the test is not uniquely derivable from PRD prose.

    def test_accept_with_current_listing_version_succeeds(self, api):
        """PRD §2.7: "Accepting an offer requires the request to carry
        expected_listing_version, a non-optional field that must equal the current
        version of the offer's Listing."
        PRD §3.5: "On acceptance the offer moves to ACCEPTED, the listing's
        sale_status moves from AVAILABLE to RESERVED ... and both the listing's
        version and the offer's version increment by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_listing_version_accept_succeeds
        """
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=5000,
                                                amount_cents=9000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        listing_version = base["listing_version"]
        accepted = get_success_data(api.accept_offer(
            base["offer"]["id"], {"expected_listing_version": listing_version},
            headers=make_seller_headers(seller_id)))
        assert accepted["status"] == "ACCEPTED"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["sale_status"] == "RESERVED"
        assert listing["version"] == listing_version + 1


class TestMeetupCreateOCC:
    def test_meetup_create_with_stale_offer_version_rejected(self, api):
        """PRD §2.7: "if the offer's version has advanced since the client read it
        (for example, because a compensation withdrew and the offer was
        re-accepted), the client's expected_offer_version is stale and the create
        is rejected with ERR_STALE_OFFER_VERSION (HTTP 412)."

        Design: Corner/errors/error_stale_offer_version_on_meetup_create
        """
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="City Hall Lobby",
                                         open_minute_of_day=480, close_minute_of_day=1080)
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        buyer = fx.create_member(role_kind="BUYER", display_name="B")
        conv = fx.create_conversation(listing_id, buyer["id"])
        offer = fx.create_offer(conv["id"], buyer["id"], amount_cents=9000)
        offer_version_old = offer["version"]
        # Accept advances the offer's version beyond offer_version_old.
        get_success_data(api.accept_offer(
            offer["id"], {"expected_listing_version": base["listing_version"]},
            headers=make_seller_headers(seller_id)))
        validate_error(api.create_meetup(
            {"offer_id": offer["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T14:00:00Z", "end_at": "2026-06-02T15:00:00Z",
             "expected_offer_version": offer_version_old},
            headers=make_buyer_headers(buyer["id"])),
            ApiErrorId.ERR_STALE_OFFER_VERSION.value)
