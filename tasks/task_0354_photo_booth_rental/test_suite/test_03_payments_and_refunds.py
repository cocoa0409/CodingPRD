"""Money lifecycle: deposit/balance/refund amount checks, forfeiture, refund tiers,
and the cancel-refund money-conservation invariant.

Deposit dollar amounts are never asserted as literals (deposit_due = quote_subtotal *
DEPOSIT_PCT, and the PRD does not pin DEPOSIT_PCT's value). Tests read deposit_due /
balance_due / the live refundable amount dynamically, then exercise the exact-amount
rules and tier behaviour, all of which ARE PRD-derivable.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, make_customer_headers, TEST_USERS,
    seed_base_scenario, seed_model_and_package, create_customer, create_booking,
    create_deposit_paid_booking, create_confirmed_booking, create_finalized_booking,
    pay_deposit, confirm_booking, cancel_confirmed_booking,
    create_payment_payload,
)

OPS = TEST_USERS["operations_manager_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


# ─── Deposit / balance / refund amount-mismatch (Queue B validations) ──

def test_deposit_amount_mismatch_rejected(api):
    """PRD §3.6: "the payment `amount` must equal the booking's `deposit_due` exactly —
    the deposit is paid in full, never partially. A wrong deposit amount is rejected with
    `ERR_DEPOSIT_AMOUNT_MISMATCH`."

    Design: Corner/validations/deposit_amount_mismatch_rejected
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    booking = create_booking(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-13T00:00:00Z",
        venue_distance_miles=0)
    wrong_amount = round(booking["deposit_due"] + 10.00, 2)
    res = api.create_payment(booking["id"], create_payment_payload("DEPOSIT", wrong_amount), FINANCE)
    validate_error(res, ApiErrorId.ERR_DEPOSIT_AMOUNT_MISMATCH.value)
    after = get_success_data(api.get_booking(booking["id"], OPS))
    assert after["payment_status"] == "UNPAID"


def test_balance_amount_mismatch_rejected(api):
    """PRD §3.6: "The payment `amount` must equal the booking's `balance_due` exactly —
    it must clear the outstanding balance — otherwise `ERR_BALANCE_AMOUNT_MISMATCH`."

    Design: Corner/validations/balance_amount_mismatch_rejected
    """
    built = create_finalized_booking()  # IN_SERVICE, EventLog finalized, DEPOSIT_PAID
    booking = built["booking"]
    wrong_balance = round(booking["balance_due"] - 100.00, 2)
    res = api.create_payment(booking["id"], create_payment_payload("BALANCE", wrong_balance), FINANCE)
    validate_error(res, ApiErrorId.ERR_BALANCE_AMOUNT_MISMATCH.value)
    after = get_success_data(api.get_booking(booking["id"], OPS))
    assert after["payment_status"] == "DEPOSIT_PAID"


def test_refund_amount_mismatch_rejected(api):
    """PRD §3.6: "The payment `amount` must equal that computed refundable amount exactly,
    otherwise `ERR_REFUND_AMOUNT_MISMATCH`."

    Design: Corner/validations/refund_amount_mismatch_rejected
    """
    # 90-day full-refund tier (clock 2026-06-14, event 2026-09-12).
    built = create_confirmed_booking()
    booking = built["booking"]
    cust_id = built["scenario"]["customer"]["id"]
    cancel_confirmed_booking(booking["id"], cust_id)
    # Full-tier refundable == deposit_due; post a clearly-wrong amount.
    wrong_refund = round(booking["deposit_due"] - 50.00, 2)
    res = api.create_payment(booking["id"], create_payment_payload("REFUND", wrong_refund), FINANCE)
    validate_error(res, ApiErrorId.ERR_REFUND_AMOUNT_MISMATCH.value)


def test_addon_qty_out_of_range_rejected(api):
    """PRD §3.3: "The quantity must fall within 1 through the catalog item's `max_qty`;
    a quantity outside that range is rejected with `ERR_QTY_OUT_OF_RANGE`."

    Design: Corner/validations/addon_qty_out_of_range_rejected
    """
    from test_helpers import create_add_on, add_add_on_line  # local to keep imports tidy
    model, package = seed_model_and_package()
    customer = create_customer()
    booking = create_booking(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    album = create_add_on(code="ALBUM", name="Leather Album", unit_price=150.00, max_qty=1)
    res = api.add_booking_add_on(
        booking["id"], {"add_on_id": album["id"], "qty": 2}, make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_QTY_OUT_OF_RANGE.value)


# ─── Forfeit inside the 30-day tier (Queue B state_machines) ───────────

def test_forfeit_inside_30_day_tier_retains_deposit(api):
    """PRD §3.6: "It is allowed only when `schedule_status` is `CANCELLED`,
    `payment_status` is `DEPOSIT_PAID`, and the cancellation refund calculation returned
    a refundable amount of exactly zero (the inside-30-day tier). No money is returned;
    the deposit is retained by the operator."

    Design: Corner/state_machines/forfeit_inside_30_day_tier_deposit_retained
    """
    # Clock 10 days before the event -> inside-30 tier -> refundable 0.
    sc = seed_base_scenario()
    api.set_clock({"to_iso8601": "2026-09-02T18:00:00Z"}, TEST_USERS["platform_admin_headers"])
    booking = create_booking(
        sc["customer"]["id"], sc["package"]["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    _, paid = pay_deposit(booking["id"])
    paid_deposit = paid["amount_paid"]
    confirmed = confirm_booking(booking["id"], sc["booth"]["id"])
    cancel_confirmed_booking(booking["id"], sc["customer"]["id"])
    forfeited = validate_success(api.forfeit_booking(booking["id"], FINANCE), 200)
    assert forfeited["payment_status"] == "FORFEITED"
    assert forfeited["amount_refunded"] == pytest.approx(0.0, abs=0.01)
    assert forfeited["amount_paid"] == pytest.approx(paid_deposit, abs=0.01)


# ─── Cancellation refund tiers (Difficulty Rule 1 + Rule 6) ────────────

class TestFullRefundTier:
    """Difficulty Rule 1 (tier variants) and Rule 6 (60-day boundary): a cancel at the
    full-refund tier makes the entire deposit refundable."""

    def test_cancel_at_90_days_full_refund_completes_to_refunded(self, api):
        """PRD §3.7: "if days-to-event is at least 60, the deposit is fully refundable
        (100%)."
        PRD §3.6: "A `REFUND` payment moves the booking from `DEPOSIT_PAID` to
        `REFUNDED`. It is allowed only when `schedule_status` is `CANCELLED`,
        `payment_status` is `DEPOSIT_PAID`, and the cancellation refund calculation
        returned a refundable amount greater than zero."

        Design: Difficulty/dual_variant_calc/cancellation_refund_tier_variants_on_booking
        """
        # Clock 2026-06-14, event 2026-09-12 -> 90 days out -> full tier.
        built = create_confirmed_booking()
        booking = built["booking"]
        cust_id = built["scenario"]["customer"]["id"]
        cancelled = cancel_confirmed_booking(booking["id"], cust_id)
        assert cancelled["schedule_status"] == "CANCELLED"
        # Full tier: refundable == deposit_due. Refund exactly that.
        refund = validate_success(
            api.create_payment(booking["id"],
                               create_payment_payload("REFUND", booking["deposit_due"]), FINANCE),
            201)
        assert refund["kind"] == "REFUND"
        after = get_success_data(api.get_booking(booking["id"], OPS))
        assert after["payment_status"] == "REFUNDED"

    def test_full_refund_equals_full_deposit_not_half(self, api):
        """PRD §3.7: "The refundable deposit is the `deposit_due` multiplied by that tier
        percentage, rounded half-up to two decimal places."
        PRD §3.6: "The payment `amount` must equal that computed refundable amount
        exactly, otherwise `ERR_REFUND_AMOUNT_MISMATCH`."

        Design: Difficulty/dual_variant_calc/cancellation_refund_tier_variants_on_booking
        """
        built = create_confirmed_booking()
        booking = built["booking"]
        cust_id = built["scenario"]["customer"]["id"]
        cancel_confirmed_booking(booking["id"], cust_id)
        # Half of the deposit must be rejected at the full (100%) tier.
        half = round(booking["deposit_due"] * 0.5, 2)
        res = api.create_payment(booking["id"], create_payment_payload("REFUND", half), FINANCE)
        validate_error(res, ApiErrorId.ERR_REFUND_AMOUNT_MISMATCH.value)


class TestRefundTierBoundary60Days:
    """Difficulty Rule 6: the day-threshold boundary at exactly 60 days uses the full
    (100%) tier, not the 30-59 (50%) tier."""

    def _confirmed_at_clock(self, api, clock_iso):
        sc = seed_base_scenario()
        api.set_clock({"to_iso8601": clock_iso}, TEST_USERS["platform_admin_headers"])
        booking = create_booking(
            sc["customer"]["id"], sc["package"]["id"],
            event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
            venue_distance_miles=0)
        pay_deposit(booking["id"])
        confirm_booking(booking["id"], sc["booth"]["id"])
        return sc, get_success_data(api.get_booking(booking["id"], OPS))

    def test_exactly_60_days_uses_full_tier(self, api):
        """PRD §3.7: "The days-to-event figure is the span from the current clock instant
        to `event_start`, expressed in days and rounded **down** to a whole number of
        days. The deposit refund percentage is then tiered: if days-to-event is at least
        60, the deposit is fully refundable (100%)."

        Design: Difficulty/boundary_precision_check/refund_tier_exactly_60_days_full_refund
        """
        # Clock 2026-07-14T18:00 -> event 2026-09-12T18:00 is exactly 60 days out.
        sc, booking = self._confirmed_at_clock(api, "2026-07-14T18:00:00Z")
        cancel_confirmed_booking(booking["id"], sc["customer"]["id"])
        # Full tier => refunding the entire deposit succeeds and reaches REFUNDED.
        validate_success(
            api.create_payment(booking["id"],
                               create_payment_payload("REFUND", booking["deposit_due"]), FINANCE),
            201)
        after = get_success_data(api.get_booking(booking["id"], OPS))
        assert after["payment_status"] == "REFUNDED"

    def test_exactly_60_days_not_half_tier(self, api):
        """PRD §3.7: "otherwise if days-to-event is at least 30 (the 30-through-59
        window), the deposit is 50% refundable."
        PRD §3.6: "The payment `amount` must equal that computed refundable amount
        exactly, otherwise `ERR_REFUND_AMOUNT_MISMATCH`."

        Design: Difficulty/boundary_precision_check/refund_tier_exactly_60_days_full_refund
        """
        sc, booking = self._confirmed_at_clock(api, "2026-07-14T18:00:00Z")
        cancel_confirmed_booking(booking["id"], sc["customer"]["id"])
        # At exactly 60 days the half-tier amount must be rejected (it is NOT 50%).
        half = round(booking["deposit_due"] * 0.5, 2)
        res = api.create_payment(booking["id"], create_payment_payload("REFUND", half), FINANCE)
        validate_error(res, ApiErrorId.ERR_REFUND_AMOUNT_MISMATCH.value)


# ─── Money conservation invariant (Difficulty Rule 9) ──────────────────

class TestCancelRefundMoneyConservation:
    """Difficulty Rule 9: after a full-refund cancel, net_cash_held == amount_paid -
    amount_refunded must equal 0."""

    def test_net_cash_zero_after_full_refund(self, api):
        """PRD §3.6: "On success the refund payment is appended, `amount_refunded` is
        increased by the amount, and the booking's `version` is incremented."
        PRD §3.7: "if days-to-event is at least 60, the deposit is fully refundable
        (100%)."

        Design: Difficulty/compensating_invariant/cancel_refund_money_conservation
        """
        built = create_confirmed_booking()
        booking = built["booking"]
        cust_id = built["scenario"]["customer"]["id"]
        cancel_confirmed_booking(booking["id"], cust_id)
        validate_success(
            api.create_payment(booking["id"],
                               create_payment_payload("REFUND", booking["deposit_due"]), FINANCE),
            201)
        after = get_success_data(api.get_booking(booking["id"], OPS))
        net = round(after["amount_paid"] - after["amount_refunded"], 2)
        assert net == pytest.approx(0.0, abs=0.01)

    def test_amount_paid_equals_amount_refunded_after_full_refund(self, api):
        """PRD §3.7: "any amount paid beyond the deposit is always fully refundable."
        PRD §3.6: "A `REFUND` payment moves the booking from `DEPOSIT_PAID` to
        `REFUNDED`."

        Design: Difficulty/compensating_invariant/cancel_refund_money_conservation
        """
        built = create_confirmed_booking()
        booking = built["booking"]
        cust_id = built["scenario"]["customer"]["id"]
        cancel_confirmed_booking(booking["id"], cust_id)
        validate_success(
            api.create_payment(booking["id"],
                               create_payment_payload("REFUND", booking["deposit_due"]), FINANCE),
            201)
        after = get_success_data(api.get_booking(booking["id"], OPS))
        assert after["amount_paid"] == pytest.approx(after["amount_refunded"], abs=0.01)
        assert after["payment_status"] == "REFUNDED"
