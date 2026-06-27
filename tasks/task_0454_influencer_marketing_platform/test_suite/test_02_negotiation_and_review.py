"""Offer negotiation cycle and content-review revision loop.

Queue A: non_linear_state_machine. Queue B: offer/content state-machine corner instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_admin_headers, make_compliance_headers, make_brand_headers, make_creator_headers,
    ApiErrorId,
    create_brand, create_creator, create_clean_creator, create_open_campaign, open_offer,
    setup_active_contract,
)

ADMIN = make_admin_headers()
COMPLIANCE = make_compliance_headers()


def _open_campaign_with_offer(api, requires_ftc=False, amount=80_000, budget=300_000):
    """brand + creator + OPEN campaign + a brand-opened OFFERED offer.
    Returns (brand, creator, campaign, deliverable, offer)."""
    brand = create_brand(budget_cents=1_000_000)
    creator = create_creator()
    campaign, deliverable = create_open_campaign(
        brand["id"], requires_ftc_disclosure=requires_ftc, campaign_budget_cents=budget,
        base_rate_cents=amount)
    offer = open_offer(brand["id"], campaign["id"], creator["id"], current_amount_cents=amount)
    return brand, creator, campaign, deliverable, offer


class TestNegotiationCycle:
    def test_counter_self_loop_keeps_countered_state(self, api):
        """PRD §3.4: "A successful counter sets current_amount_cents to the supplied
        counter_amount_cents, flips last_actor to the acting side, adds 1 to round_count,
        moves the offer to COUNTERED, and increments the offer's version."
        PRD §3.4: "A counter is permitted from either OFFERED or COUNTERED (the latter being
        a self-loop that keeps the offer in COUNTERED)".

        Brand opens 80000; Creator counters 120000 (rc1, CREATOR); Brand counters 100000
        (rc2, BRAND, still COUNTERED).

        Design: Difficulty/non_linear_state_machine/offer_counter_cycle_alternating_sides
        """
        brand, creator, _, _, offer = _open_campaign_with_offer(api, amount=80_000)
        ch = make_creator_headers(creator["id"])
        bh = make_brand_headers(brand["id"])
        o1 = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 120000,
                          "expected_offer_version": offer["version"]}, ch))
        assert o1["status"] == "COUNTERED"
        assert o1["round_count"] == 1
        assert o1["last_actor"] == "CREATOR"
        o2 = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 100000,
                          "expected_offer_version": o1["version"]}, bh))
        assert o2["status"] == "COUNTERED"
        assert o2["round_count"] == 2
        assert o2["current_amount_cents"] == 100000
        assert o2["last_actor"] == "BRAND"

    def test_counter_increments_round_and_amount(self, api):
        """PRD §3.4: "A successful counter sets current_amount_cents to the supplied
        counter_amount_cents, flips last_actor to the acting side, adds 1 to round_count,
        moves the offer to COUNTERED, and increments the offer's version."

        A single Creator counter on a Brand-opened offer: round_count 0 -> 1, status COUNTERED.

        Design: Difficulty/non_linear_state_machine/offer_counter_cycle_alternating_sides
        """
        brand, creator, _, _, offer = _open_campaign_with_offer(api, amount=80_000)
        ch = make_creator_headers(creator["id"])
        assert offer["round_count"] == 0
        o1 = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 95000,
                          "expected_offer_version": offer["version"]}, ch))
        assert o1["status"] == "COUNTERED"
        assert o1["round_count"] == 1
        assert o1["current_amount_cents"] == 95000
        assert o1["last_actor"] == "CREATOR"

    def test_new_offer_starts_offered_with_initiator(self, api):
        """PRD §3.4: "The system infers initiated_by from the acting role and records it;
        the new offer begins in OFFERED with last_actor set to the initiating side and
        round_count at 0."

        A Brand-opened offer has status OFFERED, round_count 0, last_actor BRAND.

        Design: Corner/state_machines/new_offer_starts_in_offered_state
        """
        brand = create_brand(budget_cents=1_000_000)
        creator = create_creator()
        campaign, _ = create_open_campaign(brand["id"], base_rate_cents=60_000)
        bh = make_brand_headers(brand["id"])
        resp = api.create_offer(
            {"campaign_id": campaign["id"], "creator_id": creator["id"],
             "current_amount_cents": 60000, "exclusivity_days": 0}, bh)
        offer = validate_success(resp, expected_status=201)
        assert offer["status"] == "OFFERED"
        assert offer["round_count"] == 0
        assert offer["last_actor"] == "BRAND"

    def test_counter_own_move_rejected_wrong_turn(self, api):
        """PRD §3.4: "any move — counter, accept, or decline — must come from the side
        opposite the offer's last_actor; a party that tries to act twice in a row is rejected
        with ERR_WRONG_TURN."

        Brand opened (last_actor BRAND) then Brand counters -> ERR_WRONG_TURN.

        Design: Corner/state_machines/counter_own_move_returns_wrong_turn
        """
        brand, creator, _, _, offer = _open_campaign_with_offer(api, amount=60_000)
        bh = make_brand_headers(brand["id"])
        resp = api.counter_offer(
            offer["id"], {"counter_amount_cents": 70000,
                          "expected_offer_version": offer["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_WRONG_TURN.value)

    def test_counter_at_round_cap_rejected(self, api):
        """PRD §3.4: "A counter is permitted from either OFFERED or COUNTERED (the latter
        being a self-loop that keeps the offer in COUNTERED), but only while the offer's
        round_count is strictly below the negotiation cap of 4, and only while the parent
        campaign is still OPEN."
        PRD §3.4: "A counter at or above the round cap is rejected with
        ERR_NEGOTIATION_ROUND_CAP."

        After four alternating counters (round_count 4) a fifth counter is rejected.

        Design: Corner/state_machines/counter_round_cap_returns_negotiation_round_cap
        """
        brand, creator, _, _, offer = _open_campaign_with_offer(api, amount=60_000)
        bh = make_brand_headers(brand["id"])
        ch = make_creator_headers(creator["id"])
        v = offer["version"]
        o = validate_success(api.counter_offer(offer["id"], {"counter_amount_cents": 70000, "expected_offer_version": v}, ch))
        o = validate_success(api.counter_offer(offer["id"], {"counter_amount_cents": 65000, "expected_offer_version": o["version"]}, bh))
        o = validate_success(api.counter_offer(offer["id"], {"counter_amount_cents": 68000, "expected_offer_version": o["version"]}, ch))
        o = validate_success(api.counter_offer(offer["id"], {"counter_amount_cents": 66000, "expected_offer_version": o["version"]}, bh))
        assert o["round_count"] == 4
        resp = api.counter_offer(offer["id"], {"counter_amount_cents": 67000, "expected_offer_version": o["version"]}, ch)
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_CAP.value)


class TestContentRevisionLoop:
    def test_resubmit_returns_to_submitted_increments_revision(self, api):
        """PRD §3.6: "From IN_REVIEW the reviewer can request changes, moving the submission
        IN_REVIEW → CHANGES_REQUESTED, which adds 1 to revision_count".
        PRD §3.6: "resubmitting updates the media and caption, recomputes has_ftc_disclosure
        from the new caption, and returns the submission CHANGES_REQUESTED → SUBMITTED for
        another review pass."

        submit (no tag) -> start-review -> request-changes (rc1) -> resubmit '#ad'
        -> SUBMITTED, revision_count 1, has_ftc_disclosure true.

        Design: Difficulty/non_linear_state_machine/content_revision_loop_resubmit_cycle
        """
        ctx = setup_active_contract(offer_amount_cents=90_000, base_rate_cents=90_000,
                                    requires_ftc_disclosure=True)
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/r0", "caption": "missing tag"}, ch))
        get_success_data(api.start_review(sub["id"], COMPLIANCE))
        get_success_data(api.request_changes(sub["id"], COMPLIANCE))
        resubmitted = validate_success(api.resubmit_content(
            sub["id"], {"media_url": "https://x/r1", "caption": "fixed #ad"}, ch))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1
        assert resubmitted["has_ftc_disclosure"] is True

    def test_request_changes_increments_revision_count(self, api):
        """PRD §3.6: "From IN_REVIEW the reviewer can request changes, moving the submission
        IN_REVIEW → CHANGES_REQUESTED, which adds 1 to revision_count; this is only permitted
        while revision_count is below the revision cap of 2."

        A first request-changes moves SUBMITTED->IN_REVIEW->CHANGES_REQUESTED with rc 0 -> 1.

        Design: Difficulty/non_linear_state_machine/content_revision_loop_resubmit_cycle
        """
        ctx = setup_active_contract(offer_amount_cents=90_000, base_rate_cents=90_000)
        ch = make_creator_headers(ctx["creator"]["id"])
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/rc0", "caption": "x"}, ch))
        assert sub["revision_count"] == 0
        get_success_data(api.start_review(sub["id"], COMPLIANCE))
        changed = validate_success(api.request_changes(sub["id"], COMPLIANCE))
        assert changed["status"] == "CHANGES_REQUESTED"
        assert changed["revision_count"] == 1
