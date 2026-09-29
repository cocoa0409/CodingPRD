"""Two intervals with deliberately opposite adjacency rules."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_units_equal,
    factories as f,
    fixtures as fx,
    make_courier_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
FIRST_DOOR = "2026-08-20T16:00:00Z"
SECOND_PROMISE = "2026-08-20T16:30:00Z"
ONE_MINUTE_BEFORE_THE_END = "2026-08-20T16:19:00Z"
EXACTLY_THE_END = "2026-08-20T16:20:00Z"


def _courier_already_at_a_door(api):
    """One courier holding an `INITIATED` attempt that occupies 16:00 to 16:20."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(api, jurisdiction["id"], unit_scale_factor=1.15, max_units_per_order=6.97)
    wine = fx.create_product(api, f.wine_product_payload())
    customer = fx.create_customer(api, jurisdiction["id"])
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    fx.add_identity_check(api, customer["id"])
    partner = fx.create_partner(api, license_reference="NY-DEL-0001")
    courier = fx.create_courier(api, partner["id"])
    fx.issue_certification(api, courier)

    orders = []
    for scheduled_at in (FIRST_DOOR, SECOND_PROMISE):
        order = fx.create_order(
            api, customer["id"], jurisdiction["id"], partner["id"], scheduled_at, 600
        )
        fx.add_line(api, order, wine["id"], 3)
        order = fx.submit_order(api, order)
        fx.dispatch_order(api, order)
        orders.append(order)

    resident = fx.open_attempt(api, orders[0], courier, FIRST_DOOR)
    return {
        "courier": courier,
        "courier_headers": make_courier_headers(courier["id"]),
        "order_one": orders[0],
        "order_two": orders[1],
        "resident_attempt": resident,
    }


def _attempt_request(api, world, started_at):
    return api.create_delivery_attempt(
        f.delivery_attempt_payload(
            world["order_two"]["id"], world["courier"]["id"], started_at
        ),
        world["courier_headers"],
    )


def test_01_an_attempt_one_minute_inside_the_dwell_interval_collides(api):
    """PRD 2.10: "A delivery attempt occupies its courier for 20 minutes starting at
    the attempt's `started_at`, and that interval is half-open with a zero buffer: it
    runs from `started_at` up to but not including the instant 20 minutes later. A new
    attempt collides when its interval intersects the interval of any non-terminal
    attempt of the same courier — that is, any attempt in `INITIATED`, `ID_VERIFIED` or
    `ID_REJECTED` — and the collision is reported as `ERR_COURIER_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/courier_dwell_interval_is_half_open_so_touching_attempts_are_allowed
    """
    world = _courier_already_at_a_door(api)

    response = _attempt_request(api, world, ONE_MINUTE_BEFORE_THE_END)

    validate_error(response, ApiErrorId.COURIER_SLOT_CONFLICT.value)
    attempts, _meta = validate_paginated(
        api.list_delivery_attempts(ADMIN_HEADERS, {"order_id": world["order_two"]["id"]})
    )
    assert attempts == [], (
        "the collision must leave no attempt row behind for the second order; got "
        f"{len(attempts)}"
    )


def test_02_an_attempt_at_the_excluded_end_instant_is_accepted(api):
    """PRD 2.10: "Exact adjacency is permitted here: a new attempt whose `started_at`
    equals the exact end of a previous attempt's dwell interval does not conflict."

    Design: Difficulty/resource_temporal_overlap/courier_dwell_interval_is_half_open_so_touching_attempts_are_allowed
    """
    world = _courier_already_at_a_door(api)

    created = validate_success(
        _attempt_request(api, world, EXACTLY_THE_END), expected_status=201
    )

    assert created["state"] == "INITIATED"
    assert created["started_at"] == EXACTLY_THE_END
    assert fx.read_attempt(api, world["resident_attempt"]["id"])["state"] == "INITIATED"
    assert fx.read_order(api, world["order_two"]["id"])["fulfillment_state"] == "OUT_FOR_DELIVERY"


def test_03_one_minute_of_dwell_geometry_separates_a_refusal_from_a_row(api):
    """PRD 3.6: "The attempt also reserves the courier's twenty-minute half-open
    dwell interval and can be refused with `ERR_COURIER_SLOT_CONFLICT` under the
    geometry of 2.10."

    Design: Difficulty/resource_temporal_overlap/courier_dwell_interval_is_half_open_so_touching_attempts_are_allowed
    """
    world = _courier_already_at_a_door(api)

    validate_error(
        _attempt_request(api, world, ONE_MINUTE_BEFORE_THE_END),
        ApiErrorId.COURIER_SLOT_CONFLICT.value,
    )
    validate_success(_attempt_request(api, world, EXACTLY_THE_END), expected_status=201)

    attempts, _meta = validate_paginated(
        api.list_delivery_attempts(ADMIN_HEADERS, {"courier_id": world["courier"]["id"]})
    )
    assert len(attempts) == 2, (
        "only the touching attempt may have landed alongside the resident one; got "
        f"{len(attempts)}"
    )


# ===========================================================================
# The inverted geometry: closed calendar periods where touching collides
# ===========================================================================
def _jurisdiction_holding_an_august_policy_per_class(api):
    """One August alcohol period, plus a tobacco period sharing every one of its dates."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    alcohol_policy = fx.create_policy(
        api,
        jurisdiction["id"],
        restriction_type="ALCOHOL",
        unit_scale_factor=1.15,
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    tobacco_policy = fx.create_policy(
        api,
        jurisdiction["id"],
        restriction_type="TOBACCO_VAPE",
        unit_scale_factor=1.00,
        max_units_per_order=5.00,
        max_units_per_window=20.00,
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    return {
        "jurisdiction": jurisdiction,
        "alcohol_policy": alcohol_policy,
        "tobacco_policy": tobacco_policy,
    }


def _successor_policy_request(api, jurisdiction_id, effective_from):
    return api.create_restriction_policy(
        f.restriction_policy_payload(
            jurisdiction_id,
            restriction_type="ALCOHOL",
            unit_scale_factor=1.30,
            effective_from=effective_from,
            effective_to="2026-09-30",
        ),
        ADMIN_HEADERS,
    )


def test_04_a_successor_period_starting_on_the_resident_last_date_collides(api):
    """PRD 2.10: "Two policies for the same jurisdiction and the same restriction
    class may not share even a single calendar date, and because the interval is closed
    at both ends a new period whose `effective_from` equals an existing period's
    `effective_to` *is* an overlap and is rejected with `ERR_POLICY_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_effective_period_is_closed_closed_so_touching_dates_collide
    """
    world = _jurisdiction_holding_an_august_policy_per_class(api)

    response = _successor_policy_request(api, world["jurisdiction"]["id"], "2026-08-31")

    validate_error(response, ApiErrorId.POLICY_PERIOD_OVERLAP.value)
    policies, _meta = validate_paginated(
        api.list_jurisdiction_restriction_policies(
            world["jurisdiction"]["id"], ADMIN_HEADERS, {"restriction_type": "ALCOHOL"}
        )
    )
    assert len(policies) == 1, (
        "the rejected period must not have been stored; got "
        f"{len(policies)} alcohol policy rows"
    )


def test_05_the_first_date_outside_the_closed_period_is_accepted(api):
    """PRD 3.1: "`effective_from` and `effective_to` bound the closed calendar period
    over which the row governs, and a period sharing any date with an existing period
    for the same jurisdiction and class is rejected with `ERR_POLICY_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_effective_period_is_closed_closed_so_touching_dates_collide
    """
    world = _jurisdiction_holding_an_august_policy_per_class(api)

    created = validate_success(
        _successor_policy_request(api, world["jurisdiction"]["id"], "2026-09-01"),
        expected_status=201,
    )

    assert created["effective_from"] == "2026-09-01"
    assert_units_equal(created["unit_scale_factor"], 1.30, "unit_scale_factor")
    policies, _meta = validate_paginated(
        api.list_jurisdiction_restriction_policies(
            world["jurisdiction"]["id"], ADMIN_HEADERS, {"restriction_type": "ALCOHOL"}
        )
    )
    assert len(policies) == 2


def test_06_the_overlap_rule_is_scoped_to_the_jurisdiction_and_the_class(api):
    """PRD 2.10: "A policy's `effective_from` and `effective_to` are calendar dates
    in `YYYY-MM-DD` form and the effective period they describe is **closed at both
    ends**: both the first and last date govern."

    Design: Difficulty/resource_temporal_overlap/policy_effective_period_is_closed_closed_so_touching_dates_collide
    """
    world = _jurisdiction_holding_an_august_policy_per_class(api)

    tobacco = validate_success(
        api.get_restriction_policy(world["tobacco_policy"]["id"], ADMIN_HEADERS)
    )
    assert tobacco["effective_from"] == "2026-08-01"
    assert tobacco["effective_to"] == "2026-08-31"
    assert tobacco["restriction_type"] == "TOBACCO_VAPE", (
        "the tobacco row shares every date with the alcohol row and is still admissible, "
        "which is what scopes the rule to the class as well as the jurisdiction"
    )
    validate_error(
        _successor_policy_request(api, world["jurisdiction"]["id"], "2026-08-31"),
        ApiErrorId.POLICY_PERIOD_OVERLAP.value,
    )
