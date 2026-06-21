"""Entity creation/retrieval/defaults, computed fields, listing, and the
state-machine corner cases (invalid transitions, terminal lockdown, max-attempts).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    api_client,
    make_customer_headers,
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


def _delivery(customer_id, venue_id, ws="2026-07-20T00:00:00.000Z", we="2026-07-20T00:00:00.000Z"):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, fulfillment="DELIVERY", venue_id=venue_id,
                             event_start=ws, event_end=we), h))


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


# ─── Entities ───

def test_create_catalog_item_applies_defaults(api):
    """PRD §3.1: "The `multi_day_discount_pct` is a fractional discount applied to
    rental days beyond the first — for instance, 0.20 means days two onward are
    billed at 20% off — and it defaults to 0 and must lie between 0 and 0.90
    inclusive."
    PRD §3.1: "The `deposit_per_unit_cents` is the damage deposit charged per
    reserved unit, defaulting to 0 and never negative."
    PRD §3.1: "The `requires_coi` flag marks an item that may only be confirmed
    when the venue carries valid insurance (true for tents and bounce houses) and
    defaults to false. Upon creation the item's `status` is `ACTIVE`."

    POST with required fields only => 201; defaults applied.

    Design: Corner/entities/create_catalog_item_returns_201_with_defaults
    """
    resp = api_client.create_catalog_item(
        {"sku": "TABLE-6FT", "name": "6ft Table", "category": "TABLE",
         "total_units": 30, "daily_rate_cents": 500}, AGENT)
    item = validate_success(resp, 201)
    assert item["status"] == "ACTIVE", item["status"]
    assert item["multi_day_discount_pct"] == 0, item["multi_day_discount_pct"]
    assert item["deposit_per_unit_cents"] == 0, item["deposit_per_unit_cents"]
    assert item["requires_coi"] is False, item["requires_coi"]


def test_create_catalog_item_missing_required_field_rejected(api):
    """PRD §2.1: "any request whose body is structurally malformed — a missing
    required field, a value of the wrong type, or an enumerated field carrying a
    value outside its permitted set — is rejected with `ERR_VALIDATION` (HTTP 400)."

    Omitting daily_rate_cents (required, no default) => ERR_VALIDATION 400.

    Design: Corner/entities/create_catalog_item_missing_required_field_rejected
    """
    resp = api_client.create_catalog_item(
        {"sku": "BAD-1", "name": "Bad", "category": "TABLE", "total_units": 5}, AGENT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_create_catalog_item_invalid_category_enum_rejected(api):
    """PRD §2.1: "any request whose body is structurally malformed — a missing
    required field, a value of the wrong type, or an enumerated field carrying a
    value outside its permitted set — is rejected with `ERR_VALIDATION` (HTTP 400)."

    category 'SPACESHIP' outside {TENT,TABLE,CHAIR,LINEN,BOUNCE_HOUSE} =>
    ERR_VALIDATION 400.

    Design: Corner/entities/create_catalog_item_invalid_enum_category_rejected
    """
    resp = api_client.create_catalog_item(
        {"sku": "ENUM-1", "name": "X", "category": "SPACESHIP",
         "total_units": 5, "daily_rate_cents": 100}, AGENT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_get_catalog_item_not_found(api):
    """PRD §2.10: "the system validates the path identifiers from left to right and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the **first** identifier
    in the path that does not correspond to an existing resource."

    GET a non-existent catalog item id => ERR_NOT_FOUND 404.

    Design: Corner/entities/get_catalog_item_not_found
    """
    resp = api_client.get_catalog_item(NON_EXISTENT_UUID, AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_order_system_fields_stamped_by_server(api):
    """PRD §3.3: "A new order starts with `booking_status` `DRAFT`,
    `settlement_status` `UNSETTLED`, `version` 1, and — having no lines yet — a
    `weather_cancellable` flag of false."

    POST /orders stamps booking_status=DRAFT, settlement_status=UNSETTLED,
    version=1 regardless of any client-sent values.

    Design: Corner/entities/order_system_fields_generated_input_ignored
    """
    cust = _customer()
    h = make_customer_headers(cust["id"])
    resp = api_client.create_order(
        create_order_payload(cust["id"], booking_status="CONFIRMED", version=99), h)
    order = validate_success(resp, 201)
    assert order["booking_status"] == "DRAFT", order["booking_status"]
    assert order["settlement_status"] == "UNSETTLED", order["settlement_status"]
    assert order["version"] == 1, order["version"]


def test_rental_days_computed_inclusive(api):
    """PRD §3.3: "From the window the system computes `rental_days` as the inclusive
    whole-day span — the number of whole days from `event_start` to `event_end`
    counting both ends, equivalently the day-count difference plus one — which is
    always at least 1."

    event_start Jun1, event_end Jun3 => rental_days == 3 (inclusive, not 2).

    Design: Corner/entities/rental_days_computed_inclusive_span
    """
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-03T00:00:00.000Z")
    assert order["rental_days"] == 3, order["rental_days"]


def test_list_catalog_items_paginated_envelope(api):
    """PRD §2.3: "Each list response carries the pagination bookkeeping in the
    `meta` object of the envelope, exposing `limit`, `offset`, `total_count`, and
    `has_more`."

    Two items exist; list with limit=1 => array response with total_count 2 and
    has_more true.

    Design: Corner/entities/list_catalog_items_paginated_envelope
    """
    _item(sku="P-1", category="CHAIR", total_units=10, daily_rate_cents=100)
    _item(sku="P-2", category="TABLE", total_units=10, daily_rate_cents=100)
    data, meta = validate_paginated(api_client.list_catalog_items(AGENT, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]


# ─── State machines ───

def test_fulfill_from_draft_invalid_state(api):
    """PRD §3.5: "Fulfillment requires the order to be `CONFIRMED`, otherwise
    `ERR_INVALID_STATE`."

    Fulfilling a DRAFT order (never confirmed) => ERR_INVALID_STATE 409; stays DRAFT.

    Design: Corner/state_machines/fulfill_from_draft_invalid_state
    """
    item = _item(category="CHAIR", total_units=10, daily_rate_cents=200)
    cust = _customer()
    order = _will_call(cust["id"])
    _add_line(order["id"], item["id"], 1, cust["id"])
    resp = api_client.fulfill_order(order["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api_client.get_order(order["id"], AGENT), 200)
    assert after["booking_status"] == "DRAFT", after["booking_status"]


def test_cancel_returned_order_terminal_lockdown(api):
    """PRD §3.5: "`RETURNED` is a terminal booking state."
    PRD §3.5: "An order may be cancelled while it is either `DRAFT` or `CONFIRMED`,
    by the owning customer or by the system; a cancellation attempted from any
    other booking state is rejected with `ERR_INVALID_STATE`."

    Cancelling a RETURNED order => ERR_INVALID_STATE 409.

    Design: Corner/state_machines/cancel_returned_order_terminal_lockdown
    """
    item = _item(category="CHAIR", total_units=10, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust = _customer()
    order = _will_call(cust["id"])
    _add_line(order["id"], item["id"], 1, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    get_success_data(api_client.fulfill_order(order["id"], AGENT))
    get_success_data(api_client.return_order(order["id"], AGENT))
    h = make_customer_headers(cust["id"])
    resp = api_client.cancel_order(order["id"], {"expected_order_version": confirmed["version"]}, h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_approve_rejected_certificate_invalid_state(api):
    """PRD §3.2: "Rejecting a submitted certificate advances its `status`
    `SUBMITTED → REJECTED`, may carry an optional `reason`, and recomputes the
    venue's `coi_status`; rejection is permitted only from `SUBMITTED`, otherwise
    `ERR_INVALID_STATE`."
    PRD §3.2: "Approving a submitted certificate advances its `status` `SUBMITTED →
    APPROVED` and recomputes the venue's `coi_status`; approval is permitted only
    when the certificate is `SUBMITTED` (otherwise `ERR_INVALID_STATE`) and
    additionally requires that the `coverage_end` be on or after the
    `coverage_start`, failing which the approval is rejected with
    `ERR_INVALID_COVERAGE_WINDOW`."

    Approving a REJECTED (terminal) certificate => ERR_INVALID_STATE 409.

    Design: Corner/state_machines/approve_already_rejected_cert_invalid_state
    """
    cust = _customer()
    venue = _venue(cust["id"])
    h = make_customer_headers(cust["id"])
    cert = get_success_data(api_client.create_certificate(
        venue["id"], create_certificate_payload(
            coverage_start="2026-08-01T00:00:00.000Z", coverage_end="2026-08-31T00:00:00.000Z"), h))
    get_success_data(api_client.reject_certificate(venue["id"], cert["id"], AGENT, {"reason": "expired"}))
    resp = api_client.approve_certificate(venue["id"], cert["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_reschedule_after_three_attempts_blocked(api):
    """PRD §3.6: "It is additionally permitted only while the run's `attempt_count`
    is at most 2 — a third failure forbids any further reschedule, and a reschedule
    attempted beyond that is rejected with `ERR_MAX_ATTEMPTS_EXCEEDED`."

    After three FAILED attempts (attempt_count=3), reschedule => ERR_MAX_ATTEMPTS_EXCEEDED 422.

    Design: Corner/state_machines/reschedule_after_three_attempts_blocked
    """
    item = _item(category="CHAIR", total_units=10, daily_rate_cents=200, deposit_per_unit_cents=0)
    cust = _customer()
    venue = _venue(cust["id"])
    order = _delivery(cust["id"], venue["id"])
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    crew = _crew(name="Truck 25", turnaround_minutes=0)
    run = get_success_data(api_client.create_delivery_run(
        create_delivery_run_payload(order["id"], crew["id"], leg="DROP_OFF",
                                    window_start="2026-07-19T08:00:00.000Z",
                                    window_end="2026-07-19T09:00:00.000Z"), AGENT))
    # Fail -> reschedule -> fail -> reschedule -> fail (attempt_count now 3).
    get_success_data(api_client.attempt_delivery_run(run["id"], {"outcome": "FAILED"}, AGENT))
    get_success_data(api_client.reschedule_delivery_run(
        run["id"], {"window_start": "2026-07-19T10:00:00.000Z",
                    "window_end": "2026-07-19T11:00:00.000Z"}, AGENT))
    get_success_data(api_client.attempt_delivery_run(run["id"], {"outcome": "FAILED"}, AGENT))
    get_success_data(api_client.reschedule_delivery_run(
        run["id"], {"window_start": "2026-07-19T12:00:00.000Z",
                    "window_end": "2026-07-19T13:00:00.000Z"}, AGENT))
    get_success_data(api_client.attempt_delivery_run(run["id"], {"outcome": "FAILED"}, AGENT))
    resp = api_client.reschedule_delivery_run(
        run["id"], {"window_start": "2026-07-19T14:00:00.000Z",
                    "window_end": "2026-07-19T15:00:00.000Z"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_MAX_ATTEMPTS_EXCEEDED.value, 422)
    after = validate_success(api_client.get_delivery_run(run["id"], AGENT), 200)
    assert after["attempt_count"] == 3, after["attempt_count"]
