"""Resource creation, reads, defaults, system fields, and immutability corners."""
import test_helpers as th


def test_create_order_returns_201_with_system_fields(api):
    """PRD §3.2: "A fresh order starts with `status` `CREATED`,
    `estimate_total_cents` 0, `final_total_cents` 0, and `risk_flag` false."
    PRD §2.4: "a `version`, an integer that begins at its initial value on
    creation and increments by one with every modification."

    Design: Corner/entities/create_order_returns_201_with_system_fields
    """
    customer, pickup, delivery = th.create_zone_setup()
    resp = api.create_order(
        th.create_order_payload(customer["id"], pickup["id"], delivery["id"]),
        th.make_customer_headers(customer["id"]))
    data = th.validate_success(resp, expected_status=201)
    th.assert_order(data)
    assert data["status"] == "CREATED", f"new order is CREATED, got {data['status']}"
    assert data["version"] == 1, f"new order version is 1, got {data['version']}"
    assert data["estimate_total_cents"] == 0, "estimate starts at 0"


def test_get_order_not_found_returns_404(api):
    """PRD §2.7: "A garment action under a non-existent order therefore fails with
    `ERR_ORDER_NOT_FOUND` before the garment is ever looked up"

    Design: Corner/entities/get_order_not_found_returns_404
    """
    resp = api.get_order(th.NON_EXISTENT_UUID, th.admin_headers())
    th.validate_error(resp, "ERR_ORDER_NOT_FOUND", 404)


def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_orders_pagination_envelope
    """
    customer, pickup, delivery, order, _ = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    resp = api.list_orders(th.admin_headers(), params={"limit": 10, "offset": 0})
    data, meta = th.validate_paginated(resp)
    assert isinstance(data, list)
    assert "total_count" in meta and "has_more" in meta


def test_create_order_missing_required_field_returns_400(api):
    """PRD §2.9: "request-body schema validity - required fields present, types
    and enumerations correct, and numeric ranges honored, with a violation
    reported as `ERR_INVALID_REQUEST`"
    PRD §3.2: "a `handoff_method` that is either `DOORSTEP` or `LOCKER`" (a
    required order field).

    Design: Corner/entities/create_order_missing_required_field_returns_400
    """
    customer, pickup, delivery = th.create_zone_setup()
    payload = {
        "customer_id": customer["id"],
        "pickup_window_id": pickup["id"],
        "delivery_window_id": delivery["id"],
    }  # handoff_method omitted
    resp = api.create_order(payload, th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_rush_default_false_applied(api):
    """PRD §3.2: "an optional `rush` flag that defaults to false."

    Design: Corner/entities/rush_default_false_applied
    """
    customer, pickup, delivery = th.create_zone_setup()
    resp = api.create_order(
        th.create_order_payload(customer["id"], pickup["id"], delivery["id"]),
        th.make_customer_headers(customer["id"]))
    data = th.validate_success(resp, expected_status=201)
    assert data["rush"] is False, f"rush defaults to false, got {data['rush']}"


def test_customer_system_fields_initialize_to_zero(api):
    """PRD §3.1: "On registration the customer's `status` is `ACTIVE`, their
    `wallet_credit_cents` store-credit balance starts at 0, and their
    `risk_score` starts at 0."

    Design: Corner/entities/customer_system_fields_ignored_on_input
    """
    resp = api.create_customer(th.create_customer_payload(), th.admin_headers())
    data = th.validate_success(resp, expected_status=201)
    assert data["wallet_credit_cents"] == 0, "wallet starts at 0"
    assert data["risk_score"] == 0, "risk_score starts at 0"


def test_garment_note_is_append_only_no_version(api):
    """PRD §2.4: "A `GarmentNote` therefore carries only `id` and `created_at`;
    it has neither an `updated_at` nor a `version` field."

    Design: Corner/entities/garmentnote_immutable_no_version
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}],
        actuals=[{"actual_weight_grams": 2000}],
    )
    resp = api.log_note(order["id"], garments[0]["id"],
                        th.create_note_payload(note_kind="STAIN", severity=3, description="spot"),
                        th.plant_headers())
    data = th.validate_success(resp, expected_status=201)
    th.assert_garment_note_shape(data)
    assert "version" not in data, "GarmentNote must not carry version"
    assert "updated_at" not in data, "GarmentNote must not carry updated_at"
