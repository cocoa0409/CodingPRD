"""Boundary precision: the exact handwash-station ceil(guests/20) threshold
at the confirm gate, and the exact 72.0-hour refund-tier edge at cancel
(PRD §3.4, §3.6, §3.7).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    sum_of_type,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Difficulty/boundary_precision_check/handwash_station_exact_threshold
# =====================================================================
def _setup_40_guest_booking(planned_stations, start, end):
    """40 guests -> exactly 2 stations required (ceil(40/20)); deposit 5322
    (0.30 * 17740) paid so only the handwash gate is in play."""
    ctx = fx.setup_quoted_goat_booking(
        with_insurance=True, guest_count=40,
        planned_handwash_stations=planned_stations,
        start_time=start, end_time=end,
    )
    fx.pay(ctx["booking"]["id"], ctx["customer"]["id"], 5322)
    return ctx


def test_confirm_with_one_station_below_exact_threshold_rejected(api):
    """PRD §3.4: "`required_handwash_stations` is zero when the venue's
    `requires_handwash_stations` flag is false, and otherwise the guest count
    divided by 20 rounded up — exactly divisible counts need exactly that many
    stations, so 40 guests require 2 stations and 41 require 3"
    PRD §3.6: "`planned_handwash_stations` must meet or exceed
    `required_handwash_stations` (`ERR_HANDWASH_STATIONS_INSUFFICIENT`)."

    Design: Difficulty/boundary_precision_check/handwash_station_exact_threshold
    """
    ctx = _setup_40_guest_booking(
        1, "2026-06-17T14:00:00Z", "2026-06-17T16:00:00Z")
    # Exactly at the boundary: 40 guests require exactly 2 stations, not 3.
    assert ctx["quote"]["required_handwash_stations"] == 2
    resp = api.confirm_booking(ctx["booking"]["id"],
                               make_customer_headers(ctx["customer"]["id"]))
    # 1 planned < 2 required
    validate_error(resp, ApiErrorId.ERR_HANDWASH_STATIONS_INSUFFICIENT)


def test_confirm_with_exactly_required_stations_succeeds(api):
    """PRD §3.4: "`required_handwash_stations` is zero when the venue's
    `requires_handwash_stations` flag is false, and otherwise the guest count
    divided by 20 rounded up — exactly divisible counts need exactly that many
    stations, so 40 guests require 2 stations and 41 require 3"
    PRD §3.6: "`planned_handwash_stations` must meet or exceed
    `required_handwash_stations` (`ERR_HANDWASH_STATIONS_INSUFFICIENT`)."

    Design: Difficulty/boundary_precision_check/handwash_station_exact_threshold
    """
    ctx = _setup_40_guest_booking(
        2, "2026-06-18T14:00:00Z", "2026-06-18T16:00:00Z")
    assert ctx["quote"]["required_handwash_stations"] == 2
    confirmed = validate_success(api.confirm_booking(
        ctx["booking"]["id"], make_customer_headers(ctx["customer"]["id"])))
    # The gate is >=, not >: exactly 2 planned stations confirm.
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]


# =====================================================================
# Difficulty/boundary_precision_check/cancel_refund_exactly_72h_tier
# =====================================================================
def _setup_confirmed_then_jump_to_exactly_72h_before():
    """CONFIRMED goat fixture (paid 4872); the logical clock lands exactly
    72.0 hours before the 2026-06-17T14:00:00Z start."""
    ctx = fx.setup_confirmed_goat_booking()
    fx.set_clock("2026-06-14T14:00:00Z")
    return ctx


def test_cancel_at_exactly_72h_lands_in_75_percent_tier(api):
    """PRD §3.7: "at least 72 but fewer than 168 hours refunds 75 percent of
    `total_paid_cents`, rounded half up (exactly 72.0 hours falls in this
    tier)"
    PRD §3.7: "In all variants the unrefunded remainder, when nonzero, is
    appended as a `FORFEIT` entry, and refunds are appended as `REFUND`
    entries."

    Design: Difficulty/boundary_precision_check/cancel_refund_exactly_72h_tier
    """
    ctx = _setup_confirmed_then_jump_to_exactly_72h_before()
    validate_success(api.cancel_booking(
        ctx["booking"]["id"], "CUSTOMER",
        make_customer_headers(ctx["customer"]["id"])))
    ledger = fx.list_ledger(ctx["booking"]["id"])
    # The >= boundary puts exactly 72.0h in the 75% tier.
    assert sum_of_type(ledger, "REFUND") == 3654   # round_half_up(0.75 * 4872)
    assert sum_of_type(ledger, "FORFEIT") == 1218  # 4872 - 3654


def test_cancel_at_exactly_72h_is_not_the_full_refund_tier(api):
    """PRD §3.7: "168 hours or more before start refunds everything paid; at
    least 72 but fewer than 168 hours refunds 75 percent of `total_paid_cents`,
    rounded half up (exactly 72.0 hours falls in this tier)"
    PRD §3.7: "Otherwise `payment_status` becomes `REFUND_FULL` when the
    refund equals the amount paid, `REFUND_PARTIAL` when the refund is
    positive but smaller, and `FORFEITED` when nothing is refunded."

    Design: Difficulty/boundary_precision_check/cancel_refund_exactly_72h_tier
    """
    ctx = _setup_confirmed_then_jump_to_exactly_72h_before()
    cancelled = validate_success(api.cancel_booking(
        ctx["booking"]["id"], "CUSTOMER",
        make_customer_headers(ctx["customer"]["id"])))
    assert cancelled["status"] == "CANCELLED_CUSTOMER", cancelled["status"]
    assert cancelled["payment_status"] == "REFUND_PARTIAL"

    refund = sum_of_type(fx.list_ledger(ctx["booking"]["id"]), "REFUND")
    assert refund == 3654
    assert refund != 4872  # no 100% refund at exactly 72.0h
