"""Cross-entity state dependencies: a booking depends on the resident's
posture; an assignment depends on the vendor's status.

Queue A (Difficulty):
cross_entity_state_dependency/booking_requires_resident_good_standing,
cross_entity_state_dependency/assign_requires_vendor_active.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    make_property_manager_headers,
    validate_error,
    validate_paginated,
    ApiErrorId,
)


def _setup_suspended_resident_amenity(api):
    base = fx.setup_amenity_booking_base(
        api, clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Lena", "email": "lena@x.com"},
        amenity_overrides={
            "name": "Gym", "amenity_type": "GYM", "capacity": 1,
            "base_rate_cents_per_hour": 4000, "deposit_cents": 0,
            "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440,
        },
    )
    fx.make_resident_suspended(api, base["resident"]["id"])
    version = fx.current_amenity_version(api, base["amenity"]["id"])
    return base["amenity"]["id"], base["resident"]["id"], version


def test_suspended_resident_cannot_book(api):
    """PRD §2.8: "9. **Posture gate** — amenity bookings require `GOOD_STANDING`
    (a `DELINQUENT` or `SUSPENDED` resident is rejected with
    `ERR_ACCOUNT_DELINQUENT`, 403)..."

    A resident driven to SUSPENDED by a 200000 charge is rejected with
    ERR_ACCOUNT_DELINQUENT when attempting to book.

    Design: Difficulty/cross_entity_state_dependency/booking_requires_resident_good_standing
    """
    amenity_id, resident_id, version = _setup_suspended_resident_amenity(api)
    resp = api.create_booking(
        {"amenity_id": amenity_id, "resident_id": resident_id,
         "start_at": "2026-06-11T10:00:00Z", "end_at": "2026-06-11T11:00:00Z",
         "expected_amenity_version": version},
        make_resident_headers(resident_id),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_DELINQUENT.value)


def test_suspended_resident_booking_not_created(api):
    """PRD §3.2: "The reservation is admitted only when the amenity's `status`
    is `OPEN`, the resident's `account_status` is `GOOD_STANDING`, ..."

    The suspended resident (account_status SUSPENDED) has no booking created by
    the rejected request.

    Design: Difficulty/cross_entity_state_dependency/booking_requires_resident_good_standing
    """
    amenity_id, resident_id, version = _setup_suspended_resident_amenity(api)
    resident = fx.get_resident(api, resident_id)
    assert resident["account_status"] == "SUSPENDED"
    api.create_booking(
        {"amenity_id": amenity_id, "resident_id": resident_id,
         "start_at": "2026-06-11T10:00:00Z", "end_at": "2026-06-11T11:00:00Z",
         "expected_amenity_version": version},
        make_resident_headers(resident_id),
    )
    _, meta = validate_paginated(api.list_bookings(fx.PM, params={"resident_id": resident_id}))
    assert meta["total_count"] == 0


def _setup_suspended_vendor_request(api):
    base = fx.setup_property_unit_resident(api, resident_overrides={"full_name": "Milo", "email": "milo@x.com"})
    vendor = fx.new_vendor(api, name="PlumbCo", trades=["PLUMBING"], hourly_rate_cents=8000)
    fx.get_success_data(api.suspend_vendor(vendor["id"], fx.PM))
    sr = fx.new_service_request(api, base["unit"]["id"], base["resident"]["id"], trade="PLUMBING", description="Drip")
    fx.get_success_data(api.triage_service_request(sr["id"], {}, make_property_manager_headers("pm_triage")))
    return sr["id"], vendor["id"]


def test_assigning_suspended_vendor_rejected(api):
    """PRD §3.5: "A suspended vendor targeted by an assignment is rejected with
    `ERR_VENDOR_INACTIVE`."

    Assigning a SUSPENDED vendor that does service the trade is rejected with
    ERR_VENDOR_INACTIVE (409).

    Design: Difficulty/cross_entity_state_dependency/assign_requires_vendor_active
    """
    sr_id, vendor_id = _setup_suspended_vendor_request(api)
    resp = api.assign_service_request(sr_id, {"vendor_id": vendor_id, "estimated_hours": 1},
                                      make_property_manager_headers("pm_assign"))
    validate_error(resp, ApiErrorId.ERR_VENDOR_INACTIVE.value)


def test_suspended_vendor_request_stays_triaged(api):
    """PRD §3.5: "a manager may suspend a vendor, setting its `status` to
    `SUSPENDED`, which blocks new assignments."

    The rejected assignment leaves the request in TRIAGED (never ASSIGNED).

    Design: Difficulty/cross_entity_state_dependency/assign_requires_vendor_active
    """
    sr_id, vendor_id = _setup_suspended_vendor_request(api)
    api.assign_service_request(sr_id, {"vendor_id": vendor_id, "estimated_hours": 1},
                               make_property_manager_headers("pm_assign"))
    fetched = fx.get_success_data(api.get_service_request(sr_id, fx.PM))
    assert fetched["status"] == "TRIAGED"
