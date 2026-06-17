"""Meetup scheduling: operating-hours containment, overlap collisions,
high-value police gating, validation precedence, and the cross-entity
precondition that a meetup requires an ACCEPTED offer / RESERVED listing.

Translates Difficulty instances combinatorial_formula (hours-then-overlap
ordering), priority_pair (state vs temporal), cross_entity_state_dependency
(meetup requires reserved), and resource_temporal_overlap (overlap + hours),
plus Corner validation rows for high-value police gating.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_seller_headers, make_buyer_headers, make_member_headers,
    TEST_USERS, fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Operating-hours containment at CREATE (Difficulty: resource_temporal_overlap
# and combinatorial_formula validation order)
# ---------------------------------------------------------------------------
class TestOperatingHours:
    def test_meetup_outside_spot_hours_rejected_at_create(self, api):
        """PRD §3.6: "The window must also be contained within the spot's
        operating hours: converting the meetup's start and end to minutes-of-day,
        the start minute-of-day must be at or after the spot's open_minute_of_day
        and the end minute-of-day must be at or before the spot's
        close_minute_of_day. A meetup whose window falls outside the spot's
        operating hours, spans midnight, or has an end_at at or before its
        start_at is rejected with ERR_OUTSIDE_SPOT_HOURS (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/spot_operating_hours_window_containment
        """
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="Mall Kiosk",
                                         open_minute_of_day=480, close_minute_of_day=1020)
        base = fx.setup_reserved_listing(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        buyer_id = base["buyer"]["id"]
        # 16:30-17:30: end minute-of-day 1050 exceeds close 1020.
        validate_error(api.create_meetup(
            {"offer_id": base["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T16:30:00Z", "end_at": "2026-06-02T17:30:00Z",
             "expected_offer_version": base["offer_version"]},
            headers=make_buyer_headers(buyer_id)),
            ApiErrorId.ERR_OUTSIDE_SPOT_HOURS.value)

    def test_window_ending_exactly_at_close_is_contained(self, api):
        """PRD §3.6: "the start minute-of-day must be at or after the spot's
        open_minute_of_day and the end minute-of-day must be at or before the
        spot's close_minute_of_day."

        Design: Difficulty/resource_temporal_overlap/spot_operating_hours_window_containment
        """
        # close 1020 (17:00); a window 16:00-17:00 has end minute-of-day 1020,
        # which is exactly at close — inclusive on the upper bound, so contained.
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="Mall Kiosk",
                                         open_minute_of_day=480, close_minute_of_day=1020)
        base = fx.setup_reserved_listing(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        buyer_id = base["buyer"]["id"]
        meetup = validate_success(api.create_meetup(
            {"offer_id": base["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T16:00:00Z", "end_at": "2026-06-02T17:00:00Z",
             "expected_offer_version": base["offer_version"]},
            headers=make_buyer_headers(buyer_id)), expected_status=201)
        assert meetup["status"] == "PROPOSED"

    def test_meetup_create_hours_checked_before_overlap(self, api):
        """PRD §3.6: "A meetup whose window falls outside the spot's operating
        hours, spans midnight, or has an end_at at or before its start_at is
        rejected with ERR_OUTSIDE_SPOT_HOURS (HTTP 422)."

        Design: Difficulty/combinatorial_formula/meetup_create_validation_order_pins_hours_then_overlap
        """
        # Hours containment is evaluated at CREATE; overlap is only evaluated at
        # CONFIRM. A window outside hours can never reach the confirm-time overlap
        # gate, so the create surfaces ERR_OUTSIDE_SPOT_HOURS.
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="City Hall Lobby",
                                         open_minute_of_day=480, close_minute_of_day=1080)
        base = fx.setup_reserved_listing(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        buyer_id = base["buyer"]["id"]
        # 19:00-20:00 is past close 18:00 (1080).
        resp = api.create_meetup(
            {"offer_id": base["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T19:00:00Z", "end_at": "2026-06-02T20:00:00Z",
             "expected_offer_version": base["offer_version"]},
            headers=make_buyer_headers(buyer_id))
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SPOT_HOURS.value)
        # No meetup persisted for the offer.
        meetups, _ = validate_paginated(api.list_offer_meetups(
            base["offer"]["id"], headers=make_member_headers(buyer_id)))
        assert meetups == [], "no Meetup persisted when create fails on hours"

    def test_within_hours_window_creates_meetup(self, api):
        """PRD §3.6: "The window must also be contained within the spot's
        operating hours: converting the meetup's start and end to minutes-of-day,
        the start minute-of-day must be at or after the spot's open_minute_of_day
        and the end minute-of-day must be at or before the spot's
        close_minute_of_day."

        Design: Difficulty/combinatorial_formula/meetup_create_validation_order_pins_hours_then_overlap
        """
        # A window fully inside [08:00, 18:00) passes the create-time hours gate;
        # the create therefore succeeds (the confirm-time overlap gate is a later,
        # separate step never reached at create).
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="City Hall Lobby",
                                         open_minute_of_day=480, close_minute_of_day=1080)
        base = fx.setup_reserved_listing(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        buyer_id = base["buyer"]["id"]
        meetup = validate_success(api.create_meetup(
            {"offer_id": base["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T14:00:00Z", "end_at": "2026-06-02T15:00:00Z",
             "expected_offer_version": base["offer_version"]},
            headers=make_buyer_headers(buyer_id)), expected_status=201)
        assert meetup["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Confirm-time overlap, half-open semantics (Difficulty: resource_temporal_overlap)
# ---------------------------------------------------------------------------
class TestOverlapCollision:
    def test_confirm_collides_with_confirmed_meetup(self, api):
        """PRD §3.6: "the candidate meetup's interval must not collide with any
        other CONFIRMED meetup at the same spot_id. Intervals are treated as
        half-open [start_at, end_at) in absolute UTC, and two intervals collide if
        and only if the first starts strictly before the second ends and the
        second starts strictly before the first ends ... A colliding confirmation
        is rejected with ERR_SPOT_TIME_CONFLICT (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/spot_confirmed_meetup_overlap_halfopen
        """
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="City Hall Lobby",
                                         open_minute_of_day=480, close_minute_of_day=1080)
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        # Listing A: confirm 14:00-15:00.
        ba = self._reserved(api, seller, "A")
        mt_a = get_success_data(api.create_meetup(
            {"offer_id": ba["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T14:00:00Z", "end_at": "2026-06-02T15:00:00Z",
             "expected_offer_version": ba["offer"]["version"]},
            headers=make_buyer_headers(ba["buyer"]["id"])))
        get_success_data(api.confirm_meetup(mt_a["id"], headers=make_seller_headers(seller["id"])))
        # Listing B: 14:30-15:30 overlaps MT_A by 30 minutes.
        bb = self._reserved(api, seller, "B")
        mt_b = get_success_data(api.create_meetup(
            {"offer_id": bb["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T14:30:00Z", "end_at": "2026-06-02T15:30:00Z",
             "expected_offer_version": bb["offer"]["version"]},
            headers=make_buyer_headers(bb["buyer"]["id"])))
        validate_error(api.confirm_meetup(mt_b["id"], headers=make_seller_headers(seller["id"])),
                       ApiErrorId.ERR_SPOT_TIME_CONFLICT.value)
        still = validate_success(api.get_meetup(mt_b["id"], headers=make_member_headers(bb["buyer"]["id"])))
        assert still["status"] == "PROPOSED"

    def test_adjacent_meetup_does_not_collide(self, api):
        """PRD §3.6: "under this rule a meetup ending exactly when another begins
        does not collide (adjacency is allowed, zero overlap)."

        Design: Difficulty/resource_temporal_overlap/spot_confirmed_meetup_overlap_halfopen
        """
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="City Hall Lobby",
                                         open_minute_of_day=480, close_minute_of_day=1080)
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        ba = self._reserved(api, seller, "A")
        mt_a = get_success_data(api.create_meetup(
            {"offer_id": ba["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T14:00:00Z", "end_at": "2026-06-02T15:00:00Z",
             "expected_offer_version": ba["offer"]["version"]},
            headers=make_buyer_headers(ba["buyer"]["id"])))
        get_success_data(api.confirm_meetup(mt_a["id"], headers=make_seller_headers(seller["id"])))
        # 15:00-16:00 touches MT_A's end; half-open semantics -> no collision.
        bb = self._reserved(api, seller, "B")
        mt_b = get_success_data(api.create_meetup(
            {"offer_id": bb["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T15:00:00Z", "end_at": "2026-06-02T16:00:00Z",
             "expected_offer_version": bb["offer"]["version"]},
            headers=make_buyer_headers(bb["buyer"]["id"])))
        confirmed = get_success_data(api.confirm_meetup(mt_b["id"],
                                                        headers=make_seller_headers(seller["id"])))
        assert confirmed["status"] == "CONFIRMED"

    def _reserved(self, api, seller, tag):
        """Helper: build a published listing under `seller` with an accepted
        offer, returning {buyer, offer(accepted)}."""
        buyer = fx.create_member(role_kind="BUYER", display_name=f"B{tag}")
        listing = fx.create_listing(seller["id"], title=f"Desk {tag}",
                                    ask_price_cents=10000,
                                    min_acceptable_price_cents=5000)
        listing = fx.publish_listing(listing["id"], seller["id"])
        conv = fx.create_conversation(listing["id"], buyer["id"])
        offer = fx.create_offer(conv["id"], buyer["id"], amount_cents=9000)
        accepted = get_success_data(api.accept_offer(
            offer["id"], {"expected_listing_version": listing["version"]},
            headers=make_seller_headers(seller["id"])))
        return {"buyer": buyer, "offer": accepted}


# ---------------------------------------------------------------------------
# State-vs-temporal precedence (Difficulty: priority_pair_validation_conflict)
# ---------------------------------------------------------------------------
class TestStateVsTemporalPrecedence:
    def test_reconfirm_confirmed_meetup_surfaces_invalid_state(self, api):
        """PRD §2.8: "(5) state validity — the target must be in a state from
        which the requested transition is defined (ERR_INVALID_STATE) ... then the
        domain-specific safety, temporal, constraint, referential, and fiscal
        checks described throughout Section 3 ... Earlier checks mask later ones"
        PRD §3.6: "A successful confirmation moves the meetup from PROPOSED to
        CONFIRMED and increments its version by 1."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_meetup_confirm
        """
        base = fx.setup_meetup_confirmed(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        seller_id = base["seller"]["id"]
        # Meetup already CONFIRMED; re-confirm is an undefined transition (state
        # check at priority 5 fires before any temporal overlap at priority 11).
        validate_error(api.confirm_meetup(base["meetup"]["id"],
                                          headers=make_seller_headers(seller_id)),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_confirm_proposed_meetup_succeeds_baseline(self, api):
        """PRD §3.6: "Confirmation is performed by the counterparty — the side
        that did not propose the meetup confirms it — and is permitted only from a
        PROPOSED meetup whose listing is still RESERVED with the listing's
        accepted_offer_id equal to this meetup's offer_id."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_meetup_confirm
        """
        base = fx.setup_meetup_proposed(ask_price_cents=10000,
                                        min_acceptable_price_cents=5000,
                                        amount_cents=9000)
        seller_id = base["seller"]["id"]
        confirmed = get_success_data(api.confirm_meetup(base["meetup"]["id"],
                                                        headers=make_seller_headers(seller_id)))
        assert confirmed["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Cross-entity precondition: meetup requires accepted offer / reserved listing
# ---------------------------------------------------------------------------
class TestMeetupRequiresReserved:
    def test_meetup_against_proposed_offer_rejected(self, api):
        """PRD §3.6: "Once an offer has been accepted and its listing reserved,
        either party schedules a meetup against that offer"
        PRD §2.8: "(5) state validity — the target must be in a state from which
        the requested transition is defined (ERR_INVALID_STATE)"

        Design: Difficulty/cross_entity_state_dependency/meetup_create_requires_offer_accepted_and_listing_reserved
        """
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="City Hall Lobby",
                                         open_minute_of_day=480, close_minute_of_day=1080)
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=5000,
                                                amount_cents=9000)
        buyer_id = base["buyer"]["id"]
        # Offer is still PROPOSED (never accepted); listing is AVAILABLE.
        validate_error(api.create_meetup(
            {"offer_id": base["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T14:00:00Z", "end_at": "2026-06-02T15:00:00Z",
             "expected_offer_version": base["offer"]["version"]},
            headers=make_buyer_headers(buyer_id)),
            ApiErrorId.ERR_INVALID_STATE.value)

    def test_meetup_against_accepted_offer_succeeds(self, api):
        """PRD §3.6: "Once an offer has been accepted and its listing reserved,
        either party schedules a meetup against that offer by supplying the
        offer_id, the spot_id where the exchange will happen, a proposed start_at
        (inclusive) and end_at (exclusive), and the expected_offer_version"

        Design: Difficulty/cross_entity_state_dependency/meetup_create_requires_offer_accepted_and_listing_reserved
        """
        base = fx.setup_meetup_proposed(ask_price_cents=10000,
                                        min_acceptable_price_cents=5000,
                                        amount_cents=9000)
        assert base["meetup"]["status"] == "PROPOSED"
        assert base["meetup"]["offer_id"] == base["offer"]["id"]


# ---------------------------------------------------------------------------
# High-value police-verified gating (Corner: validations)
# ---------------------------------------------------------------------------
class TestHighValueGating:
    def test_high_value_meetup_requires_police_spot(self, api):
        """PRD §3.6: "if the listing's ask_price_cents is at or above the
        high-value threshold of 50000 cents, the chosen spot's is_police_verified
        must be true; confirming a high-value meetup at a non-police-verified spot
        is rejected with ERR_SPOT_NOT_POLICE_VERIFIED (HTTP 422)."

        Design: Corner/validations/high_value_meetup_requires_police_spot
        """
        fx.set_clock("2026-06-01T08:00:00Z")
        spot = fx.create_safe_trade_spot(name="Coffee Shop", is_police_verified=False,
                                         open_minute_of_day=480, close_minute_of_day=1080)
        base = fx.setup_reserved_listing(ask_price_cents=60000,
                                         min_acceptable_price_cents=50000,
                                         amount_cents=55000,
                                         category_slug="electronics")
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        meetup = get_success_data(api.create_meetup(
            {"offer_id": base["offer"]["id"], "spot_id": spot["id"],
             "start_at": "2026-06-02T14:00:00Z", "end_at": "2026-06-02T15:00:00Z",
             "expected_offer_version": base["offer_version"]},
            headers=make_buyer_headers(buyer_id)))
        validate_error(api.confirm_meetup(meetup["id"], headers=make_seller_headers(seller_id)),
                       ApiErrorId.ERR_SPOT_NOT_POLICE_VERIFIED.value)
        still = validate_success(api.get_meetup(meetup["id"], headers=make_member_headers(buyer_id)))
        assert still["status"] == "PROPOSED"
