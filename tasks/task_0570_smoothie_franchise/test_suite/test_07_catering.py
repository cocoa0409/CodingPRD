"""Catering booking: vehicle availability, prep-capacity and vehicle-window overlap, quote."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_catering_env, set_vehicle_maintenance,
    make_customer_headers,
    create_catering_booking_payload,
)


def _book(api, store_id, customer_id, payload):
    return api.create_catering_booking(store_id, payload, make_customer_headers(customer_id))


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/catering_delivery_requires_vehicle_available
# ---------------------------------------------------------------------------

def test_delivery_booking_on_maintenance_vehicle_rejected(api):
    """PRD §3.7: "For a `DELIVERY` booking, the named vehicle must be `AVAILABLE`, else
    `ERR_VEHICLE_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/catering_delivery_requires_vehicle_available
    """
    env = setup_catering_env(api, catering_capacity=50, with_vehicle=True)
    set_vehicle_maintenance(api, env["vehicle"]["id"], env["franchisee"]["id"])
    payload = create_catering_booking_payload(
        env["customer"]["id"], "DELIVERY", 5,
        [{"menu_item_id": env["menu_item"]["id"], "qty": 5}],
        "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z",
        delivery_vehicle_id=env["vehicle"]["id"],
        delivery_window_start="2026-06-01T12:00:00Z", delivery_window_end="2026-06-01T13:00:00Z",
    )
    resp = _book(api, env["store"]["id"], env["customer"]["id"], payload)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_UNAVAILABLE.value)


def test_delivery_booking_on_available_vehicle_succeeds(api):
    """PRD §3.7: "For a `DELIVERY` booking, the named vehicle must be `AVAILABLE`, else
    `ERR_VEHICLE_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/catering_delivery_requires_vehicle_available
    """
    env = setup_catering_env(api, catering_capacity=50, with_vehicle=True)
    payload = create_catering_booking_payload(
        env["customer"]["id"], "DELIVERY", 5,
        [{"menu_item_id": env["menu_item"]["id"], "qty": 5}],
        "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z",
        delivery_vehicle_id=env["vehicle"]["id"],
        delivery_window_start="2026-06-01T12:00:00Z", delivery_window_end="2026-06-01T13:00:00Z",
    )
    resp = _book(api, env["store"]["id"], env["customer"]["id"], payload)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "REQUESTED", f"Expected REQUESTED, got {data['status']}"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/catering_store_prep_capacity_overlap
# ---------------------------------------------------------------------------

def _pickup_payload(env, headcount, prep_start, prep_end, qty=1):
    return create_catering_booking_payload(
        env["customer"]["id"], "PICKUP", headcount,
        [{"menu_item_id": env["menu_item"]["id"], "qty": qty}],
        prep_start, prep_end,
    )


def test_overlapping_prep_windows_exceed_capacity(api):
    """PRD §3.7: "summing the `headcount` of every active booking whose prep window
    overlaps this one (again half-open, adjacency allowed) together with this booking's
    own `headcount` must not exceed the store's `catering_capacity`, else
    `ERR_CATERING_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/catering_store_prep_capacity_overlap
    """
    env = setup_catering_env(api, catering_capacity=10)
    validate_success(_book(api, env["store"]["id"], env["customer"]["id"],
                           _pickup_payload(env, 8, "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")),
                     expected_status=201)
    resp = _book(api, env["store"]["id"], env["customer"]["id"],
                 _pickup_payload(env, 5, "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z"))
    validate_error(resp, ApiErrorId.ERR_CATERING_CAPACITY_EXCEEDED.value)


def test_adjacent_prep_windows_do_not_exceed_capacity(api):
    """PRD §3.7: "summing the `headcount` of every active booking whose prep window
    overlaps this one (again half-open, adjacency allowed) together with this booking's
    own `headcount` must not exceed the store's `catering_capacity`, else
    `ERR_CATERING_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/catering_store_prep_capacity_overlap
    """
    env = setup_catering_env(api, catering_capacity=10)
    validate_success(_book(api, env["store"]["id"], env["customer"]["id"],
                           _pickup_payload(env, 8, "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")),
                     expected_status=201)
    # Adjacent window [12:00,14:00) does not overlap [10:00,12:00), so 8+5 never sums.
    resp = _book(api, env["store"]["id"], env["customer"]["id"],
                 _pickup_payload(env, 5, "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z"))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "REQUESTED", f"Expected REQUESTED, got {data['status']}"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/catering_vehicle_delivery_window_overlap
# ---------------------------------------------------------------------------

def _delivery_payload(env, del_start, del_end):
    return create_catering_booking_payload(
        env["customer"]["id"], "DELIVERY", 2,
        [{"menu_item_id": env["menu_item"]["id"], "qty": 2}],
        "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z",
        delivery_vehicle_id=env["vehicle"]["id"],
        delivery_window_start=del_start, delivery_window_end=del_end,
    )


def test_overlapping_vehicle_windows_double_booked(api):
    """PRD §3.7: "The delivery window must not overlap another active booking already
    using that same vehicle; overlap is judged on a half-open basis so that windows that
    merely touch end-to-start are allowed, and a true overlap is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/catering_vehicle_delivery_window_overlap
    """
    env = setup_catering_env(api, catering_capacity=50, with_vehicle=True)
    validate_success(_book(api, env["store"]["id"], env["customer"]["id"],
                           _delivery_payload(env, "2026-06-01T14:00:00Z", "2026-06-01T15:00:00Z")),
                     expected_status=201)
    resp = _book(api, env["store"]["id"], env["customer"]["id"],
                 _delivery_payload(env, "2026-06-01T14:30:00Z", "2026-06-01T15:30:00Z"))
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value)


def test_adjacent_vehicle_windows_allowed(api):
    """PRD §3.7: "The delivery window must not overlap another active booking already
    using that same vehicle; overlap is judged on a half-open basis so that windows that
    merely touch end-to-start are allowed, and a true overlap is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/catering_vehicle_delivery_window_overlap
    """
    env = setup_catering_env(api, catering_capacity=50, with_vehicle=True)
    validate_success(_book(api, env["store"]["id"], env["customer"]["id"],
                           _delivery_payload(env, "2026-06-01T14:00:00Z", "2026-06-01T15:00:00Z")),
                     expected_status=201)
    # [15:00,16:00) merely touches [14:00,15:00) end-to-start, which is allowed.
    resp = _book(api, env["store"]["id"], env["customer"]["id"],
                 _delivery_payload(env, "2026-06-01T15:00:00Z", "2026-06-01T16:00:00Z"))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "REQUESTED", f"Expected REQUESTED, got {data['status']}"


# ---------------------------------------------------------------------------
# Corner/validations/catering_past_window_returns_invalid_window
# ---------------------------------------------------------------------------

def test_catering_past_window_returns_invalid_window(api):
    """PRD §3.7: "no window may lie in the past relative to the current clock; a violation
    is rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/catering_past_window_returns_invalid_window
    """
    env = setup_catering_env(api, catering_capacity=10, clock="2026-06-10T00:00:00Z",
                             menu_base_price=500)
    resp = _book(api, env["store"]["id"], env["customer"]["id"],
                 _pickup_payload(env, 4, "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z", qty=4))
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# ---------------------------------------------------------------------------
# Corner/calculations/catering_quote_computed
# ---------------------------------------------------------------------------

def test_catering_quote_computed(api):
    """PRD §3.7: "the items total is the sum over items of the menu item's
    `base_price_cents` multiplied by its `qty`; the service fee is the `headcount`
    multiplied by 200 cents per head; and the quote is the items total plus the service
    fee plus the tax on their sum, where tax is 8% of the items-plus-service amount
    rounded half up."

    Design: Corner/calculations/catering_quote_computed
    """
    env = setup_catering_env(api, catering_capacity=10, menu_base_price=500)
    resp = _book(api, env["store"]["id"], env["customer"]["id"],
                 _pickup_payload(env, 8, "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z", qty=3))
    data = validate_success(resp, expected_status=201)
    # items 500*3=1500, service 8*200=1600, tax round(3100*0.08)=248, quote 3348.
    assert data["quoted_price_cents"] == 3348, (
        f"Expected quoted_price 3348, got {data['quoted_price_cents']}"
    )
