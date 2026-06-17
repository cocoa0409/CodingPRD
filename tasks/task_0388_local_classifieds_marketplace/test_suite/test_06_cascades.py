"""Cascading removals, compensating reservations, and conserved counters.

Translates the Difficulty transitive_cascade and compensating_invariant
instances, plus Corner state-machine / cross-cutting rows for suspend/ban
cascades, reinstatement non-reversal, spam-flag auto-hide, and the
remove-cancels-meetup chain.
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
# Member suspend depth-3 cascade (Difficulty: transitive_cascade)
# ---------------------------------------------------------------------------
class TestSuspendCascade:
    def test_suspend_removes_listing_expires_offer_closes_conversation(self, api):
        """PRD §3.7: "Suspending an ACTIVE member removes all of that member's
        listings whose publication_status is ACTIVE: each such listing transitions
        to REMOVED, and each removal in turn closes its OPEN conversations and
        expires its PROPOSED/COUNTERED offers — the transitive cascade above."

        Design: Difficulty/transitive_cascade/member_suspend_cascade_depth3
        """
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=5000,
                                                amount_cents=9000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        listing_id = base["listing"]["id"]
        offer_id = base["offer"]["id"]
        conv_id = base["conversation"]["id"]
        suspended = get_success_data(api.suspend_member(seller_id, headers=MOD))
        assert suspended["status"] == "SUSPENDED"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["publication_status"] == "REMOVED", "hop 1: suspend removes listing"
        offer = validate_success(api.get_offer(offer_id, headers=make_member_headers(buyer_id)))
        assert offer["status"] == "EXPIRED", "hop 2: removal expires open offer"
        conv = validate_success(api.get_conversation(conv_id, headers=make_member_headers(buyer_id)))
        assert conv["status"] == "CLOSED", "hop 2: removal closes conversation"

    def test_suspend_decrements_active_listing_count(self, api):
        """PRD §3.7: "Suspending an ACTIVE member removes all of that member's
        listings whose publication_status is ACTIVE: each such listing transitions
        to REMOVED"
        PRD §3.7: "From ACTIVE, removal decrements the seller's
        active_listing_count by 1"

        Design: Difficulty/transitive_cascade/member_suspend_cascade_depth3
        """
        base = fx.setup_listing_with_open_offer(ask_price_cents=10000,
                                                min_acceptable_price_cents=5000,
                                                amount_cents=9000)
        seller_id = base["seller"]["id"]
        get_success_data(api.suspend_member(seller_id, headers=MOD))
        member = validate_success(api.get_member(seller_id, headers=make_member_headers(seller_id)))
        assert member["active_listing_count"] == 0


# ---------------------------------------------------------------------------
# Meetup complete depth-2 cascade (Difficulty: transitive_cascade)
# ---------------------------------------------------------------------------
class TestCompleteCascade:
    def test_complete_sells_listing_and_closes_conversation(self, api):
        """PRD §3.6: "Completion moves the meetup to COMPLETED, cascades the
        listing's sale_status from RESERVED to SOLD, forces the listing's
        publication_status to REMOVED if it is currently ACTIVE or EXPIRED ...
        closes the listing's OPEN conversations"

        Design: Difficulty/transitive_cascade/meetup_complete_cascade_depth2_sells_and_closes
        """
        base = fx.setup_meetup_confirmed(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        listing_id = base["listing"]["id"]
        conv_id = base["conversation"]["id"]
        completed = get_success_data(api.complete_meetup(base["meetup"]["id"],
                                                         headers=make_seller_headers(seller_id)))
        assert completed["status"] == "COMPLETED"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["sale_status"] == "SOLD", "hop 1: complete sells listing"
        conv = validate_success(api.get_conversation(conv_id, headers=make_member_headers(buyer_id)))
        assert conv["status"] == "CLOSED", "hop 2: SOLD closes conversation"

    def test_complete_removes_publication_when_active(self, api):
        """PRD §3.6: "forces the listing's publication_status to REMOVED if it is
        currently ACTIVE or EXPIRED (and decrements the seller's
        active_listing_count if the listing was ACTIVE)"

        Design: Difficulty/transitive_cascade/meetup_complete_cascade_depth2_sells_and_closes
        """
        base = fx.setup_meetup_confirmed(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        get_success_data(api.complete_meetup(base["meetup"]["id"],
                                             headers=make_seller_headers(seller_id)))
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["publication_status"] == "REMOVED"


# ---------------------------------------------------------------------------
# Reservation compensation conserves open-offer ledger (compensating_invariant)
# ---------------------------------------------------------------------------
class TestReservationCompensation:
    def test_meetup_cancel_reverts_reservation_and_conserves_ledger(self, api):
        """PRD §3.6: "When the cancelled meetup references the listing's
        accepted_offer_id, the listing's sale_status reverts from RESERVED to
        AVAILABLE, the accepted_offer_id is cleared, and the previously ACCEPTED
        offer is compensated to WITHDRAWN"
        PRD §3.5: "An accepted offer that is later compensated back to WITHDRAWN
        (when its reserving meetup falls through, see §3.6) leaves the counter
        unchanged, because an ACCEPTED offer was already out of the open set"

        Design: Difficulty/compensating_invariant/reservation_compensation_conserves_open_offer_ledger
        """
        base = fx.setup_meetup_confirmed(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        listing_id, offer_id = base["listing"]["id"], base["offer"]["id"]
        cancelled = get_success_data(api.cancel_meetup(base["meetup"]["id"],
                                                       headers=make_buyer_headers(buyer_id)))
        assert cancelled["status"] == "CANCELLED"
        offer = validate_success(api.get_offer(offer_id, headers=make_member_headers(buyer_id)))
        assert offer["status"] == "WITHDRAWN"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["sale_status"] == "AVAILABLE"
        assert listing["accepted_offer_id"] is None
        assert listing["open_offer_count"] == 0, "conserved: accepted offer never re-enters open set"

    def test_meetup_cancel_clears_accepted_offer_id(self, api):
        """PRD §3.6: "the listing's sale_status reverts from RESERVED to
        AVAILABLE, the accepted_offer_id is cleared, and the previously ACCEPTED
        offer is compensated to WITHDRAWN; the meetup moves to CANCELLED"

        Design: Difficulty/compensating_invariant/reservation_compensation_conserves_open_offer_ledger
        """
        base = fx.setup_meetup_proposed(ask_price_cents=10000,
                                        min_acceptable_price_cents=5000,
                                        amount_cents=9000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        listing_id = base["listing"]["id"]
        get_success_data(api.cancel_meetup(base["meetup"]["id"],
                                           headers=make_buyer_headers(buyer_id)))
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["accepted_offer_id"] is None
        assert listing["sale_status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Flag uphold conserves active-flag ledger (compensating_invariant)
# ---------------------------------------------------------------------------
class TestFlagLedgerConservation:
    def test_flag_uphold_returns_active_flag_count_to_zero(self, api):
        """PRD §3.7: "When a flag targets a listing, that listing's
        active_flag_count increments by 1 on flag creation"
        PRD §3.7: "Upholding a flag moves it to UPHELD: when the target is a
        listing, that listing's active_flag_count decrements by 1, the listing's
        seller's upheld_flag_count increments by 1, and that seller's trust_score
        is recomputed"

        Design: Difficulty/compensating_invariant/flag_uphold_then_listing_active_flag_count_conserved
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        reporter = fx.create_member(role_kind="BUYER", display_name="R")
        flag = fx.raise_listing_flag(listing_id, reporter["id"], reason="SPAM")
        upheld = get_success_data(api.uphold_flag(flag["id"], {"resolution_note": "confirmed spam"},
                                                  headers=MOD))
        assert upheld["status"] == "UPHELD"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["active_flag_count"] == 0, "open-flag ledger conserved: +1 raise, -1 resolve"
        member = validate_success(api.get_member(seller_id, headers=MOD))
        assert member["upheld_flag_count"] == 1, "resolution recorded separately"

    def test_flag_uphold_drops_seller_trust_by_penalty(self, api):
        """PRD §3.1: "compute a flag penalty equal to 15 multiplied by the
        member's upheld_flag_count. The raw score is the base plus the
        verification bonus plus the completion bonus minus the flag penalty."

        Design: Difficulty/compensating_invariant/flag_uphold_then_listing_active_flag_count_conserved
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        reporter = fx.create_member(role_kind="BUYER", display_name="R")
        flag = fx.raise_listing_flag(listing_id, reporter["id"], reason="SPAM")
        get_success_data(api.uphold_flag(flag["id"], headers=MOD))
        member = validate_success(api.get_member(seller_id, headers=MOD))
        # raw = 50 + 0 + 0 - 1*15 = 35.
        assert member["trust_score"] == 35


# ---------------------------------------------------------------------------
# Corner: listing removal cancels confirmed meetup
# ---------------------------------------------------------------------------
class TestRemoveCancelsMeetup:
    def test_remove_listing_cancels_meetup_withdraws_offer(self, api):
        """PRD §3.7: "Listing removal ... From ACTIVE, removal ... clears
        accepted_offer_id ... and cancels any PROPOSED or CONFIRMED meetup on the
        listing to CANCELLED"

        NOTE: the original `assert offer["status"] == "WITHDRAWN"` assertion was
        removed (STEP 1c partial-coverage split). §3.7's removal-from-ACTIVE
        cascade is a self-contained enumeration that "freezes the sale dimension
        at its current value" and expires only PROPOSED/COUNTERED offers — it does
        not touch the ACCEPTED offer, and its "freezes the sale dimension" clause
        directly contradicts §3.6's reservation reversal (which moves sale_status
        back to AVAILABLE). §3.6's ACCEPTED->WITHDRAWN compensation is bound to the
        meetup cancel/no-show endpoints, not to the §3.7 removal cascade, so a
        faithful PRD-only implementer leaves the offer ACCEPTED here. The asserted
        WITHDRAWN outcome is therefore not uniquely derivable from PRD prose.

        Design: Corner/cross_cutting_complexity_layers/cascade_listing_remove_cancels_open_meetup
        """
        base = fx.setup_meetup_confirmed(ask_price_cents=10000,
                                         min_acceptable_price_cents=5000,
                                         amount_cents=9000)
        seller_id, buyer_id = base["seller"]["id"], base["buyer"]["id"]
        listing_id, offer_id = base["listing"]["id"], base["offer"]["id"]
        meetup_id = base["meetup"]["id"]
        get_success_data(api.remove_listing(listing_id, headers=MOD))
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["publication_status"] == "REMOVED"
        assert listing["accepted_offer_id"] is None
        meetup = validate_success(api.get_meetup(meetup_id, headers=make_member_headers(buyer_id)))
        assert meetup["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Corner: spam-flag auto-hide, reinstate non-reversal, ban threshold
# ---------------------------------------------------------------------------
class TestModerationSideEffects:
    def test_spam_flag_threshold_auto_hides_listing(self, api):
        """PRD §3.7: "once a listing's active_flag_count reaches the spam-flag
        threshold of 3 the listing is auto-hidden — cascaded to REMOVED — with the
        full removal cascade below."

        Design: Corner/state_machines/spam_flag_threshold_auto_hides_listing
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        r1 = fx.create_member(role_kind="BUYER", display_name="R1")
        r2 = fx.create_member(role_kind="BUYER", display_name="R2")
        r3 = fx.create_member(role_kind="BUYER", display_name="R3")
        fx.raise_listing_flag(listing_id, r1["id"], reason="SPAM")
        fx.raise_listing_flag(listing_id, r2["id"], reason="SPAM")
        fx.raise_listing_flag(listing_id, r3["id"], reason="SPAM")
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["active_flag_count"] == 3
        assert listing["publication_status"] == "REMOVED"

    def test_member_reinstate_does_not_republish_listings(self, api):
        """PRD §3.1: "Reinstatement moves a SUSPENDED member back to ACTIVE,
        permitted only while the status is SUSPENDED; reinstatement does not
        automatically republish anything — the seller must republish manually."

        Design: Corner/state_machines/member_reinstate_does_not_republish_listings
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        seller_id = base["seller"]["id"]
        listing_id = base["listing"]["id"]
        get_success_data(api.suspend_member(seller_id, headers=MOD))
        reinstated = get_success_data(api.reinstate_member(seller_id, headers=MOD))
        assert reinstated["status"] == "ACTIVE"
        listing = validate_success(api.get_listing(listing_id, headers=make_member_headers(seller_id)))
        assert listing["publication_status"] == "REMOVED", "removal is not reversed"
        member = validate_success(api.get_member(seller_id, headers=make_member_headers(seller_id)))
        assert member["active_listing_count"] == 0

    def test_ban_below_threshold_returns_error(self, api):
        """PRD §3.1: "a ban attempted while the upheld_flag_count is below 2 is
        rejected with ERR_BAN_THRESHOLD_NOT_MET (HTTP 409)."

        Design: Corner/state_machines/ban_below_threshold_returns_error
        """
        member = fx.create_member(role_kind="BOTH", display_name="M")
        validate_error(api.ban_member(member["id"], headers=MOD),
                       ApiErrorId.ERR_BAN_THRESHOLD_NOT_MET.value)
        fetched = validate_success(api.get_member(member["id"], headers=MOD))
        assert fetched["status"] == "ACTIVE"
