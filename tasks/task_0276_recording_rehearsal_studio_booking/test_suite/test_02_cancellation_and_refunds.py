"""Cancellation refunds and the wallet cascade (Difficulty rules 1, 4, 6, 9).

Covers the held-full vs confirmed-tiered refund divergence, the inclusive
cancellation-tier boundary, the money-conservation invariant, and the
cancel -> refund -> wallet-credit cascade.
"""
from test_helpers import (
    setup_studio_room_client,
    create_booking,
    pay_deposit,
    confirm,
    set_clock,
    api_client,
    TEST_USERS,
    make_client_headers,
    get_success_data,
    get_booking,
    get_client,
    find_refund_payment,
)

SM = TEST_USERS["studio_manager_headers"]


def _cancel(booking, client):
    headers = make_client_headers(client["id"])
    return get_success_data(api_client.cancel_booking(booking["id"], headers))


# =====================================================================
# Difficulty rule 1 — dual_variant_calc:
#   cancellation_held_full_vs_confirmed_tiered_refund
# =====================================================================
class TestHeldVsConfirmedRefund:
    """held_full_refund always refunds amount_paid in full; confirmed_tiered retains
    late_cancel_fee_pct of base_charge inside the partial tier — same 14400 deposit."""

    def _setup(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60, "cancellation_tier_hours": 48,
                              "late_cancel_fee_pct": 0.25},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        return studio, room, client

    def test_held_cancel_refunds_deposit_in_full(self):
        """PRD §3.7: "If the booking was never confirmed — it is being cancelled while still
        HELD — the client is refunded in full whatever they had paid: the refund equals
        amount_paid_cents."

        Design: Difficulty/dual_variant_calc/cancellation_held_full_vs_confirmed_tiered_refund
        """
        studio, room, client = self._setup()
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(booking, client, 14400)
        _cancel(booking, client)
        refund = find_refund_payment(booking["id"])
        assert refund is not None, "expected a REFUND payment"
        assert refund["amount_cents"] == 14400, refund["amount_cents"]

    def test_confirmed_partial_tier_retains_late_fee(self):
        """PRD §3.7: "If the hours before start fall short of the cutoff, the cancellation is in
        the partial tier: the studio retains a fee equal to base_charge_cents multiplied by
        late_cancel_fee_pct rounded half up to a whole cent, and the refund is the amount paid
        minus that fee, floored at zero so the refund never goes negative."

        Design: Difficulty/dual_variant_calc/cancellation_held_full_vs_confirmed_tiered_refund
        """
        studio, room, client = self._setup()
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-20T09:00:00Z", end_at="2026-07-20T12:30:00Z")
        pay_deposit(booking, client, 14400)
        confirm(booking)
        set_clock("2026-07-20T08:00:00Z")  # 1h before start -> partial tier
        _cancel(booking, client)
        refund = find_refund_payment(booking["id"])
        assert refund is not None, "expected a REFUND payment"
        # base 24000, fee = round_half_up(24000*0.25)=6000, refund = 14400 - 6000 = 8400
        assert refund["amount_cents"] == 8400, refund["amount_cents"]


# =====================================================================
# Difficulty rule 6 — boundary_precision_check:
#   cancellation_tier_exact_boundary_is_full_refund
# =====================================================================
class TestCancellationTierBoundary:
    """Cancelling EXACTLY cancellation_tier_hours before start is the inclusive FULL-refund
    tier."""

    def _setup_confirmed(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60, "cancellation_tier_hours": 48,
                              "late_cancel_fee_pct": 0.25},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(booking, client, 14400)
        confirm(booking)
        return booking, client

    def test_exactly_at_tier_cutoff_is_full_refund(self):
        """PRD §3.7: "If that figure is greater than or equal to the studio's
        cancellation_tier_hours, the cancellation falls in the full-refund tier and the refund
        again equals amount_paid_cents; the boundary is inclusive, so cancelling at exactly the
        cutoff still earns a full refund."

        Design: Difficulty/boundary_precision_check/cancellation_tier_exact_boundary_is_full_refund
        """
        booking, client = self._setup_confirmed()
        set_clock("2026-07-08T09:00:00Z")  # exactly 48h before start 07-10 09:00
        _cancel(booking, client)
        refund = find_refund_payment(booking["id"])
        assert refund is not None, "expected a REFUND payment"
        assert refund["amount_cents"] == 14400, refund["amount_cents"]
        bk = get_booking(booking["id"])
        assert bk["settlement_status"] == "REFUNDED", bk["settlement_status"]

    def test_just_inside_partial_tier_retains_fee(self):
        """PRD §3.7: "If the hours before start fall short of the cutoff, the cancellation is in
        the partial tier: the studio retains a fee equal to base_charge_cents multiplied by
        late_cancel_fee_pct rounded half up to a whole cent, and the refund is the amount paid
        minus that fee, floored at zero so the refund never goes negative."

        Design: Difficulty/boundary_precision_check/cancellation_tier_exact_boundary_is_full_refund
        """
        booking, client = self._setup_confirmed()
        # 47h before start (one hour inside the cutoff) -> partial tier
        set_clock("2026-07-08T10:00:00Z")
        _cancel(booking, client)
        refund = find_refund_payment(booking["id"])
        assert refund is not None, "expected a REFUND payment"
        assert refund["amount_cents"] == 8400, refund["amount_cents"]


# =====================================================================
# Difficulty rule 9 — compensating_invariant:
#   cancel_refund_conserves_money_paid
# =====================================================================
class TestRefundConservesMoney:
    """amount_paid_at_cancel == refund_amount + retained_fee holds exactly, no cent drift."""

    def _setup_confirmed_partial(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60, "cancellation_tier_hours": 48,
                              "late_cancel_fee_pct": 0.25},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(booking, client, 14400)
        confirm(booking)
        set_clock("2026-07-10T08:00:00Z")  # 1h before start -> partial tier
        return booking, client

    def test_partial_refund_amount_is_paid_minus_fee(self):
        """PRD §3.7: "the studio retains a fee equal to base_charge_cents multiplied by
        late_cancel_fee_pct rounded half up to a whole cent, and the refund is the amount paid
        minus that fee, floored at zero so the refund never goes negative."

        Design: Difficulty/compensating_invariant/cancel_refund_conserves_money_paid
        """
        booking, client = self._setup_confirmed_partial()
        _cancel(booking, client)
        refund = find_refund_payment(booking["id"])
        assert refund is not None, "expected a REFUND payment"
        assert refund["amount_cents"] == 8400, refund["amount_cents"]

    def test_paid_equals_refund_plus_retained_fee(self):
        """PRD §3.7: "the studio retains a fee equal to base_charge_cents multiplied by
        late_cancel_fee_pct rounded half up to a whole cent, and the refund is the amount paid
        minus that fee, floored at zero so the refund never goes negative."

        Design: Difficulty/compensating_invariant/cancel_refund_conserves_money_paid
        """
        booking, client = self._setup_confirmed_partial()
        paid_at_cancel = 14400  # exact deposit paid
        _cancel(booking, client)
        refund = find_refund_payment(booking["id"])
        retained_fee = 6000  # round_half_up(24000 * 0.25)
        assert refund["amount_cents"] + retained_fee == paid_at_cancel
        bk = get_booking(booking["id"])
        assert bk["settlement_status"] == "REFUNDED", bk["settlement_status"]


# =====================================================================
# Difficulty rule 4 — transitive_cascade:
#   booking_cancel_cascades_to_refund_to_wallet_credit
# =====================================================================
class TestCancelRefundWalletCascade:
    """Depth-2 cascade: cancel -> REFUND payment (WALLET) -> wallet_credit_cents increment."""

    def _setup_confirmed_full_tier(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60, "cancellation_tier_hours": 48,
                              "late_cancel_fee_pct": 0.25},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(booking, client, 14400)
        confirm(booking)
        return studio, room, client, booking

    def test_refund_lands_in_wallet_as_credit(self):
        """PRD §3.7: "Cancellation drives schedule_status to CANCELLED, releases every gear
        rental and engineer assignment on the booking, computes the refund, and — if any money
        had been paid — creates a REFUND payment whose refund_destination is WALLET (studio
        policy issues all cancellation refunds as wallet credit)."

        Design: Difficulty/transitive_cascade/booking_cancel_cascades_to_refund_to_wallet_credit
        """
        studio, room, client, booking = self._setup_confirmed_full_tier()
        # cancel while still > 48h before start (full-refund tier, no fee)
        _cancel(booking, client)
        refund = find_refund_payment(booking["id"])
        assert refund is not None, "expected a REFUND payment"
        assert refund["amount_cents"] == 14400, refund["amount_cents"]
        assert refund["refund_destination"] == "WALLET", refund["refund_destination"]

    def test_wallet_credit_increments_by_refund_amount(self):
        """PRD §3.7: "On the money axis the settlement moves through REFUNDING and then to
        REFUNDED, and when the refund lands in the wallet the client's wallet_credit_cents is
        increased by the refunded amount."

        Design: Difficulty/transitive_cascade/booking_cancel_cascades_to_refund_to_wallet_credit
        """
        studio, room, client, booking = self._setup_confirmed_full_tier()
        _cancel(booking, client)
        bk = get_booking(booking["id"])
        assert bk["schedule_status"] == "CANCELLED", bk["schedule_status"]
        assert bk["settlement_status"] == "REFUNDED", bk["settlement_status"]
        refreshed = get_client(client["id"])
        assert refreshed["wallet_credit_cents"] == 14400, refreshed["wallet_credit_cents"]
