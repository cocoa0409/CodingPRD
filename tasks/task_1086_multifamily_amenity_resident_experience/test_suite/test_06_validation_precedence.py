"""Validation-ladder precedence: posture gate outranks temporal windows, and
referential compatibility outranks the vendor quota.

Queue A (Difficulty):
priority_pair_validation_conflict/booking_safety_beats_temporal,
priority_pair_validation_conflict/assign_referential_beats_constraint.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    make_property_manager_headers,
    validate_error,
    validate_paginated,
    ApiErrorId,
)


def _setup_delinquent_vs_held_slot(api):
    """Resident B holds a CONFIRMED booking on a capacity-1 GYM; Resident A is
    made DELINQUENT. Returns (amenity_id, res_a_id, expected_version)."""
    prop = fx.new_property(api, name="Cedar", address="5 Cedar St", guest_parking_capacity=5)
    unit_a = fx.new_unit(api, prop["id"], unit_number="501")
    unit_b = fx.new_unit(api, prop["id"], unit_number="502")
    res_a = fx.new_resident(api, unit_a["id"], full_name="Ann", email="ann@x.com")
    res_b = fx.new_resident(api, unit_b["id"], full_name="Bob", email="bob@x.com")
    fx.set_clock(api, "2026-05-20T00:00:00Z")
    amenity = fx.new_amenity(api, prop["id"], name="Gym", amenity_type="GYM", capacity=1,
                             base_rate_cents_per_hour=4000, deposit_cents=0,
                             buffer_minutes=0, open_minute=0, close_minute=1440)
    fx.new_booking(api, amenity["id"], res_b["id"], "2026-06-05T10:00:00Z", "2026-06-05T12:00:00Z",
                   expected_version=amenity["version"])
    fx.charge_resident(api, res_a["id"], 60000, "arrears")
    version = fx.current_amenity_version(api, amenity["id"])
    return amenity["id"], res_a["id"], version


def test_delinquent_booking_reports_posture_over_overlap(api):
    """PRD §2.8: "9. **Posture gate** — amenity bookings require `GOOD_STANDING`
    (a `DELINQUENT` or `SUSPENDED` resident is rejected with
    `ERR_ACCOUNT_DELINQUENT`, 403)..."

    A DELINQUENT resident booking a slot already held by another resident is
    rejected with ERR_ACCOUNT_DELINQUENT (posture gate, priority 9) rather than
    ERR_BOOKING_OVERLAP (temporal, priority 10).

    Design: Difficulty/priority_pair_validation_conflict/booking_safety_beats_temporal
    """
    amenity_id, res_a_id, version = _setup_delinquent_vs_held_slot(api)
    resp = api.create_booking(
        {"amenity_id": amenity_id, "resident_id": res_a_id,
         "start_at": "2026-06-05T10:00:00Z", "end_at": "2026-06-05T12:00:00Z",
         "expected_amenity_version": version},
        make_resident_headers(res_a_id),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_DELINQUENT.value)


def test_delinquent_booking_not_created(api):
    """PRD §2.8: "they are evaluated in a fixed priority order so that the
    reported error is deterministic."

    Because the posture gate (priority 9) pre-empts the temporal check, the
    losing error ERR_BOOKING_OVERLAP is not returned and no booking is created
    for the delinquent resident.

    Design: Difficulty/priority_pair_validation_conflict/booking_safety_beats_temporal
    """
    amenity_id, res_a_id, version = _setup_delinquent_vs_held_slot(api)
    resp = api.create_booking(
        {"amenity_id": amenity_id, "resident_id": res_a_id,
         "start_at": "2026-06-05T10:00:00Z", "end_at": "2026-06-05T12:00:00Z",
         "expected_amenity_version": version},
        make_resident_headers(res_a_id),
    )
    error_id = resp.json()["data"]["error_id"]
    assert error_id != ApiErrorId.ERR_BOOKING_OVERLAP.value, "temporal error must be pre-empted"
    _, meta = validate_paginated(api.list_bookings(fx.PM, params={"resident_id": res_a_id}))
    assert meta["total_count"] == 0, "no booking created for the rejected request"


def _setup_at_capacity_mismatch_vendor(api):
    """ELECTRICAL-only vendor with limit 1 already holding one ASSIGNED job; a
    PLUMBING request triaged and awaiting assignment. Returns (sr2_id,
    vendor_id)."""
    base = fx.setup_property_unit_resident(api, resident_overrides={"full_name": "Cy", "email": "cy@x.com"})
    unit_id = base["unit"]["id"]
    resident_id = base["resident"]["id"]
    vendor = fx.new_vendor(api, name="Sparky", trades=["ELECTRICAL"], hourly_rate_cents=9000, active_job_limit=1)
    sr1 = fx.new_service_request(api, unit_id, resident_id, trade="ELECTRICAL", description="Outlet dead")
    triage_hdr = make_property_manager_headers("pm_triage")
    assign_hdr = make_property_manager_headers("pm_assign")
    fx.get_success_data(api.triage_service_request(sr1["id"], {}, triage_hdr))
    fx.get_success_data(api.assign_service_request(sr1["id"], {"vendor_id": vendor["id"], "estimated_hours": 1}, assign_hdr))
    sr2 = fx.new_service_request(api, unit_id, resident_id, trade="PLUMBING", description="Clog")
    fx.get_success_data(api.triage_service_request(sr2["id"], {}, triage_hdr))
    return sr2["id"], vendor["id"]


def test_assign_reports_trade_mismatch_over_capacity(api):
    """PRD §2.8: "8. **Referential compatibility** — for vendor assignment the
    request's `trade` is a member of the vendor's `trades` (otherwise
    `ERR_VENDOR_TRADE_MISMATCH`, 422)..."

    Assigning an at-capacity vendor that also does not service the request's
    trade yields ERR_VENDOR_TRADE_MISMATCH (priority 8) rather than
    ERR_VENDOR_AT_CAPACITY (priority 11).

    Design: Difficulty/priority_pair_validation_conflict/assign_referential_beats_constraint
    """
    sr2_id, vendor_id = _setup_at_capacity_mismatch_vendor(api)
    resp = api.assign_service_request(sr2_id, {"vendor_id": vendor_id, "estimated_hours": 1},
                                      make_property_manager_headers("pm_assign"))
    validate_error(resp, ApiErrorId.ERR_VENDOR_TRADE_MISMATCH.value)


def test_assign_mismatch_leaves_request_triaged(api):
    """PRD §3.5: "From `TRIAGED`, a manager assigns a vendor by supplying the
    `vendor_id`, an `estimated_hours`, and an optional `estimated_parts_cents`."

    Because the referential check pre-empts the quota check and rejects the
    assignment, the request stays TRIAGED (never ASSIGNED) and the losing
    ERR_VENDOR_AT_CAPACITY is not returned.

    Design: Difficulty/priority_pair_validation_conflict/assign_referential_beats_constraint
    """
    sr2_id, vendor_id = _setup_at_capacity_mismatch_vendor(api)
    resp = api.assign_service_request(sr2_id, {"vendor_id": vendor_id, "estimated_hours": 1},
                                      make_property_manager_headers("pm_assign"))
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_VENDOR_AT_CAPACITY.value
    fetched = fx.get_success_data(api.get_service_request(sr2_id, fx.PM))
    assert fetched["status"] == "TRIAGED"
