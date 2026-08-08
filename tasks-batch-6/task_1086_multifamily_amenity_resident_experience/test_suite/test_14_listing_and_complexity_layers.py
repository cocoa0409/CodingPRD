"""Listing pagination plus the cross-cutting complexity layers: vendor quota
gate and amenity optimistic-concurrency.

Queue B (Corner): endpoints/list_bookings_pagination_reports_total_and_has_more,
cross_cutting_complexity_layers/*.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    make_property_manager_headers,
    validate_paginated,
    validate_error,
    ApiErrorId,
)


def test_list_bookings_pagination_reports_total_and_has_more(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`
    (the total number of matching resources before the page window is applied),
    and `has_more` (true when further resources remain beyond the current page)
    inside `meta`."

    Over two bookings, a limit-1 page returns one row with total_count 2 and
    has_more true.

    Design: Corner/endpoints/list_bookings_pagination_reports_total_and_has_more
    """
    base = fx.setup_amenity_booking_base(
        api, clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Deb", "email": "deb@x.com"},
        amenity_overrides={"name": "Gym", "amenity_type": "GYM", "capacity": 1,
                           "base_rate_cents_per_hour": 1000, "deposit_cents": 0,
                           "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440},
    )
    amenity_id = base["amenity"]["id"]
    resident_id = base["resident"]["id"]
    fx.new_booking(api, amenity_id, resident_id, "2026-06-13T10:00:00Z", "2026-06-13T11:00:00Z",
                   expected_version=base["amenity"]["version"])
    fx.new_booking(api, amenity_id, resident_id, "2026-06-13T12:00:00Z", "2026-06-13T13:00:00Z")

    data, meta = validate_paginated(
        api.list_bookings(fx.PM, params={"resident_id": resident_id, "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_assign_vendor_at_capacity_returns_409(api):
    """PRD §3.5: "the vendor's `active_job_count` is strictly below its
    `active_job_limit` (otherwise `ERR_VENDOR_AT_CAPACITY`)."

    A matching-trade GENERAL vendor already at its active_job_limit of 1 is
    rejected with ERR_VENDOR_AT_CAPACITY on a second assignment.

    Design: Corner/cross_cutting_complexity_layers/assign_vendor_at_capacity_returns_409
    """
    base = fx.setup_property_unit_resident(api, resident_overrides={"full_name": "Ed", "email": "ed@x.com"})
    unit_id = base["unit"]["id"]
    resident_id = base["resident"]["id"]
    vendor = fx.new_vendor(api, name="Handy", trades=["GENERAL"], hourly_rate_cents=5000, active_job_limit=1)
    triage_hdr = make_property_manager_headers("pm_1")
    sr1 = fx.new_service_request(api, unit_id, resident_id, trade="GENERAL", description="one")
    fx.get_success_data(api.triage_service_request(sr1["id"], {}, triage_hdr))
    fx.get_success_data(api.assign_service_request(sr1["id"], {"vendor_id": vendor["id"], "estimated_hours": 1}, triage_hdr))
    sr2 = fx.new_service_request(api, unit_id, resident_id, trade="GENERAL", description="two")
    fx.get_success_data(api.triage_service_request(sr2["id"], {}, triage_hdr))

    resp = api.assign_service_request(sr2["id"], {"vendor_id": vendor["id"], "estimated_hours": 1}, triage_hdr)
    validate_error(resp, ApiErrorId.ERR_VENDOR_AT_CAPACITY.value)


def test_booking_create_stale_amenity_version_returns_412(api):
    """PRD §2.4: "If another writer has advanced the amenity's `version` since
    the client last read it, so that `expected_amenity_version` no longer equals
    the amenity's current `version`, the creation is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    After one booking bumps the amenity version 1->2, a second create for a
    non-overlapping slot still carrying version 1 is rejected with
    ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/booking_create_stale_amenity_version_returns_412
    """
    base = fx.setup_amenity_booking_base(
        api, clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Fay", "email": "fay@x.com"},
        amenity_overrides={"name": "Gym", "amenity_type": "GYM", "capacity": 1,
                           "base_rate_cents_per_hour": 1000, "deposit_cents": 0,
                           "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440},
    )
    amenity_id = base["amenity"]["id"]
    resident_id = base["resident"]["id"]
    initial_version = base["amenity"]["version"]
    fx.new_booking(api, amenity_id, resident_id, "2026-06-14T10:00:00Z", "2026-06-14T11:00:00Z",
                   expected_version=initial_version)
    resp = api.create_booking(
        {"amenity_id": amenity_id, "resident_id": resident_id,
         "start_at": "2026-06-14T12:00:00Z", "end_at": "2026-06-14T13:00:00Z",
         "expected_amenity_version": initial_version},
        make_resident_headers(resident_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
