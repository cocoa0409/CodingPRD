"""Order/showtime state-machine branches, refund cascades, loyalty accrual and
reversal, and conserved-quantity invariants across forward+compensating actions.
"""
from test_helpers import TEST_USERS, get_success_data
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_seat_conservation

MANAGER = TEST_USERS["manager_headers"]
AGENT = TEST_USERS["agent_headers"]


# ===========================================================================
# Difficulty/non_linear_state_machine/order_paid_branches_to_refunded
# ===========================================================================

def test_paid_order_refund_branch_voids_tickets_and_credits_wallet(api):
    """PRD §3.7: "Refunding moves the order to REFUNDED and cascades as follows:
    the order's payment has its refunded_cents increased by the refunded amount
    and its status set to REFUNDED; if the destination is the original payment
    method, the funds return to the payer, whereas if the destination is the
    wallet, the member's wallet_credit_cents is credited by the refunded amount;
    every ticket on the order is VOIDED and every bound seat returns to FREE; the
    loyalty points originally accrued for this order are subtracted from the
    member's loyalty_points and the member's tier is re-derived; and the
    showtime's version is incremented."

    Design: Difficulty/non_linear_state_machine/order_paid_branches_to_refunded
    """
    ctx = fx.setup_paid_order(base_price_cents=1000, num_seats=1)
    order = ctx["order"]
    seat0 = ctx["seat_ids"][0]

    refunded = get_success_data(
        api.refund_order(order["id"], {"refund_destination": "WALLET"}, AGENT)
    )
    assert refunded["status"] == "REFUNDED"

    tickets = get_success_data(api.list_order_tickets(order["id"], MANAGER))
    assert all(t["state"] == "VOIDED" for t in tickets)

    seats = get_success_data(api.get_showtime_seats(ctx["showtime"]["id"], MANAGER, params={"limit": 100}))
    target = next(s for s in seats if s["id"] == seat0)
    assert target["occupancy"] == "FREE"

    member = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert member["wallet_credit_cents"] == 1000  # 1000c refunded to wallet
    assert member["loyalty_points"] == 0  # base 1000 -> 10 points accrued then reversed


def test_paid_order_refund_marks_order_terminal(api):
    """PRD §3.7: "Once an order is PAID, a BoxOfficeAgent may refund it."

    Design: Difficulty/non_linear_state_machine/order_paid_branches_to_refunded
    """
    ctx = fx.setup_paid_order(base_price_cents=1000, num_seats=1)
    order = ctx["order"]
    assert order["status"] == "PAID"

    refunded = get_success_data(
        api.refund_order(order["id"], {"refund_destination": "ORIGINAL"}, AGENT)
    )
    assert refunded["status"] == "REFUNDED"


# ===========================================================================
# Difficulty/non_linear_state_machine/showtime_branches_scheduled_to_cancelled
# ===========================================================================

def test_scheduled_showtime_cancel_branch_releases_seats(api):
    """PRD §3.8: "Cancelling a SCHEDULED screening is the simple case: no orders
    exist yet, so the system merely releases any pre-created seats back to FREE
    occupancy and increments the showtime's version."

    Design: Difficulty/non_linear_state_machine/showtime_branches_scheduled_to_cancelled
    """
    base = fx.setup_base(seat_count=4)
    showtime = fx.schedule_showtime(base["auditorium"]["id"], base["film"]["id"])
    assert showtime["status"] == "SCHEDULED"

    cancelled = get_success_data(
        api.cancel_showtime(showtime["id"], {"expected_showtime_version": showtime["version"]}, MANAGER)
    )
    assert cancelled["status"] == "CANCELLED"

    seats = get_success_data(api.get_showtime_seats(showtime["id"], MANAGER, params={"limit": 100}))
    assert all(s["occupancy"] == "FREE" for s in seats)


def test_scheduled_showtime_cancel_is_terminal_not_on_sale(api):
    """PRD §3.8: "The screening moves to CANCELLED, a terminal status, and the
    consequences differ by where it started."
    PRD §3.2: "A newly scheduled showtime starts in SCHEDULED status."

    Design: Difficulty/non_linear_state_machine/showtime_branches_scheduled_to_cancelled
    """
    base = fx.setup_base(seat_count=4)
    showtime = fx.schedule_showtime(base["auditorium"]["id"], base["film"]["id"])

    cancelled = get_success_data(
        api.cancel_showtime(showtime["id"], {"expected_showtime_version": showtime["version"]}, MANAGER)
    )
    assert cancelled["status"] == "CANCELLED"
    # Re-read confirms it stayed CANCELLED (terminal).
    reread = get_success_data(api.get_showtime(showtime["id"], MANAGER))
    assert reread["status"] == "CANCELLED"


# ===========================================================================
# Difficulty/transitive_cascade/cancel_showtime_refund_payment_credit_wallet_depth3
# ===========================================================================

def test_cancel_showtime_cascades_refund_payment_and_wallet(api):
    """PRD §3.8: "Cancelling an ON_SALE screening unwinds all live commitments in
    one atomic step. Every PAID order on the screening is refunded in full (driving
    each through its own refund cascade — payment marked refunded, tickets voided,
    seats freed, and loyalty reversed, exactly as in Section 3.7, except that this
    cascade is permitted even after the screening's start because it originates from
    the cancel)."
    PRD §3.7: "if the destination is the wallet, the member's wallet_credit_cents
    is credited by the refunded amount"

    Design: Difficulty/transitive_cascade/cancel_showtime_refund_payment_credit_wallet_depth3
    """
    ctx = fx.setup_paid_order(base_price_cents=1500, num_seats=1)
    showtime = ctx["showtime"]
    order = ctx["order"]

    version_now = fx.current_version(showtime["id"])
    cancelled = get_success_data(
        api.cancel_showtime(showtime["id"], {"expected_showtime_version": version_now}, MANAGER)
    )
    assert cancelled["status"] == "CANCELLED"

    reread_order = get_success_data(api.get_order(order["id"], MANAGER))
    assert reread_order["status"] == "REFUNDED"

    payments = get_success_data(api.list_order_payments(order["id"], MANAGER))
    assert len(payments) == 1
    assert payments[0]["status"] == "REFUNDED"
    assert payments[0]["refunded_cents"] == 1500
    # PRD §3.8 enumerates the cancel cascade as "payment marked refunded, tickets
    # voided, seats freed, and loyalty reversed" and supplies no refund_destination;
    # §3.7's wallet credit is conditional on the destination being the wallet, which
    # the cancel cascade never names. A PRD-faithful cancel returns funds to the
    # original payment method, so no wallet-credit outcome is uniquely derivable.


def test_cancel_on_sale_showtime_voids_tickets_and_frees_seats(api):
    """PRD §3.8: "Every ticket on the screening, whether it was HELD or SOLD, is
    VOIDED, and every seat on the screening returns to FREE. The showtime's version
    is incremented to reflect the cascade."

    Design: Difficulty/transitive_cascade/cancel_showtime_refund_payment_credit_wallet_depth3
    """
    ctx = fx.setup_paid_order(base_price_cents=1500, num_seats=1)
    showtime = ctx["showtime"]
    order = ctx["order"]

    version_now = fx.current_version(showtime["id"])
    get_success_data(
        api.cancel_showtime(showtime["id"], {"expected_showtime_version": version_now}, MANAGER)
    )

    tickets = get_success_data(api.list_order_tickets(order["id"], MANAGER))
    assert all(t["state"] == "VOIDED" for t in tickets)

    seats = get_success_data(api.get_showtime_seats(showtime["id"], MANAGER, params={"limit": 100}))
    assert all(s["occupancy"] == "FREE" for s in seats)


# ===========================================================================
# Difficulty/transitive_cascade/pay_accrues_loyalty_then_rederives_tier_depth2
# ===========================================================================

def test_pay_accrues_loyalty_points(api):
    """PRD §3.5: "The member's loyalty is accrued as described in Section 3.3 —
    one point per full 100 cents of the ticket subtotal — and the member's tier is
    re-derived from the new balance."

    Design: Difficulty/transitive_cascade/pay_accrues_loyalty_then_rederives_tier_depth2
    """
    # 2 STANDARD seats at base 2500 -> subtotal 5000 -> 50 points.
    ctx = fx.setup_paid_order(base_price_cents=2500, num_seats=2)
    member = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert member["loyalty_points"] == 50


def test_pay_rederives_tier_to_silver_at_threshold(api):
    """PRD §3.3: "After every accrual or reversal, the member's tier is re-derived
    from the resulting lifetime loyalty_points balance using these breakpoints,
    evaluated against the balance with at-least (greater-than-or-equal) semantics:
    the member is GOLD when the balance is at least 200 points, otherwise SILVER
    when the balance is at least 50 points, otherwise BRONZE."

    Design: Difficulty/transitive_cascade/pay_accrues_loyalty_then_rederives_tier_depth2
    """
    ctx = fx.setup_paid_order(base_price_cents=2500, num_seats=2)
    member = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert member["loyalty_points"] == 50
    assert member["tier"] == "SILVER"


# ===========================================================================
# Difficulty/compensating_invariant/seat_count_conserved_across_pay_then_refund
# ===========================================================================

def test_seat_map_conserved_after_pay_then_refund(api):
    """PRD §2.6: "seats_sold is the count of tickets on the showtime in SOLD state,
    seats_held is the count of tickets in HELD state that have not expired, and
    gross_receipts_cents is the sum of final_price_cents over the showtime's sold,
    non-refunded tickets."
    PRD §3.7: "every ticket on the order is VOIDED and every bound seat returns to
    FREE; the loyalty points originally accrued for this order are subtracted from
    the member's loyalty_points and the member's tier is re-derived; and the
    showtime's version is incremented."

    Design: Difficulty/compensating_invariant/seat_count_conserved_across_pay_then_refund
    """
    ctx = fx.setup_paid_order(base_price_cents=1000, num_seats=2, seat_count=4)
    order = ctx["order"]
    showtime = ctx["showtime"]

    get_success_data(api.refund_order(order["id"], {"refund_destination": "ORIGINAL"}, AGENT))

    reread = get_success_data(api.get_showtime(showtime["id"], MANAGER))
    assert reread["seats_sold"] == 0
    assert reread["seats_held"] == 0

    seats = get_success_data(api.get_showtime_seats(showtime["id"], MANAGER, params={"limit": 100}))
    assert_seat_conservation(seats, 4)
    assert all(s["occupancy"] == "FREE" for s in seats)


def test_seats_sold_reflects_paid_order_before_refund(api):
    """PRD §2.6: "seats_sold is the count of tickets on the showtime in SOLD state,
    seats_held is the count of tickets in HELD state that have not expired, and
    gross_receipts_cents is the sum of final_price_cents over the showtime's sold,
    non-refunded tickets."
    PRD §3.5: "Each ticket then transitions from HELD to SOLD, and each bound seat's
    occupancy becomes SOLD."

    Design: Difficulty/compensating_invariant/seat_count_conserved_across_pay_then_refund
    """
    ctx = fx.setup_paid_order(base_price_cents=1000, num_seats=2, seat_count=4)
    showtime = ctx["showtime"]

    reread = get_success_data(api.get_showtime(showtime["id"], MANAGER))
    assert reread["seats_sold"] == 2
    seats = get_success_data(api.get_showtime_seats(showtime["id"], MANAGER, params={"limit": 100}))
    assert_seat_conservation(seats, 4)
    assert sum(1 for s in seats if s["occupancy"] == "SOLD") == 2


# ===========================================================================
# Difficulty/compensating_invariant/loyalty_points_conserved_across_accrue_then_reverse
# ===========================================================================

def test_loyalty_points_return_to_zero_after_refund(api):
    """PRD §3.3: "The exact same number of points that were granted for an order is
    subtracted again if that order is later refunded or exchanged."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_across_accrue_then_reverse
    """
    # 2 seats at base 2500 -> subtotal 5000 -> +50, then refunded -> 0.
    ctx = fx.setup_paid_order(base_price_cents=2500, num_seats=2)
    order = ctx["order"]

    before = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert before["loyalty_points"] == 50

    get_success_data(api.refund_order(order["id"], {"refund_destination": "ORIGINAL"}, AGENT))

    after = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert after["loyalty_points"] == 0
    assert after["tier"] == "BRONZE"


def test_refund_demotes_tier_when_balance_drops(api):
    """PRD §3.3: "Because reversals reduce the balance, a refund or exchange can
    demote a member's tier."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_across_accrue_then_reverse
    """
    ctx = fx.setup_paid_order(base_price_cents=2500, num_seats=2)
    order = ctx["order"]

    promoted = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert promoted["tier"] == "SILVER"

    get_success_data(api.refund_order(order["id"], {"refund_destination": "ORIGINAL"}, AGENT))

    demoted = get_success_data(api.get_member(ctx["member"]["id"], MANAGER))
    assert demoted["tier"] == "BRONZE"
