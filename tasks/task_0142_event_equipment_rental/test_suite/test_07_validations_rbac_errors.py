"""Single-failure validations, error-catalog coverage, RBAC denial/ownership, and
the cross-cutting OCC / cascade / FK-integrity corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    api_client,
    make_customer_headers,
    anonymous_headers,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_catalog_item_payload,
    create_customer_payload,
    create_venue_payload,
    create_certificate_payload,
    create_order_payload,
    add_line_payload,
    create_crew_payload,
    create_delivery_run_payload,
    get_success_data,
)

AGENT = TEST_USERS["rental_agent_headers"]
ADJUSTER = TEST_USERS["deposit_adjuster_headers"]


def _item(**ov):
    return get_success_data(api_client.create_catalog_item(create_catalog_item_payload(**ov), AGENT))


def _customer():
    return get_success_data(api_client.create_customer(create_customer_payload(), AGENT))


def _venue(customer_id, zone="LOCAL"):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_venue(
        create_venue_payload(customer_id, delivery_zone=zone), h))


def _will_call(customer_id, ws="2026-06-01T00:00:00.000Z", we="2026-06-01T00:00:00.000Z"):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, event_start=ws, event_end=we), h))


def _delivery(customer_id, venue_id):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, fulfillment="DELIVERY", venue_id=venue_id,
                             event_start="2026-07-25T00:00:00.000Z",
                             event_end="2026-07-25T00:00:00.000Z"), h))


def _add_line(order_id, item_id, qty, customer_id):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.add_line(order_id, add_line_payload(item_id, qty), h))


def _confirm_ok(order_id, customer_id):
    h = make_customer_headers(customer_id)
    cur = get_success_data(api_client.get_order(order_id, h))
    return validate_success(
        api_client.confirm_order(order_id, {"expected_order_version": cur["version"]}, h), 200)


def _crew(**ov):
    return get_success_data(api_client.create_crew(create_crew_payload(**ov), AGENT))


def _returned_will_call(item, qty):
    cust = _customer()
    order = _will_call(cust["id"])
    _add_line(order["id"], item["id"], qty, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    get_success_data(api_client.fulfill_order(order["id"], AGENT))
    returned = get_success_data(api_client.return_order(order["id"], AGENT))
    return cust, returned


# ─── Validations (single-failure) ───

def test_confirm_empty_order_rejected(api):
    """PRD §3.4: "the system requires that the order hold at least one line; a
    confirmation on an order with zero lines is rejected with `ERR_ORDER_EMPTY`."

    Design: Corner/validations/confirm_empty_order_rejected
    """
    cust = _customer()
    order = _will_call(cust["id"])
    h = make_customer_headers(cust["id"])
    resp = api_client.confirm_order(order["id"], {"expected_order_version": order["version"]}, h)
    validate_error(resp, ApiErrorId.ERR_ORDER_EMPTY.value, 422)


def test_create_order_invalid_event_window_rejected(api):
    """PRD §3.3: "The event window must be well-formed: the `event_end` must be on
    or after the `event_start`, otherwise the order is rejected with
    `ERR_INVALID_EVENT_WINDOW`."

    event_end before event_start => ERR_INVALID_EVENT_WINDOW 422.

    Design: Corner/validations/create_order_invalid_event_window_rejected
    """
    cust = _customer()
    h = make_customer_headers(cust["id"])
    resp = api_client.create_order(
        create_order_payload(cust["id"], event_start="2026-06-05T00:00:00.000Z",
                             event_end="2026-06-01T00:00:00.000Z"), h)
    validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_WINDOW.value, 422)


def test_delivery_order_missing_venue_rejected(api):
    """PRD §3.3: "A delivery order must name a venue that belongs to the ordering
    customer; a delivery order missing a valid customer-owned `venue_id` is
    rejected with `ERR_VENUE_REQUIRED`, a check applied both when the order is
    created and again at confirmation time."

    DELIVERY order created with no venue_id => ERR_VENUE_REQUIRED 422.

    Design: Corner/validations/delivery_order_missing_venue_rejected
    """
    cust = _customer()
    h = make_customer_headers(cust["id"])
    resp = api_client.create_order(
        create_order_payload(cust["id"], fulfillment="DELIVERY",
                             event_start="2026-06-01T00:00:00.000Z",
                             event_end="2026-06-01T00:00:00.000Z"), h)
    validate_error(resp, ApiErrorId.ERR_VENUE_REQUIRED.value, 422)


def test_certificate_invalid_coverage_window_rejected(api):
    """PRD §3.2: "This same coverage-window sanity check — `coverage_end` not
    earlier than `coverage_start` — is also enforced at submission time."

    coverage_end before coverage_start at submission => ERR_INVALID_COVERAGE_WINDOW 422.

    Design: Corner/validations/cert_invalid_coverage_window_rejected
    """
    cust = _customer()
    venue = _venue(cust["id"])
    h = make_customer_headers(cust["id"])
    resp = api_client.create_certificate(
        venue["id"], create_certificate_payload(
            coverage_start="2026-08-31T00:00:00.000Z",
            coverage_end="2026-08-01T00:00:00.000Z"), h)
    validate_error(resp, ApiErrorId.ERR_INVALID_COVERAGE_WINDOW.value, 422)


def test_weather_cancel_without_warning_event_rejected(api):
    """PRD §3.9: "If no such matching `WARNING` event exists, the request is
    rejected with `ERR_NO_WEATHER_EVENT`."

    Confirmed order, no weather events posted => weather-cancel ERR_NO_WEATHER_EVENT 422.

    Design: Corner/validations/weather_cancel_without_warning_event_rejected
    """
    item = _item(category="CHAIR", total_units=10, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust = _customer()
    order = _will_call(cust["id"])
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    h = make_customer_headers(cust["id"])
    resp = api_client.weather_cancel_order(order["id"], h)
    validate_error(resp, ApiErrorId.ERR_NO_WEATHER_EVENT.value, 422)


def test_add_line_to_confirmed_order_rejected(api):
    """PRD §3.3: "Adding a line is allowed only while the order's `booking_status`
    is `DRAFT`; an attempt to add a line to a non-draft order is rejected with
    `ERR_LINE_NOT_DRAFT`, and adding a line that references a retired item is
    rejected with `ERR_INACTIVE_ITEM`."

    Adding a line to a CONFIRMED order => ERR_LINE_NOT_DRAFT 409.

    Design: Corner/validations/add_line_to_confirmed_order_rejected
    """
    item = _item(category="CHAIR", total_units=10, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust = _customer()
    order = _will_call(cust["id"])
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    h = make_customer_headers(cust["id"])
    resp = api_client.add_line(order["id"], add_line_payload(item["id"], 1), h)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_DRAFT.value, 409)


def test_add_line_for_retired_item_rejected(api):
    """PRD §3.1: "Once retired, the item may no longer back a new order line: any
    attempt to add a line referencing a retired item is rejected with
    `ERR_INACTIVE_ITEM`, while lines already in a `RESERVED` state are entirely
    unaffected by the retirement."

    Item retired via the retire endpoint, then add line => ERR_INACTIVE_ITEM 422.

    Design: Corner/validations/add_line_for_retired_item_rejected
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200, deposit_per_unit_cents=0)
    get_success_data(api_client.retire_catalog_item(item["id"], AGENT))
    cust = _customer()
    order = _will_call(cust["id"])
    h = make_customer_headers(cust["id"])
    resp = api_client.add_line(order["id"], add_line_payload(item["id"], 1), h)
    validate_error(resp, ApiErrorId.ERR_INACTIVE_ITEM.value, 422)


# ─── Errors ───

def test_confirm_stale_version_rejected(api):
    """PRD §2.11: "A prior writer may have added or removed a line — which
    legitimately bumps the order's `version` and changes the availability and
    insurance picture — so a confirmation whose `expected_order_version` is older
    than the order's current `version` is acting on a stale view and is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Add one line (capture version), add a second line (version advances), then
    confirm with the pre-second-add version => ERR_STALE_VERSION 412.

    Design: Corner/errors/confirm_stale_version_returns_412
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust = _customer()
    order = _will_call(cust["id"])
    h = make_customer_headers(cust["id"])
    line1 = validate_success(api_client.add_line(order["id"], add_line_payload(item["id"], 1), h), 201)
    stale_version = line1["version"]
    # Second line bumps the order version, making stale_version outdated.
    get_success_data(api_client.add_line(order["id"], add_line_payload(item["id"], 1), h))
    resp = api_client.confirm_order(order["id"], {"expected_order_version": stale_version}, h)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_forfeit_exceeds_held_rejected(api):
    """PRD §3.8: "The `forfeit_amount_cents` must not exceed the current held
    balance; a forfeiture larger than what is held is rejected with
    `ERR_FORFEIT_EXCEEDS_HELD`."

    RETURNED order with held 1000; forfeit 1500 (> held) => ERR_FORFEIT_EXCEEDS_HELD 422.

    Design: Corner/errors/forfeit_exceeds_held_returns_422
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=200, requires_coi=False)
    cust, returned = _returned_will_call(item, 5)
    resp = api_client.settle_deposit(
        returned["id"],
        {"disposition": "FORFEIT", "forfeit_amount_cents": 1500,
         "expected_order_version": returned["version"], "reason": "over"},
        ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_FORFEIT_EXCEEDS_HELD.value, 422)


def test_return_before_pickup_completed_rejected(api):
    """PRD §3.5: "For a `DELIVERY` order, return additionally requires that the
    pickup run for the order has reached `COMPLETED`, failing which it is rejected
    with `ERR_DELIVERY_NOT_COMPLETED`."

    DELIVERY order FULFILLED (drop-off completed) but PICK_UP run still SCHEDULED;
    return => ERR_DELIVERY_NOT_COMPLETED 409.

    Design: Corner/errors/return_before_pickup_completed_returns_409
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust = _customer()
    venue = _venue(cust["id"])
    order = _delivery(cust["id"], venue["id"])
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    crew = _crew(name="Truck 42", turnaround_minutes=0)
    drop = get_success_data(api_client.create_delivery_run(
        create_delivery_run_payload(order["id"], crew["id"], leg="DROP_OFF",
                                    window_start="2026-07-25T08:00:00.000Z",
                                    window_end="2026-07-25T09:00:00.000Z"), AGENT))
    get_success_data(api_client.attempt_delivery_run(drop["id"], {"outcome": "SUCCESS"}, AGENT))
    get_success_data(api_client.fulfill_order(order["id"], AGENT))
    get_success_data(api_client.create_delivery_run(
        create_delivery_run_payload(order["id"], crew["id"], leg="PICK_UP",
                                    window_start="2026-07-26T08:00:00.000Z",
                                    window_end="2026-07-26T09:00:00.000Z"), AGENT))
    resp = api_client.return_order(order["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_COMPLETED.value, 409)


# ─── RBAC ───

def test_customer_cannot_create_catalog_item(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Customer calling POST /catalog-items (RentalAgent-only) => ERR_UNAUTHORIZED 403.

    Design: Corner/rbac/customer_cannot_create_catalog_item
    """
    cust = _customer()
    h = make_customer_headers(cust["id"])
    resp = api_client.create_catalog_item(
        create_catalog_item_payload(sku="X-1", category="CHAIR", total_units=5,
                                    daily_rate_cents=100), h)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_rental_agent_cannot_settle_deposit(api):
    """PRD §2.1: "Critically, a rental agent **cannot** settle deposits — that
    authority is withheld to preserve segregation of duties."

    RentalAgent calling POST /orders/{id}/deposit/settle => ERR_UNAUTHORIZED 403.

    Design: Corner/rbac/rental_agent_cannot_settle_deposit_segregation
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200, deposit_per_unit_cents=100)
    cust, returned = _returned_will_call(item, 5)
    resp = api_client.settle_deposit(
        returned["id"],
        {"disposition": "RELEASE", "expected_order_version": returned["version"]},
        AGENT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_customer_cannot_act_on_other_customers_order(api):
    """PRD §2.1: "a `Customer` may act only on venues and orders whose
    `customer_id` equals their own `X-User-ID`, and any attempt by a customer to
    mutate an order or venue they do not own is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Customer B confirming Customer A's order => ERR_NOT_RESOURCE_OWNER 403.

    Design: Corner/rbac/customer_cannot_act_on_other_customers_order
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust_a = _customer()
    cust_b = _customer()
    order = _will_call(cust_a["id"])
    line = _add_line(order["id"], item["id"], 1, cust_a["id"])
    resp = api_client.confirm_order(
        order["id"], {"expected_order_version": line["version"]},
        make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Request with no role/id headers => ERR_UNAUTHENTICATED 401.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api_client.create_catalog_item(
        create_catalog_item_payload(sku="NOAUTH", category="CHAIR", total_units=5,
                                    daily_rate_cents=100), anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ─── Cross-cutting layers ───

def test_order_version_increments_on_add_line(api):
    """PRD §2.4: "The `version` on a `RentalOrder` begins at 1 when the order is
    created and increases by exactly 1 on every mutation of that order, including
    mutations driven by cascades rather than by a direct client call."
    PRD §2.4: "Adding or removing a line, confirming, fulfilling, returning,
    cancelling, weather-cancelling, and settling the deposit each advance the
    order's `version` by one."

    Create order (version 1); add one line => version 2.

    Design: Corner/cross_cutting_complexity_layers/order_version_increments_on_each_mutation
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust = _customer()
    order = _will_call(cust["id"])
    assert order["version"] == 1, order["version"]
    _add_line(order["id"], item["id"], 1, cust["id"])
    refreshed = get_success_data(api_client.get_order(order["id"], make_customer_headers(cust["id"])))
    assert refreshed["version"] == 2, refreshed["version"]


def test_add_line_for_nonexistent_item_not_found(api):
    """PRD §2.10: "the system validates the path identifiers from left to right and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the **first** identifier
    in the path that does not correspond to an existing resource."
    PRD §2.10: "This existence check precedes any business-rule evaluation."

    Add a line whose item_id references no CatalogItem => ERR_NOT_FOUND 404.

    Design: Corner/cross_cutting_complexity_layers/fk_order_line_references_existing_item
    """
    cust = _customer()
    order = _will_call(cust["id"])
    h = make_customer_headers(cust["id"])
    resp = api_client.add_line(order["id"], add_line_payload(NON_EXISTENT_UUID, 1), h)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_list_order_lines_returns_all_lines(api):
    """PRD §2.3: "Each list response carries the pagination bookkeeping in the
    `meta` object of the envelope, exposing `limit`, `offset`, `total_count`, and
    `has_more`."

    An order with two lines: GET /orders/{id}/lines returns an array with
    total_count 2.

    Design: Corner/cross_cutting_complexity_layers/list_order_lines_reverse_reachability
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust = _customer()
    order = _will_call(cust["id"])
    _add_line(order["id"], item["id"], 1, cust["id"])
    _add_line(order["id"], item["id"], 2, cust["id"])
    h = make_customer_headers(cust["id"])
    data, meta = validate_paginated(api_client.list_lines(order["id"], h))
    assert meta["total_count"] == 2, meta["total_count"]
