"""Offers and the cyclic negotiation loop.

Translates the Difficulty non_linear_state_machine cyclic-counter and
boundary_precision instances on Offer, plus Corner rows for turn order, round
cap, sibling cascade, terminal lockdown, offer expiry sweep, OCC on accept, FK
copy integrity, and immediate-consistency of open_offer_count.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_seller_headers, make_buyer_headers, make_member_headers,
    TEST_USERS, fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Cyclic counter rounds (Difficulty: non_linear_state_machine)
# ---------------------------------------------------------------------------
class TestCyclicCounter:
    def test_three_counter_rounds_alternate_sides(self, api):
        """PRD §3.5: "A counter sets the offer's status to COUNTERED, records the
        new amount_cents, flips last_actor_side to the acting side, increments
        round_count by 1, and refreshes expires_at to the current clock plus 48
        hours"

        Design: Difficulty/non_linear_state_machine/offer_cyclic_counter_rounds
        """
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=1000,
                                                amount_cents=5000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        offer_id = base["offer"]["id"]
        # B proposed (round 0, last_actor_side BUYER). S, B, S counter -> round 3.
        get_success_data(api.counter_offer(offer_id, {"amount_cents": 8000},
                                           headers=make_seller_headers(seller_id)))
        get_success_data(api.counter_offer(offer_id, {"amount_cents": 6000},
                                           headers=make_buyer_headers(buyer_id)))
        last = get_success_data(api.counter_offer(offer_id, {"amount_cents": 7000},
                                                  headers=make_seller_headers(seller_id)))
        assert last["status"] == "COUNTERED"
        assert last["round_count"] == 3
        assert last["last_actor_side"] == "SELLER"

    def test_counter_increments_round_each_loop(self, api):
        """PRD §3.5: "A counter ... increments round_count by 1 ... Because a
        counter moves an already-open offer to another open state, it leaves the
        listing's open_offer_count unchanged."

        Design: Difficulty/non_linear_state_machine/offer_cyclic_counter_rounds
        """
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=1000,
                                                amount_cents=5000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        offer_id = base["offer"]["id"]
        listing_id = base["listing"]["id"]
        r1 = get_success_data(api.counter_offer(offer_id, {"amount_cents": 8000},
                                                headers=make_seller_headers(seller_id)))
        assert r1["round_count"] == 1 and r1["last_actor_side"] == "SELLER"
        r2 = get_success_data(api.counter_offer(offer_id, {"amount_cents": 6000},
                                                headers=make_buyer_headers(buyer_id)))
        assert r2["round_count"] == 2 and r2["last_actor_side"] == "BUYER"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["open_offer_count"] == 1, "counter leaves open_offer_count unchanged"


# ---------------------------------------------------------------------------
# Floor inclusive boundary (Difficulty: boundary_precision_check)
# ---------------------------------------------------------------------------
class TestFloorBoundary:
    def test_offer_at_floor_proposed_below_floor_rejected(self, api):
        """PRD §3.5: "The boundary is inclusive on acceptance: when the actor is
        the buyer and the proposed amount_cents is strictly below the listing's
        min_acceptable_price_cents, the offer is created and then immediately
        transitioned to REJECTED, and it is not counted in the listing's
        open_offer_count (it never net-enters the open set). An offer exactly at
        the floor is allowed through."

        Design: Difficulty/boundary_precision_check/offer_floor_inclusive_boundary
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=8000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        b1 = fx.create_member(role_kind="BUYER", display_name="B1")
        b2 = fx.create_member(role_kind="BUYER", display_name="B2")
        conv1 = fx.create_conversation(listing_id, b1["id"])
        conv2 = fx.create_conversation(listing_id, b2["id"])
        at_floor = get_success_data(api.create_offer(
            {"conversation_id": conv1["id"], "amount_cents": 8000},
            headers=make_buyer_headers(b1["id"])))
        below = get_success_data(api.create_offer(
            {"conversation_id": conv2["id"], "amount_cents": 7999},
            headers=make_buyer_headers(b2["id"])))
        assert at_floor["status"] == "PROPOSED", "offer exactly at floor is allowed"
        assert below["status"] == "REJECTED", "offer below floor is auto-rejected"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["open_offer_count"] == 1, "only the at-floor offer entered the open set"

    def test_offer_one_above_floor_proposed(self, api):
        """PRD §3.5: "when the actor is the buyer and the proposed amount_cents is
        strictly below the listing's min_acceptable_price_cents, the offer is
        created and then immediately transitioned to REJECTED ... An offer exactly
        at the floor is allowed through."

        Design: Difficulty/boundary_precision_check/offer_floor_inclusive_boundary
        """
        # X+1 side of the boundary: 8001 (above floor 8000) must be PROPOSED.
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=8000)
        listing_id = base["listing"]["id"]
        buyer = fx.create_member(role_kind="BUYER", display_name="B")
        conv = fx.create_conversation(listing_id, buyer["id"])
        offer = get_success_data(api.create_offer(
            {"conversation_id": conv["id"], "amount_cents": 8001},
            headers=make_buyer_headers(buyer["id"])))
        assert offer["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Empty offer pool (Difficulty: boundary_precision_check)
# ---------------------------------------------------------------------------
class TestEmptyOfferPool:
    def test_fresh_listing_has_zero_open_offers(self, api):
        """PRD §3.2: "its open_offer_count and active_flag_count are 0"
        PRD §3.5: "The listing's open_offer_count is a strictly conserved
        denormalized counter: at all times it must equal the number of offers on
        that listing whose status is PROPOSED or COUNTERED."

        Design: Difficulty/boundary_precision_check/empty_offer_pool_listing_has_zero_open_offers
        """
        base = fx.setup_published_listing()
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        resp = api.list_listing_offers(listing_id, headers=make_seller_headers(seller_id))
        data, meta = validate_paginated(resp)
        assert data == [], "no offers yet"
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["open_offer_count"] == 0

    def test_empty_offer_listing_offers_array_envelope(self, api):
        """PRD §2.2: "The response_type is either "object" for a single resource
        or "array" for a list of resources."
        PRD §3.5: "The listing's open_offer_count is a strictly conserved
        denormalized counter: at all times it must equal the number of offers on
        that listing whose status is PROPOSED or COUNTERED."

        Design: Difficulty/boundary_precision_check/empty_offer_pool_listing_has_zero_open_offers
        """
        base = fx.setup_published_listing()
        seller_id = base["seller"]["id"]
        resp = api.list_listing_offers(base["listing"]["id"],
                                       headers=make_seller_headers(seller_id))
        data, _ = validate_paginated(resp)
        assert isinstance(data, list) and len(data) == 0


# ---------------------------------------------------------------------------
# Turn order, round cap, terminal lockdown, sibling cascade
# ---------------------------------------------------------------------------
class TestNegotiationGuards:
    def test_counter_when_not_your_turn_rejected(self, api):
        """PRD §3.5: "A counter attempted by the side that just moved is rejected
        with ERR_NOT_YOUR_TURN (HTTP 409)"

        Design: Corner/state_machines/counter_when_not_your_turn_rejected
        """
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=1000,
                                                amount_cents=5000)
        buyer_id = base["buyer"]["id"]
        # Buyer just proposed (last_actor_side BUYER); a buyer counter is not their turn.
        validate_error(api.counter_offer(base["offer"]["id"], {"amount_cents": 5500},
                                         headers=make_buyer_headers(buyer_id)),
                       ApiErrorId.ERR_NOT_YOUR_TURN.value)

    def test_counter_on_withdrawn_offer_returns_invalid_state(self, api):
        """PRD §3.5: "Withdrawing is the buyer's prerogative: only the offer's
        buyer may withdraw, moving a PROPOSED or COUNTERED offer to WITHDRAWN"
        PRD §3.5: "A counter takes a new amount_cents and is permitted only when
        the offer's status is PROPOSED or COUNTERED"

        Design: Corner/state_machines/counter_on_withdrawn_offer_returns_invalid_state
        """
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=1000,
                                                amount_cents=5000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        offer_id = base["offer"]["id"]
        get_success_data(api.withdraw_offer(offer_id, headers=make_buyer_headers(buyer_id)))
        validate_error(api.counter_offer(offer_id, {"amount_cents": 6000},
                                         headers=make_seller_headers(seller_id)),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_max_rounds_reached_on_sixth_counter(self, api):
        """PRD §3.5: "a counter attempted once round_count has reached 5 is
        rejected with ERR_MAX_ROUNDS_REACHED (HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_offer_round_cap_boundary
        """
        base = fx.setup_offer_at_round(5, ask_price_cents=10000,
                                       min_acceptable_price_cents=1000)
        assert base["offer"]["round_count"] == 5
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        offer_id = base["offer"]["id"]
        # last_actor_side after 5 rounds (S,B,S,B,S) is SELLER, so buyer is entitled.
        validate_error(api.counter_offer(offer_id, {"amount_cents": 7000},
                                         headers=make_buyer_headers(buyer_id)),
                       ApiErrorId.ERR_MAX_ROUNDS_REACHED.value)

    def test_accept_offer_rejects_sibling_offers_cascade(self, api):
        """PRD §3.5: "every sibling offer on that listing still in PROPOSED or
        COUNTERED is cascaded to REJECTED; the listing's open_offer_count is
        reconciled downward to remove both the accepted offer and each rejected
        sibling from the open set"

        Design: Corner/state_machines/accept_offer_rejects_sibling_offers_cascade
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        b1 = fx.create_member(role_kind="BUYER", display_name="B1")
        b2 = fx.create_member(role_kind="BUYER", display_name="B2")
        conv1 = fx.create_conversation(listing_id, b1["id"])
        conv2 = fx.create_conversation(listing_id, b2["id"])
        off1 = fx.create_offer(conv1["id"], b1["id"], amount_cents=9000)
        off2 = fx.create_offer(conv2["id"], b2["id"], amount_cents=8500)
        accepted = get_success_data(api.accept_offer(
            off1["id"], {"expected_listing_version": base["listing_version"]},
            headers=make_seller_headers(seller_id)))
        assert accepted["status"] == "ACCEPTED"
        sibling = validate_success(api.get_offer(off2["id"], headers=make_member_headers(b2["id"])))
        assert sibling["status"] == "REJECTED"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["open_offer_count"] == 0


# ---------------------------------------------------------------------------
# Offer expiry sweep, FK copy integrity, immediate consistency
# ---------------------------------------------------------------------------
class TestOfferLifecycleAndDerived:
    def test_offer_expiry_sweep_via_clock_advance(self, api):
        """PRD §3.5: "When the clock advances to or beyond an offer's expires_at,
        a PROPOSED or COUNTERED offer transitions to EXPIRED, its open_offer_count
        contribution is removed (the listing's counter decrements by 1)"

        Design: Corner/state_machines/offer_expiry_sweep_via_clock_advance
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=1000,
                                                amount_cents=5000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        offer_id, listing_id = base["offer"]["id"], base["listing"]["id"]
        fx.advance_clock("2026-06-04T00:00:00Z")
        offer = validate_success(api.get_offer(offer_id, headers=make_member_headers(buyer_id)))
        assert offer["status"] == "EXPIRED"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["open_offer_count"] == 0

    def test_offer_copies_listing_and_party_fks_from_conversation(self, api):
        """PRD §3.5: "At creation, the offer's listing_id, buyer_id, and seller_id
        are copied from the conversation"

        Design: Corner/entities/flat_topology_fk_integrity_offer_listing_id_copied
        """
        base = fx.setup_published_listing()
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        buyer = fx.create_member(role_kind="BUYER", display_name="B")
        conv = fx.create_conversation(listing_id, buyer["id"])
        offer = get_success_data(api.create_offer(
            {"conversation_id": conv["id"], "amount_cents": 9000},
            headers=make_buyer_headers(buyer["id"])))
        assert offer["listing_id"] == listing_id
        assert offer["seller_id"] == seller_id
        assert offer["buyer_id"] == buyer["id"]

    def test_open_offer_count_visible_immediately(self, api):
        """PRD §2.6: "The platform maintains several denormalized counters that
        must remain exactly consistent with the records they summarize, recomputed
        synchronously inside the request that disturbs them."
        PRD §3.5: "a fresh proposal adds 1"

        Design: Corner/consistency_model/immediate_consistency_open_offer_count_in_same_response
        """
        base = fx.setup_published_listing()
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        buyer = fx.create_member(role_kind="BUYER", display_name="B")
        conv = fx.create_conversation(listing_id, buyer["id"])
        fx.create_offer(conv["id"], buyer["id"], amount_cents=9000)
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["open_offer_count"] == 1


# ---------------------------------------------------------------------------
# Reverse-reachability read
# ---------------------------------------------------------------------------
class TestListingOffersRead:
    def test_listing_offers_includes_cascade_rejected_sibling(self, api):
        """PRD §3.5: "every sibling offer on that listing still in PROPOSED or
        COUNTERED is cascaded to REJECTED"

        Design: Corner/endpoints/computed_read_listing_offers_reverse_reachability
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        b1 = fx.create_member(role_kind="BUYER", display_name="B1")
        b2 = fx.create_member(role_kind="BUYER", display_name="B2")
        conv1 = fx.create_conversation(listing_id, b1["id"])
        conv2 = fx.create_conversation(listing_id, b2["id"])
        off1 = fx.create_offer(conv1["id"], b1["id"], amount_cents=9000)
        off2 = fx.create_offer(conv2["id"], b2["id"], amount_cents=8500)
        get_success_data(api.accept_offer(
            off1["id"], {"expected_listing_version": base["listing_version"]},
            headers=make_seller_headers(seller_id)))
        resp = api.list_listing_offers(listing_id, headers=make_seller_headers(seller_id))
        data, _ = validate_paginated(resp)
        by_id = {o["id"]: o for o in data}
        assert len(data) == 2
        assert by_id[off1["id"]]["status"] == "ACCEPTED"
        assert by_id[off2["id"]]["status"] == "REJECTED"
