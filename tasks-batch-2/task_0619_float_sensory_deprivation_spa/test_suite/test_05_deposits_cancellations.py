"""Deposit computation, cancellation timing (timely refund vs late forfeit), the no-show fee
and strike, and the cancel-cutoff boundary."""
from test_helpers import (
    validate_success, validate_error,
    setup_confirmed_couples_cash_booking_for_noshow,
    setup_confirmed_cash_booking_at_cancel_boundary,
    setup_confirmed_cash_booking_for_late_cancel,
    setup_confirmed_cash_booking_for_noshow_strike,
    get_payments_for_booking,
    api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


# ─── Deposit-then-fee order (comb_c_deposit_then_fee_order) ───────────────
def test_couples_deposit_is_doubled(api):
    """PRD §3.5: "The **deposit** (`deposit_cents`) is a flat twenty dollars — two thousand
    cents — and is doubled to four thousand cents for a couples booking."

    Design: Difficulty/combinatorial_formula/comb_c_deposit_then_fee_order
    """
    ctx = setup_confirmed_couples_cash_booking_for_noshow()
    assert ctx["booking"]["deposit_cents"] == 4000, (
        f"couples deposit must be 4000, got {ctx['booking']['deposit_cents']}"
    )


def test_no_show_fee_equals_doubled_deposit(api):
    """PRD §3.7: "A no-show forfeits the deposit by recording a `NO_SHOW_FEE` payment for the
    positive `deposit_cents`".

    Design: Difficulty/combinatorial_formula/comb_c_deposit_then_fee_order
    """
    ctx = setup_confirmed_couples_cash_booking_for_noshow()
    bk = ctx["booking"]
    noshow = validate_success(api.no_show_booking(bk["id"], FRONTDESK), 200)
    assert noshow["status"] == "NO_SHOW"
    fees = [p for p in get_payments_for_booking(bk["id"])
            if p["kind"] == "NO_SHOW_FEE" and p["amount_cents"] == 4000]
    assert len(fees) == 1, f"expected one NO_SHOW_FEE of 4000, got {fees}"


# ─── Cancel cutoff boundary (boundary_cancel_cutoff_exact_24h) ────────────
def test_cancel_at_exact_24h_cutoff_is_timely_refund(api):
    """PRD §3.7: "A **timely** cancellation — where the current time is at or before the
    booking's `start_utc` minus the cancellation cutoff of twenty-four hours — refunds the
    deposit in full, recording a `DEPOSIT_REFUND` payment whose `amount_cents` is the negative
    of `deposit_cents` against the booking's funding instrument."

    Design: Difficulty/boundary_precision_check/boundary_cancel_cutoff_exact_24h
    """
    # Clock at exactly start - 24h (inclusive boundary): timely -> DEPOSIT_REFUND -2000.
    ctx = setup_confirmed_cash_booking_at_cancel_boundary()
    bk = ctx["booking"]
    cancelled = validate_success(api.cancel_booking(bk["id"], FRONTDESK), 200)
    assert cancelled["status"] == "CANCELLED"
    payments = get_payments_for_booking(bk["id"])
    refunds = [p for p in payments
               if p["kind"] == "DEPOSIT_REFUND" and p["amount_cents"] == -2000]
    assert len(refunds) == 1, f"expected one DEPOSIT_REFUND of -2000, got {refunds}"


def test_cancel_at_exact_24h_cutoff_has_no_late_fee(api):
    """PRD §3.7: "A **late** cancellation — where the current time is past that twenty-four-
    hour cutoff — forfeits the deposit in full, recording a `LATE_FEE` payment whose
    `amount_cents` is the positive `deposit_cents` against the same instrument."

    Design: Difficulty/boundary_precision_check/boundary_cancel_cutoff_exact_24h
    """
    ctx = setup_confirmed_cash_booking_at_cancel_boundary()
    bk = ctx["booking"]
    validate_success(api.cancel_booking(bk["id"], FRONTDESK), 200)
    late_fees = [p for p in get_payments_for_booking(bk["id"]) if p["kind"] == "LATE_FEE"]
    assert late_fees == [], f"a timely cancel at the cutoff must not post a LATE_FEE, got {late_fees}"


# ─── Late cancel forfeit (late_cancel_forfeits_deposit_late_fee) ──────────
def test_late_cancel_posts_late_fee(api):
    """PRD §3.7: "A **late** cancellation — where the current time is past that twenty-four-
    hour cutoff — forfeits the deposit in full, recording a `LATE_FEE` payment whose
    `amount_cents` is the positive `deposit_cents` against the same instrument."

    Design: Corner/validations/late_cancel_forfeits_deposit_late_fee
    """
    # Single CASH booking, clock 14h before start (inside 24h cutoff -> late).
    ctx = setup_confirmed_cash_booking_for_late_cancel()
    bk = ctx["booking"]
    cancelled = validate_success(api.cancel_booking(bk["id"], FRONTDESK), 200)
    assert cancelled["status"] == "CANCELLED"
    payments = get_payments_for_booking(bk["id"])
    late_fees = [p for p in payments if p["kind"] == "LATE_FEE" and p["amount_cents"] == 2000]
    assert len(late_fees) == 1, f"expected one LATE_FEE of 2000, got {late_fees}"


def test_late_cancel_has_no_deposit_refund(api):
    """PRD §3.7: "A **timely** cancellation ... refunds the deposit in full, recording a
    `DEPOSIT_REFUND` payment whose `amount_cents` is the negative of `deposit_cents`".

    Design: Corner/validations/late_cancel_forfeits_deposit_late_fee
    """
    ctx = setup_confirmed_cash_booking_for_late_cancel()
    bk = ctx["booking"]
    validate_success(api.cancel_booking(bk["id"], FRONTDESK), 200)
    refunds = [p for p in get_payments_for_booking(bk["id"]) if p["kind"] == "DEPOSIT_REFUND"]
    assert refunds == [], f"a late cancel must not post a DEPOSIT_REFUND, got {refunds}"


# ─── No-show strike (derived_member_no_show_strike_increments) ────────────
def test_no_show_increments_strike_keeps_member_active(api):
    """PRD §3.7: "A no-show forfeits the deposit by recording a `NO_SHOW_FEE` payment for the
    positive `deposit_cents`, and it strikes the member: the member's `no_show_strikes`
    increases by one, and once that count reaches the suspension threshold of three the
    member's `status` flips to `SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/derived_member_no_show_strike_increments
    """
    ctx = setup_confirmed_cash_booking_for_noshow_strike()
    bk, member = ctx["booking"], ctx["member"]
    noshow = validate_success(api.no_show_booking(bk["id"], FRONTDESK), 200)
    assert noshow["status"] == "NO_SHOW"
    refreshed = validate_success(api.get_member(member["id"], FRONTDESK), 200)
    assert refreshed["no_show_strikes"] == 1, (
        f"expected one strike, got {refreshed['no_show_strikes']}"
    )
    assert refreshed["status"] == "ACTIVE", "one strike is below the threshold of three"
