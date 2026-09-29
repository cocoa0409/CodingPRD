"""Writes whose admissibility is owned by a state the written row cannot see."""

from test_helpers import (
    MANAGER,
    PLANNER,
    ApiErrorId,
    accept_offer,
    api_client,
    create_order_payload,
    get_success_data,
    link_offer,
    make_driver_headers,
    make_fleet_planner_headers,
    make_transport_manager_headers,
    new_backhaul_offer,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_route_posting,
    new_store,
    new_trip,
    place_bid,
    read_offer,
    read_posting,
    read_store,
    read_trip,
    review_offer,
    set_clock,
    setup_f1,
    validate_error,
)

MILE_A = {
    "plan_code": "MILE-A",
    "mileage_cents_per_mile": 78,
    "stop_cents_per_stop": 2200,
    "drop_hook_cents": 1500,
    "hourly_cents_per_minute": 42,
    "minimum_daily_cents": 24000,
    "backhaul_bonus_pct": 0.05,
}

# The one order body used before, during and after the suspension.
ORDER_BODY = {
    "cases": 300,
    "weight_lbs": 6500,
    "requested_window_start": "2026-08-06T08:00:00Z",
    "requested_window_end": "2026-08-06T14:00:00Z",
    "temperature_mode": "DRY",
    "priority": 3,
}


def _active_store_with_one_order():
    """A store in its default posture plus one order raised while it was ACTIVE."""
    set_clock()
    store = new_store(store_code="S-1007", region_code="EAST", dock_count=2,
                      cases_per_hour_unload_rate=600, dock_open_minute=240,
                      dock_close_minute=1320)
    assert store["status"] == "ACTIVE"
    order = new_order(store["id"], **ORDER_BODY)
    assert order["status"] == "UNSCHEDULED"
    return {"store": store, "order": order}


def _suspend(store_id, status):
    return get_success_data(api_client.set_store_status(store_id, {"status": status}, MANAGER))


def test_suspending_the_store_refuses_a_byte_identical_order_body(api):
    """PRD §3.3: "Raising an order against a `SUSPENDED` store is refused with
    `ERR_STORE_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_creation_depends_on_the_store_status_dimension
    """
    ctx = _active_store_with_one_order()
    suspended = _suspend(ctx["store"]["id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        api.create_order(create_order_payload(ctx["store"]["id"], **ORDER_BODY), PLANNER),
        ApiErrorId.ERR_STORE_SUSPENDED,
        409,
    )
    # An UNSCHEDULED order is not yet inside the ledger, so the refusal left no trace.
    assert read_store(ctx["store"]["id"])["open_scheduled_cases"] == 0
    assert get_success_data(api.get_order(ctx["order"]["id"], PLANNER))["status"] == "UNSCHEDULED"


def test_the_suspension_gate_is_reversible_and_never_cascades_to_existing_orders(api):
    """PRD §3.1: "Suspension is deliberately toothless towards work already committed: no
    cascade fires, trips already planned keep every stop they had, and the only consequence
    is that a *new* plan commitment touching a `SUSPENDED` store is refused with
    `ERR_STORE_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_creation_depends_on_the_store_status_dimension
    """
    ctx = _active_store_with_one_order()
    _suspend(ctx["store"]["id"], "SUSPENDED")
    validate_error(
        api.create_order(create_order_payload(ctx["store"]["id"], **ORDER_BODY), PLANNER),
        ApiErrorId.ERR_STORE_SUSPENDED,
        409,
    )
    reinstated = _suspend(ctx["store"]["id"], "ACTIVE")
    assert reinstated["status"] == "ACTIVE"

    admitted = new_order(ctx["store"]["id"], **ORDER_BODY)
    assert admitted["id"] != ctx["order"]["id"]
    assert admitted["status"] == "UNSCHEDULED"
    assert read_store(ctx["store"]["id"])["open_scheduled_cases"] == 0
    assert get_success_data(api.get_order(ctx["order"]["id"], PLANNER))["status"] == "UNSCHEDULED"


def _one_cancelled_board_and_one_open_board():
    """RT-910 is cancelled, RT-911 stays open, and D-95 is eligible for both."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-ATL", region_code="SOUTH", tractor_capacity=26,
                            driver_headcount_target=13, fixed_ownership_cents_per_day=9800,
                            overhead_cents_per_day=3100, dedicated_rate_cents_per_mile=272,
                            dedicated_rate_cents_per_case=198)
    pay_plan = new_pay_plan(**MILE_A)
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-95",
                       seniority_date="2015-02-09")
    assert driver["safety_score"] == 100
    assert driver["status"] == "ACTIVE"
    publisher = make_transport_manager_headers("user-tm-1")

    def posting(route_code):
        return new_route_posting(domicile["id"], headers=publisher, route_code=route_code,
                                 weekly_miles=2100, weekly_stops=35,
                                 start_effective_date="2026-09-01",
                                 bid_close_at="2026-08-20T00:00:00Z")

    closed = posting("RT-910")
    open_board = posting("RT-911")
    assert closed["status"] == "OPEN"
    cancelled = get_success_data(
        api_client.cancel_route_posting(closed["id"], {"reason_code": "ROUTE_RETIRED"}, publisher)
    )
    return {
        "driver": driver,
        "closed": closed,
        "cancelled": cancelled,
        "open_board": open_board,
    }


def test_the_stale_version_guard_answers_before_the_closed_board_does(api):
    """PRD §2.7: "It runs after the entity's own state check and before every cross-entity
    check, so a stale version on an otherwise doomed request still returns 412."

    Design: Difficulty/cross_entity_state_dependency/bid_admission_depends_on_the_posting_status_after_its_own_occ_gate
    """
    ctx = _one_cancelled_board_and_one_open_board()
    assert ctx["cancelled"]["status"] == "CANCELLED"
    assert ctx["cancelled"]["bid_count"] == 0
    assert ctx["cancelled"]["version"] > ctx["closed"]["version"]

    validate_error(
        api.create_route_bid(
            {
                "route_posting_id": ctx["closed"]["id"],
                # The version the posting carried before it was cancelled.
                "expected_posting_version": ctx["closed"]["version"],
            },
            make_driver_headers(ctx["driver"]["id"]),
        ),
        ApiErrorId.ERR_STALE_POSTING_VERSION,
        412,
    )
    assert read_posting(ctx["closed"]["id"])["bid_count"] == 0


def test_only_the_current_version_exposes_the_posting_state_objection(api):
    """PRD §3.9: "The posting must be `OPEN` or the bid is `ERR_POSTING_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/bid_admission_depends_on_the_posting_status_after_its_own_occ_gate
    """
    ctx = _one_cancelled_board_and_one_open_board()
    validate_error(
        api.create_route_bid(
            {
                "route_posting_id": ctx["closed"]["id"],
                "expected_posting_version": ctx["cancelled"]["version"],
            },
            make_driver_headers(ctx["driver"]["id"]),
        ),
        ApiErrorId.ERR_POSTING_NOT_OPEN,
        409,
    )
    still_closed = read_posting(ctx["closed"]["id"])
    assert still_closed["bid_count"] == 0
    assert still_closed["version"] == ctx["cancelled"]["version"]

    # The same bidder against the open board proves the refusals were the board's fault.
    admitted = place_bid(ctx["driver"]["id"], ctx["open_board"]["id"],
                        ctx["open_board"]["version"])
    assert admitted["status"] == "SUBMITTED"


# 210 incremental miles of DRY freight for 400 cases: variable cost 42450 cents.
PRAIRIE_OFFER = {
    "origin_kind": "THIRD_PARTY",
    "shipper_name": "Prairie Freight",
    "origin_region_code": "MIDWEST",
    "revenue_cents": 54000,
    "cases": 400,
    "weight_lbs": 9000,
    "deadhead_miles": 42,
    "loaded_miles": 168,
    "temperature_mode": "DRY",
    "pickup_window_start": "2026-08-09T10:00:00Z",
    "pickup_window_end": "2026-08-09T16:00:00Z",
    "offer_expires_at": "2026-08-15T00:00:00Z",
}

SOURCING_PLANNER = "user-planner-2"


def _draft_trip_with_two_offers():
    """A DRAFT trip that owns nothing, one live offer and one already rejected."""
    set_clock()
    destination = new_store(store_code="S-1008", region_code="MIDWEST", dock_count=2,
                            cases_per_hour_unload_rate=600, dock_open_minute=0,
                            dock_close_minute=1439)
    domicile = new_domicile(domicile_code="DOM-STL", region_code="MIDWEST", tractor_capacity=22,
                            driver_headcount_target=11, fixed_ownership_cents_per_day=9500,
                            overhead_cents_per_day=3000, dedicated_rate_cents_per_mile=270,
                            dedicated_rate_cents_per_case=195)
    trip = new_trip(domicile["id"], trip_code="TRIP-R",
                    planned_start_at="2026-08-09T06:00:00Z")
    planner = make_fleet_planner_headers(SOURCING_PLANNER)
    live = new_backhaul_offer(destination["id"], headers=planner, **PRAIRIE_OFFER)
    doomed = new_backhaul_offer(destination["id"], headers=planner, **PRAIRIE_OFFER)
    review_offer(doomed["id"], planner)
    rejected = get_success_data(
        api_client.reject_offer(doomed["id"], {"reason_code": "LANE_NOT_NEEDED"}, MANAGER)
    )
    return {
        "trip": trip,
        "live": live,
        "rejected": rejected,
        "planner": planner,
    }


def test_a_rejected_offer_is_permanently_outside_the_linkable_set(api):
    """PRD §3.6: "A `PROPOSED` or `UNDER_REVIEW` offer may be pre-linked and simply credits
    nothing until it is accepted, but a `REJECTED`, `WITHDRAWN` or `EXPIRED` offer can never
    be linked, and the attempt is `ERR_OFFER_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/trip_backhaul_credit_tracks_the_offer_state_without_touching_the_trip
    """
    ctx = _draft_trip_with_two_offers()
    assert ctx["trip"]["backhaul_credit_cents"] == 0
    assert ctx["trip"]["backhaul_offer_id"] is None
    assert ctx["live"]["status"] == "PROPOSED"
    assert ctx["rejected"]["status"] == "REJECTED"

    validate_error(
        api.link_backhaul_offer(
            ctx["trip"]["id"],
            {
                "backhaul_offer_id": ctx["rejected"]["id"],
                "expected_trip_version": ctx["trip"]["version"],
            },
            MANAGER,
        ),
        ApiErrorId.ERR_OFFER_NOT_ACCEPTED,
        409,
    )
    # The refusal left the trip's version alone, so the same expected version still works.
    linked = link_offer(ctx["trip"]["id"], ctx["live"]["id"], ctx["trip"]["version"])
    assert linked["backhaul_offer_id"] == ctx["live"]["id"]
    assert linked["backhaul_credit_cents"] == 0
    assert linked["version"] > ctx["trip"]["version"]


def test_pricing_a_linked_offer_still_leaves_the_trip_uncredited(api):
    """PRD §3.6: "the trip's `backhaul_credit_cents` becomes the new offer's
    `contribution_margin_cents` when that offer is already `ACCEPTED` and zero otherwise;
    and the trip's `version` advances."

    Design: Difficulty/cross_entity_state_dependency/trip_backhaul_credit_tracks_the_offer_state_without_touching_the_trip
    """
    ctx = _draft_trip_with_two_offers()
    link_offer(ctx["trip"]["id"], ctx["live"]["id"], ctx["trip"]["version"])
    priced = review_offer(ctx["live"]["id"], ctx["planner"])
    assert priced["status"] == "UNDER_REVIEW"
    assert priced["tier_margin_pct"] == 0.2139
    assert priced["contribution_margin_cents"] == 8310
    assert priced["margin_pct"] == 0.1539
    assert read_trip(ctx["trip"]["id"])["backhaul_credit_cents"] == 0


def test_accepting_the_offer_moves_the_trips_money_without_addressing_the_trip(api):
    """PRD §3.6: "the offer moves `UNDER_REVIEW → ACCEPTED`, and the linked trip's
    `backhaul_credit_cents` becomes the offer's `contribution_margin_cents` with the trip's
    `version` advancing alongside the offer's."

    Design: Difficulty/cross_entity_state_dependency/trip_backhaul_credit_tracks_the_offer_state_without_touching_the_trip
    """
    ctx = setup_f1(stage="planned")
    destination = new_store(store_code="S-1008", region_code="MIDWEST", dock_count=2,
                            cases_per_hour_unload_rate=600, dock_open_minute=0,
                            dock_close_minute=1439)
    planner = make_fleet_planner_headers(SOURCING_PLANNER)
    offer = new_backhaul_offer(destination["id"], headers=planner, **PRAIRIE_OFFER)
    link_offer(ctx["trip"]["id"], offer["id"], ctx["planned_trip"]["version"])
    review_offer(offer["id"], planner)
    assert read_trip(ctx["trip"]["id"])["backhaul_credit_cents"] == 0

    accepted = accept_offer(offer["id"], make_transport_manager_headers("user-tm-4"))
    assert accepted["status"] == "ACCEPTED"
    credited = read_trip(ctx["trip"]["id"])
    assert credited["backhaul_credit_cents"] == 8310
    assert credited["backhaul_offer_id"] == offer["id"]
    assert read_offer(offer["id"])["contribution_margin_cents"] == 8310
