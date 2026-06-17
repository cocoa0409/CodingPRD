"""Authentication, role authorization, ownership, and validation precedence.

Translates the Difficulty priority_pair (ownership vs round-cap) and
cross_entity (publish requires seller active) instances, plus Corner validation,
error, and RBAC rows.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_seller_headers, make_buyer_headers, make_member_headers,
    TEST_USERS, fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MOD = TEST_USERS["moderator_headers"]


# ---------------------------------------------------------------------------
# Ownership vs round cap precedence (Difficulty: priority_pair)
# ---------------------------------------------------------------------------
class TestOwnershipBeatsRoundCap:
    def test_outsider_counter_at_round_cap_surfaces_not_owner(self, api):
        """PRD §2.8: "(3) resource ownership for ownership-scoped operations
        (ERR_NOT_RESOURCE_OWNER); ... then the domain-specific safety, temporal,
        constraint, referential, and fiscal checks described throughout Section 3
        ... Earlier checks mask later ones"
        PRD §2.1: "A member who is authenticated and holds an allowed role but is
        not the owner of the targeted resource is rejected with
        ERR_NOT_RESOURCE_OWNER (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/ownership_vs_round_cap_on_offer_counter
        """
        base = fx.setup_offer_at_round(5, ask_price_cents=10000,
                                       min_acceptable_price_cents=1000)
        assert base["offer"]["round_count"] == 5
        offer_id = base["offer"]["id"]
        outsider = fx.create_member(role_kind="BUYER", display_name="X")
        # Outsider is neither the conversation's buyer nor seller; ownership (3)
        # is checked before the round cap (13).
        validate_error(api.counter_offer(offer_id, {"amount_cents": 6000},
                                         headers=make_buyer_headers(outsider["id"])),
                       ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    def test_owner_counter_at_round_cap_surfaces_round_cap(self, api):
        """PRD §3.5: "a counter attempted once round_count has reached 5 is
        rejected with ERR_MAX_ROUNDS_REACHED (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/ownership_vs_round_cap_on_offer_counter
        """
        base = fx.setup_offer_at_round(5, ask_price_cents=10000,
                                       min_acceptable_price_cents=1000)
        assert base["offer"]["round_count"] == 5
        offer_id = base["offer"]["id"]
        buyer_id = base["buyer"]["id"]
        # Buyer IS the owner and IS entitled to respond (last move was seller),
        # so the only remaining failure is the round cap.
        validate_error(api.counter_offer(offer_id, {"amount_cents": 6000},
                                         headers=make_buyer_headers(buyer_id)),
                       ApiErrorId.ERR_MAX_ROUNDS_REACHED.value)


# ---------------------------------------------------------------------------
# Publish requires seller ACTIVE (Difficulty: cross_entity_state_dependency)
# ---------------------------------------------------------------------------
class TestPublishRequiresSellerActive:
    def test_suspended_seller_cannot_publish_draft(self, api):
        """PRD §3.3: "A suspended or banned seller attempting to publish is
        rejected with ERR_MEMBER_NOT_ACTIVE (HTTP 403)."

        Design: Difficulty/cross_entity_state_dependency/listing_publish_requires_seller_active
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        listing = fx.create_listing(seller["id"], ask_price_cents=10000,
                                    min_acceptable_price_cents=5000, title="Rug")
        get_success_data(api.suspend_member(seller["id"], headers=MOD))
        validate_error(api.publish_listing(listing["id"], headers=make_seller_headers(seller["id"])),
                       ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)
        fetched = validate_success(api.get_listing(listing["id"],
                                                   headers=make_member_headers(seller["id"])))
        assert fetched["publication_status"] == "DRAFT", "publish blocked by seller state"

    def test_active_seller_publishes_draft(self, api):
        """PRD §3.3: "Publication is permitted only when the listing is currently
        DRAFT; the seller's own status is ACTIVE"

        Design: Difficulty/cross_entity_state_dependency/listing_publish_requires_seller_active
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        listing = fx.create_listing(seller["id"], ask_price_cents=10000,
                                    min_acceptable_price_cents=5000, title="Rug")
        published = get_success_data(api.publish_listing(listing["id"],
                                                         headers=make_seller_headers(seller["id"])))
        assert published["publication_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: fiscal / category / participant / self-trade validations
# ---------------------------------------------------------------------------
class TestFiscalAndReferentialValidations:
    def test_self_trade_on_own_listing_rejected(self, api):
        """PRD §3.4: "A member may not open a conversation on their own listing —
        when the buyer_id equals the listing's seller_id the request is rejected
        with ERR_CANNOT_TRADE_OWN_LISTING (HTTP 422)"

        Design: Corner/validations/self_trade_on_own_listing_rejected
        """
        fx.create_category(slug="furniture", name="Furniture")
        member = fx.create_member(role_kind="BOTH", display_name="M")
        listing = fx.create_listing(member["id"], ask_price_cents=10000,
                                    min_acceptable_price_cents=5000, title="Desk")
        listing = fx.publish_listing(listing["id"], member["id"])
        validate_error(api.create_conversation(
            {"listing_id": listing["id"], "buyer_id": member["id"]},
            headers=make_buyer_headers(member["id"])),
            ApiErrorId.ERR_CANNOT_TRADE_OWN_LISTING.value)

    def test_floor_above_ask_rejected_on_create(self, api):
        """PRD §3.2: "the private floor must be coherent with the asking price:
        min_acceptable_price_cents must be at least 1 and at most the
        ask_price_cents; a floor above the ask (or below 1) is rejected with
        ERR_FLOOR_ABOVE_ASK (HTTP 422)."

        Design: Corner/validations/floor_above_ask_rejected_on_create
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        validate_error(api.create_listing(
            {"seller_id": seller["id"], "category_slug": "furniture",
             "title": "Desk", "description": "oak",
             "ask_price_cents": 5000, "min_acceptable_price_cents": 6000},
            headers=make_seller_headers(seller["id"])),
            ApiErrorId.ERR_FLOOR_ABOVE_ASK.value)

    def test_price_exceeds_category_cap_on_create(self, api):
        """PRD §3.2: "when the listing's category carries a non-zero
        max_price_cents, the ask_price_cents must not exceed that cap; an ask above
        a non-zero category cap is rejected with ERR_PRICE_EXCEEDS_CATEGORY_CAP
        (HTTP 422)."

        Design: Corner/validations/price_exceeds_category_cap_on_create
        """
        fx.create_category(slug="tickets", name="Tickets", max_price_cents=20000)
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        validate_error(api.create_listing(
            {"seller_id": seller["id"], "category_slug": "tickets",
             "title": "Concert", "description": "front row",
             "ask_price_cents": 25000, "min_acceptable_price_cents": 10000},
            headers=make_seller_headers(seller["id"])),
            ApiErrorId.ERR_PRICE_EXCEEDS_CATEGORY_CAP.value)

    def test_message_from_non_participant_rejected(self, api):
        """PRD §3.4: "The sender must be a participant of the thread — that is, the
        sender_id must equal the conversation's buyer_id or its seller_id; an
        outsider attempting to post is rejected with ERR_NOT_CONVERSATION_PARTICIPANT
        (HTTP 403)."

        Design: Corner/validations/message_from_non_participant_rejected
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        listing_id = base["listing"]["id"]
        buyer = fx.create_member(role_kind="BUYER", display_name="B")
        outsider = fx.create_member(role_kind="BUYER", display_name="X")
        conv = fx.create_conversation(listing_id, buyer["id"])
        validate_error(api.create_message(
            {"conversation_id": conv["id"], "sender_id": outsider["id"], "body": "hi"},
            headers=make_member_headers(outsider["id"])),
            ApiErrorId.ERR_NOT_CONVERSATION_PARTICIPANT.value)

    def test_phone_verification_gated_category_publish_rejected(self, api):
        """PRD §3.3: "A publish into a verification-gated category by an unverified
        seller is rejected with ERR_SELLER_NOT_PHONE_VERIFIED (HTTP 422)."

        Design: Corner/validations/phone_verification_gated_category_publish_rejected
        """
        fx.create_category(slug="vehicles", name="Vehicles",
                           requires_phone_verified_seller=True)
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        listing = fx.create_listing(seller["id"], category_slug="vehicles",
                                    title="Sedan", ask_price_cents=40000,
                                    min_acceptable_price_cents=30000)
        validate_error(api.publish_listing(listing["id"],
                                           headers=make_seller_headers(seller["id"])),
                       ApiErrorId.ERR_SELLER_NOT_PHONE_VERIFIED.value)
        fetched = validate_success(api.get_listing(listing["id"],
                                                   headers=make_member_headers(seller["id"])))
        assert fetched["publication_status"] == "DRAFT"

    def test_existence_checked_before_state_on_publish(self, api):
        """PRD §2.8: "(4) existence of every referenced resource, left to right
        (ERR_NOT_FOUND); (5) state validity ... Earlier checks mask later ones"

        Design: Corner/validations/validation_priority_existence_before_state_on_publish
        """
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        validate_error(api.publish_listing("11111111-1111-1111-1111-111111111111",
                                           headers=make_seller_headers(seller["id"])),
                       ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: auth and RBAC
# ---------------------------------------------------------------------------
class TestAuthAndRbac:
    def test_missing_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "When either header is missing or malformed on an endpoint
        that requires authentication, the request is rejected with
        ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_missing_headers
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        # No auth headers at all on a mutating endpoint.
        validate_error(api.create_listing(
            {"seller_id": seller["id"], "category_slug": "furniture",
             "title": "Desk", "description": "oak",
             "ask_price_cents": 10000, "min_acceptable_price_cents": 5000},
            headers={}),
            ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_buyer_cannot_publish_listing(self, api):
        """PRD §2.1: "When the headers are present and well-formed but the declared
        role is not among the roles authorized for the endpoint, the request is
        rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/buyer_cannot_publish_listing
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        buyer = fx.create_member(role_kind="BUYER", display_name="B")
        listing = fx.create_listing(seller["id"], ask_price_cents=10000,
                                    min_acceptable_price_cents=5000, title="Desk")
        validate_error(api.publish_listing(listing["id"],
                                           headers=make_buyer_headers(buyer["id"])),
                       ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_non_owner_seller_cannot_patch_others_listing(self, api):
        """PRD §2.1: "for listing operations the relevant key is the listing's
        seller_id ... A member who is authenticated and holds an allowed role but
        is not the owner of the targeted resource is rejected with
        ERR_NOT_RESOURCE_OWNER (HTTP 403)."

        Design: Corner/rbac/non_owner_seller_cannot_patch_others_listing
        """
        fx.create_category(slug="furniture", name="Furniture")
        s1 = fx.create_member(role_kind="SELLER", display_name="S1")
        s2 = fx.create_member(role_kind="SELLER", display_name="S2")
        listing = fx.create_listing(s1["id"], ask_price_cents=10000,
                                    min_acceptable_price_cents=5000, title="Desk")
        validate_error(api.patch_listing(listing["id"], {"ask_price_cents": 9000},
                                         headers=make_seller_headers(s2["id"])),
                       ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    def test_member_cannot_uphold_flag(self, api):
        """PRD §2.1: "the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
        PRD §3.7: "A Moderator resolves a flag from OPEN into one of two terminal
        branches with divergent effects."

        Design: Corner/rbac/member_cannot_uphold_flag
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        listing_id = base["listing"]["id"]
        reporter = fx.create_member(role_kind="BUYER", display_name="R")
        flag = fx.raise_listing_flag(listing_id, reporter["id"], reason="SPAM")
        validate_error(api.uphold_flag(flag["id"], headers=make_member_headers(reporter["id"])),
                       ApiErrorId.ERR_FORBIDDEN_ROLE.value)
