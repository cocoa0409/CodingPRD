"""Transitive cancel cascade (booking -> schedule -> assignment -> total recompute),
balance/amount-paid recomputation on settlement, and the compensating-action
invariants (net cash retained == cancellation fee; order/cancel restores total).

Queue A (difficulty) instances exercised here:
  transitive_cascade / cancel_booking_releases_shooter_recomputes_total_depth3
  transitive_cascade / settle_balance_recomputes_amount_paid_then_balance_depth2
  compensating_invariant / cancel_refund_leaves_net_retained_equals_cancellation_fee
  compensating_invariant / addon_order_then_cancel_restores_booking_total
Queue B (corner) instances exercised here:
  cross_cutting_complexity_layers / occ_correct_schedule_version_assignment_succeeds
  cross_cutting_complexity_layers / derived_balance_due_reconciles_after_addon_then_deposit
  consistency_model / immediate_total_visible_in_addon_response
"""
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    make_client_headers, assert_booking_money_invariants,
    # fixtures
    setup_draft_booking, setup_confirmed_booking, setup_deposit_paid_booking,
    assign_second_shooter, settle_deposit, set_clock,
    # factories
    add_on_order_payload, create_payment_payload, cancel_add_on_order_payload,
    second_shooter_assignment_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def _make_second_shooter(rate=8000):
    return get_success_data(
        api_client.create_photographer(
            {"email": "ss@studio.test", "full_name": "Second Shooter",
             "skills": ["PHOTO"], "hourly_rate_cents": rate}, ADMIN
        )
    )


# ===========================================================================
# transitive_cascade / cancel_booking_releases_shooter_recomputes_total_depth3
# ===========================================================================
def test_cancel_confirmed_booking_releases_shooter_and_recomputes_total(api):
    """PRD §3.8: "the booking's SCHEDULED or RESCHEDULED shoot schedule is moved to
    CANCELLED, and that schedule cancellation in turn releases each ASSIGNED
    second-shooter assignment on it (moving each to RELEASED), with each release
    removing that assignment's contribution. After the releases settle, the booking's
    total_fee_cents and balance_due_cents are recomputed."

    WEDDING requested 8h: base 200000 + 30000 overage + 32000 shooter = 262000. Cancel
    from CONFIRMED -> schedule CANCELLED, assignment RELEASED, total recomputes to 230000.

    Design: Difficulty/transitive_cascade/cancel_booking_releases_shooter_recomputes_total_depth3
    """
    ctx = setup_confirmed_booking(
        session_type="WEDDING", tier="STANDARD",
        base_fee_cents=200000, included_shoot_hours=6, overage_hourly_rate_cents=15000,
        included_edited_images=100, requested_shoot_hours=8, requires_model_release=True,
        lead_hourly_rate_cents=12000,
        start_utc="2026-07-01T14:00:00Z", end_utc="2026-07-01T18:00:00Z",
    )
    booking, client, schedule = ctx["booking"], ctx["client"], ctx["schedule"]
    second = _make_second_shooter(8000)
    sched_now = get_success_data(api.get_shoot_schedule(schedule["id"], ADMIN))
    assignment = assign_second_shooter(schedule["id"], second["id"], sched_now["version"])
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["total_fee_cents"] == 262000

    set_clock("2026-06-10T00:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["workflow_status"] == "CANCELLED"
    assert cancelled["total_fee_cents"] == 230000, (
        f"shooter fee 32000 removed -> 230000, got {cancelled['total_fee_cents']}"
    )
    schedule_after = validate_success(api.get_shoot_schedule(schedule["id"], ADMIN))
    assert schedule_after["status"] == "CANCELLED"
    assignment_after = validate_success(
        api.get_second_shooter_assignment(assignment["id"], ADMIN)
    )
    assert assignment_after["status"] == "RELEASED"


def test_cancel_confirmed_booking_cascades_schedule_to_cancelled(api):
    """PRD §3.8: "Cancelling a CONFIRMED booking moves it CONFIRMED -> CANCELLED and
    triggers a deeper cascade ... the booking's SCHEDULED or RESCHEDULED shoot schedule
    is moved to CANCELLED."

    Even with no second shooter on it, cancelling a CONFIRMED booking cascades its
    schedule to CANCELLED (depth-1 leg of the cascade chain).

    Design: Difficulty/transitive_cascade/cancel_booking_releases_shooter_recomputes_total_depth3
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-20T10:00:00Z", end_utc="2026-07-20T12:00:00Z",
    )
    booking, client, schedule = ctx["booking"], ctx["client"], ctx["schedule"]
    set_clock("2026-07-01T00:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["workflow_status"] == "CANCELLED"
    schedule_after = validate_success(api.get_shoot_schedule(schedule["id"], ADMIN))
    assert schedule_after["status"] == "CANCELLED"


# ===========================================================================
# transitive_cascade / settle_balance_recomputes_amount_paid_then_balance_depth2
# ===========================================================================
def test_settle_balance_recomputes_amount_paid_and_balance(api):
    """PRD §3.6: "Settling a BALANCE requires the booking to be DEPOSIT_PAID and the
    payment to be PENDING with its amount_cents equal to the booking's current
    balance_due_cents; on success the track advances DEPOSIT_PAID -> PAID_IN_FULL, again
    recomputing the paid and balance figures."

    PORTRAIT total 100000, deposit 30000 settled (balance 70000). Settling a BALANCE of
    70000 -> amount_paid 100000, balance_due 0, payment_status PAID_IN_FULL.

    Design: Difficulty/transitive_cascade/settle_balance_recomputes_amount_paid_then_balance_depth2
    """
    ctx = setup_deposit_paid_booking(
        start_utc="2026-07-09T10:00:00Z", end_utc="2026-07-09T12:00:00Z",
    )
    booking = ctx["booking"]
    assert booking["payment_status"] == "DEPOSIT_PAID"
    assert booking["balance_due_cents"] == 70000
    balance_pay = get_success_data(
        api.create_payment(create_payment_payload(booking["id"], "BALANCE", 70000), ADMIN)
    )
    validate_success(api.settle_payment(balance_pay["id"], ADMIN))
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["amount_paid_cents"] == 100000
    assert booking_now["balance_due_cents"] == 0
    assert booking_now["payment_status"] == "PAID_IN_FULL"


def test_settle_deposit_recomputes_amount_paid_and_balance(api):
    """PRD §3.6: "Settling a DEPOSIT requires the booking to be UNPAID and the payment to
    be PENDING with its amount_cents equal to the booking's deposit_due_cents; on success
    the payment becomes SETTLED, the booking's amount_paid_cents and balance_due_cents are
    recomputed, and the payment track advances UNPAID -> DEPOSIT_PAID."

    PORTRAIT total 100000, deposit 30000 settled -> amount_paid 30000, balance 70000,
    payment_status DEPOSIT_PAID.

    Design: Difficulty/transitive_cascade/settle_balance_recomputes_amount_paid_then_balance_depth2
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-09T10:00:00Z", end_utc="2026-07-09T12:00:00Z",
    )
    booking = ctx["booking"]
    settle_deposit(booking["id"], booking["deposit_due_cents"])
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["amount_paid_cents"] == 30000
    assert booking_now["balance_due_cents"] == 70000
    assert booking_now["payment_status"] == "DEPOSIT_PAID"


# ===========================================================================
# compensating_invariant / cancel_refund_leaves_net_retained_equals_cancellation_fee
# ===========================================================================
def test_refund_settlement_leaves_net_retained_equal_to_fee(api):
    """PRD §3.6: "Settling a REFUND requires the booking to be REFUND_PENDING and the
    payment to be PENDING with its amount_cents equal to the booking's amount_paid_cents
    minus its cancellation_fee_cents; on success the refund subtracts from
    amount_paid_cents, the balance is recomputed, and the track returns
    REFUND_PENDING -> UNPAID, leaving the studio having retained exactly the cancellation fee."

    Deposit 30000 settled; cancel at lead>=14 -> fee 7500, REFUND_PENDING. A REFUND of
    30000-7500=22500 settles -> amount_paid 7500 (== fee), payment_status UNPAID.

    Design: Difficulty/compensating_invariant/cancel_refund_leaves_net_retained_equals_cancellation_fee
    """
    ctx = setup_deposit_paid_booking(
        start_utc="2026-08-20T10:00:00Z", end_utc="2026-08-20T12:00:00Z",
    )
    booking, client = ctx["booking"], ctx["client"]
    set_clock("2026-08-01T10:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["cancellation_fee_cents"] == 7500
    assert cancelled["payment_status"] == "REFUND_PENDING"
    refund = get_success_data(
        api.create_payment(create_payment_payload(booking["id"], "REFUND", 22500), ADMIN)
    )
    validate_success(api.settle_payment(refund["id"], ADMIN))
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["amount_paid_cents"] == 7500, (
        f"net retained 30000-22500 = 7500 (== fee), got {booking_now['amount_paid_cents']}"
    )
    assert booking_now["cancellation_fee_cents"] == 7500
    assert booking_now["payment_status"] == "UNPAID"


def test_cancel_overpaid_booking_enters_refund_pending(api):
    """PRD §3.8: "if the booking's amount_paid_cents exceeds its cancellation_fee_cents,
    the payment track moves to REFUND_PENDING so a compensating refund can be settled;
    otherwise the payment track is left as it was."

    Deposit 30000 paid; cancel at lead>=14 -> fee 7500. Since 30000 > 7500 the payment
    track moves to REFUND_PENDING.

    Design: Difficulty/compensating_invariant/cancel_refund_leaves_net_retained_equals_cancellation_fee
    """
    ctx = setup_deposit_paid_booking(
        start_utc="2026-08-20T10:00:00Z", end_utc="2026-08-20T12:00:00Z",
    )
    booking, client = ctx["booking"], ctx["client"]
    set_clock("2026-08-01T10:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["amount_paid_cents"] == 30000
    assert cancelled["cancellation_fee_cents"] == 7500
    assert cancelled["payment_status"] == "REFUND_PENDING"


# ===========================================================================
# compensating_invariant / addon_order_then_cancel_restores_booking_total
# ===========================================================================
def test_addon_order_then_cancel_restores_total(api):
    """PRD §3.8: "Cancelling an order - which also carries expected_booking_version -
    moves it ORDERED -> CANCELLED, recomputes the booking's total_fee_cents and
    balance_due_cents, and bumps the version again."

    PORTRAIT total 100000; order PRINT 60@500 (27000) -> total 127000; cancel that exact
    order -> total restored to 100000, order CANCELLED.

    Design: Difficulty/compensating_invariant/addon_order_then_cancel_restores_booking_total
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    client_h = make_client_headers(client["id"])
    order = get_success_data(
        api.create_add_on_order(
            booking["id"], add_on_order_payload("PRINT", 60, 500, booking["version"]), client_h
        )
    )
    after_order = validate_success(api.get_booking(booking["id"], ADMIN))
    assert after_order["total_fee_cents"] == 127000
    cancelled = validate_success(
        api.cancel_add_on_order(
            order["id"], cancel_add_on_order_payload(after_order["version"]), client_h
        )
    )
    assert cancelled["status"] == "CANCELLED"
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["total_fee_cents"] == 100000, (
        f"cancelling the 27000 order restores 100000, got {booking_now['total_fee_cents']}"
    )


def test_addon_order_raises_total_then_cancel_balances_invariant(api):
    """PRD §3.8: "because it joins the booking total, creating it recomputes the booking's
    total_fee_cents and balance_due_cents and bumps the booking's version. Cancelling an
    order ... moves it ORDERED -> CANCELLED, recomputes the booking's total_fee_cents and
    balance_due_cents."

    Order ALBUM 2@8000 (16000+3500=19500) raises 100000 -> 119500; cancelling restores
    100000 and the money invariant holds throughout.

    Design: Difficulty/compensating_invariant/addon_order_then_cancel_restores_booking_total
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    client_h = make_client_headers(client["id"])
    order = get_success_data(
        api.create_add_on_order(
            booking["id"], add_on_order_payload("ALBUM", 2, 8000, booking["version"]), client_h
        )
    )
    after_order = validate_success(api.get_booking(booking["id"], ADMIN))
    assert after_order["total_fee_cents"] == 119500
    assert_booking_money_invariants(after_order)
    validate_success(
        api.cancel_add_on_order(
            order["id"], cancel_add_on_order_payload(after_order["version"]), client_h
        )
    )
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["total_fee_cents"] == 100000
    assert_booking_money_invariants(booking_now)


# ===========================================================================
# cross_cutting_complexity_layers / occ_correct_schedule_version_assignment_succeeds
# ===========================================================================
def test_second_shooter_assignment_with_current_version_succeeds(api):
    """PRD §3.5: "Its billable extent is derived from the window ... take the window's
    duration as end_utc minus start_utc, convert to hours, and round up to a whole number
    of hours to obtain billable_hours. The assignment fee, assignment_fee_cents, is then
    billable_hours multiplied by the staffed photographer's hourly_rate_cents, pinned on
    the assignment at creation."

    4h window (14:00-18:00), shooter rate 8000, current schedule version -> 201,
    billable_hours 4, assignment_fee 32000.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_schedule_version_assignment_succeeds
    """
    ctx = setup_confirmed_booking(
        session_type="WEDDING", tier="STANDARD",
        base_fee_cents=200000, included_shoot_hours=6, overage_hourly_rate_cents=15000,
        included_edited_images=100, requested_shoot_hours=6, requires_model_release=True,
        lead_hourly_rate_cents=12000,
        start_utc="2026-09-10T14:00:00Z", end_utc="2026-09-10T18:00:00Z",
    )
    schedule = ctx["schedule"]
    second = _make_second_shooter(8000)
    sched_now = get_success_data(api.get_shoot_schedule(schedule["id"], ADMIN))
    assignment = validate_success(
        api.create_second_shooter_assignment(
            schedule["id"],
            second_shooter_assignment_payload(second["id"], sched_now["version"]),
            ADMIN,
        ),
        expected_status=201,
    )
    assert assignment["billable_hours"] == 4
    assert assignment["assignment_fee_cents"] == 32000


# ===========================================================================
# cross_cutting_complexity_layers / derived_balance_due_reconciles_after_addon_then_deposit
# ===========================================================================
def test_balance_due_reconciles_after_addon_then_deposit(api):
    """PRD §3.2: "The balance is then total_fee_cents minus amount_paid_cents, never
    allowed below zero ... This balance is recomputed at confirmation and again on every
    payment settlement." PRD §3.2: "Multiply the booking's total_fee_cents at confirm
    time by the package's deposit_pct and round that product half up to whole cents."

    PRINT add-on (27000) raises total to 127000; deposit 0.30*127000=38100 settled ->
    amount_paid 38100, balance_due 127000-38100 = 88900.

    Design: Corner/cross_cutting_complexity_layers/derived_balance_due_reconciles_after_addon_then_deposit
    """
    base = setup_draft_booking()
    booking, client, package, photographer = (
        base["booking"], base["client"], base["package"], base["photographer"]
    )
    client_h = make_client_headers(client["id"])
    get_success_data(
        api.create_add_on_order(
            booking["id"], add_on_order_payload("PRINT", 60, 500, booking["version"]), client_h
        )
    )
    # sign contract, schedule, confirm
    from test_helpers import create_signed_contract, create_schedule
    create_signed_contract(booking["id"], client["id"], includes_model_release=False)
    create_schedule(booking["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z")
    confirmed = validate_success(api.confirm_booking(booking["id"], client_h))
    assert confirmed["total_fee_cents"] == 127000
    assert confirmed["deposit_due_cents"] == 38100
    deposit_pay = get_success_data(
        api.create_payment(create_payment_payload(booking["id"], "DEPOSIT", 38100), ADMIN)
    )
    validate_success(api.settle_payment(deposit_pay["id"], ADMIN))
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["amount_paid_cents"] == 38100
    assert booking_now["balance_due_cents"] == 88900, (
        f"127000 - 38100 = 88900, got {booking_now['balance_due_cents']}"
    )


# ===========================================================================
# consistency_model / immediate_total_visible_in_addon_response
# ===========================================================================
def test_addon_total_immediately_visible_on_get(api):
    """PRD §2.5: "A booking exposes several computed monetary fields - total_fee_cents,
    deposit_due_cents, amount_paid_cents, balance_due_cents, and cancellation_fee_cents -
    that the server keeps in step with the events that drive them rather than accepting
    them as input. Whenever any of these is recomputed, the booking is mutated."

    After POST add-on-orders, an immediate GET shows the updated total_fee_cents (127000).

    Design: Corner/consistency_model/immediate_total_visible_in_addon_response
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    client_h = make_client_headers(client["id"])
    get_success_data(
        api.create_add_on_order(
            booking["id"], add_on_order_payload("PRINT", 60, 500, booking["version"]), client_h
        )
    )
    booking_now = validate_success(api.get_booking(booking["id"], client_h))
    assert booking_now["total_fee_cents"] == 127000
