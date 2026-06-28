"""Compensating invariants (wallet / gift-card conservation), the strict
late-cancel boundary, and the fiscal-rejection errors.

Each test translates exactly one design-index instance.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_guest_headers,
    set_clock,
    create_venue,
    create_bay,
    create_member,
    create_member_with_wallet,
    create_game_card,
    create_gift_card,
    create_hold_reservation,
    confirm_reservation,
    create_queue_ticket,
    setup_confirmed_reservation,
)

RM = TEST_USERS["range_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ===========================================================================
# Queue A — boundary_precision_check / late_cancel_exactly_120_minutes_is_on_time_no_fee
# ===========================================================================
class TestLateCancelBoundary:
    def _confirmed_reservation_wallet(self, api):
        # PEAK / WEEKDAY / 60-min / PLATINUM / base 2500 => quote 6800; wallet 50000.
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue(base_rate_cents_per_half_hour=2500)
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000, tier="PLATINUM")
        res = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "PEAK",
            day_type="WEEKDAY", pay_source="WALLET")
        confirmed = confirm_reservation(res["id"], member["id"], bay["version"])
        assert confirmed["quoted_price_cents"] == 6800
        return venue, bay, member, confirmed

    def test_cancel_exactly_at_boundary_is_on_time_no_fee(self, api):
        """PRD §3.4: "If the current clock is at or before `start_utc` minus the
        late-cancel window of 120 minutes, the cancel is on time: it is a full reversal
        — the original `BAY_RESERVATION` charge is set to `REVERSED`, and if the pay
        source was `WALLET` the member's `wallet_balance_cents` is credited back by the
        charge amount, the provisional loyalty accrued at confirmation is reversed out
        of `pending_loyalty_points`, and `no_show_fee_cents` stays 0."
        PRD §3.4: "The boundary is strict: a cancel exactly at `start_utc` minus 120
        minutes is on time and incurs no fee, while one minute later is late and does
        incur the fee."

        Cancel at exactly 16:00 (start 18:00 minus 120 min) is on time: CANCELLED,
        no_show_fee_cents 0, wallet fully restored to 50000.

        Design: Difficulty/boundary_precision_check/late_cancel_exactly_120_minutes_is_on_time_no_fee
        """
        venue, bay, member, confirmed = self._confirmed_reservation_wallet(api)
        set_clock("2026-06-02T16:00:00Z")
        cancelled = validate_success(
            api.cancel_reservation(confirmed["id"], make_guest_headers(member["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["no_show_fee_cents"] == 0
        member_after = validate_success(api.get_member(member["id"], RM), 200)
        assert member_after["wallet_balance_cents"] == 50000

    def test_cancel_one_minute_late_incurs_fee(self, api):
        """PRD §3.4: "If instead the current clock is strictly after `start_utc` minus
        120 minutes, the cancel is late: `no_show_fee_cents` is set to the no-show fee,
        which is `quoted_price_cents` times 0.50 rounded half up; the original bay
        charge is reversed and a new charge of kind `NO_SHOW_FEE` for that fee is
        created, so the net wallet effect is to debit the fee; and the provisional
        loyalty is reversed. The boundary is strict: a cancel exactly at `start_utc`
        minus 120 minutes is on time and incurs no fee, while one minute later is late
        and does incur the fee."

        Cancel at 16:01 (one minute past the 16:00 boundary) is late:
        no_show_fee_cents = round(6800*0.50) = 3400.

        Design: Difficulty/boundary_precision_check/late_cancel_exactly_120_minutes_is_on_time_no_fee
        """
        venue, bay, member, confirmed = self._confirmed_reservation_wallet(api)
        set_clock("2026-06-02T16:01:00Z")
        cancelled = validate_success(
            api.cancel_reservation(confirmed["id"], make_guest_headers(member["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["no_show_fee_cents"] == 3400


# ===========================================================================
# Queue A — compensating_invariant / wallet_conserved_across_confirm_then_ontime_cancel
# ===========================================================================
class TestWalletConservation:
    def test_wallet_restored_and_charge_reversed_after_ontime_cancel(self, api):
        """PRD §3.4: "If the current clock is at or before `start_utc` minus the
        late-cancel window of 120 minutes, the cancel is on time: it is a full reversal
        — the original `BAY_RESERVATION` charge is set to `REVERSED`, and if the pay
        source was `WALLET` the member's `wallet_balance_cents` is credited back by the
        charge amount, the provisional loyalty accrued at confirmation is reversed out
        of `pending_loyalty_points`, and `no_show_fee_cents` stays 0."

        Confirm debits wallet 50000 -> 43200; an on-time cancel (well before the 120-min
        boundary) credits it back to exactly 50000, zeroes pending loyalty, and sets the
        charge REVERSED.

        Design: Difficulty/compensating_invariant/wallet_conserved_across_confirm_then_ontime_cancel
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue(base_rate_cents_per_half_hour=2500)
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000, tier="PLATINUM")
        res = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-05T18:00:00Z", "2026-06-05T19:00:00Z", "PEAK",
            day_type="WEEKDAY", pay_source="WALLET")
        confirmed = confirm_reservation(res["id"], member["id"], bay["version"])
        chg_id = confirmed["charge_id"]
        # Still 2026-06-01T12:00:00Z, far before start - 120 min.
        cancelled = validate_success(
            api.cancel_reservation(confirmed["id"], make_guest_headers(member["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        member_after = validate_success(api.get_member(member["id"], RM), 200)
        assert member_after["wallet_balance_cents"] == 50000
        assert member_after["pending_loyalty_points"] == 0
        charge_after = validate_success(api.get_charge(chg_id, RM), 200)
        assert charge_after["status"] == "REVERSED"

    def test_wallet_debited_by_quote_on_confirm(self, api):
        """PRD §3.4: "If the pay source is `WALLET`, the member's `wallet_balance_cents`
        is debited by `quoted_price_cents`."

        Forward leg of the conserved-quantity invariant: a WALLET confirm of a 6800
        quote debits the wallet from 50000 to 43200.

        Design: Difficulty/compensating_invariant/wallet_conserved_across_confirm_then_ontime_cancel
        """
        set_clock("2026-06-01T12:00:00Z")
        venue = create_venue(base_rate_cents_per_half_hour=2500)
        bay = create_bay(venue["id"])
        member = create_member_with_wallet(50000, tier="PLATINUM")
        res = create_hold_reservation(
            venue["id"], bay["id"], member["id"],
            "2026-06-05T18:00:00Z", "2026-06-05T19:00:00Z", "PEAK",
            day_type="WEEKDAY", pay_source="WALLET")
        confirmed = confirm_reservation(res["id"], member["id"], bay["version"])
        assert confirmed["quoted_price_cents"] == 6800
        member_after = validate_success(api.get_member(member["id"], RM), 200)
        assert member_after["wallet_balance_cents"] == 43200


# ===========================================================================
# Queue A — compensating_invariant / gift_card_value_conserved_across_redemption
# ===========================================================================
class TestGiftCardConservation:
    def test_remaining_plus_redeemed_equals_face_and_wallet_credited(self, api):
        """PRD §3.2: "Its `remaining_cents` starts at the face value and is the face
        value minus the sum of all redemptions, never negative, while
        `redeemed_total_cents` accumulates every amount redeemed against it, so that
        `redeemed_total_cents` and `remaining_cents` always sum back to
        `face_value_cents`."
        PRD §3.2: "Redeeming a gift card takes a target `member_id` and an
        `amount_cents`: the amount is subtracted from `remaining_cents` and added to
        `redeemed_total_cents`, and the same `amount_cents` is credited to that
        member's `wallet_balance_cents` with the member's `version` incremented by 1..."

        Redeeming 6800 of a 25000 card: remaining 18200, redeemed_total 6800
        (sum 25000) and the member wallet credited 6800.

        Design: Difficulty/compensating_invariant/gift_card_value_conserved_across_redemption
        """
        member = create_member()  # wallet 0
        gift = create_gift_card(25000)
        redeemed = validate_success(
            api.redeem_gift_card(gift["id"], {"member_id": member["id"], "amount_cents": 6800}, RM),
            200)
        assert redeemed["remaining_cents"] == 18200
        assert redeemed["redeemed_total_cents"] == 6800
        member_after = validate_success(api.get_member(member["id"], RM), 200)
        assert member_after["wallet_balance_cents"] == 6800

    def test_redemption_conserves_face_value(self, api):
        """PRD §3.2: "Its `remaining_cents` starts at the face value and is the face
        value minus the sum of all redemptions, never negative, while
        `redeemed_total_cents` accumulates every amount redeemed against it, so that
        `redeemed_total_cents` and `remaining_cents` always sum back to
        `face_value_cents`."

        The conserved-quantity invariant stated directly: after redeeming 6800 of a
        25000 card, remaining_cents + redeemed_total_cents == face_value_cents (25000).

        Design: Difficulty/compensating_invariant/gift_card_value_conserved_across_redemption
        """
        member = create_member()
        gift = create_gift_card(25000)
        redeemed = validate_success(
            api.redeem_gift_card(gift["id"], {"member_id": member["id"], "amount_cents": 6800}, RM),
            200)
        assert redeemed["remaining_cents"] + redeemed["redeemed_total_cents"] == \
            redeemed["face_value_cents"]
        assert redeemed["face_value_cents"] == 25000


# ===========================================================================
# Queue B — errors instances
# ===========================================================================
def test_gift_card_redeem_over_remaining_returns_insufficient_funds(api):
    """PRD §3.2: "A redemption whose `amount_cents` exceeds the card's
    `remaining_cents` is rejected with `ERR_INSUFFICIENT_FUNDS`."

    Redeeming 5000 against a card with remaining 3000 returns ERR_INSUFFICIENT_FUNDS
    (402); the card value is unchanged.

    Design: Corner/errors/error_gift_card_redeem_over_remaining_insufficient_funds
    """
    member = create_member()
    gift = create_gift_card(3000)
    resp = api.redeem_gift_card(
        gift["id"], {"member_id": member["id"], "amount_cents": 5000}, RM)
    validate_error(resp, "ERR_INSUFFICIENT_FUNDS", expected_status=402)
    gift_after = validate_success(api.get_gift_card(gift["id"], RM), 200)
    assert gift_after["remaining_cents"] == 3000


def test_gift_card_full_redeem_flips_to_depleted(api):
    """PRD §3.2: "A gift card's `status` is `ISSUED` until `remaining_cents` reaches
    0, at which point it becomes `DEPLETED`."
    PRD §3.2: "Redeeming a gift card takes a target `member_id` and an `amount_cents`:
    the amount is subtracted from `remaining_cents` and added to `redeemed_total_cents`,
    and the same `amount_cents` is credited to that member's `wallet_balance_cents`
    with the member's `version` incremented by 1; if `remaining_cents` reaches 0 the
    card flips to `DEPLETED`."

    Redeeming exactly the remaining 5000 of a 5000 card leaves remaining_cents 0,
    flips status to DEPLETED, and credits the member wallet 5000.

    Design: Corner/errors/gift_card_full_redeem_flips_to_depleted
    """
    member = create_member()
    gift = create_gift_card(5000)
    redeemed = validate_success(
        api.redeem_gift_card(gift["id"], {"member_id": member["id"], "amount_cents": 5000}, RM),
        200)
    assert redeemed["remaining_cents"] == 0
    assert redeemed["status"] == "DEPLETED"
    member_after = validate_success(api.get_member(member["id"], RM), 200)
    assert member_after["wallet_balance_cents"] == 5000


def test_insufficient_funds_on_wallet_confirm(api):
    """PRD §3.4: "If `pay_source` is `WALLET`, the member's `wallet_balance_cents` must
    be at least `quoted_price_cents`, else `ERR_INSUFFICIENT_FUNDS`."

    Confirming a WALLET reservation (quote 8000) when wallet is only 1000 returns
    ERR_INSUFFICIENT_FUNDS (402); the reservation stays HOLD.

    Design: Corner/errors/error_insufficient_funds_on_wallet_confirm
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue()
    bay = create_bay(venue["id"])
    member = create_member_with_wallet(1000, tier="STANDARD")
    res = create_hold_reservation(
        venue["id"], bay["id"], member["id"],
        "2026-06-02T18:00:00Z", "2026-06-02T19:00:00Z", "PEAK",
        day_type="WEEKDAY", pay_source="WALLET")
    resp = api.confirm_reservation(
        res["id"], {"expected_bay_version": bay["version"]}, make_guest_headers(member["id"]))
    validate_error(resp, "ERR_INSUFFICIENT_FUNDS", expected_status=402)
    res_after = validate_success(api.get_reservation(res["id"], RM), 200)
    assert res_after["status"] == "HOLD"


def test_card_depleted_on_seat_next_with_zero_credit_card(api):
    """PRD §3.5: "If the ticket names a `game_card_id`, that game card must be `ACTIVE`
    with `credits_remaining` of at least 1, else `ERR_CARD_DEPLETED`."
    PRD §3.5: "If a `game_card_id` was supplied, its `credits_remaining` is decremented
    by 1, and if that reaches 0 the card flips to `DEPLETED`."

    A 1-credit card is spent seating a first ticket (card -> DEPLETED); a second ticket
    carrying the same depleted card is rejected at seat_next with ERR_CARD_DEPLETED and
    stays WAITING.

    Design: Corner/errors/error_card_depleted_on_seat_next_with_zero_credit_card
    """
    set_clock("2026-06-01T12:00:00Z")
    venue = create_venue(bay_count=2)
    b1 = create_bay(venue["id"], label="B1")
    b2 = create_bay(venue["id"], label="B2")
    member = create_member()
    card = create_game_card(member["id"], credits_total=1)
    create_queue_ticket(venue["id"], member["id"], game_card_id=card["id"])
    # First seating consumes the single credit; card becomes DEPLETED.
    v_now = validate_success(api.get_venue(venue["id"], RM), 200)
    validate_success(
        api.seat_next(venue["id"], {"expected_venue_version": v_now["version"]}, FD), 200)
    tk2 = create_queue_ticket(venue["id"], member["id"], game_card_id=card["id"])
    v_now2 = validate_success(api.get_venue(venue["id"], RM), 200)
    resp = api.seat_next(venue["id"], {"expected_venue_version": v_now2["version"]}, FD)
    validate_error(resp, "ERR_CARD_DEPLETED", expected_status=409)
    tk2_after = validate_success(api.get_queue_ticket(tk2["id"], FD), 200)
    assert tk2_after["status"] == "WAITING"
