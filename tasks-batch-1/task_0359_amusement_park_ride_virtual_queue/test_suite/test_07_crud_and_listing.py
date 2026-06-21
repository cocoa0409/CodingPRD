"""CRUD, system-field, validation, and listing tests for the corner index's
entities and endpoints sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_park, create_ride, create_guest, create_window,
    make_park_admin_headers, make_guest_headers,
)

ADMIN = make_park_admin_headers()


def test_create_ride_returns_201_with_defaults(api):
    """PRD §3.1: "each of these three defaults to its safe value — 0, false, and
    false respectively. A ride is born `OPEN` with `booked_slot_count` at 0 and its
    `posted_wait_minutes` computed."

    Design: Corner/entities/create_ride_returns_201_with_defaults
    """
    park = create_park()
    resp = api.create_ride(park["id"], {"name": "Coaster", "hourly_throughput": 100}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["operational_status"] == "OPEN", f"expected OPEN, got {data['operational_status']}"
    assert data["min_height_cm"] == 0, f"expected min_height_cm 0, got {data['min_height_cm']}"
    assert data["booked_slot_count"] == 0, f"expected booked_slot_count 0, got {data['booked_slot_count']}"


def test_create_reservation_missing_queue_type_rejected(api):
    """PRD §2.10: "Malformed input — a missing required field, a value of the wrong
    shape, or an enum outside its permitted set — is rejected with `ERR_VALIDATION`."

    queue_type is a required input field with no default.

    Design: Corner/entities/create_reservation_missing_required_queue_type_returns_validation
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100)
    window = create_window(ride["id"])
    guest = create_guest(park["id"], full_name="G1")
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": guest["id"], "return_window_id": window["id"],
         "expected_return_window_id_version": window["version"]},
        make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_guest_not_found_returns_404(api):
    """PRD §2.10: "Before any business rule runs, the system confirms that every
    resource named in the request — whether in the URL path or the body — exists ...
    the first missing identifier short-circuits the request with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_guest_not_found_returns_404
    """
    create_park()
    resp = api.get_guest("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_system_fields_minted_on_park_create(api):
    """PRD §3.1: "A freshly created park starts with `admitted_count` at 0 and
    `day_phase` at `OPEN`".
    PRD §2.4: "The `version` field is an integer that begins at its initial value
    and increments by one on every mutation".

    Design: Corner/entities/system_fields_minted_on_park_create
    """
    resp = api.create_park({"name": "P", "gate_capacity": 50, "operating_date": "2026-06-15"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["admitted_count"] == 0, f"expected admitted_count 0, got {data['admitted_count']}"
    assert data["day_phase"] == "OPEN", f"expected day_phase OPEN, got {data['day_phase']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_invalid_tier_enum_rejected(api):
    """PRD §2.10: "Malformed input — a missing required field, a value of the wrong
    shape, or an enum outside its permitted set — is rejected with `ERR_VALIDATION`."

    tier outside {MULTI_PASS, SINGLE_PASS}.

    Design: Corner/entities/type_constraint_invalid_tier_enum_rejected
    """
    park = create_park()
    resp = api.create_entitlement_plan(
        park["id"], {"tier": "GOLD_PASS", "price_cents": 1000, "max_concurrent_holds": 2}, ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_list_rides_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    count of all matching resources before pagination and `has_more` indicates
    whether further pages exist beyond the current window."

    Design: Corner/endpoints/list_rides_paginated_envelope
    """
    park = create_park()
    create_ride(park["id"], hourly_throughput=100, name="R1")
    create_ride(park["id"], hourly_throughput=50, name="R2")
    resp = api.list_rides(park["id"], ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"
