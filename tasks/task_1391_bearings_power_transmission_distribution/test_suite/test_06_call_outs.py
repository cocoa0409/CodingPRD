"""Emergency after-hours call-outs: fees, one-truck capacity, and the
reservation preemption cascade on fulfillment."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    build_user_headers,
    create_product, create_branch, create_customer, create_branch_stock,
    create_confirmed_order_with_line, reserve_line, create_call_out,
    dispatch_call_out, set_clock,
    get_order, get_order_line, get_branch_stock, get_reservation,
    get_call_out, get_customer,
    make_customer_plant_headers,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_preemption_scenario():
    """Stock on_hand 5 fully reserved by customer A's order (FULLY_SOURCED);
    customer B's call-out for qty 3 dispatched after-hours on a weekday."""
    set_clock("2026-08-03T10:00:00Z")
    product = create_product(sku="BRG-22220", list_price_cents=10000)
    branch = create_branch(code="PHX-08")
    customer_a = create_customer(name="Desert Plant A")
    customer_b = create_customer(name="Desert Plant B")
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=5)
    order, line = create_confirmed_order_with_line(
        customer_a["id"], branch["id"], product["id"], qty=5)
    reservation = reserve_line(line["id"], stock["id"], 5)
    call_out = create_call_out(branch["id"], customer_b["id"], product["id"], qty=3)
    set_clock("2026-08-03T18:00:00Z")  # after close; 2026-08-03 is a Monday
    dispatch_call_out(call_out["id"], "tech-7")
    return {"product": product, "branch": branch, "customer_a": customer_a,
            "customer_b": customer_b, "stock": stock, "order": order,
            "line": line, "reservation": reservation, "call_out": call_out}


def test_callout_fulfill_fee_parts_and_total_charge(api):
    """PRD §3.6: "start with the branch's `after_hours_fee_cents`; if the
    branch-local day is a Saturday or Sunday, multiply by 1.5 with round-half-up;
    then add 250 cents per unit of `qty` for handling."
    PRD §3.6: "`parts_amount_cents` is the `qty` times the contract-lag unit
    price for this customer and product anchored at the fulfillment instant,
    `total_charge_cents` is fee plus parts, the call-out moves to `FULFILLED`,
    and the customer's `open_receivables_cents` grows by the total charge."

    Design: Difficulty/transitive_cascade/callout_fulfill_preemption_cascade
    """
    ctx = _setup_preemption_scenario()
    fulfilled = validate_success(
        api.fulfill_call_out(ctx["call_out"]["id"],
                             build_user_headers("tech-7", "OnCallTechnician")), 200)
    assert fulfilled["status"] == "FULFILLED"
    # Weekday: 20000 base + 3 * 250 handling.
    assert fulfilled["call_out_fee_cents"] == 20750, (
        f"expected 20000 + 750 = 20750, got {fulfilled['call_out_fee_cents']}")
    assert fulfilled["parts_amount_cents"] == 30000  # 3 * 10000, no contract
    assert fulfilled["total_charge_cents"] == 50750
    assert fulfilled["preempted_reservation_ids"] == [ctx["reservation"]["id"]]
    customer_b = get_customer(ctx["customer_b"]["id"])
    assert customer_b["open_receivables_cents"] == 50750


def test_callout_fulfill_preemption_cascade_reverts_line_and_order(api):
    """PRD §3.6: "when `available_qty` is short, the server seizes `ACTIVE`
    reservations for this branch and product in `created_at` descending order
    (newest first) until the demand is covered; each seized reservation moves to
    `PREEMPTED`, its order line falls back to `PENDING_SOURCING`, and that
    line's order has its fulfillment re-evaluated (a `FULLY_SOURCED` order
    reverts to `CONFIRMED`)."

    Design: Difficulty/transitive_cascade/callout_fulfill_preemption_cascade
    """
    ctx = _setup_preemption_scenario()
    validate_success(api.fulfill_call_out(
        ctx["call_out"]["id"],
        build_user_headers("tech-7", "OnCallTechnician")), 200)
    reservation = get_reservation(ctx["reservation"]["id"])
    assert reservation["status"] == "PREEMPTED"
    line = get_order_line(ctx["line"]["id"])
    assert line["sourcing_status"] == "PENDING_SOURCING"
    order = get_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "CONFIRMED"
    stock = get_branch_stock(ctx["stock"]["id"])
    assert stock["on_hand_qty"] == 2
    assert stock["reserved_qty"] == 0


def _setup_two_callouts():
    """Branch; two customers; stock 20; CO1 (A) and CO2 (B) REQUESTED,
    clock pinned after-hours on a weekday."""
    set_clock("2026-08-03T18:00:00Z")  # Monday 18:00 local, after close 17
    product = create_product(sku="BRG-6305", list_price_cents=3000)
    branch = create_branch(code="ABQ-15")
    customer_a = create_customer(name="Mesa Plant A")
    customer_b = create_customer(name="Mesa Plant B")
    create_branch_stock(branch["id"], product["id"], on_hand_qty=20)
    co1 = create_call_out(branch["id"], customer_a["id"], product["id"], qty=1)
    co2 = create_call_out(branch["id"], customer_b["id"], product["id"], qty=1)
    return {"product": product, "branch": branch, "co1": co1, "co2": co2}


def test_second_dispatch_blocked_while_one_dispatched(api):
    """PRD §3.6: "enforces one-truck capacity: the branch must have zero other
    call-outs in `DISPATCHED` status (`ERR_BRANCH_CALLOUT_CAPACITY`, 409)."

    Design: Difficulty/resource_temporal_overlap/branch_single_dispatched_callout_capacity
    """
    ctx = _setup_two_callouts()
    dispatched = dispatch_call_out(ctx["co1"]["id"], "tech-1")
    assert dispatched["status"] == "DISPATCHED"
    res = api.dispatch_call_out(ctx["co2"]["id"],
                                build_user_headers("tech-2", "OnCallTechnician"))
    validate_error(res, ApiErrorId.ERR_BRANCH_CALLOUT_CAPACITY, expected_status=409)


def test_capacity_released_by_cancel_allows_next_dispatch(api):
    """PRD §3.6: "Cancellation — by the technician or by the plant whose
    call-out it is — requires `REQUESTED` or `DISPATCHED`
    (`ERR_CALL_OUT_NOT_CANCELLABLE`, 409) and moves to `CANCELLED`."
    PRD §3.6: "the branch must have zero other call-outs in `DISPATCHED` status
    (`ERR_BRANCH_CALLOUT_CAPACITY`, 409)".

    Design: Difficulty/resource_temporal_overlap/branch_single_dispatched_callout_capacity
    """
    ctx = _setup_two_callouts()
    dispatch_call_out(ctx["co1"]["id"], "tech-1")
    validate_error(
        api.dispatch_call_out(ctx["co2"]["id"],
                              build_user_headers("tech-2", "OnCallTechnician")),
        ApiErrorId.ERR_BRANCH_CALLOUT_CAPACITY, expected_status=409)
    validate_success(api.cancel_call_out(
        ctx["co1"]["id"], build_user_headers("tech-1", "OnCallTechnician")), 200)
    dispatched2 = validate_success(api.dispatch_call_out(
        ctx["co2"]["id"], build_user_headers("tech-2", "OnCallTechnician")), 200)
    assert dispatched2["status"] == "DISPATCHED"
    # Weekday fee: 20000 base + 1 * 250 handling.
    assert dispatched2["call_out_fee_cents"] == 20250, (
        f"expected 20000 + 250 = 20250, got {dispatched2['call_out_fee_cents']}")


def test_callout_fulfill_with_zero_stock_goes_stock_unavailable(api):
    """PRD §3.6: "It requires `DISPATCHED` (`ERR_CALL_OUT_NOT_DISPATCHED`,
    409). If the stock record's `on_hand_qty` is below `qty`, the call-out
    collapses to `STOCK_UNAVAILABLE` instead."
    PRD §3.6: "The call-out is born `REQUESTED` with `call_out_fee_cents`,
    `parts_amount_cents`, and `total_charge_cents` zero, `responder_id` null,
    and `preempted_reservation_ids` empty."

    Design: Corner/state_machines/callout_fulfill_with_zero_stock_goes_stock_unavailable
    """
    set_clock("2026-08-03T18:30:00Z")  # Monday, after-hours
    product = create_product(sku="BRG-6021", list_price_cents=1000)
    branch = create_branch(code="STK-11")
    customer = create_customer(name="Stockout Plant", credit_limit_cents=1000000)
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=0)
    call_out = create_call_out(branch["id"], customer["id"], product["id"], qty=3)
    dispatch_call_out(call_out["id"], "tech-9")
    fulfilled = validate_success(api.fulfill_call_out(
        call_out["id"], build_user_headers("tech-9", "OnCallTechnician")), 200)
    assert fulfilled["status"] == "STOCK_UNAVAILABLE"
    assert get_branch_stock(stock["id"])["on_hand_qty"] == 0
    assert get_customer(customer["id"])["open_receivables_cents"] == 0
    assert get_call_out(call_out["id"])["preempted_reservation_ids"] == []
