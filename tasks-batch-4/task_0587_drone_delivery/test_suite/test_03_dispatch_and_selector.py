"""Dispatch: the airframe selector, the pad hold, the provisional energy figure and the
stale-read guard on the order."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    abort_flight,
    add_airframe,
    assert_flight,
    assert_instant,
    assert_km,
    assert_money,
    assert_pct,
    create_customer,
    create_drone,
    create_nest,
    create_order,
    create_ready_battery,
    create_service_area,
    create_weather_observation,
    dispatch_order_payload,
    install_battery,
    read_customer,
    read_drone,
    read_flight,
    read_nest,
    read_order,
    set_clock,
    setup_planned_flight,
    setup_quoted_order,
    setup_world,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["dispatch_operator_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


# ================================================================= what dispatch writes
def test_dispatch_creates_a_planned_unfiled_flight(api):
    """PRD §3.4: "A flight is created with `ops_state` `PLANNED` and `clearance_state`
    `UNFILED`; its `order_id` names the order, its `drone_id` names the selector's winner, its
    `launch_nest_id` and `recovery_nest_id` both name the requested nest, and its `battery_id`
    names the pack currently installed on the winning airframe."
    PRD §3.4: "`planned_route_km`, `wind_kph_at_dispatch`, `required_energy_pct`,
    `eta_recovery_at`, `pad_hold_start` and `pad_hold_end` are all computed and stored as
    described above; `actual_route_km`, `actual_energy_pct`, `filed_by_user_id`,
    `released_by_user_id` and `abort_reason` all start null."

    Design: Corner/state_machines/new_flight_starts_planned_and_unfiled
    """
    w = setup_quoted_order()

    resp = api.dispatch_order(
        w["order"]["id"],
        dispatch_order_payload(w["nest"]["id"], w["order"]["version"]),
        OPERATOR,
    )
    flight = validate_success(resp, 201)

    assert_flight(flight)
    assert flight["ops_state"] == "PLANNED"
    assert flight["clearance_state"] == "UNFILED"
    assert flight["actual_energy_pct"] is None
    assert flight["actual_route_km"] is None
    assert flight["abort_reason"] is None
    assert flight["filed_by_user_id"] is None
    assert flight["released_by_user_id"] is None
    assert flight["order_id"] == w["order"]["id"]
    assert flight["drone_id"] == w["drone"]["id"]
    assert flight["battery_id"] == w["battery"]["id"]
    assert flight["launch_nest_id"] == w["nest"]["id"]
    assert flight["recovery_nest_id"] == w["nest"]["id"]


def test_cancelling_an_assigned_order_is_rejected(api):
    """PRD §3.3: "A `QUOTED` order may be cancelled by its owning `Customer` or by a
    `DispatchOperator`, moving `QUOTED → CANCELLED` and advancing the order's `version` by one.
    Cancellation is only available from `QUOTED`. An order that is `ASSIGNED` or `IN_TRANSIT`
    has a live sortie attached to it and must be unwound at the flight level first; an order
    that is already `DELIVERED` or `CANCELLED` is terminal. In all four of those cases the
    cancellation attempt is rejected with `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409)."
    PRD §3.4: "The customer's `held_total` increases by the order's `order_total`."

    Design: Corner/state_machines/cancel_order_after_dispatch_rejected
    """
    w = setup_planned_flight()

    resp = api.cancel_order(w["order"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)

    order = read_order(w["order"]["id"])
    assert order["status"] == "ASSIGNED"
    assert_money(read_customer(w["customer"]["id"])["held_total"], 8.96, "held_total")
    assert read_flight(w["flight"]["id"])["ops_state"] == "PLANNED"


def test_flights_are_reachable_by_drone_battery_and_recovery_nest_filters(api):
    """PRD §3.10: "Flights are listable by `order_id`, `drone_id`, `launch_nest_id`,
    `recovery_nest_id`, `battery_id` and `ops_state`, and a single flight read exposes both
    state dimensions and both energy figures side by side."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the number of items
    matching the filters before pagination is applied and `has_more` indicates whether items
    remain beyond the current page."

    Design: Corner/endpoints/flights_filterable_by_drone_id_and_battery_id
    """
    w = setup_planned_flight()

    for params in (
        {"drone_id": w["drone"]["id"]},
        {"battery_id": w["battery"]["id"]},
        {"recovery_nest_id": w["nest"]["id"]},
    ):
        resp = api.list_flights(TECH, params=params)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert meta["total_count"] == 1, f"filter {params} must return exactly the one flight"
        assert meta["has_more"] is False
        assert len(data) == 1
        assert data[0]["id"] == w["flight"]["id"]


# ========================================================================= the selector
def test_selector_ranks_by_charge_then_hours_since_service(api):
    """PRD §3.4: "Among the surviving candidates, the winner is the one with the greatest
    battery `charge_pct`. Ties on charge are broken by the smallest `hours_since_service`. Ties
    on both are broken by the earliest `created_at` — the longest-registered airframe wins. No
    random or arbitrary key participates in the ranking. If no drone survives the filter,
    dispatch is rejected with `ERR_NO_ELIGIBLE_DRONE` (HTTP 409); there is no queueing and no
    deferral."
    PRD §3.4: "The winning drone moves `IDLE → RESERVED` and its `version` advances by one."

    Design: Corner/calculations/selector_ranks_by_charge_then_hours_then_created_at
    """
    w = setup_world(pad_count=3, tail_number="N101", hours_since_service=20)
    second = add_airframe(w, "N102", "B-2", hours_since_service=5)
    third = add_airframe(w, "N103", "B-3", hours_since_service=0, battery_charge_pct=90)

    w = setup_quoted_order(world=w)
    flight = validate_success(
        api.dispatch_order(
            w["order"]["id"],
            dispatch_order_payload(w["nest"]["id"], w["order"]["version"]),
            OPERATOR,
        ),
        201,
    )

    # 100% beats 90%; among the two 100% packs the 5 h airframe beats the 20 h one.
    assert flight["drone_id"] == second["drone"]["id"], (
        "the selector must pick the 100%-charge / 5 h airframe"
    )
    assert read_drone(second["drone"]["id"])["status"] == "RESERVED"
    assert read_drone(w["drone"]["id"])["status"] == "IDLE"
    assert read_drone(third["drone"]["id"])["status"] == "IDLE"


def test_dispatch_with_no_installed_pack_finds_no_eligible_drone(api):
    """PRD §3.4: "A drone is a candidate only if every one of the following holds: its
    `home_nest_id` is the nest named in the request (drones based at *other* nests of the same
    service area are not candidates); its `status` is `IDLE`; its `max_payload_g` is at least
    the order's `payload_weight_g`; its `installed_battery_id` is not null; that installed
    pack's `state` is `READY`; that pack's `charge_pct` is at least the energy the sortie would
    require of *that particular airframe*; its `blocking_risk_score` is strictly below 70.0; and
    it has no `SCHEDULED` maintenance log whose half-open window from `scheduled_start` up to
    but not including `scheduled_end` overlaps the half-open flight window running from the
    current logical clock up to but not including that airframe's own `eta_recovery_at`."

    Design: Difficulty/boundary_precision_check/dispatch_empty_candidate_pool_zero_drones
    """
    w = setup_quoted_order(world=setup_world(install=False))

    resp = api.dispatch_order(
        w["order"]["id"],
        dispatch_order_payload(w["nest"]["id"], w["order"]["version"]),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_DRONE.value)


def test_empty_candidate_pool_leaves_order_drone_and_pad_ledger_untouched(api):
    """PRD §3.4: "If no drone survives the filter, dispatch is rejected with
    `ERR_NO_ELIGIBLE_DRONE` (HTTP 409); there is no queueing and no deferral."
    PRD §2.10: "A nest's `reserved_pads` is the count of physical pad slots currently held, and
    after every request it must equal the number of flights whose `recovery_nest_id` is that
    nest and whose `ops_state` is one of `PLANNED`, `LAUNCHED`, `DROPPING` or `RETURNING`."

    Design: Difficulty/boundary_precision_check/dispatch_empty_candidate_pool_zero_drones
    """
    w = setup_quoted_order(world=setup_world(install=False))

    resp = api.dispatch_order(
        w["order"]["id"],
        dispatch_order_payload(w["nest"]["id"], w["order"]["version"]),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_DRONE.value)

    order = read_order(w["order"]["id"])
    assert order["status"] == "QUOTED"
    assert order["version"] == 1, "a rejected dispatch mutates nothing"

    drone = read_drone(w["drone"]["id"])
    assert drone["status"] == "IDLE"
    assert drone["installed_battery_id"] is None

    assert read_nest(w["nest"]["id"])["reserved_pads"] == 0

    _, meta = validate_paginated(
        api.list_flights(OPERATOR, params={"order_id": w["order"]["id"]})
    )
    assert meta["total_count"] == 0, "no Flight is created by a rejected dispatch"


def test_dispatch_to_a_nest_of_another_service_area_is_rejected(api):
    """PRD §3.4: "The named nest must be `OPEN` and must belong to the order's service area — a
    `CLOSED` nest, or a nest sitting in a different area, is `ERR_NEST_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/dispatch_to_nest_outside_the_orders_service_area_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    bay = create_service_area(name="Bay")
    coast = create_service_area(name="Coast")
    coast_nest = create_nest(coast["id"], name="C1")
    battery = create_ready_battery(coast_nest["id"])
    drone = create_drone(coast_nest["id"], tail_number="N201")
    drone = install_battery(drone["id"], battery["id"])
    customer = create_customer()
    order = create_order(customer["id"], bay["id"])

    resp = api.dispatch_order(
        order["id"], dispatch_order_payload(coast_nest["id"], order["version"]), OPERATOR
    )
    validate_error(resp, ApiErrorId.ERR_NEST_UNAVAILABLE.value)

    reread = read_order(order["id"])
    assert reread["status"] == "QUOTED"
    assert reread["version"] == 1
    assert read_drone(drone["id"])["status"] == "IDLE"


# ================================================= the provisional energy requirement
def test_required_energy_applies_the_clamped_wind_penalty(api):
    """PRD §3.4: "Take a *wind factor*: one, plus 0.02 for every kilometre per hour by which
    the frozen wind exceeds 10.0 kph, where a wind at or below 10.0 kph contributes nothing at
    all (the excess is clamped at zero, never negative). The *core* consumption for a given
    route length is that route length in kilometres, multiplied by 1.6 percent of charge per
    kilometre, multiplied by the payload factor, multiplied by the wind factor."
    PRD §3.4: "The provisional figure written to the flight as `required_energy_pct` at
    dispatch is the core consumption of the `planned_route_km`, plus 3.0 percent of hover
    allowance, plus a 15.0 percent planning reserve — the whole sum rounded half up to one
    decimal place, with no intermediate rounding."
    PRD §3.4: "The estimated recovery time, `eta_recovery_at`, is the logical clock at
    dispatch, advanced by the cruise leg — the `planned_route_km` divided by the airframe's
    `cruise_speed_kmh`, converted from hours to minutes by multiplying by sixty, and then
    **rounded up to a whole number of minutes** — and then advanced by a further 3 minutes of
    hover allowance."

    Design: Difficulty/combinatorial_formula/energy_formula_three_input_nonlinear_wind_clamp
    """
    w = setup_world()
    create_weather_observation(
        w["sa"]["id"],
        observed_at="2026-06-01T08:30:00Z",
        wind_kph=30,
        gust_kph=40,
        visibility_km=5,
        precip="NONE",
    )
    w = setup_quoted_order(world=w, payload_weight_g=2000, priority="STANDARD")

    flight = validate_success(
        api.dispatch_order(
            w["order"]["id"],
            dispatch_order_payload(w["nest"]["id"], w["order"]["version"]),
            OPERATOR,
        ),
        201,
    )

    assert_pct(flight["wind_kph_at_dispatch"], 30.0, "wind_kph_at_dispatch")
    assert_km(flight["planned_route_km"], 11.100, "planned_route_km")
    # 11.100 * 1.6 * (1 + 2.0*0.08) * (1 + (30-10)*0.02) + 3.0 + 15.0 = 46.84224 -> 46.8
    assert_pct(flight["required_energy_pct"], 46.8, "required_energy_pct")
    # 11.100 / 60 h = 11.1 min -> ceil 12 min, + 3 min hover = 09:15.
    assert_instant(flight["eta_recovery_at"], "2026-06-01T09:15:00Z", "eta_recovery_at")


def test_wind_at_the_free_threshold_contributes_nothing_to_required_energy(api):
    """PRD §3.4: "Take a *wind factor*: one, plus 0.02 for every kilometre per hour by which
    the frozen wind exceeds 10.0 kph, where a wind at or below 10.0 kph contributes nothing at
    all (the excess is clamped at zero, never negative). The *core* consumption for a given
    route length is that route length in kilometres, multiplied by 1.6 percent of charge per
    kilometre, multiplied by the payload factor, multiplied by the wind factor."
    PRD §3.4: "Start from a *payload factor*: one, plus the order's payload mass in kilograms —
    `payload_weight_g` divided by one thousand — multiplied by 0.08."

    Design: Difficulty/combinatorial_formula/energy_formula_three_input_nonlinear_wind_clamp
    """
    w = setup_world()
    create_weather_observation(
        w["sa"]["id"],
        observed_at="2026-06-01T08:30:00Z",
        wind_kph=10,
        gust_kph=12,
        visibility_km=8,
        precip="NONE",
    )
    w = setup_quoted_order(world=w, payload_weight_g=2000, priority="STANDARD")

    flight = validate_success(
        api.dispatch_order(
            w["order"]["id"],
            dispatch_order_payload(w["nest"]["id"], w["order"]["version"]),
            OPERATOR,
        ),
        201,
    )

    assert_pct(flight["wind_kph_at_dispatch"], 10.0, "wind_kph_at_dispatch")
    # a 10.0 kph wind is exactly at the free threshold: wind_factor stays 1.0, so the same
    # order that needs 46.8 at 30 kph needs only 38.6 here.
    assert_pct(flight["required_energy_pct"], 38.6, "required_energy_pct")


# ============================================================== the pad-hold interval
def test_touching_pad_holds_collide_on_a_single_pad_nest(api):
    """PRD §3.4: "Each live sortie holds its recovery nest's pad across a closed interval:
    `pad_hold_start` is 5 minutes before `eta_recovery_at`, and `pad_hold_end` is 10 minutes
    after `eta_recovery_at`."
    PRD §3.4: "Endpoints that merely touch **do** intersect: a hold that ends at exactly the
    minute another begins collides with it. If the number of such overlapping holds is greater
    than or equal to the nest's `pad_count`, dispatch is rejected with `ERR_NEST_PADS_FULL`
    (HTTP 409) — the nest tolerates at most `pad_count` minus one concurrent holds beside the
    newcomer."

    Design: Difficulty/resource_temporal_overlap/nest_pad_hold_closed_interval_aggregate_capacity
    """
    w = setup_world(pad_count=1, tail_number="N101")
    add_airframe(w, "N102", "B-2")
    first = setup_planned_flight(world=dict(w))
    order_2 = create_order(w["customer"]["id"], w["sa"]["id"])

    assert_instant(
        first["flight"]["pad_hold_start"], "2026-06-01T09:10:00Z", "pad_hold_start"
    )
    assert_instant(first["flight"]["pad_hold_end"], "2026-06-01T09:25:00Z", "pad_hold_end")

    # At 09:15 the candidate hold is [09:25, 09:40] — it touches the live hold at exactly 09:25.
    set_clock("2026-06-01T09:15:00Z")
    resp = api.dispatch_order(
        order_2["id"], dispatch_order_payload(w["nest"]["id"], order_2["version"]), OPERATOR
    )
    validate_error(resp, ApiErrorId.ERR_NEST_PADS_FULL.value)

    assert read_order(order_2["id"])["status"] == "QUOTED"


def test_pad_hold_one_minute_later_is_disjoint_and_accepted(api):
    """PRD §3.4: "The capacity check counts the flights already recovering at the requested
    nest whose `ops_state` is `PLANNED`, `LAUNCHED`, `DROPPING` or `RETURNING`, and whose own
    closed pad-hold interval intersects the closed candidate interval of the sortie being
    planned."
    PRD §2.10: "Dispatch increments it by one; recovery decrements it by one; an abort from any
    non-terminal `ops_state` decrements it by one."

    Design: Difficulty/resource_temporal_overlap/nest_pad_hold_closed_interval_aggregate_capacity
    """
    w = setup_world(pad_count=1, tail_number="N101")
    add_airframe(w, "N102", "B-2")
    setup_planned_flight(world=dict(w))
    order_3 = create_order(w["customer"]["id"], w["sa"]["id"])

    # At 09:16 the candidate hold is [09:26, 09:41] — disjoint from the live [09:10, 09:25].
    set_clock("2026-06-01T09:16:00Z")
    flight_3 = validate_success(
        api.dispatch_order(
            order_3["id"],
            dispatch_order_payload(w["nest"]["id"], order_3["version"]),
            OPERATOR,
        ),
        201,
    )

    assert_instant(flight_3["pad_hold_start"], "2026-06-01T09:26:00Z", "pad_hold_start")
    assert_instant(flight_3["pad_hold_end"], "2026-06-01T09:41:00Z", "pad_hold_end")
    assert read_nest(w["nest"]["id"])["reserved_pads"] == 2, (
        "both live sorties hold a slot at the nest"
    )


# ============================================================ stale-read protection
def test_stale_expected_order_version_on_redispatch_is_rejected(api):
    """PRD §2.9: "Dispatching an order requires `expected_order_version` in the request body.
    This field is not optional. It must carry the client's last observed `version` of the target
    order. If it does not equal the order's current `version` at the moment the request is
    processed, the dispatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) and nothing is
    mutated."
    PRD §2.9: "The reason this guard exists is concrete: a prior dispatch of the same order
    creates a flight, reserves a pad and moves the order to `ASSIGNED`, all of which advance the
    order's `version`; a subsequent abort returns the order to `QUOTED` and advances the
    `version` again."

    Design: Corner/cross_cutting_layers/occ_stale_order_version_on_redispatch
    """
    w = setup_planned_flight()
    stale_version = w["order"]["version"]  # the version the client read before dispatching
    abort_flight(w["flight"]["id"])

    stale = api.dispatch_order(
        w["order"]["id"],
        dispatch_order_payload(w["nest"]["id"], stale_version),
        OPERATOR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ORDER_VERSION.value)

    order = read_order(w["order"]["id"])
    assert order["status"] == "QUOTED"
    assert order["version"] == 3, "dispatch bumped to 2, abort bumped to 3; the 412 bumps nothing"

    fresh = validate_success(
        api.dispatch_order(
            w["order"]["id"],
            dispatch_order_payload(w["nest"]["id"], order["version"]),
            OPERATOR,
        ),
        201,
    )
    assert fresh["ops_state"] == "PLANNED"

    reread = read_order(w["order"]["id"])
    assert reread["status"] == "ASSIGNED"
    assert reread["version"] == 4
