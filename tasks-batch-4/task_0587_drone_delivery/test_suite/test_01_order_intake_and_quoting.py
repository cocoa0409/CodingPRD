"""Order intake: geography registration, geometry, fee, surcharge and the quote."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_km,
    assert_money,
    assert_order,
    assert_service_area,
    create_customer,
    create_order,
    create_order_payload,
    create_service_area,
    create_service_area_payload,
    create_nest_payload,
    suspend_service_area,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["dispatch_operator_headers"]


# ============================================================ geography registration
def test_service_area_is_created_active_at_version_one(api):
    """PRD §3.1: "A newly registered area's `status` is `ACTIVE`."
    PRD §2.5: "Every persisted resource carries an `id`: a server-minted UUID with no
    type prefix, assigned at creation and never reused."
    PRD §2.5: "Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp,
    refreshed on every mutation of the resource — and `version`, an integer that starts at 1
    on creation and increments by exactly one on every mutation."

    Design: Corner/entities/create_service_area_applies_active_default_and_system_fields
    """
    resp = api.create_service_area(create_service_area_payload(), ADMIN)
    data = validate_success(resp, 201)

    assert_service_area(data)
    assert data["status"] == "ACTIVE", "a newly registered area starts ACTIVE"
    assert data["version"] == 1, "version starts at 1 on creation"

    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_nest_registration_with_unknown_service_area_is_not_found(api):
    """PRD §2.6: "Order intake, nest registration, drone registration, battery registration,
    battery installation, incident filing, maintenance scheduling, geofence publication and
    weather publication all name other resources by identifier — `customer_id`,
    `service_area_id`, `home_nest_id`, `nest_id`, `drone_id`, `battery_id`, `flight_id`,
    `incident_id`, `authorization_id` — and every one of them must resolve to an existing
    record before any business rule runs."
    PRD §2.6: "A dangling body-level foreign key yields the corresponding not-found code,
    not a validation error."

    Design: Corner/entities/nest_create_with_unknown_service_area_returns_not_found
    """
    payload = create_nest_payload(NON_EXISTENT_UUID, name="Ghost", pad_count=1)
    resp = api.create_nest(payload, ADMIN)

    validate_error(resp, ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND.value)


# ================================================================ order intake shape
def test_order_without_payload_weight_is_a_request_shape_violation(api):
    """PRD §3.3: "An order is placed by the `Customer` themselves or by a `DispatchOperator`
    acting on their behalf, naming the `customer_id`, the `service_area_id` that must serve it,
    a gross `payload_weight_g` in grams (strictly greater than zero), and an optional `priority`
    of `STANDARD`, `URGENT` or `MEDICAL`, defaulting to `STANDARD`."
    PRD §2.11: "Request shape: required fields present, types correct, enum values in range,
    and numeric constraints satisfied — `payload_weight_g` greater than zero, `pad_count` at
    least 1, `requested_alt_ft` greater than zero and at most 400, `hover_alt_ft` greater than
    zero and at most 400, `limit` between 1 and 100 inclusive, `offset` at least zero
    (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/entities/create_order_missing_payload_weight_returns_invalid_request
    """
    sa = create_service_area()
    customer = create_customer()

    payload = {
        "customer_id": customer["id"],
        "service_area_id": sa["id"],
        "priority": "STANDARD",
    }
    resp = api.create_order(payload, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    listed, meta = validate_paginated(
        api.list_orders(OPERATOR, params={"customer_id": customer["id"]})
    )
    assert meta["total_count"] == 0, "the rejected intake must not create an Order"
    assert listed == []


def test_order_priority_defaults_to_standard(api):
    """PRD §3.3: "An order is placed by the `Customer` themselves or by a `DispatchOperator`
    acting on their behalf, naming the `customer_id`, the `service_area_id` that must serve it,
    a gross `payload_weight_g` in grams (strictly greater than zero), and an optional `priority`
    of `STANDARD`, `URGENT` or `MEDICAL`, defaulting to `STANDARD`."
    PRD §3.3: "The subtotal is then multiplied by the priority multiplier — 1.0 for `STANDARD`,
    1.35 for `URGENT`, 1.60 for `MEDICAL` — and the product is rounded half up to two decimal
    places to give `delivery_fee`."

    Design: Corner/entities/create_order_omitting_priority_defaults_to_standard
    """
    sa = create_service_area()
    customer = create_customer()

    payload = {
        "customer_id": customer["id"],
        "service_area_id": sa["id"],
        "payload_weight_g": 2000,
    }
    order = validate_success(api.create_order(payload, OPERATOR), 201)

    assert_order(order)
    assert order["priority"] == "STANDARD"
    # base 6.50 (5.550 km) + payload 1.80 => 8.30 at the 1.0 STANDARD multiplier.
    assert_money(order["delivery_fee"], 8.30, "delivery_fee")
    assert_money(order["airspace_surcharge"], 0.66, "airspace_surcharge")
    assert_money(order["order_total"], 8.96, "order_total")


def test_order_freezes_the_customers_dropoff_point_and_derives_distance(api):
    """PRD §3.3: "The customer's current `dropoff_lat` and `dropoff_lon` are copied onto the
    order and frozen there — a later change to the customer's address does not retroactively
    move an existing order."
    PRD §3.3: "The order's `distance_km` is then the planar distance (§2.7) from the service
    area's centroid to that frozen dropoff point, at three decimal places."
    PRD §3.3: "The order comes into existence with `status` `QUOTED` and `version` 1."

    Design: Corner/entities/order_freezes_customer_dropoff_coordinates
    """
    sa = create_service_area()
    customer = create_customer(dropoff_lat=37.05, dropoff_lon=-122.0)

    order = validate_success(
        api.create_order(create_order_payload(customer["id"], sa["id"]), OPERATOR), 201
    )

    assert order["dropoff_lat"] == 37.05
    assert order["dropoff_lon"] == -122.0
    # 0.05 degrees of latitude * 111.0 km/deg = 5.550 km.
    assert_km(order["distance_km"], 5.550)
    assert order["status"] == "QUOTED"


def test_unknown_order_id_returns_order_not_found(api):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first identifier
    that names nothing terminates the request with the 404 belonging to that identifier's
    entity."
    PRD §2.6: "The full family of not-found codes is `ERR_SERVICE_AREA_NOT_FOUND`,
    `ERR_NEST_NOT_FOUND`, `ERR_DRONE_NOT_FOUND`, `ERR_BATTERY_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`,
    `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_GEOFENCE_ZONE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    and `ERR_MAINTENANCE_LOG_NOT_FOUND`, each returning HTTP 404."

    Design: Corner/entities/get_order_with_unknown_id_returns_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, OPERATOR)

    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"


def test_orders_list_is_paginated_with_envelope_meta(api):
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10 when omitted,
    may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the number of items
    matching the filters before pagination is applied and `has_more` indicates whether items
    remain beyond the current page."

    Design: Corner/entities/orders_list_is_paginated_with_envelope_fields
    """
    sa = create_service_area()
    customer = create_customer()
    for _ in range(3):
        create_order(customer["id"], sa["id"])

    resp = api.list_orders(
        OPERATOR, params={"customer_id": customer["id"], "limit": 2, "offset": 0}
    )
    data, meta = validate_paginated(resp)

    assert resp.json()["response_type"] == "array"
    assert len(data) == 2, "limit=2 must cap the page at two orders"
    assert meta["total_count"] == 3, "total_count counts matches before pagination"
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    # limit defaults to 10 when omitted, so all three come back on one page.
    all_data, all_meta = validate_paginated(
        api.list_orders(OPERATOR, params={"customer_id": customer["id"]})
    )
    assert all_meta["limit"] == 10
    assert len(all_data) == 3
    assert all_meta["has_more"] is False


# ==================================================================== intake gates
def test_distance_at_exactly_max_range_is_accepted_and_beyond_it_is_rejected(api):
    """PRD §3.3: "If `distance_km` is greater than the area's `max_range_km`, the order is
    rejected with `ERR_OUT_OF_SERVICE_RANGE` (HTTP 422); a distance exactly equal to
    `max_range_km` is accepted."
    PRD §2.7: "Given two coordinate pairs, take the difference of the latitudes and multiply it
    by 111.0 kilometres per degree of latitude to obtain the north-south leg; take the
    difference of the longitudes and multiply it by 85.0 kilometres per degree of longitude to
    obtain the east-west leg; the distance is the square root of the sum of the squares of the
    two legs, rounded half up to three decimal places."

    Design: Corner/calculations/distance_exactly_at_max_range_accepted_one_step_beyond_rejected
    """
    sa = create_service_area(name="Edge", max_range_km=5.55)
    near = create_customer(name="Near", email="near@x.com", dropoff_lat=37.05, dropoff_lon=-122.0)
    far = create_customer(name="Far", email="far@x.com", dropoff_lat=37.051, dropoff_lon=-122.0)

    ok = validate_success(
        api.create_order(create_order_payload(near["id"], sa["id"]), OPERATOR), 201
    )
    # 0.05 degrees of latitude * 111.0 km/deg == 5.550 km == exactly max_range_km.
    assert_km(ok["distance_km"], 5.550)

    rejected = api.create_order(create_order_payload(far["id"], sa["id"]), OPERATOR)
    validate_error(rejected, ApiErrorId.ERR_OUT_OF_SERVICE_RANGE.value)

    _, meta = validate_paginated(
        api.list_orders(OPERATOR, params={"service_area_id": sa["id"]})
    )
    assert meta["total_count"] == 1, "only the in-range order exists"


def test_payload_at_exactly_the_area_limit_is_accepted_and_one_gram_beyond_is_rejected(api):
    """PRD §3.3: "If the payload is heavier than the area's `max_payload_g`, the order is
    rejected with `ERR_PAYLOAD_EXCEEDS_LIMIT` (HTTP 422); a payload exactly equal to
    `max_payload_g` is accepted."

    Design: Corner/calculations/payload_exactly_at_area_limit_accepted_one_gram_beyond_rejected
    """
    sa = create_service_area(max_payload_g=2500)
    customer = create_customer()

    ok = validate_success(
        api.create_order(
            create_order_payload(customer["id"], sa["id"], payload_weight_g=2500), OPERATOR
        ),
        201,
    )
    assert ok["payload_weight_g"] == 2500

    rejected = api.create_order(
        create_order_payload(customer["id"], sa["id"], payload_weight_g=2501), OPERATOR
    )
    validate_error(rejected, ApiErrorId.ERR_PAYLOAD_EXCEEDS_LIMIT.value)


def test_intake_into_a_suspended_service_area_is_rejected(api):
    """PRD §3.1: "A suspended area rejects new order intake, rejects dispatch and rejects
    launch, all with `ERR_SERVICE_AREA_SUSPENDED`; sorties already airborne are untouched and
    may complete normally."
    PRD §3.3: "Intake into a `SUSPENDED` service area is rejected with
    `ERR_SERVICE_AREA_SUSPENDED`."

    Design: Corner/validations/suspended_service_area_blocks_new_orders
    """
    sa = create_service_area()
    customer = create_customer()
    suspended = suspend_service_area(sa["id"])
    assert suspended["status"] == "SUSPENDED"

    resp = api.create_order(create_order_payload(customer["id"], sa["id"]), OPERATOR)
    validate_error(resp, ApiErrorId.ERR_SERVICE_AREA_SUSPENDED.value)

    _, meta = validate_paginated(
        api.list_orders(OPERATOR, params={"service_area_id": sa["id"]})
    )
    assert meta["total_count"] == 0, "no Order row is created in a suspended area"


# ================================================================ the pinned fee order
def test_delivery_fee_rounds_each_component_before_the_priority_multiplier(api):
    """PRD §3.3: "Each of those two components is rounded half up to two decimal places **on
    its own**, and only then are the two rounded figures added together to form a subtotal."
    PRD §3.3: "The subtotal is then multiplied by the priority multiplier — 1.0 for `STANDARD`,
    1.35 for `URGENT`, 1.60 for `MEDICAL` — and the product is rounded half up to two decimal
    places to give `delivery_fee`."
    PRD §3.3: "Summing the raw components and rounding once at the end is explicitly *not* the
    rule and will yield different cents on some orders."

    Design: Difficulty/combinatorial_formula/fee_component_rounding_order_pinned
    """
    sa = create_service_area()
    customer = create_customer()

    order = validate_success(
        api.create_order(
            create_order_payload(
                customer["id"], sa["id"], payload_weight_g=1050, priority="URGENT"
            ),
            OPERATOR,
        ),
        201,
    )

    assert_km(order["distance_km"], 5.550)
    # base 6.50 + round(1.05 * 0.90, 2) = 6.50 + 0.95 = 7.45; 7.45 * 1.35 = 10.0575 -> 10.06.
    # "sum then round once" would give round((6.50 + 0.945) * 1.35, 2) = 10.05.
    assert_money(order["delivery_fee"], 10.06, "delivery_fee")


def test_urgent_order_surcharge_and_total_follow_the_component_rounded_fee(api):
    """PRD §3.3: "The base component is selected by the order's one-way `distance_km` against
    inclusive upper bounds: a distance of at most 5.0 km takes a base of 4.00; a distance
    greater than 5.0 km but at most 12.0 km takes a base of 6.50; any greater distance takes a
    base of 9.00."
    PRD §3.3: "The `airspace_surcharge` is that percentage of `delivery_fee`, rounded half up
    to two decimal places. The `order_total` is `delivery_fee` plus `airspace_surcharge`,
    rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/fee_component_rounding_order_pinned
    """
    sa = create_service_area()
    customer = create_customer()

    order = validate_success(
        api.create_order(
            create_order_payload(
                customer["id"], sa["id"], payload_weight_g=1050, priority="URGENT"
            ),
            OPERATOR,
        ),
        201,
    )

    # delivery_fee 10.06 sits in the 8% band; 0.08 * 10.06 = 0.8048 -> 0.80.
    assert_money(order["delivery_fee"], 10.06, "delivery_fee")
    assert_money(order["airspace_surcharge"], 0.80, "airspace_surcharge")
    assert_money(order["order_total"], 10.86, "order_total")


def test_surcharge_tier_is_keyed_on_delivery_fee_not_on_order_total(api):
    """PRD §3.3: "The regulatory `airspace_surcharge` is a percentage of the delivery fee, and
    the percentage tier is keyed on `delivery_fee` — the pre-surcharge figure — and never on
    `order_total`, even though `order_total` is what the customer actually pays."
    PRD §3.3: "A `delivery_fee` of at most 8.00 draws 5 percent; a fee greater than 8.00 but at
    most 15.00 draws 8 percent; a fee greater than 15.00 draws 12 percent."

    Design: Difficulty/combinatorial_formula/surcharge_tier_keyed_on_presurcharge_fee
    """
    sa = create_service_area()
    customer = create_customer()

    order = validate_success(
        api.create_order(
            create_order_payload(
                customer["id"], sa["id"], payload_weight_g=1500, priority="STANDARD"
            ),
            OPERATOR,
        ),
        201,
    )

    # fee 7.85 <= 8.00 -> 5% -> 0.39 -> total 8.24. Keying the tier on order_total (8.24 > 8.00)
    # would draw 8% and yield 0.63 / 8.48 instead.
    assert_money(order["delivery_fee"], 7.85, "delivery_fee")
    assert_money(order["airspace_surcharge"], 0.39, "airspace_surcharge")
    assert_money(order["order_total"], 8.24, "order_total")


def test_delivery_fee_of_exactly_eight_falls_into_the_lower_surcharge_tier(api):
    """PRD §3.3: "A `delivery_fee` of at most 8.00 draws 5 percent; a fee greater than 8.00 but
    at most 15.00 draws 8 percent; a fee greater than 15.00 draws 12 percent."
    PRD §3.3: "Both boundary fees — exactly 8.00 and exactly 15.00 — fall into the *lower*
    tier."

    Design: Difficulty/combinatorial_formula/surcharge_tier_keyed_on_presurcharge_fee
    """
    sa = create_service_area()
    customer = create_customer()

    order = validate_success(
        api.create_order(
            create_order_payload(
                customer["id"], sa["id"], payload_weight_g=1667, priority="STANDARD"
            ),
            OPERATOR,
        ),
        201,
    )

    # base 6.50 + round(1.667 * 0.90, 2) = 6.50 + 1.50 = 8.00 exactly, at the 1.0 multiplier.
    assert_money(order["delivery_fee"], 8.00, "delivery_fee")
    # 8.00 is the boundary and draws the LOWER 5% band: 0.05 * 8.00 = 0.40 (not 8% -> 0.64).
    assert_money(order["airspace_surcharge"], 0.40, "airspace_surcharge")
    assert_money(order["order_total"], 8.40, "order_total")
