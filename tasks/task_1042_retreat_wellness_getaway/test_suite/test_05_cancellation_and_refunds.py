"""Guest vs operator refund variants, lead-time refund ladder, and cash/occupancy conservation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, setup_booking, setup_booking_deposit_paid, get_room,
)
from test_helpers.constants import DEFAULT_CLOCK

_OP = TEST_USERS["operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / cancellation_refund_guest_vs_operator_variant
# ---------------------------------------------------------------------------
def test_guest_cancel_thirty_days_out_refunds_half(api):
    """PRD §3.7: "thirty or more but fewer than sixty days ahead receives half ... the refund
    amount is the booking's amount_paid_cents multiplied by the selected percentage, rounded
    half up to a whole cent, and stored in refund_cents."

    Design: Difficulty/dual_variant_calc/cancellation_refund_guest_vs_operator_variant
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    set_clock(api, "2026-08-02T00:00:00Z")  # exactly 30 days before start 2026-09-01
    booking = validate_success(api.cancel_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert booking["status"] == "CANCELLED"
    assert booking["cancelled_by"] == "GUEST"
    assert booking["refund_cents"] == 45225


def test_operator_retreat_cancel_forces_full_refund(api):
    """PRD §3.7: "When instead the cancellation is driven by an operator cancelling the whole retreat, `cancelled_by` is `OPERATOR` and the refund is forced to the full amount regardless of lead time."

    Design: Difficulty/dual_variant_calc/cancellation_refund_guest_vs_operator_variant
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    set_clock(api, "2026-08-02T00:00:00Z")  # 30 days out — guest tier would be 0.50
    validate_success(api.cancel_retreat(ctx["retreat"]["id"], _OP), 200)
    booking = validate_success(api.get_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert booking["status"] == "CANCELLED"
    assert booking["cancelled_by"] == "OPERATOR"
    assert booking["refund_cents"] == 90450  # full amount_paid, not the 0.50 tier's 45225


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / refund_tier_boundary_exactly_30_days
# ---------------------------------------------------------------------------
def test_refund_at_exactly_thirty_days_is_half(api):
    """PRD §3.7: "thirty or more but fewer than sixty days ahead receives half ... The lead
    time is the number of whole days between the current logical time and the retreat's
    start_date, taken as the floor of the gap divided into 86400-second days."

    Design: Difficulty/boundary_precision_check/refund_tier_boundary_exactly_30_days
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    set_clock(api, "2026-08-02T00:00:00Z")  # exactly 30 days
    booking = validate_success(api.cancel_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert booking["refund_cents"] == 45225


def test_refund_at_twenty_nine_days_drops_to_quarter(api):
    """PRD §3.7: "fourteen or more but fewer than thirty days ahead receives a quarter ... the
    refund amount is the booking's amount_paid_cents multiplied by the selected percentage,
    rounded half up to a whole cent."

    Design: Difficulty/boundary_precision_check/refund_tier_boundary_exactly_30_days
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    set_clock(api, "2026-08-03T00:00:00Z")  # 29 days before start 2026-09-01
    booking = validate_success(api.cancel_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert booking["refund_cents"] == 22613  # round(90450 * 0.25) = round(22612.5)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / cash_conserved_on_deposit_then_full_refund
# ---------------------------------------------------------------------------
def test_guest_cancel_sixty_plus_days_out_full_refund(api):
    """PRD §3.7: "A guest cancelling sixty or more days ahead receives a full refund ... the
    refund amount is the booking's amount_paid_cents multiplied by the selected percentage."

    Design: Difficulty/compensating_invariant/cash_conserved_on_deposit_then_full_refund
    """
    # Default clock 2026-07-01 is 62 days before start 2026-09-01 (>= 60-day tier).
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    booking = validate_success(api.cancel_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert booking["cancelled_by"] == "GUEST"
    assert booking["refund_cents"] == 90450


def test_full_refund_records_refund_payment_and_preserves_amount_paid(api):
    """PRD §3.7: "If that refund is greater than zero, the server records a `Payment` of type `REFUND` for the refund amount. Note that refunds never reduce `amount_paid_cents`, which continues to reflect the gross deposit and balance actually paid."

    Design: Difficulty/compensating_invariant/cash_conserved_on_deposit_then_full_refund
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    booking = validate_success(api.cancel_booking(ctx["booking"]["id"], gh), 200)
    assert booking["amount_paid_cents"] == 90450  # unchanged by the refund
    payments = validate_success(api.list_booking_payments(ctx["booking"]["id"], gh), 200)
    refunds = [p for p in payments if p["type"] == "REFUND"]
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 90450


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / booking_branch_pending_to_cancelled_divergent
# ---------------------------------------------------------------------------
def test_cancel_unpaid_booking_zero_refund_releases_beds(api):
    """PRD §3.7: "Cancelling always releases capacity and transport: the booking's party_size
    is subtracted from the room's reserved_beds and from the retreat's reserved_count."
    PRD §3.7: "the refund amount is the booking's `amount_paid_cents` multiplied by the selected percentage, rounded half up to a whole cent, and stored in `refund_cents`."

    Design: Difficulty/non_linear_state_machine/booking_branch_pending_to_cancelled_divergent
    """
    ctx = setup_booking(api, party_size=2, room_overrides={"bed_count": 4})
    booking = validate_success(api.cancel_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert booking["status"] == "CANCELLED"
    assert booking["refund_cents"] == 0  # nothing was paid
    room = get_room(api, ctx["retreat"]["id"], ctx["room"]["id"])
    assert room["reserved_beds"] == 0


def test_deposit_branch_from_pending_creates_deposit_payment(api):
    """PRD §3.3: "First the guest pays the deposit, moving the booking from PENDING_DEPOSIT to
    DEPOSIT_PAID ... A successful deposit records a Payment of type DEPOSIT for the deposit
    amount and adds that amount to amount_paid_cents."

    Design: Difficulty/non_linear_state_machine/booking_branch_pending_to_cancelled_divergent
    """
    ctx = setup_booking(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    booking = validate_success(
        api.pay_deposit(ctx["booking"]["id"], ctx["booking"]["deposit_cents"], gh), 200)
    assert booking["status"] == "DEPOSIT_PAID"
    assert booking["amount_paid_cents"] == 90450
    payments = validate_success(api.list_booking_payments(ctx["booking"]["id"], gh), 200)
    deposits = [p for p in payments if p["type"] == "DEPOSIT"]
    assert len(deposits) == 1
    assert deposits[0]["amount_cents"] == 90450


# ---------------------------------------------------------------------------
# Corner: state_machines / corner_cancel_already_cancelled_booking_invalid
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_booking_rejected(api):
    """PRD §3.7: "A guest may cancel their own booking from `PENDING_DEPOSIT`, `DEPOSIT_PAID`, or `CONFIRMED`"

    Design: Corner/state_machines/corner_cancel_already_cancelled_booking_invalid
    """
    ctx = setup_booking(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    validate_success(api.cancel_booking(ctx["booking"]["id"], gh), 200)
    resp = api.cancel_booking(ctx["booking"]["id"], gh)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
