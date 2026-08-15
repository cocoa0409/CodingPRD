"""Offers: system-initialized round numbers, the counter-offer cycle,
invalid/terminal transitions, and OCC on accept."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_counter_payload,
    get_success_data,
    listing_headers,
    selling_headers,
    setup_accepted_offer,
    setup_active_listing,
    submit_offer,
    validate_error,
    validate_success,
)


def test_root_offer_initialized_pending_round_one(api):
    """PRD §3.4: "A fresh offer arrives PENDING with `round_no` 1 — or one more
    than its parent's round when `parent_offer_id` is set"

    Design: Corner/entities/offer_round_no_system_initialized
    """
    deal = setup_active_listing()
    offer = submit_offer(deal, offer_price_cents=100000000)
    assert offer["status"] == "PENDING"
    assert offer["round_no"] == 1
    assert offer.get("parent_offer_id") in (None,)


class TestCounterOfferCycle:
    def test_seller_counter_flips_original_and_mints_child_round_two(self, api):
        """PRD §3.4: "Countering — the ListingAgent's third answer — flips the
        original offer to COUNTERED, bumps its `version`, mints a child offer in
        PENDING whose `parent_offer_id` links back to the original and whose
        `round_no` is one higher, and raises an OFFER_COUNTERED event"
        PRD §4: "the offer counter action, which answers 201 because it mints
        the child offer"

        Design: Difficulty/non_linear_state_machine/offer_counter_cycle_pending_countered_pending
        """
        deal = setup_active_listing()
        offer = submit_offer(deal, offer_price_cents=100000000,
                             acceptance_deadline="2026-08-20T00:00:00Z")
        child = validate_success(
            api.counter_offer(
                offer["id"],
                create_counter_payload(
                    offer["version"],
                    offer_price_cents=105000000,
                    acceptance_deadline="2026-08-22T00:00:00Z",
                ),
                listing_headers(deal),
            ),
            201,
        )
        assert child["status"] == "PENDING"
        assert child["round_no"] == 2, f"child round_no must be one higher, got {child['round_no']}"
        assert child["parent_offer_id"] == offer["id"]

        original = get_success_data(api.get_offer(offer["id"], listing_headers(deal)))
        assert original["status"] == "COUNTERED"

    def test_buyer_counter_of_counter_mints_grandchild_round_three(self, api):
        """PRD §3.4: "The chain is cyclic: the buyer's side answers a counter by
        countering the child in turn, flipping that child from COUNTERED and
        minting a grandchild in PENDING at the next round"

        Design: Difficulty/non_linear_state_machine/offer_counter_cycle_pending_countered_pending
        """
        deal = setup_active_listing()
        offer = submit_offer(deal, offer_price_cents=100000000,
                             acceptance_deadline="2026-08-20T00:00:00Z")
        child = validate_success(
            api.counter_offer(
                offer["id"],
                create_counter_payload(
                    offer["version"],
                    offer_price_cents=105000000,
                    acceptance_deadline="2026-08-22T00:00:00Z",
                ),
                listing_headers(deal),
            ),
            201,
        )
        grandchild = validate_success(
            api.counter_offer(
                child["id"],
                create_counter_payload(
                    child["version"],
                    offer_price_cents=103000000,
                    acceptance_deadline="2026-08-24T00:00:00Z",
                ),
                selling_headers(deal),
            ),
            201,
        )
        assert grandchild["status"] == "PENDING"
        assert grandchild["round_no"] == 3
        assert grandchild["parent_offer_id"] == child["id"]

        child_after = get_success_data(api.get_offer(child["id"], selling_headers(deal)))
        assert child_after["status"] == "COUNTERED"


def test_reject_accepted_offer_is_invalid(api):
    """PRD §3.4: "While an offer stands PENDING and the clock has not passed its
    `acceptance_deadline`, the listing side answers in one of three ways" and
    "Rejection moves the offer to REJECTED."
    PRD §2.8: "does the server ask whether the target resource's current state
    permits the requested transition, rejecting with `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/offer_reject_from_accepted_is_invalid_transition
    """
    deal = setup_accepted_offer()
    res = api.reject_offer(deal["offer"]["id"], listing_headers(deal))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    offer = get_success_data(api.get_offer(deal["offer"]["id"], listing_headers(deal)))
    assert offer["status"] == "ACCEPTED"


def test_rejected_offer_is_terminal_no_withdrawal(api):
    """PRD §3.4: "REJECTED, EXPIRED, WITHDRAWN, CLOSED, and FAILED are the
    offer's terminal states." and "Withdrawal moves a PENDING offer to WITHDRAWN"
    — a REJECTED offer permits no further transition.

    Design: Corner/state_machines/offer_terminal_lockdown_no_transitions_from_rejected
    """
    deal = setup_active_listing()
    offer = submit_offer(deal)
    rejected = validate_success(api.reject_offer(offer["id"], listing_headers(deal)))
    assert rejected["status"] == "REJECTED"

    res = api.withdraw_offer(offer["id"], selling_headers(deal))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_offer(offer["id"], listing_headers(deal)))
    assert after["status"] == "REJECTED"


def test_accept_with_stale_offer_version_rejected(api):
    """PRD §2.6: "Accepting an offer requires `expected_offer_version` carrying
    the caller's last-observed `version` of that offer." and "When the supplied
    value does not match the parent entity's current `version`, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/err_stale_version_on_offer_accept
    """
    deal = setup_active_listing()
    offer = submit_offer(deal, offer_price_cents=100000000,
                         acceptance_deadline="2026-08-10T00:00:00Z")
    child = validate_success(
        api.counter_offer(
            offer["id"],
            create_counter_payload(
                offer["version"],
                offer_price_cents=105000000,
                acceptance_deadline="2026-08-12T00:00:00Z",
            ),
            listing_headers(deal),
        ),
        201,
    )
    res = api.accept_offer(
        child["id"],
        {"expected_offer_version": child["version"] - 1},
        listing_headers(deal),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
