"""Network configuration and order intake: creation, defaults, payload validation,
existence, listing, and the quoted-fee combinatorial formula."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_depot_payload, create_order_payload,
    assert_depot, assert_order,
    make_customer, make_depot, make_order,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_depot_returns_created_resource(api):
    """PRD §3.1: "A depot is created with a name and a region_code denoting
    the service region it serves." PRD §4: "Operations that create a new
    resource return 201 Created."

    Design: Corner/entities/create_depot_returns_201_with_fields
    """
    resp = api.create_depot(create_depot_payload(region_code="CA"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_depot(data)
    assert data["region_code"] == "CA", "region_code must be echoed back"


def test_create_depot_starts_at_version_one(api):
    """PRD §2.4: "version — an integer that begins at creation and increments
    by one on every mutation of the resource."

    Design: Corner/entities/create_depot_returns_201_with_fields
    """
    data = validate_success(api.create_depot(create_depot_payload(), ADMIN), expected_status=201)
    assert data["version"] == 1, f"a freshly created resource must be at version 1, got {data['version']}"


def test_create_order_missing_service_level_rejected(api):
    """PRD §2.9: "Payload validity — required fields present, enums valid ...
    failure yields ERR_VALIDATION." PRD §3.2: "The ordered service_level is one
    of THRESHOLD, ROOM_OF_CHOICE, or WHITE_GLOVE."

    Design: Corner/entities/create_order_missing_service_level_returns_validation
    """
    cust = make_customer(api)
    payload = {
        "customer_id": cust["id"], "item_description": "Table",
        "weight_lbs": 100, "volume_cuft": 20, "declared_value_cents": 10000,
    }
    validate_error(api.create_order(payload, PLANNER), ApiErrorId.ERR_VALIDATION.value)


def test_create_order_invalid_service_level_enum_rejected(api):
    """PRD §2.9: "Payload validity — required fields present, enums valid ...
    failure yields ERR_VALIDATION." PRD §3.2: "The ordered service_level is one
    of THRESHOLD, ROOM_OF_CHOICE, or WHITE_GLOVE."

    Design: Corner/entities/create_order_invalid_enum_service_level_returns_validation
    """
    cust = make_customer(api)
    payload = create_order_payload(cust["id"], service_level="PLATINUM")
    validate_error(api.create_order(payload, PLANNER), ApiErrorId.ERR_VALIDATION.value)


def test_create_order_nonpositive_weight_rejected(api):
    """PRD §3.2: "its weight_lbs and volume_cuft (each of which must be strictly
    greater than 0)." PRD §2.9: "the field-level constraints of §3 satisfied
    (weight_lbs greater than 0 ...); failure yields ERR_VALIDATION."

    Design: Corner/entities/create_order_nonpositive_weight_invalid_request
    """
    cust = make_customer(api)
    payload = create_order_payload(cust["id"], weight_lbs=0)
    validate_error(api.create_order(payload, PLANNER), ApiErrorId.ERR_VALIDATION.value)


def test_create_order_applies_flag_defaults(api):
    """PRD §3.2: "Three option fields tune the job: assembly_required (default
    false), haul_away_required (default false, for old-item debris removal), and
    stair_flights (default 0, the number of stair flights up to the room of
    choice)."

    Design: Corner/entities/create_order_applies_flag_defaults
    """
    cust = make_customer(api)
    data = validate_success(
        api.create_order(create_order_payload(cust["id"], service_level="THRESHOLD", weight_lbs=100), PLANNER),
        expected_status=201,
    )
    assert data["assembly_required"] is False
    assert data["haul_away_required"] is False
    assert data["stair_flights"] == 0


def test_create_order_quotes_threshold_defaults(api):
    """PRD §3.2: "Start from the service base for the ordered level: THRESHOLD
    costs 4000 cents ... Add the weight surcharge ... items from 76 through 150
    pounds add 1500 cents." PRD §3.2: "The resulting sum is quoted_fee_cents."

    Design: Corner/entities/create_order_applies_flag_defaults
    """
    cust = make_customer(api)
    data = validate_success(
        api.create_order(create_order_payload(cust["id"], service_level="THRESHOLD", weight_lbs=100), PLANNER),
        expected_status=201,
    )
    # 4000 (THRESHOLD base) + 1500 (76..150 weight tier), no multiplier/add-ons.
    assert data["quoted_fee_cents"] == 5500, f"expected 5500, got {data['quoted_fee_cents']}"


def test_new_team_liability_points_default_zero(api):
    """PRD §3.1: "Two computed exposure figures ride along on the crew:
    estimated_liability_points and settled_liability_points, both starting at 0
    and reconciled as described in §3.7."

    Design: Corner/entities/new_team_liability_points_default_zero
    """
    from test_helpers import make_team
    depot = make_depot(api)
    team = make_team(api, depot["id"])
    assert team["estimated_liability_points"] == 0
    assert team["settled_liability_points"] == 0


def test_new_dock_defaults_open_and_buffer(api):
    """PRD §3.1: "a buffer_min, the required clear gap in minutes between two
    booked appointments on that dock, defaulting to 30. A dock begins life OPEN."

    Design: Corner/entities/new_dock_status_defaults_open
    """
    from test_helpers import make_dock
    depot = make_depot(api)
    dock = make_dock(api, depot["id"])
    assert dock["status"] == "OPEN"
    assert dock["buffer_min"] == 30


def test_get_unknown_order_returns_not_found(api):
    """PRD §2.8: "Each missing identifier maps to its own not-found error:
    ERR_DEPOT_NOT_FOUND, ERR_DOCK_NOT_FOUND, ERR_TEAM_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND, ERR_ORDER_NOT_FOUND ..."

    Design: Corner/entities/get_order_not_found_returns_404
    """
    validate_error(api.get_order(UNKNOWN_UUID, PLANNER), ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_create_order_unknown_customer_returns_not_found(api):
    """PRD §2.8: "A body foreign key (depot_id, dock_id, team_id, customer_id,
    order_id, window_id, route_id, stop_id) is likewise checked for existence.
    Each missing identifier maps to its own not-found error: ... ERR_CUSTOMER_NOT_FOUND ..."

    Design: Corner/entities/create_order_customer_not_found_returns_404
    """
    payload = create_order_payload(UNKNOWN_UUID)
    validate_error(api.create_order(payload, PLANNER), ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_list_orders_returns_pagination_envelope(api):
    """PRD §2.3: "Every list-based response carries limit, offset, total_count,
    and has_more inside the meta object of the envelope." PRD §2.2: "The
    response_type is either "object" for a single resource or "array" for a list
    of resources."

    Design: Corner/entities/list_orders_returns_pagination_envelope
    """
    cust = make_customer(api)
    make_order(api, cust["id"])
    data, meta = validate_paginated(api.list_orders(PLANNER))
    assert isinstance(data, list)
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


# --- Difficulty: combinatorial quote formula (non-linear WG multiplier) ---

def test_quote_full_white_glove_combination(api):
    """PRD §3.2: "Take the sum of the service base and the weight surcharge and
    multiply it by the white-glove multiplier — 1.15 when the ordered
    service_level is WHITE_GLOVE, and 1.00 otherwise — then round that product
    half up to a whole cent."
    PRD §3.2: "To the core charge, add the stair charge: take the smaller of
    stair_flights and the billable ceiling of 5 flights, and multiply by 800
    cents per flight. Then add a flat 2500 cents when assembly_required is true,
    and a flat 3000 cents when haul_away_required is true. The resulting sum is
    quoted_fee_cents."

    Design: Difficulty/combinatorial_formula/quote_nonlinear_wg_multiplier_mode_a
    """
    cust = make_customer(api)
    order = validate_success(
        api.create_order(
            create_order_payload(
                cust["id"], item_description="Sofa", weight_lbs=200, volume_cuft=30,
                declared_value_cents=250000, service_level="WHITE_GLOVE",
                assembly_required=True, haul_away_required=True, stair_flights=6,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    # round((12000+3500)*1.15)=17825, +min(6,5)*800=4000, +2500 assembly, +3000 haul = 27325
    assert order["quoted_fee_cents"] == 27325, f"expected 27325, got {order['quoted_fee_cents']}"
    assert_order(order)


def test_quote_white_glove_multiplier_applies_before_flat_addons(api):
    """PRD §3.2: "Take the sum of the service base and the weight surcharge and
    multiply it by the white-glove multiplier — 1.15 when the ordered
    service_level is WHITE_GLOVE, and 1.00 otherwise — then round that product
    half up to a whole cent. This rounded amount is the core charge; rounding
    happens exactly once here, before any flat add-ons."

    Design: Difficulty/combinatorial_formula/quote_nonlinear_wg_multiplier_mode_a
    """
    cust = make_customer(api)
    order = validate_success(
        api.create_order(
            create_order_payload(
                cust["id"], item_description="Sofa", weight_lbs=200, volume_cuft=30,
                declared_value_cents=250000, service_level="WHITE_GLOVE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    # No stair/assembly/haul: quote is the isolated core = round((12000+3500)*1.15) = 17825.
    assert order["quoted_fee_cents"] == 17825, f"expected 17825, got {order['quoted_fee_cents']}"
