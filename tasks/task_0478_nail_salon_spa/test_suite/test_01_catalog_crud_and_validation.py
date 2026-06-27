"""Catalogue CRUD, defaults, required fields, type constraints, FK existence,
computed end_at, system-field handling, and list-envelope shape."""
from datetime import datetime, timezone

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_client, assert_station, assert_technician, assert_appointment,
    create_client_payload, create_menu_item_payload, create_technician_payload,
    create_appointment_payload, create_station_payload,
    TEST_USERS, NON_EXISTENT_UUID,
    make_station, make_menu_item, make_add_on, make_technician, make_client,
    book_appointment, attach_add_on, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_create_client_returns_201_with_defaults(api):
    """PRD §3.4: "The system maintains four computed fields on every client: a
    `loyalty_points_balance` of redeemable points (defaulting to 0), an
    `active_no_show_strikes` rolling count of unexpired strikes (defaulting to 0),
    a `deposit_required` flag (defaulting to false), and a `last_no_show_at`
    timestamp marking the most recent no-show (null until one occurs)."

    Design: Corner/entities/create_client_returns_201_with_defaults
    """
    res = api.create_client(create_client_payload(full_name="Ada Lovelace"), FRONT_DESK)
    client = validate_success(res, expected_status=201)
    assert_client(client)
    assert client["loyalty_points_balance"] == 0
    assert client["active_no_show_strikes"] == 0
    assert client["deposit_required"] is False


def test_get_technician_not_found_returns_404(api):
    """PRD §2.6: "the first identifier in the path that does not resolve to an
    existing resource produces `ERR_NOT_FOUND` before any later identifier or any
    body field is examined."

    Design: Corner/entities/get_technician_not_found_returns_404
    """
    res = api.get_technician(NON_EXISTENT_UUID, MANAGER)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_menu_item_missing_required_field_returns_invalid_request(api):
    """PRD §2.11: "the request body's structural well-formedness is checked:
    required fields present, enum values legal, integers within their declared
    ranges, and `start_at` parsing as an ISO 8601 instant, failing which
    `ERR_INVALID_REQUEST` is returned."
    PRD §3.3: "a `base_price_cents` list price (a non-negative integer)."

    Design: Corner/entities/create_menu_item_missing_required_field_returns_invalid_request
    """
    payload = create_menu_item_payload()
    del payload["base_price_cents"]
    res = api.create_menu_item(payload, MANAGER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_station_default_requires_autoclave_true(api):
    """PRD §3.2: "a `requires_autoclave` boolean that defaults to true. A new
    station's derived `sanitation_status` begins `DIRTY` until a passing
    sterilization cycle is logged against it."

    Design: Corner/entities/create_station_default_requires_autoclave_true
    """
    payload = create_station_payload()
    payload.pop("requires_autoclave", None)
    res = api.create_station(payload, MANAGER)
    station = validate_success(res, expected_status=201)
    assert_station(station)
    assert station["requires_autoclave"] is True
    assert station["sanitation_status"] == "DIRTY"


def test_appointment_end_at_computed_from_duration_and_addons(api):
    """PRD §3.5: "The appointment's window end, `end_at`, is computed as the
    `start_at` plus the service's `duration_minutes` plus the sum of the
    `extra_minutes` of any attached add-ons, expressed as a half-open interval
    that includes the start instant and excludes the end instant."
    PRD §3.5: "Attaching recomputes the appointment's `end_at` and increments the
    appointment's `version` by one."

    Design: Corner/entities/appointment_end_at_computed_from_duration_and_addons
    """
    set_clock("2026-07-01T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(duration_minutes=45, base_price_cents=4500,
                          requires_sterile_station=False)
    addon = make_add_on(price_cents=1500, extra_minutes=10)
    tech = make_technician(station["id"])
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-07-01T13:00:00Z")
    attach_add_on(appt["id"], addon["id"], appt["version"])

    got = validate_success(api.get_appointment(appt["id"], FRONT_DESK))
    # 13:00 + (45 + 10) minutes = 13:55. Compare by instant, format-robust.
    end_at = datetime.fromisoformat(got["end_at"].replace("Z", "+00:00"))
    expected = datetime(2026, 7, 1, 13, 55, 0, tzinfo=timezone.utc)
    assert end_at == expected, f"expected end_at 13:55Z, got {got['end_at']}"


def test_system_fields_ignored_on_create(api):
    """PRD §3.4: "The system maintains four computed fields on every client: a
    `loyalty_points_balance` of redeemable points (defaulting to 0)".

    Design: Corner/entities/system_fields_ignored_on_create
    """
    payload = create_client_payload(full_name="Spoofer")
    payload["loyalty_points_balance"] = 999  # client-supplied — must be ignored
    res = api.create_client(payload, FRONT_DESK)
    client = validate_success(res, expected_status=201)
    assert client["loyalty_points_balance"] == 0


def test_create_technician_invalid_pay_model_enum_rejected(api):
    """PRD §2.11: "the request body's structural well-formedness is checked:
    required fields present, enum values legal, integers within their declared
    ranges, and `start_at` parsing as an ISO 8601 instant, failing which
    `ERR_INVALID_REQUEST` is returned."
    PRD §3.1: "The `pay_model` is one of `COMMISSION` or `BOOTH_RENT`".

    Design: Corner/entities/create_technician_invalid_pay_model_enum_rejected
    """
    station = make_station(requires_autoclave=False)
    payload = create_technician_payload(station["id"], pay_model="SALARY")
    res = api.create_technician(payload, MANAGER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_client_email_rejected(api):
    """PRD §3.4: "A `FrontDesk` operator or `SalonManager` registers a `Client`
    with a `full_name` (non-empty) and an `email` that must be non-empty and
    unique across clients (a collision yields `ERR_DUPLICATE_RESOURCE`)."

    Design: Corner/entities/duplicate_client_email_rejected
    """
    api.create_client(create_client_payload(full_name="First", email="dup@x.com"),
                      FRONT_DESK)
    res = api.create_client(create_client_payload(full_name="Second", email="dup@x.com"),
                            FRONT_DESK)
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


def test_appointment_unknown_service_fk_returns_not_found(api):
    """PRD §2.6: "The same `ERR_NOT_FOUND` rule applies to every foreign key
    supplied in a request body — `client_id`, `technician_id`, `station_id`,
    `service_item_id`, `gift_card_id`, `add_on_id`, `logged_by_technician_id`,
    `purchaser_client_id`, and `appointment_id` — each of which must reference an
    existing resource, validated in the order the body presents them."

    Design: Corner/entities/appointment_unknown_service_fk_returns_not_found
    """
    station = make_station(requires_autoclave=False)
    tech = make_technician(station["id"])
    client = make_client()
    payload = create_appointment_payload(
        client["id"], tech["id"], station["id"], NON_EXISTENT_UUID,
        origin="APPOINTMENT", start_at="2026-07-02T13:00:00Z",
    )
    res = api.create_appointment(payload, FRONT_DESK)
    validate_error(res, "ERR_NOT_FOUND")


def test_list_appointments_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_appointments_pagination_envelope
    """
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                     origin="WALK_IN")

    data, meta = validate_paginated(api.list_appointments(FRONT_DESK))
    assert meta["total_count"] >= 1
    assert "has_more" in meta
    assert isinstance(data, list)
