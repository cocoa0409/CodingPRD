"""CRUD surface (event defaults, computed zero totals, not-found, required/typed
fields, listing, payment immutability), reverse-reachability listings, the
logical clock, RBAC denials, optimistic-concurrency guards, and immediate-
consistency cascades visible in a single response.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_event, create_function_room, add_schedule_item,
    get_event, get_event_version, record_payment,
    setup_confirmed_event,
    TEST_USERS,
)
from test_helpers.api_client import api_client

_SALES = TEST_USERS["sales_manager_headers"]
_CAPTAIN = TEST_USERS["banquet_captain_headers"]
_CLERK = TEST_USERS["accounting_clerk_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Corner: entities (creation, defaults, computed, not-found, validation)
# ===========================================================================

def test_create_event_returns_201_with_defaults_applied(api):
    """PRD §3.2: "Four pricing rates may optionally be supplied at creation, each defaulting
    and bounded as follows: `overset_pct`, the kitchen overset fraction the venue agrees to
    prepare above the guarantee, defaults to 0.05 and must be between 0 and 0.10 inclusive;
    `service_charge_pct`, the taxable service-charge rate, defaults to 0.22 and must be
    between 0 and 0.30 inclusive; `gratuity_pct`, the non-taxable gratuity rate, defaults to
    0.0 and must be between 0 and 0.25 inclusive; and `sales_tax_pct`, the sales-tax rate,
    defaults to 0.08 and must be between 0 and 0.15 inclusive."
    PRD §3.2: "A new event begins in `INQUIRY` status with `guarantee_count` and
    `actual_attendance` both null"

    Design: Corner/entities/create_event_returns_201_with_defaults_applied
    """
    ev = validate_success(api.create_event(
        {"account_name": "Default Co", "event_date": "2026-09-01",
         "setup_style": "ROUNDS", "expected_attendance": 80}, _SALES), expected_status=201)
    assert ev["status"] == "INQUIRY", f"got {ev['status']}"
    assert ev["overset_pct"] == 0.05, f"got {ev['overset_pct']}"
    assert ev["service_charge_pct"] == 0.22, f"got {ev['service_charge_pct']}"
    assert ev["gratuity_pct"] == 0.0, f"got {ev['gratuity_pct']}"
    assert ev["sales_tax_pct"] == 0.08, f"got {ev['sales_tax_pct']}"
    assert ev["guarantee_count"] is None, f"got {ev['guarantee_count']}"


def test_get_event_returns_zero_totals_on_empty_children(api):
    """PRD §3.2: "A new event begins in `INQUIRY` status with `guarantee_count` and
    `actual_attendance` both null, and with all of its computed totals derived from an empty
    set of children, which evaluate to zero."

    Design: Corner/entities/get_event_returns_zero_totals_on_empty_children
    """
    event = create_event(account_name="Empty Co", event_date="2026-09-02",
                         setup_style="THEATER", expected_attendance=10)
    ev = get_event(event["id"])
    assert ev["estimated_total_cents"] == 0, f"got {ev['estimated_total_cents']}"
    assert ev["paid_to_date_cents"] == 0, f"got {ev['paid_to_date_cents']}"
    assert ev["balance_due_cents"] == 0, f"got {ev['balance_due_cents']}"


def test_get_nonexistent_event_returns_not_found(api):
    """PRD §2.8: "every resource named in the path is resolved left to right — the event
    before any booking, link, schedule item, or payment nested beneath it — and every
    foreign key carried in the body (a `function_room_id` or a `hotel_room_block_id`) must
    resolve; any unresolved reference yields `ERR_NOT_FOUND` (HTTP 404), reported against
    the first missing identifier encountered."

    Design: Corner/entities/get_nonexistent_event_returns_not_found
    """
    resp = api.get_event("00000000-0000-4000-8000-000000000000", _SALES)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_event_missing_required_field_invalid_request(api):
    """PRD §2.8: "For write operations, the request body is then checked: it must be
    present, all required fields supplied with the correct types, and every enum-typed value
    must fall within its declared domain; a malformed, incomplete, mistyped, or out-of-range
    body yields `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_event_missing_required_field_returns_invalid_request
    """
    resp = api.create_event(
        {"account_name": "NoStyle Co", "event_date": "2026-09-03",
         "expected_attendance": 30}, _SALES)  # setup_style omitted (required, no default)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_event_bad_enum_setup_style_invalid_request(api):
    """PRD §2.8: "every enum-typed value must fall within its declared domain; a malformed,
    incomplete, mistyped, or out-of-range body yields `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "The `setup_style` is one of `ROUNDS`, `THEATER`, `CLASSROOM`, or `RECEPTION`"

    Design: Corner/entities/create_event_bad_enum_setup_style_returns_invalid_request
    """
    resp = api.create_event(
        {"account_name": "BadEnum Co", "event_date": "2026-09-04",
         "setup_style": "BANQUET", "expected_attendance": 30}, _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_event_overset_out_of_range_returns_validation_range(api):
    """PRD §2.8: "When a body field carries a percentage — `overset_pct`,
    `service_charge_pct`, `gratuity_pct`, or `sales_tax_pct` — that falls outside its
    permitted range, the request is rejected with `ERR_VALIDATION_RANGE` (HTTP 422)."
    PRD §3.2: "`overset_pct`, the kitchen overset fraction the venue agrees to prepare above
    the guarantee, defaults to 0.05 and must be between 0 and 0.10 inclusive"

    Design: Corner/entities/create_event_overset_out_of_range_returns_validation_range
    """
    resp = api.create_event(
        {"account_name": "Range Co", "event_date": "2026-09-05", "setup_style": "ROUNDS",
         "expected_attendance": 30, "overset_pct": 0.5}, _SALES)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_RANGE.value)


def test_create_booking_with_unknown_function_room_not_found(api):
    """PRD §2.8: "every foreign key carried in the body (a `function_room_id` or a
    `hotel_room_block_id`) must resolve; any unresolved reference yields `ERR_NOT_FOUND`
    (HTTP 404), reported against the first missing identifier encountered."

    Design: Corner/entities/create_booking_with_unknown_function_room_returns_not_found
    """
    event = create_event(account_name="FK Co", event_date="2026-09-06",
                         setup_style="THEATER", expected_attendance=30)
    resp = api.create_booking(
        event["id"], {"function_room_id": "11111111-1111-4111-8111-111111111111",
                      "start_utc": "2026-09-06T18:00:00Z", "end_utc": "2026-09-06T22:00:00Z",
                      "expected_event_version": event["version"]}, _SALES)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_events_paginated_envelope(api):
    """PRD §2.3: "Every paginated list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_events_paginated_envelope
    """
    create_event(account_name="List A", event_date="2026-09-07",
                 setup_style="ROUNDS", expected_attendance=10)
    create_event(account_name="List B", event_date="2026-09-08",
                 setup_style="ROUNDS", expected_attendance=10)
    data, meta = validate_paginated(api.list_events(_SALES, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert len(data) == 1, f"limit=1 should return one row, got {len(data)}"
    assert meta["has_more"] is True, f"got {meta['has_more']}"


def test_payment_is_immutable_no_version_field(api):
    """PRD §2.4: "A **Payment** is an immutable, append-only event-log record: it carries
    only an `id` and a `created_at`, and has neither an `updated_at` nor a `version` field."
    PRD §2.4: "The only mutation a payment ever undergoes is being voided, which flips a
    status flag rather than rewriting the record."

    Design: Corner/entities/payment_is_immutable_no_version_field
    """
    event = create_event(account_name="Immut Co", event_date="2026-09-09",
                         setup_style="THEATER", expected_attendance=20,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    add_schedule_item(event["id"], 50000, label="Deposit", due_date="2026-08-01")
    pay = validate_success(api.create_payment(
        event["id"], {"amount_cents": 50000, "method": "CARD",
                      "expected_event_version": event["version"]}, _CLERK), expected_status=201)
    assert pay["status"] == "APPLIED", f"got {pay['status']}"
    assert "version" not in pay, "Payment must not expose a version field"
    assert "updated_at" not in pay, "Payment must not expose an updated_at field"


# ===========================================================================
# Corner: endpoints (reverse-reachability listing, clock)
# ===========================================================================

def test_list_bookings_by_function_room_filtered(api):
    """PRD §3.1: "Both function rooms and hotel room blocks are addressable on their own and
    are also reverse-navigable: the bookings made against a particular function room can be
    listed"

    Design: Corner/endpoints/list_bookings_by_function_room_filtered
    """
    room = create_function_room(name="Salon T", max_capacity=200,
                                turnover_buffer_minutes=0, hourly_rental_cents=0)
    event = create_event(account_name="Disc Co", event_date="2029-05-01",
                         setup_style="THEATER", expected_attendance=40)
    booking = get_success_data(api.create_booking(
        event["id"], {"function_room_id": room["id"], "start_utc": "2029-05-01T18:00:00Z",
                      "end_utc": "2029-05-01T22:00:00Z",
                      "expected_event_version": event["version"]}, _SALES))
    data, _meta = validate_paginated(api.list_function_room_bookings(room["id"], _SALES))
    assert len(data) == 1, f"one booking on the room, got {len(data)}"
    assert data[0]["id"] == booking["id"], f"got {data[0]['id']}"


def test_clock_set_echoes_instant(api):
    """PRD §2.9: "An administrative test-driving capability sets the clock to a supplied
    instant carried in the `to_iso8601` field, and the response echoes the resulting
    `current_utc`."

    Design: Corner/endpoints/clock_default_time_before_any_set
    """
    res = validate_success(api.set_clock({"to_iso8601": "2030-01-01T00:00:00Z"}, _ADMIN))
    assert res["current_utc"] == "2030-01-01T00:00:00Z", f"got {res['current_utc']}"


# ===========================================================================
# Corner: rbac
# ===========================================================================

def test_banquet_captain_cannot_create_event(api):
    """PRD §2.1: "A `BanquetCaptain` owns guarantee locking and post-event actualization,
    the day-of operations, but may not create inquiries or edit pricing lines."
    PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation under the access-control matrix in Section 4, the
    request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/banquet_captain_cannot_create_event
    """
    resp = api.create_event(
        {"account_name": "Wrong Role", "event_date": "2029-09-01",
         "setup_style": "THEATER", "expected_attendance": 30}, _CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_sales_manager_cannot_lock_guarantee(api):
    """PRD §2.1: "A `BanquetCaptain` owns guarantee locking and post-event actualization"
    PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation under the access-control matrix in Section 4, the
    request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/sales_manager_cannot_lock_guarantee
    """
    from test_helpers import setup_definite_event
    event_definite, _room, _booking = setup_definite_event(
        event_overrides={"account_name": "RBAC Co", "event_date": "2029-10-01",
                         "setup_style": "THEATER", "expected_attendance": 40,
                         "service_charge_pct": 0.0, "gratuity_pct": 0.0, "sales_tax_pct": 0.0},
        room_overrides={"name": "Salon V", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2029-10-01T18:00:00Z", end_utc="2029-10-01T22:00:00Z",
    )
    add_schedule_item(event_definite["id"], 50000, label="Deposit", due_date="2029-09-01")
    v = get_event_version(event_definite["id"])
    record_payment(event_definite["id"], 50000, v, method="WIRE")
    # lock-guarantee is a BanquetCaptain exclusive; SalesManager is forbidden.
    resp = api.lock_guarantee(event_definite["id"], {"guarantee_count": 40}, _SALES)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    assert get_event(event_definite["id"])["status"] == "DEFINITE"


def test_accounting_clerk_cannot_create_booking(api):
    """PRD §2.1: "A `SalesManager` owns the event sales lifecycle: inquiry creation, space
    holds, room bookings, menu and service lines, and cancellation, acting as the booking
    author."
    PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation under the access-control matrix in Section 4, the
    request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/accounting_clerk_cannot_create_booking
    """
    room = create_function_room(name="Salon W", max_capacity=300,
                                turnover_buffer_minutes=0, hourly_rental_cents=0)
    event = create_event(account_name="Peer Co", event_date="2029-11-01",
                         setup_style="THEATER", expected_attendance=40)
    resp = api.create_booking(
        event["id"], {"function_room_id": room["id"], "start_utc": "2029-11-01T18:00:00Z",
                      "end_utc": "2029-11-01T22:00:00Z",
                      "expected_event_version": event["version"]}, _CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_unknown_role_returns_unauthenticated(api, unknown_role_headers):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a known
    role, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.list_events(unknown_role_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers (OCC) + consistency_model
# ===========================================================================

def test_occ_stale_event_version_on_booking_create(api):
    """PRD §2.7: "A new booking changes the event's room-hold composition; if another writer
    has advanced the event's `version` since the client last read it, the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412), so a client cannot append a booking to event state
    it has not observed."
    PRD §2.7: "A successful booking create increments the event's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_event_version_on_booking_create
    """
    room = create_function_room(name="Salon X", max_capacity=300,
                                turnover_buffer_minutes=0, hourly_rental_cents=0)
    event = create_event(account_name="OCC Co", event_date="2029-12-01",
                         setup_style="THEATER", expected_attendance=40)
    v0 = event["version"]
    # First create bumps version to v0+1.
    get_success_data(api.create_booking(
        event["id"], {"function_room_id": room["id"], "start_utc": "2029-12-01T18:00:00Z",
                      "end_utc": "2029-12-01T20:00:00Z", "expected_event_version": v0}, _SALES))
    # Second create still carrying v0 is stale.
    resp = api.create_booking(
        event["id"], {"function_room_id": room["id"], "start_utc": "2029-12-01T21:00:00Z",
                      "end_utc": "2029-12-01T23:00:00Z", "expected_event_version": v0}, _SALES)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_correct_event_version_on_payment_succeeds(api):
    """PRD §2.7: "Likewise, when an `AccountingClerk` records a payment on an event, the
    request must carry `expected_event_version` equal to that event's current `version`."
    PRD §2.7: "A successful payment record increments the event's `version` by one."
    PRD §3.8: "Once recorded, the system recomputes the event's `paid_to_date_cents`, re-runs
    the allocation waterfall, and recomputes `balance_due_cents`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_event_version_on_payment_succeeds_and_bumps
    """
    event = create_event(account_name="OCC2 Co", event_date="2030-01-15",
                         setup_style="THEATER", expected_attendance=30,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    v0 = event["version"]
    validate_success(api.create_payment(
        event["id"], {"amount_cents": 25000, "method": "ACH",
                      "expected_event_version": v0}, _CLERK), expected_status=201)
    ev = get_event(event["id"])
    assert ev["paid_to_date_cents"] == 25000, f"got {ev['paid_to_date_cents']}"


def test_occ_stale_payment_after_prior_payment_bumped_version(api):
    """PRD §2.7: "Because each applied payment re-runs the payment allocation and shifts the
    outstanding balance, a payment carrying a stale event version is rejected with
    `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the current balance
    before paying again. A successful payment record increments the event's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/stale_occ_payment_after_prior_payment_bumped_version
    """
    event = create_event(account_name="OCC3 Co", event_date="2030-02-01",
                         setup_style="THEATER", expected_attendance=30,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    v0 = event["version"]
    validate_success(api.create_payment(
        event["id"], {"amount_cents": 10000, "method": "CARD",
                      "expected_event_version": v0}, _CLERK), expected_status=201)
    # Second payment still carrying v0 (prior payment bumped version) is stale.
    resp = api.create_payment(
        event["id"], {"amount_cents": 10000, "method": "CARD",
                      "expected_event_version": v0}, _CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_lock_guarantee_cascade_visible_in_same_response(api):
    """PRD §3.5: "On success the system sets the event's `guarantee_count` to the supplied
    value, recomputes `billable_count` (now the oversetted guarantee), recomputes
    `estimated_total_cents` using the estimate variant of the charge rollup, and — because
    the per-person headcount has changed — recomputes the `extended_cents` of every
    `PER_PERSON` menu line on the event as a cascade."
    PRD §2.5: "These reconciliations are immediate and synchronous: the moment a triggering
    operation completes, all affected totals, allocations, and committed-room counts reflect
    the new reality."

    Design: Corner/consistency_model/lock_guarantee_cascade_visible_in_same_response
    """
    confirmed, _room, _booking, menu_ids = setup_confirmed_event(
        event_overrides={"account_name": "Immed Co", "event_date": "2030-04-01",
                         "setup_style": "THEATER", "expected_attendance": 100,
                         "overset_pct": 0.05, "service_charge_pct": 0.0,
                         "gratuity_pct": 0.0, "sales_tax_pct": 0.0},
        room_overrides={"name": "Salon Y", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2030-04-01T18:00:00Z", end_utc="2030-04-01T22:00:00Z",
        menu_lines=[{"name": "Plated", "pricing_mode": "PER_PERSON", "unit_price_cents": 10000}],
        guarantee_count=120, deposit_amount_cents=50000,
    )
    # lock-guarantee response (returned by the fixture) reflects the cascade immediately.
    assert confirmed["billable_count"] == 126, (
        f"ceil(120*1.05)=126 visible in the same response, got {confirmed['billable_count']}"
    )
    assert confirmed["estimated_total_cents"] == 1260000, (
        f"10000*126=1260000, got {confirmed['estimated_total_cents']}"
    )
    lines = get_success_data(api.list_menu_lines(confirmed["id"], _SALES))
    ml = next(l for l in lines if l["id"] == menu_ids[0])
    assert ml["extended_cents"] == 1260000, f"got {ml['extended_cents']}"
