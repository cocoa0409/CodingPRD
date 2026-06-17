"""State-machine corner tests: initial/terminal states, precondition
enforcement, idempotency, compensation, cross-entity receive (PRD §3.2–§3.11).

Queue B — corner section: state_machines (non-stub instances).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_customer, create_sku, create_tier, create_ticket,
    create_special_order, open_layaway_with_deposit, create_build,
    create_confirmed_special_order, create_appraised_trade_in, create_bay,
    open_layaway, reserve_part, reserve_frame, get_sku,
    create_bay_booking_payload, make_customer_headers,
    TEST_USERS,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


def test_ticket_initial_state_is_intake():
    """PRD §3.2: "A new ticket begins in `INTAKE`."

    A freshly created service ticket has status==INTAKE.

    Design: Corner/state_machines/ticket_initial_state_is_intake
    """
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = validate_success(api_client.create_service_ticket(
        {"customer_id": cust["id"], "tier_id": tier["id"]}, ADV), 201)
    assert ticket["status"] == "INTAKE"


def test_approve_ticket_from_intake_invalid_state():
    """PRD §3.2: "From `AWAITING_APPROVAL`, the customer approves the quote,
    moving the ticket to `IN_PROGRESS`; approval is permitted only from
    `AWAITING_APPROVAL`".
    PRD §3.2: "A transition requested from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE`."

    Approving a ticket still in INTAKE (no quote) returns ERR_INVALID_STATE.

    Design: Corner/state_machines/approve_ticket_from_intake_invalid_state
    """
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = create_ticket(cust["id"], tier["id"])
    res = api_client.approve_service_ticket(ticket["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_closed_ticket_terminal_lockdown():
    """PRD §3.2: "the terminal states are `CLOSED` and `CANCELLED`."
    PRD §3.2: "A transition requested from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE`."

    A CLOSED ticket cannot be cancelled — cancel returns ERR_INVALID_STATE and
    the ticket stays CLOSED.

    Design: Corner/state_machines/cancel_closed_ticket_terminal_lockdown
    """
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = create_ticket(cust["id"], tier["id"])
    validate_success(api_client.quote_service_ticket(ticket["id"], ADV), 200)
    validate_success(api_client.approve_service_ticket(
        ticket["id"], make_customer_headers(cust["id"])), 200)
    validate_success(api_client.complete_service_ticket(ticket["id"], ADV), 200)
    validate_success(api_client.close_service_ticket(ticket["id"], ADV), 200)
    res = api_client.cancel_service_ticket(ticket["id"], ADV)
    validate_error(res, "ERR_INVALID_STATE")
    reread = validate_success(api_client.get_service_ticket(ticket["id"], ADV), 200)
    assert reread["status"] == "CLOSED"


def test_special_order_confirm_without_deposit_short():
    """PRD §3.8: "Confirming a special order moves it from `QUOTED` to
    `CONFIRMED` and is permitted only from `QUOTED` and only when
    `deposit_paid_cents` is at least `deposit_required_cents`; a confirm with too
    little deposit is rejected with `ERR_DEPOSIT_SHORT`."

    Confirming a QUOTED special order with no deposit paid returns
    ERR_DEPOSIT_SHORT.

    Design: Corner/state_machines/special_order_confirm_without_deposit_invalid_or_deposit_short
    """
    cust = create_customer()
    sku = create_sku(name="Special Wheel", category="PART", list_price_cents=60000, on_hand=0)
    so = create_special_order(cust["id"], sku["id"], 1)
    res = api_client.confirm_special_order(so["id"], SA)
    validate_error(res, "ERR_DEPOSIT_SHORT")


def test_layaway_fulfill_not_paid_off():
    """PRD §3.7: "Fulfillment is permitted only from `ACTIVE` and only when
    `deposit_cents` is at least `price_cents`; a fulfill attempted on a plan that
    is not fully paid off is rejected with `ERR_LAYAWAY_NOT_PAID_OFF`."

    Fulfilling a plan whose deposit (15000) is below price (40000) returns
    ERR_LAYAWAY_NOT_PAID_OFF.

    Design: Corner/state_machines/layaway_fulfill_not_paid_off
    """
    cust = create_customer()
    sku = create_sku(name="Layaway Bike", category="BIKE", list_price_cents=40000, on_hand=3)
    plan = open_layaway_with_deposit(cust["id"], sku["id"], 15000)
    res = api_client.fulfill_layaway_plan(plan["id"], SA)
    validate_error(res, "ERR_LAYAWAY_NOT_PAID_OFF")


def test_build_mark_parts_reserved_before_ready():
    """PRD §3.9: "The build advances from `DRAFT` to `PARTS_RESERVED` only when
    readiness is met: `reserved_part_count` must be at least
    `required_part_count` and the frame's reservation for this build must be
    `ACTIVE`. A mark-parts-reserved attempt that fails either condition is
    rejected with `ERR_BUILD_NOT_READY`."

    Marking parts reserved on a DRAFT build with 0 reserved parts (< required 2)
    returns ERR_BUILD_NOT_READY.

    Design: Corner/state_machines/build_mark_parts_reserved_before_ready
    """
    cust = create_customer()
    frame = create_sku(name="Build Frame", category="BIKE", list_price_cents=50000, on_hand=2)
    build = create_build(cust["id"], frame["id"], required_part_count=2)
    res = api_client.mark_parts_reserved_build_job(build["id"], ADV)
    validate_error(res, "ERR_BUILD_NOT_READY")


def test_build_cancel_releases_reservations_compensation():
    """PRD §3.9: "A build may be cancelled from `DRAFT`, `PARTS_RESERVED`, or
    `ASSEMBLING` to `CANCELLED`, which releases every `ACTIVE` reservation of the
    build (`ACTIVE → RELEASED`) and lowers each `Sku`'s `reserved` as
    compensation."

    Cancelling a DRAFT build with one frame + one part reservation returns both
    Skus' reserved to 0.

    Design: Corner/state_machines/build_cancel_releases_reservations_compensation
    """
    cust = create_customer()
    frame = create_sku(name="Comp Frame", category="BIKE", list_price_cents=50000, on_hand=2)
    part = create_sku(name="Comp Part", category="PART", list_price_cents=1000, on_hand=5)
    build = create_build(cust["id"], frame["id"], required_part_count=1)
    reserve_frame(build["id"])
    reserve_part(build["id"], part["id"], 1)
    cancelled = validate_success(api_client.cancel_build_job(build["id"], ADV), 200)
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api_client.get_sku(frame["id"], MGR), 200)["reserved"] == 0
    assert validate_success(api_client.get_sku(part["id"], MGR), 200)["reserved"] == 0


def test_special_order_receive_bubbles_stock_and_reservation():
    """PRD §3.8: "Receiving goods moves the order from `CONFIRMED` to `ARRIVED`:
    it increases the `Sku`'s `on_hand` by the order's `qty`, creates one `ACTIVE`
    reservation with `holder_type` `SPECIAL_ORDER`, raises the `Sku`'s `reserved`
    by `qty`".

    Receiving a CONFIRMED special order (qty 1) on a 0-stock Sku raises on_hand
    to 1 and reserved to 1.

    Design: Corner/state_machines/special_order_receive_bubbles_stock_and_reservation
    """
    cust = create_customer()
    sku = create_sku(name="Imported Frame", category="BIKE", list_price_cents=60000, on_hand=0)
    so = create_confirmed_special_order(cust["id"], sku["id"], 1)
    arrived = validate_success(api_client.receive_special_order(so["id"], SA), 200)
    assert arrived["status"] == "ARRIVED"
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["on_hand"] == 1
    assert sku_after["reserved"] == 1


def test_tradein_reject_terminal():
    """PRD §3.11: "rejecting moves it from `APPRAISED` to `REJECTED` with no
    further effect."
    PRD §3.11: "a `status` of `APPRAISED`, `ACCEPTED`, or `REJECTED`, ... with
    `ACCEPTED` and `REJECTED` terminal."

    A REJECTED trade-in is terminal: a subsequent accept returns
    ERR_INVALID_STATE.

    Design: Corner/state_machines/tradein_reject_terminal
    """
    cust = create_customer()
    ti = create_appraised_trade_in(cust["id"], "C", 10000)
    validate_success(api_client.reject_trade_in(ti["id"], MGR), 200)
    res = api_client.accept_trade_in(ti["id"], MGR)
    validate_error(res, "ERR_INVALID_STATE")
    reread = validate_success(api_client.get_trade_in(ti["id"], MGR), 200)
    assert reread["status"] == "REJECTED"


def test_bay_booking_release_then_rebook_invalid_state():
    """PRD §3.4: "A `ServiceAdvisor` may release a booking, moving it from
    `BOOKED` to `RELEASED`".
    PRD §3.2: "A transition requested from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE`."

    Releasing an already-RELEASED booking a second time returns
    ERR_INVALID_STATE.

    Design: Corner/state_machines/bay_booking_release_then_rebook_invalid_state
    """
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = create_ticket(cust["id"], tier["id"])
    bay = create_bay(name="Bay 2")
    booking = validate_success(api_client.create_bay_booking(create_bay_booking_payload(
        bay["id"], ticket["id"], "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z"), ADV), 201)
    validate_success(api_client.release_bay_booking(booking["id"], ADV), 200)
    res = api_client.release_bay_booking(booking["id"], ADV)
    validate_error(res, "ERR_INVALID_STATE")
