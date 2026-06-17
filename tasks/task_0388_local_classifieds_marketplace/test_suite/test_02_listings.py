"""Listing creation, publication, expiry, renewal, and parallel state dimensions.

Translates Difficulty-queue instances on the Listing state machine plus the
Corner-queue entity / state-machine / validation rows that govern listing
lifecycle (create defaults, invalid transitions, expiry sweep, caps).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, assert_listing,
    make_seller_headers, make_buyer_headers, make_member_headers,
    TEST_USERS, fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Creation, system fields, defaults
# ---------------------------------------------------------------------------
class TestListingCreation:
    def test_create_listing_returns_201_with_initial_fields(self, api):
        """PRD §3.2: "A newly created listing begins with publication_status of
        DRAFT and sale_status of AVAILABLE; its expires_at is null, its
        renewal_count is 0, its open_offer_count and active_flag_count are 0, and
        its accepted_offer_id is null."
        PRD §2.4: "version is an integer that begins at the resource's creation
        value and increments by exactly one on every mutation that changes the
        resource."

        Design: Corner/entities/create_listing_returns_201_with_all_fields
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        resp = api.create_listing(
            {"seller_id": seller["id"], "category_slug": "furniture",
             "title": "Oak Desk", "description": "solid",
             "ask_price_cents": 10000, "min_acceptable_price_cents": 5000},
            headers=make_seller_headers(seller["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["publication_status"] == "DRAFT"
        assert data["sale_status"] == "AVAILABLE"
        assert data["version"] == 1
        assert data["ask_price_cents"] == 10000
        assert_listing(data, expect_floor=True)

    def test_new_listing_initial_state_is_draft_available(self, api):
        """PRD §3.2: "A newly created listing begins with publication_status of
        DRAFT and sale_status of AVAILABLE"

        Design: Corner/state_machines/new_listing_initial_state_is_draft_available
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        data = validate_success(api.create_listing(
            {"seller_id": seller["id"], "category_slug": "furniture",
             "title": "Desk", "description": "oak",
             "ask_price_cents": 10000, "min_acceptable_price_cents": 5000},
            headers=make_seller_headers(seller["id"])), expected_status=201)
        assert data["publication_status"] == "DRAFT"
        assert data["sale_status"] == "AVAILABLE"

    def test_listing_system_fields_ignore_client_input(self, api):
        """PRD §3.2: "A newly created listing begins with publication_status of
        DRAFT and sale_status of AVAILABLE; its expires_at is null, its
        renewal_count is 0, its open_offer_count and active_flag_count are 0, and
        its accepted_offer_id is null."

        Design: Corner/entities/listing_system_fields_ignore_client_input
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        # Client tries to dictate system fields; server must ignore them.
        data = validate_success(api.create_listing(
            {"seller_id": seller["id"], "category_slug": "furniture",
             "title": "Desk", "description": "oak",
             "ask_price_cents": 10000, "min_acceptable_price_cents": 5000,
             "publication_status": "ACTIVE", "expires_at": "2030-01-01T00:00:00Z",
             "version": 99},
            headers=make_seller_headers(seller["id"])), expected_status=201)
        assert data["publication_status"] == "DRAFT"
        assert data["expires_at"] is None
        assert data["version"] == 1

    def test_create_listing_missing_ask_price_returns_invalid_request(self, api):
        """PRD §3.2: "A Seller creates a listing by supplying its seller_id, the
        category_slug it belongs to, a title (non-empty, at most 120 characters),
        a description, an ask_price_cents (the publicly listed asking price, at
        least 1 cent), and a min_acceptable_price_cents (the seller's private
        floor)."

        Design: Corner/entities/create_listing_missing_ask_price_returns_invalid_request
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        validate_error(api.create_listing(
            {"seller_id": seller["id"], "category_slug": "furniture",
             "title": "Desk", "description": "oak",
             "min_acceptable_price_cents": 5000},
            headers=make_seller_headers(seller["id"])),
            ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_listing_requires_existing_category(self, api):
        """PRD §2.5: "The same left-to-right existence rule governs every foreign
        key supplied in a request body or path — a referenced listing_id,
        conversation_id, offer_id, spot_id, category_slug, or member identifier
        that does not resolve to an existing resource yields ERR_NOT_FOUND."

        Design: Corner/entities/listing_requires_existing_category
        """
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        validate_error(api.create_listing(
            {"seller_id": seller["id"], "category_slug": "ghost",
             "title": "Desk", "description": "oak",
             "ask_price_cents": 10000, "min_acceptable_price_cents": 5000},
            headers=make_seller_headers(seller["id"])),
            ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_listing_not_found_returns_404(self, api):
        """PRD §2.5: "a referenced listing_id ... that does not resolve to an
        existing resource yields ERR_NOT_FOUND."

        Design: Corner/entities/get_listing_not_found_returns_404
        """
        validate_error(
            api.get_listing("00000000-0000-0000-0000-000000000000", headers=ANON),
            ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Parallel publication & sale dimensions (Difficulty: non_linear_state_machine)
# ---------------------------------------------------------------------------
class TestParallelDimensions:
    def test_accept_reserves_sale_dimension_publication_stays_active(self, api):
        """PRD §3.5: "On acceptance the offer moves to ACCEPTED, the listing's
        sale_status moves from AVAILABLE to RESERVED, the listing's
        accepted_offer_id is set to the accepted offer"

        Design: Difficulty/non_linear_state_machine/listing_parallel_publication_and_sale_dimensions
        """
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=5000,
                                                amount_cents=9000)
        seller_id = base["seller"]["id"]
        get_success_data(api.accept_offer(
            base["offer"]["id"], {"expected_listing_version": base["listing_version"]},
            headers=make_seller_headers(seller_id)))
        listing = validate_success(api.get_listing(base["listing"]["id"],
                                                   headers=make_member_headers(seller_id)))
        assert listing["publication_status"] == "ACTIVE"
        assert listing["sale_status"] == "RESERVED"
        assert listing["accepted_offer_id"] == base["offer"]["id"]

    def test_publication_dimension_independent_of_reservation(self, api):
        """PRD §1 (intro): "listings carry two independent status dimensions at
        once, one tracking whether the post is published and one tracking whether
        the item is still for sale."
        PRD §3.5: "the listing's sale_status moves from AVAILABLE to RESERVED"

        Design: Difficulty/non_linear_state_machine/listing_parallel_publication_and_sale_dimensions
        """
        base = fx.setup_listing_with_open_offer(amount_cents=9000)
        seller_id = base["seller"]["id"]
        before = validate_success(api.get_listing(base["listing"]["id"],
                                                  headers=make_member_headers(seller_id)))
        assert before["publication_status"] == "ACTIVE"
        assert before["sale_status"] == "AVAILABLE"
        get_success_data(api.accept_offer(
            base["offer"]["id"], {"expected_listing_version": base["listing_version"]},
            headers=make_seller_headers(seller_id)))
        after = validate_success(api.get_listing(base["listing"]["id"],
                                                 headers=make_member_headers(seller_id)))
        # Publication dimension untouched while sale dimension advanced.
        assert after["publication_status"] == "ACTIVE"
        assert after["sale_status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Invalid transitions, expiry sweep, renewal caps
# ---------------------------------------------------------------------------
class TestPublicationTransitions:
    def test_publish_from_active_returns_invalid_state(self, api):
        """PRD §3.3: "Publication is permitted only when the listing is currently
        DRAFT"

        Design: Corner/state_machines/publish_from_active_returns_invalid_state
        """
        base = fx.setup_published_listing()
        seller_id = base["seller"]["id"]
        validate_error(api.publish_listing(base["listing"]["id"],
                                           headers=make_seller_headers(seller_id)),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_listing_expiry_sweep_via_clock_advance(self, api):
        """PRD §3.3: "When the clock is advanced to or beyond a listing's
        expires_at, an ACTIVE listing transitions to EXPIRED ... On expiry the
        seller's active_listing_count decrements by 1"

        Design: Corner/state_machines/listing_expiry_sweep_via_clock_advance
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        base = fx.setup_published_listing()
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        fx.advance_clock("2026-07-02T00:00:00Z")
        listing = validate_success(api.get_listing(listing_id,
                                                   headers=make_member_headers(seller_id)))
        assert listing["publication_status"] == "EXPIRED"
        member = validate_success(api.get_member(seller_id, headers=make_member_headers(seller_id)))
        assert member["active_listing_count"] == 0

    def test_active_listing_limit_on_fourth_publish(self, api):
        """PRD §3.3: "A seller who already holds 3 active listings is rejected with
        ERR_ACTIVE_LISTING_LIMIT (HTTP 409)."

        Design: Corner/validations/active_listing_limit_on_fourth_publish
        """
        setup = fx.setup_seller_with_active_listings(3)
        seller_id = setup["seller"]["id"]
        member = validate_success(api.get_member(seller_id, headers=make_member_headers(seller_id)))
        assert member["active_listing_count"] == 3
        validate_error(api.publish_listing(setup["draft_listing"]["id"],
                                           headers=make_seller_headers(seller_id)),
                       ApiErrorId.ERR_ACTIVE_LISTING_LIMIT.value)

    def test_renew_cap_reached_rejected(self, api):
        """PRD §3.3: "a renew when the renewal_count has already reached 2 is
        rejected with ERR_MAX_RENEWALS_REACHED (HTTP 409)."

        Design: Corner/validations/renew_cap_reached_rejected
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        base = fx.setup_published_listing()
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        get_success_data(api.renew_listing(listing_id, headers=make_seller_headers(seller_id)))
        renewed = get_success_data(api.renew_listing(listing_id, headers=make_seller_headers(seller_id)))
        assert renewed["renewal_count"] == 2
        validate_error(api.renew_listing(listing_id, headers=make_seller_headers(seller_id)),
                       ApiErrorId.ERR_MAX_RENEWALS_REACHED.value)


# ---------------------------------------------------------------------------
# Listing search / pagination
# ---------------------------------------------------------------------------
class TestListingSearch:
    def test_list_listings_pagination_envelope(self, api):
        """PRD §2.3: "The meta block of a list response carries the pagination
        fields limit, offset, total_count (the total number of records matching
        the query before the page window is applied), and has_more (a boolean
        that is true when records remain beyond the current page)."

        Design: Corner/endpoints/list_listings_pagination_envelope
        """
        setup = fx.setup_seller_with_active_listings(3)
        # setup_seller_with_active_listings leaves one extra DRAFT; filter ACTIVE.
        seller_id = setup["seller"]["id"]
        resp = api.list_listings(headers=ANON, params={
            "seller_id": seller_id, "publication_status": "ACTIVE",
            "limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, "limit honored"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
