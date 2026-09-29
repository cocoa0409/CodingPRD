"""Access control: peer roles, the authentication gate, driver scope and split duties."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    NON_EXISTENT_UUID,
    PAYROLL,
    PLANNER,
    SAFETY,
    ApiErrorId,
    TEST_USERS,
    add_delivery_stop,
    assign_resources,
    create_driver_payload,
    create_pay_plan_payload,
    create_store_payload,
    create_telematics_event_payload,
    create_tractor_payload,
    create_work_order_payload,
    dispatch_trip,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
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
    new_tractor,
    new_trailer,
    new_trip,
    place_bid,
    plan_trip,
    read_offer,
    read_posting,
    read_trip,
    review_offer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DRIVER_ROLE_HEADERS = TEST_USERS["driver_headers"]


# ------------------------------------------------- six peers, no hierarchy among them ----


def _roster_built_by_its_rightful_owners():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-R1")
    store = new_store(store_code="S-6100")
    plan = new_pay_plan(plan_code="MILE-C")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-R1")
    tractor = new_tractor(domicile["id"], unit_code="TR-R1")
    trailer = new_trailer(domicile["id"], trailer_code="TL-R1")
    posting = new_route_posting(domicile["id"], route_code="P-R1")
    trip = new_trip(domicile["id"], trip_code="TRIP-R1",
                    planned_start_at="2026-08-20T06:00:00Z")
    return {"domicile": domicile, "store": store, "plan": plan, "driver": driver,
            "tractor": tractor, "trailer": trailer, "posting": posting, "trip": trip}


def test_each_role_is_refused_at_least_one_operation_that_belongs_to_another(api):
    """PRD §2.1: "Once the role is recognised, it must appear in the authorised-role list of the
    endpoint being called; if it does not, the request fails with `ERR_UNAUTHORIZED` (HTTP 403),
    and again this happens before existence is tested, so a role with no business at an endpoint
    learns nothing about whether the addressed row exists." And PRD §2.1: "A
    `MaintenanceCoordinator` owns the equipment roster and the shop schedule and may never assign
    equipment to a trip — it can only make equipment available or unavailable through the shop
    lifecycle."

    Design: Corner/rbac/each_role_is_denied_the_exclusive_operations_of_every_other_role
    """
    ctx = _roster_built_by_its_rightful_owners()

    # A TransportManager may hire drivers but may not register stores, ...
    validate_error(api.create_store(create_store_payload(store_code="S-6101"), MANAGER),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    # ... a FleetPlanner may open trips but may not hire drivers, ...
    validate_error(
        api.create_driver(
            create_driver_payload(ctx["domicile"]["id"], ctx["plan"]["id"],
                                  driver_code="D-R1X"),
            PLANNER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    # ... and the operationally senior TransportManager may not mint pay structure.
    validate_error(api.create_pay_plan(create_pay_plan_payload(plan_code="MILE-X"), MANAGER),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(
        api.create_tractor(create_tractor_payload(ctx["domicile"]["id"], unit_code="TR-R1X"),
                           PLANNER),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_telematics_event(
            create_telematics_event_payload(ctx["driver"]["id"], "HARD_BRAKE", 1,
                                            "2026-07-20T14:00:00Z"),
            MAINTENANCE,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_route_bid(
            {"route_posting_id": ctx["posting"]["id"],
             "expected_posting_version": ctx["posting"]["version"]},
            MANAGER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.assign_trip_resources(
            ctx["trip"]["id"],
            {"driver_id": ctx["driver"]["id"], "tractor_id": ctx["tractor"]["id"],
             "trailer_id": ctx["trailer"]["id"]},
            make_driver_headers(ctx["driver"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_work_order(
            create_work_order_payload(tractor_id=ctx["tractor"]["id"]),
            MANAGER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    # The planner who built the schedule cannot read its cost benchmark.
    validate_error(
        api.get_cost_benchmark(
            ctx["domicile"]["id"], PLANNER,
            {"variant": "INCREMENTAL_VARIABLE", "window_start": "2026-08-01T00:00:00Z",
             "window_end": "2026-08-31T00:00:00Z"},
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )


def test_the_refused_writes_leave_no_trace_while_the_shared_acts_go_through(api):
    """PRD §2.7: "The **first** violated check short-circuits the request: no later check runs, no
    side effect is applied anywhere in the graph, and no row's `version` moves." And PRD §3.7:
    "From `DRAFT`, cancellation takes the trip `DRAFT → CANCELLED`: every stop in `PLANNED` or
    `ARRIVED` moves to `SKIPPED`; the tractor and trailer, if non-null, return to `AVAILABLE`; and
    the trip's `driver_id`, `tractor_id` and `trailer_id` are all cleared to null."

    Design: Corner/rbac/each_role_is_denied_the_exclusive_operations_of_every_other_role
    """
    ctx = _roster_built_by_its_rightful_owners()
    validate_error(api.create_store(create_store_payload(store_code="S-6101"), MANAGER),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(
        api.create_driver(
            create_driver_payload(ctx["domicile"]["id"], ctx["plan"]["id"],
                                  driver_code="D-R1X"),
            PLANNER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_route_bid(
            {"route_posting_id": ctx["posting"]["id"],
             "expected_posting_version": ctx["posting"]["version"]},
            MANAGER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.assign_trip_resources(
            ctx["trip"]["id"],
            {"driver_id": ctx["driver"]["id"], "tractor_id": ctx["tractor"]["id"],
             "trailer_id": ctx["trailer"]["id"]},
            make_driver_headers(ctx["driver"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    stores, store_meta = validate_paginated(
        api.list_stores(PLANNER, {"region_code": "MIDWEST", "limit": 50, "offset": 0})
    )
    assert store_meta["total_count"] == 1
    assert stores[0]["store_code"] == "S-6100"
    drivers, driver_meta = validate_paginated(
        api.list_drivers(SAFETY, {"domicile_id": ctx["domicile"]["id"], "limit": 50,
                                  "offset": 0})
    )
    assert driver_meta["total_count"] == 1
    assert drivers[0]["driver_code"] == "D-R1"
    bids, bid_meta = validate_paginated(
        api.list_route_bids(MAINTENANCE, {"route_posting_id": ctx["posting"]["id"],
                                          "limit": 50, "offset": 0})
    )
    assert bid_meta["total_count"] == 0
    assert bids == []

    # The reference reads are open to every role, including the entity-backed Driver.
    seen = validate_success(
        api.get_trip(ctx["trip"]["id"], make_driver_headers(ctx["driver"]["id"]))
    )
    assert seen["driver_id"] is None
    assert seen["version"] == 1

    cancelled = validate_success(api.cancel_trip(ctx["trip"]["id"], {"reason_code": "VOLUME_DROP"},
                                     MANAGER))
    assert cancelled["plan_status"] == "CANCELLED"


# ------------------------------------------------------ identity is settled before anything ----


def _one_store_to_probe():
    set_clock()
    return new_store(store_code="S-6110")


def test_a_missing_or_unknown_role_is_reported_before_existence(api):
    """PRD §2.1: "If `X-User-Role` is missing, empty, or carries a value outside the six roles
    below, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before any
    path parameter is resolved, so a request with a bad role against a completely fictional
    resource id still returns 401 rather than a 404."

    Design: Corner/rbac/an_unrecognised_role_header_is_reported_before_any_other_objection
    """
    store = _one_store_to_probe()
    validate_error(api.get_store(store["id"], headers_without_role()),
                   ApiErrorId.ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_store(store["id"], headers_with_unknown_role("FleetAdmin")),
                   ApiErrorId.ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_store(NON_EXISTENT_UUID, headers_without_role()),
                   ApiErrorId.ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_store(NON_EXISTENT_UUID, headers_with_unknown_role("FleetAdmin")),
                   ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_authentication_also_outranks_request_shape_and_covers_the_missing_user_id(api):
    """PRD §2.7: "1. **Authentication.** `X-User-Role` must be present and must be one of the six
    declared roles. Applies to every endpoint. Violation: `ERR_UNAUTHENTICATED`." And PRD §2.1:
    "Every request — reads included — must carry two headers. `X-User-ID` identifies the acting
    principal and `X-User-Role` declares the capacity in which it is acting."

    Design: Corner/rbac/an_unrecognised_role_header_is_reported_before_any_other_objection
    """
    store = _one_store_to_probe()
    # A body missing almost every required field, sent anonymously: still 401, not 422.
    validate_error(api.create_store({"store_code": "S-6111"}, headers_without_role()),
                   ApiErrorId.ERR_UNAUTHENTICATED, 401)
    # The Driver role is entity-backed, so a missing X-User-ID is an identity failure.
    validate_error(api.arrive_at_stop(NON_EXISTENT_UUID, headers_without_user_id("Driver")),
                   ApiErrorId.ERR_UNAUTHENTICATED, 401)
    # With any of the six declared roles the same read succeeds.
    for headers in (PLANNER, MANAGER, PAYROLL, SAFETY, MAINTENANCE, DRIVER_ROLE_HEADERS):
        seen = validate_success(api.get_store(store["id"], headers))
        assert seen["store_code"] == "S-6110"


# ------------------------------------------------- the driver reaches only their own work ----


def _dispatched_trip_of_driver_a_and_an_idle_driver_b():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-R3")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-6130")
    driver_a = new_driver(domicile["id"], plan["id"], driver_code="D-R3A",
                          seniority_date="2019-03-01")
    driver_b = new_driver(domicile["id"], plan["id"], driver_code="D-R3B",
                          seniority_date="2018-01-01")
    tractor = new_tractor(domicile["id"], unit_code="TR-R3")
    trailer = new_trailer(domicile["id"], trailer_code="TL-R3")
    order = new_order(store["id"])
    trip = new_trip(domicile["id"], trip_code="TRIP-R3",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                             "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], driver_a["id"], tractor["id"], trailer["id"])
    plan_trip(trip["id"])
    dispatch_trip(trip["id"])
    posting = new_route_posting(domicile["id"], route_code="P-R3")
    bid = place_bid(driver_a["id"], posting["id"], posting["version"])
    assert bid["driver_id"] == driver_a["id"]
    return {"driver_a": driver_a, "driver_b": driver_b, "trip": trip, "stop": stop,
            "posting": posting, "bid": bid}


def test_a_stranger_driver_is_refused_at_the_stop_and_at_the_close_out(api):
    """PRD §3.7: "Checking in at a stop — a `Driver` acting on their own trip or a
    `TransportManager` acting on any — takes the stop `PLANNED → ARRIVED` and may record an
    `actual_arrival_at` instant." And PRD §2.1: "Any of these mismatches is rejected with
    `ERR_DRIVER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/a_driver_is_scoped_to_their_own_trip_stops_bids_and_disputes
    """
    ctx = _dispatched_trip_of_driver_a_and_an_idle_driver_b()
    stranger = make_driver_headers(ctx["driver_b"]["id"])
    owner = make_driver_headers(ctx["driver_a"]["id"])

    validate_error(api.arrive_at_stop(ctx["stop"]["id"], stranger),
                   ApiErrorId.ERR_DRIVER_SCOPE_VIOLATION, 403)
    arrived = validate_success(api.arrive_at_stop(ctx["stop"]["id"], owner))
    assert arrived["status"] == "ARRIVED"
    done = validate_success(api.complete_stop(ctx["stop"]["id"], {"cases_handled": 600}, owner))
    assert done["status"] == "COMPLETED"

    # The trip is IN_PROGRESS with every stop terminal, so only ownership can be the objection.
    validate_error(
        api.complete_trip(ctx["trip"]["id"],
                          {"actual_drive_minutes": 120, "actual_duty_minutes": 195}, stranger),
        ApiErrorId.ERR_DRIVER_SCOPE_VIOLATION,
        403,
    )
    closed = validate_success(
        api.complete_trip(ctx["trip"]["id"],
                          {"actual_drive_minutes": 120, "actual_duty_minutes": 195}, owner)
    )
    assert closed["plan_status"] == "COMPLETED"
    assert closed["settlement_status"] == "ACCRUED"


def test_a_stranger_driver_disputes_no_pay_and_withdraws_no_bid(api):
    """PRD §3.8: "Any other payroll status is `ERR_INVALID_STATE_TRANSITION`, and a `Driver`
    disputing a trip that is not theirs is `ERR_DRIVER_SCOPE_VIOLATION`." And PRD §3.9: "A driver
    may withdraw their own bid — anyone else's is `ERR_DRIVER_SCOPE_VIOLATION` — which moves it
    `SUBMITTED → WITHDRAWN`, lowers the posting's `bid_count` by one, and advances the posting's
    `version`."

    Design: Corner/rbac/a_driver_is_scoped_to_their_own_trip_stops_bids_and_disputes
    """
    ctx = _dispatched_trip_of_driver_a_and_an_idle_driver_b()
    stranger = make_driver_headers(ctx["driver_b"]["id"])
    owner = make_driver_headers(ctx["driver_a"]["id"])
    validate_success(api.arrive_at_stop(ctx["stop"]["id"], owner))
    validate_success(api.complete_stop(ctx["stop"]["id"], {"cases_handled": 600}, owner))
    validate_success(
        api.complete_trip(ctx["trip"]["id"],
                          {"actual_drive_minutes": 120, "actual_duty_minutes": 195}, owner)
    )

    validate_error(
        api.dispute_settlement(ctx["trip"]["id"], {"dispute_note": "Miles look short"},
                               stranger),
        ApiErrorId.ERR_DRIVER_SCOPE_VIOLATION,
        403,
    )
    disputed = validate_success(
        api.dispute_settlement(ctx["trip"]["id"], {"dispute_note": "Miles look short"},
                               owner)
    )
    assert disputed["settlement_status"] == "DISPUTED"

    validate_error(api.withdraw_route_bid(ctx["bid"]["id"], stranger),
                   ApiErrorId.ERR_DRIVER_SCOPE_VIOLATION, 403)
    assert validate_success(api.get_route_bid(ctx["bid"]["id"], MANAGER))["status"] == "SUBMITTED"
    pulled = validate_success(api.withdraw_route_bid(ctx["bid"]["id"], owner))
    assert pulled["status"] == "WITHDRAWN"
    assert read_posting(ctx["posting"]["id"])["bid_count"] == 0


# -------------------------------------------------- two decisions need two operators ----


def _thin_offer_sourced_by_operator_u1():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-R4")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-6140")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-R4")
    tractor = new_tractor(domicile["id"], unit_code="TR-R4")
    trailer = new_trailer(domicile["id"], trailer_code="TL-R4")
    order = new_order(store["id"])
    trip = new_trip(domicile["id"], trip_code="TRIP-R4",
                    planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                      "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    committed = plan_trip(trip["id"])
    offer = new_backhaul_offer(store["id"], headers=make_fleet_planner_headers("U1"),
                              revenue_cents=45000, offer_expires_at="2026-08-18T00:00:00Z",
                              pickup_window_start="2026-08-20T14:00:00Z",
                              pickup_window_end="2026-08-20T20:00:00Z")
    assert offer["created_by_user_id"] == "U1"
    link_offer(trip["id"], offer["id"], committed["version"])
    reviewed = review_offer(offer["id"], make_fleet_planner_headers("U1"))
    assert reviewed["status"] == "UNDER_REVIEW"
    return trip, reviewed


def test_the_sourcing_operator_may_not_waive_the_floor_on_their_own_thin_load(api):
    """PRD §3.6: "Step ten sets `contribution_margin_cents` to `gross_margin_cents` less
    `commission_cents`." And PRD §3.6: "The offer's `margin_pct` must be at or above the 8 percent
    contribution-margin floor; below the floor the acceptance is refused with
    `ERR_MARGIN_BELOW_FLOOR` unless the request carries `margin_exception_approved` as true." And
    PRD §3.6: "And when a margin exception *is* claimed, the acting `X-User-ID` must differ from
    the offer's `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` — one operator may not
    both source a thin load and waive the floor on it."

    Design: Corner/rbac/an_operator_may_not_approve_their_own_exception_or_award_their_own_posting
    """
    _trip, reviewed = _thin_offer_sourced_by_operator_u1()
    assert reviewed["variable_cost_cents"] == 41500
    assert reviewed["gross_margin_cents"] == 3500
    assert reviewed["tier_margin_pct"] == 0.0778
    assert reviewed["commission_cents"] == 1350
    assert reviewed["contribution_margin_cents"] == 2150
    assert reviewed["margin_pct"] == 0.0478

    # Without the flag the segregation rule is never reached: the floor speaks first.
    validate_error(api.accept_offer(reviewed["id"], make_transport_manager_headers("U1")),
                   ApiErrorId.ERR_MARGIN_BELOW_FLOOR, 422)
    # With the flag, the same operator that priced the load is refused the waiver.
    validate_error(
        api.accept_offer(reviewed["id"], make_transport_manager_headers("U1"),
                         {"margin_exception_approved": True}),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    untouched = read_offer(reviewed["id"])
    assert untouched["status"] == "UNDER_REVIEW"
    assert untouched["margin_exception_approved"] is False


def test_a_second_operator_on_the_same_role_may_waive_it(api):
    """PRD §2.11: "Accepting a backhaul offer *with a margin exception* requires that `X-User-ID`
    differ from the offer's recorded `created_by_user_id`; awarding a route posting requires that
    `X-User-ID` differ from the posting's recorded `created_by_user_id`." And PRD §3.6: "On
    success the offer's `margin_exception_approved` is set to the supplied flag, the offer moves
    `UNDER_REVIEW → ACCEPTED`, and the linked trip's `backhaul_credit_cents` becomes the offer's
    `contribution_margin_cents` with the trip's `version` advancing alongside the offer's."

    Design: Corner/rbac/an_operator_may_not_approve_their_own_exception_or_award_their_own_posting
    """
    trip, reviewed = _thin_offer_sourced_by_operator_u1()
    validate_error(
        api.accept_offer(reviewed["id"], make_transport_manager_headers("U1"),
                         {"margin_exception_approved": True}),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    accepted = validate_success(
        api.accept_offer(reviewed["id"], make_transport_manager_headers("U2"),
                         {"margin_exception_approved": True})
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["margin_exception_approved"] is True
    assert read_trip(trip["id"])["backhaul_credit_cents"] == 2150


def _posting_published_by_operator_u1():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-R4")
    plan = new_pay_plan(plan_code="MILE-C")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-R4",
                        seniority_date="2019-03-01")
    posting = new_route_posting(domicile["id"], headers=make_transport_manager_headers("U1"),
                                route_code="P-R4", bid_close_at="2026-08-15T00:00:00Z")
    assert posting["created_by_user_id"] == "U1"
    bid = place_bid(driver["id"], posting["id"], posting["version"])
    set_clock("2026-08-16T00:00:00Z", MANAGER)
    return driver, posting, bid


def test_the_publishing_manager_may_not_award_their_own_route(api):
    """PRD §3.9: "And the acting `X-User-ID` must differ from the posting's `created_by_user_id`;
    the manager who published a route may not award it, which is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/an_operator_may_not_approve_their_own_exception_or_award_their_own_posting
    """
    _driver, posting, bid = _posting_published_by_operator_u1()
    validate_error(
        api.award_route_posting(posting["id"], make_transport_manager_headers("U1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert validate_success(api.get_route_bid(bid["id"], MANAGER))["status"] == "SUBMITTED"
    still_open = read_posting(posting["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["awarded_driver_id"] is None


def test_a_third_operator_awards_the_same_route_to_the_waiting_bidder(api):
    """PRD §2.11: "Two decisions in this domain may not be made by a single person, and because
    operator identifiers are role-agnostic — the same operator id may legitimately arrive under
    different role headers — the check compares identifiers, not roles."

    Design: Corner/rbac/an_operator_may_not_approve_their_own_exception_or_award_their_own_posting
    """
    driver, posting, bid = _posting_published_by_operator_u1()
    validate_error(
        api.award_route_posting(posting["id"], make_transport_manager_headers("U1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    awarded = validate_success(
        api.award_route_posting(posting["id"], make_transport_manager_headers("U3"))
    )
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_driver_id"] == driver["id"]
    assert validate_success(api.get_route_bid(bid["id"], MANAGER))["status"] == "AWARDED"
