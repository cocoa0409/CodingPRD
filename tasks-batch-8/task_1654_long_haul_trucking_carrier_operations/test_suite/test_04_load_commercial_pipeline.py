"""The load commercial lifecycle: tender defaults, screening (fuel surcharge
and provisional margin), acceptance fiscal gates, rejection, and the tiered
cancellation schedule (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_customer,
    create_fuel_rate,
    create_lane,
    dispatch_trip,
    get_load,
    get_tractor,
    get_trip,
    make_load_planner_headers,
    post_check_call,
    set_clock,
    setup_accepted_load,
    setup_dispatched_trip,
    setup_planned_trip,
    setup_refdata,
    tender_load,
    validate_error,
    validate_success,
)

LOAD_PLANNER = make_load_planner_headers()


def test_load_tender_opens_tendered_with_null_computed(api):
    """PRD §3.2: "The tender opens in `TENDERED` status with
    `reassignment_count` at 0; its `fuel_surcharge_cents`,
    `projected_margin_cents`, `projected_rpm_cents`, `final_margin_cents`, and
    `cancellation_fee_cents` do not exist yet, and `total_accessorial_cents`
    stands at 0."

    Design: Corner/state_machines/load_initial_state_tendered
    """
    set_clock("2026-08-01T06:00:00Z")
    customer = create_customer()
    lane = create_lane()
    load = tender_load(customer["id"], lane["id"])
    assert load["status"] == "TENDERED"
    assert load["reassignment_count"] == 0
    assert load["total_accessorial_cents"] == 0
    assert load.get("final_margin_cents") is None
    assert load.get("fuel_surcharge_cents") is None


def test_rescreen_screened_load_rejected(api):
    """PRD §3.2: "Screening is the carrier's first profitability gate, run by a
    `LoadPlanner` against a `TENDERED` load — screening from any other status
    is rejected with `ERR_LOAD_NOT_TENDERED`."

    Design: Corner/state_machines/load_rescreen_after_screen_rejected
    """
    ctx = setup_refdata()
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    validate_success(api_client.screen_load(load["id"], LOAD_PLANNER))
    resp = api_client.screen_load(load["id"], LOAD_PLANNER)
    validate_error(resp, ApiErrorId.ERR_LOAD_NOT_TENDERED)


def test_screen_without_national_rate_unavailable(api):
    """PRD §3.2: "Screening needs a national fuel benchmark: the single
    StateFuelRate row whose `state_code` is `US-NATIONAL` and whose effective
    window contains the logical now; if no such row is current, the screen
    fails with `ERR_FUEL_RATE_UNAVAILABLE`."

    Design: Corner/errors/screen_without_national_rate_unavailable
    """
    ctx = setup_refdata(with_national_rate=False)
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    resp = api_client.screen_load(load["id"], LOAD_PLANNER)
    validate_error(resp, ApiErrorId.ERR_FUEL_RATE_UNAVAILABLE)


def test_fsc_floored_at_zero_below_baseline(api):
    """PRD §3.2: "The fuel surcharge rests on a baseline of 300 cents per
    gallon: the excess is the amount by which the national row's
    `avg_pump_price_cents` exceeds that baseline, floored at zero, so a
    national average at or below 300 cents yields no surcharge at all."
    PRD §3.2: "`projected_margin_cents` is revenue minus cost, and
    `projected_rpm_cents` is revenue divided by estimated total miles, rounded
    half up to whole cents."

    Design: Corner/calculations/fsc_floored_zero_below_baseline
    """
    ctx = setup_refdata(pump_price_cents=280)
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    screened = validate_success(api_client.screen_load(load["id"], LOAD_PLANNER))
    assert screened["fuel_surcharge_cents"] == 0, "280 < 300 baseline floors at 0"
    # revenue 250000; cost 1000 * (145 + 62) = 207000
    assert screened["projected_margin_cents"] == 43000
    assert screened["projected_rpm_cents"] == 250


def test_accept_rejected_when_margin_below_floor(api):
    """PRD §3.2: "second, the recomputed `projected_margin_cents` must be at
    least zero and the recomputed `projected_rpm_cents` must reach the lane's
    `rpm_floor_cents`, failing which the acceptance is rejected with
    `ERR_MARGIN_BELOW_FLOOR` (HTTP 402)."

    Design: Corner/validations/accept_margin_floor_fiscal
    """
    ctx = setup_refdata(lane_overrides={"rpm_floor_cents": 500})
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    screened = validate_success(api_client.screen_load(load["id"], LOAD_PLANNER))
    assert screened["status"] == "SCREENED"
    assert screened["projected_rpm_cents"] == 271
    resp = api_client.accept_load(load["id"], LOAD_PLANNER)
    validate_error(resp, ApiErrorId.ERR_MARGIN_BELOW_FLOOR)


def test_accept_requires_screened_and_reject_requires_early_state(api):
    """PRD §3.2: "Only a `SCREENED` load may be accepted (otherwise
    `ERR_LOAD_NOT_SCREENED`)".
    PRD §3.2: "A `LoadPlanner` may reject a load while it is `TENDERED` or
    `SCREENED` — from any later state, rejection draws
    `ERR_LOAD_NOT_REJECTABLE` — moving it to the terminal `REJECTED` state
    with no financial consequence."

    Design: Corner/errors/load_accept_and_reject_state_errors
    """
    ctx = setup_accepted_load()
    accepted = ctx["load"]
    tendered = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])

    validate_error(api_client.accept_load(tendered["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_LOAD_NOT_SCREENED)
    validate_error(api_client.reject_load(accepted["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_LOAD_NOT_REJECTABLE)


def test_cancel_tendered_and_accepted_fee_tiers(api):
    """PRD §3.2: "Cancelling a `TENDERED` or `SCREENED` load costs nothing: the
    fee is 0. Cancelling an `ACCEPTED` load costs a flat 15000 cents."

    Design: Corner/state_machines/load_cancel_accepted_flat_fee_tier
    """
    ctx = setup_accepted_load()
    accepted = ctx["load"]
    tendered = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])

    cancelled = validate_success(api_client.cancel_load(accepted["id"], LOAD_PLANNER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 15000
    cancelled2 = validate_success(api_client.cancel_load(tendered["id"], LOAD_PLANNER))
    assert cancelled2["cancellation_fee_cents"] == 0


def test_cancel_assigned_applies_tonu_greater_of_tier(api):
    """PRD §3.2: "Cancelling an `ASSIGNED` or `DISPATCHED` load is a
    truck-order-not-used event, and the fee is the greater of 25000 cents and
    ten percent of the `rate_cents` linehaul, rounded half up to whole cents."
    PRD §3.2: "When a load in `ASSIGNED` or `DISPATCHED` is cancelled, its
    non-terminal trip — one in `PLANNED`, `DISPATCHED`, or `AT_PICKUP` — is
    cancelled with it, the trip's `cancel_reason` recorded as `CUSTOMER`, and
    the trip's tractor is released from `ASSIGNED` back to `AVAILABLE`."

    Design: Corner/state_machines/load_cancel_tonu_greater_of_tier
    """
    ctx = setup_planned_trip(rate_cents=300000, cdl_number="CDL-C14",
                             unit_number="T-C14")
    cancelled = validate_success(
        api_client.cancel_load(ctx["load"]["id"], LOAD_PLANNER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 30000, (
        "max(25000, round_half_up(300000 * 0.10)) = 30000")

    trip = get_trip(ctx["trip"]["id"])
    assert trip["status"] == "CANCELLED"
    assert trip["cancel_reason"] == "CUSTOMER"
    assert get_tractor(ctx["tractor"]["id"])["status"] == "AVAILABLE"


def test_cancel_in_transit_rejected(api):
    """PRD §3.2: "Cancellation from `IN_TRANSIT` or any later state is not
    permitted at all and is rejected with `ERR_LOAD_NOT_CANCELLABLE`."

    Design: Corner/state_machines/load_cancel_in_transit_rejected
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-C12", unit_number="T-C12")
    set_clock("2026-08-02T10:00:00Z")
    post_check_call(ctx["trip"]["id"], ctx["driver"]["id"], kind="ARRIVED_PICKUP",
                    occurred_at="2026-08-02T07:50:00Z", state_code="TX",
                    odometer_miles=100120)
    post_check_call(ctx["trip"]["id"], ctx["driver"]["id"], kind="DEPARTED_PICKUP",
                    occurred_at="2026-08-02T10:00:00Z", state_code="TX",
                    odometer_miles=100120)
    assert get_load(ctx["load"]["id"])["status"] == "IN_TRANSIT"
    resp = api_client.cancel_load(ctx["load"]["id"], LOAD_PLANNER)
    validate_error(resp, ApiErrorId.ERR_LOAD_NOT_CANCELLABLE)


def test_accept_visibility_immediate(api):
    """PRD §2.7: "Derived fields are reconciled immediately at the event that
    changes them, never lazily at read time."
    PRD §3.2: "Only a `SCREENED` load may be accepted (otherwise
    `ERR_LOAD_NOT_SCREENED`), and acceptance recomputes the fuel surcharge and
    the provisional margin and rate-per-mile with the currently effective
    `US-NATIONAL` row, overwriting the earlier snapshot."

    Design: Corner/consistency_model/immediate_read_after_transition
    """
    ctx = setup_refdata()
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    validate_success(api_client.screen_load(load["id"], LOAD_PLANNER))
    accepted = validate_success(api_client.accept_load(load["id"], LOAD_PLANNER))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["fuel_surcharge_cents"] == 20769
    reread = get_load(load["id"])
    assert reread["status"] == "ACCEPTED"
    assert reread["projected_margin_cents"] == 63769


def test_customer_credit_hold_cycle_guards(api):
    """PRD §3.1: "A `LoadPlanner` may place an `ACTIVE` customer on
    `CREDIT_HOLD` — doing so from any other status, or releasing a customer
    that is not on hold, is rejected with `ERR_CUSTOMER_INVALID_STATE` — and
    may later release the hold back to `ACTIVE`."

    Design: Corner/state_machines/customer_credit_hold_cycle_guards
    """
    customer = create_customer()
    held = validate_success(api_client.credit_hold_customer(customer["id"], LOAD_PLANNER))
    assert held["status"] == "CREDIT_HOLD"
    validate_error(api_client.credit_hold_customer(customer["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_CUSTOMER_INVALID_STATE)
    released = validate_success(
        api_client.release_credit_hold_customer(customer["id"], LOAD_PLANNER))
    assert released["status"] == "ACTIVE"
    validate_error(
        api_client.release_credit_hold_customer(customer["id"], LOAD_PLANNER),
        ApiErrorId.ERR_CUSTOMER_INVALID_STATE)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / load_accept_gated_by_customer_state
# ---------------------------------------------------------------------------

def test_accept_blocked_by_customer_credit_hold(api):
    """PRD §3.2: "Two fiscal gates then apply in a fixed order: first, the
    tendering customer's `status` must be `ACTIVE`, since acceptance against a
    customer on `CREDIT_HOLD` is rejected with `ERR_CUSTOMER_CREDIT_HOLD`
    (HTTP 402)".

    Design: Difficulty/cross_entity_state_dependency/load_accept_gated_by_customer_state
    """
    ctx = setup_refdata()
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    validate_success(api_client.screen_load(load["id"], LOAD_PLANNER))
    validate_success(api_client.credit_hold_customer(ctx["customer"]["id"],
                                                     LOAD_PLANNER))
    resp = api_client.accept_load(load["id"], LOAD_PLANNER)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)


def test_accept_succeeds_after_credit_hold_release(api):
    """PRD §3.2: "Two fiscal gates then apply in a fixed order: first, the
    tendering customer's `status` must be `ACTIVE`, since acceptance against a
    customer on `CREDIT_HOLD` is rejected with `ERR_CUSTOMER_CREDIT_HOLD`
    (HTTP 402)".
    PRD §3.1: "A `LoadPlanner` may place an `ACTIVE` customer on `CREDIT_HOLD`
    ... and may later release the hold back to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/load_accept_gated_by_customer_state
    """
    ctx = setup_refdata()
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    validate_success(api_client.screen_load(load["id"], LOAD_PLANNER))
    validate_success(api_client.credit_hold_customer(ctx["customer"]["id"],
                                                     LOAD_PLANNER))
    validate_success(api_client.release_credit_hold_customer(ctx["customer"]["id"],
                                                             LOAD_PLANNER))
    accepted = validate_success(api_client.accept_load(load["id"], LOAD_PLANNER))
    assert accepted["status"] == "ACCEPTED"
