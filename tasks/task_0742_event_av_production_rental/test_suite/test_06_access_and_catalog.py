"""Access control, catalog CRUD validation, input defaults, pagination guards, and
listing/reverse-reachability."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    new_customer, new_venue, new_equipment, new_order, add_reservation,
    create_order_payload, create_coi_payload, make_client_headers,
)


# ─── entities / get_nonexistent_order_returns_not_found ───────────────
def test_get_nonexistent_order_returns_not_found(api, account_manager_headers):
    """PRD §2.7: "Every resource id named in the path or referenced as a foreign key in
    the body must resolve to an existing record; path identifiers are validated left to
    right (see §2.10). A miss yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_order_returns_not_found
    """
    res = api.get_order(NON_EXISTENT_UUID, account_manager_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── entities / create_equipment_missing_required_field_rejected ──────
def test_create_equipment_missing_daily_rate_rejected(api, warehouse_manager_headers):
    """PRD §2.7: "The body must be well-formed: required fields present, enum fields
    carrying legal values, `qty` at least 1, `reserve_end_date` on or after
    `reserve_start_date`, `event_end_date` on or after `event_start_date`, `shift_end`
    strictly after `shift_start`, and every coverage, rate, or limit amount
    non-negative. A violation yields `ERR_VALIDATION`."

    Design: Corner/entities/create_equipment_missing_required_field_rejected
    """
    payload = {"name": "No Rate", "category": "SOUND", "total_units": 5,
               "replacement_value_cents": 100000}  # daily_rate_cents omitted
    res = api.create_equipment(payload, warehouse_manager_headers)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


# ─── entities / reservation_is_standby_defaults_false ─────────────────
def test_reservation_is_standby_defaults_false(api, warehouse_manager_headers):
    """PRD §3.2: "The optional flag `is_standby` marks a reservation as a standby line,
    which changes how it is priced (see §3.6) and defaults to false."

    Design: Corner/entities/reservation_is_standby_defaults_false
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment()
    order = new_order(cust["id"], ven["id"])

    # add_reservation with is_standby=None omits the field, exercising the server default.
    reservation = add_reservation(order["id"], led["id"], qty=1)
    assert reservation["is_standby"] is False
    assert reservation["status"] == "HELD"


# ─── validations / missing_role_header_returns_unauthenticated ────────
def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or names a role the system does not
    recognize, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    payload = create_order_payload("some-customer", "some-venue")
    res = api.create_order(payload, {})  # no X-User-Role header
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── validations / list_orders_invalid_limit_rejected ─────────────────
def test_list_orders_invalid_limit_rejected(api, account_manager_headers):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or a negative
    `offset`, is rejected with `ERR_PAGINATION_INVALID`."

    Design: Corner/validations/list_orders_invalid_limit_rejected
    """
    res = api.list_orders(account_manager_headers, params={"limit": 0})
    validate_error(res, "ERR_PAGINATION_INVALID", expected_status=400)


# ─── rbac / warehouse_manager_cannot_create_order_forbidden ───────────
def test_warehouse_manager_cannot_create_order(api, warehouse_manager_headers):
    """PRD §2.1: "When the header is present and valid but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/warehouse_manager_cannot_create_order_forbidden
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)

    res = api.create_order(create_order_payload(cust["id"], ven["id"]),
                           warehouse_manager_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ─── rbac / client_cannot_submit_coi_for_other_customers_order_forbidden ──
def test_client_cannot_submit_coi_for_other_customers_order(api):
    """PRD §2.1: "A `Client` who submits a certificate of insurance against an order
    owned by a different customer, or who reads a record belonging to another customer,
    is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/client_cannot_submit_coi_for_other_customers_order_forbidden
    """
    cust_a = new_customer(name="OwnerA", contact_email="oa@x.test",
                          credit_limit_cents=100_000_000)
    cust_b = new_customer(name="OtherB", contact_email="ob@x.test",
                          credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    order = new_order(cust_a["id"], ven["id"])  # owned by customer A

    res = api.create_coi(order["id"],
                         create_coi_payload(insurer="X", coverage_amount_cents=100000),
                         make_client_headers(cust_b["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ─── endpoints / list_reservations_by_order_and_equipment ─────────────
def test_list_reservations_by_order_and_equipment(api, warehouse_manager_headers):
    """PRD §2.3: "Unless a specific endpoint states otherwise, every list is returned
    sorted by `created_at` in ascending order."
    PRD §4 endpoint: "GET | `/equipment-reservations` | List / filter reservations".

    Design: Corner/endpoints/list_reservations_by_order_and_equipment
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment()
    order = new_order(cust["id"], ven["id"])
    reservation = add_reservation(order["id"], led["id"], qty=1)

    by_order, _ = validate_paginated(
        api.list_reservations(warehouse_manager_headers, params={"order_id": order["id"]}))
    assert any(r["id"] == reservation["id"] for r in by_order), \
        "reservation must be discoverable by order_id"

    by_equipment, _ = validate_paginated(
        api.list_reservations(warehouse_manager_headers, params={"equipment_id": led["id"]}))
    assert any(r["id"] == reservation["id"] for r in by_equipment), \
        "reservation must be discoverable by equipment_id"
