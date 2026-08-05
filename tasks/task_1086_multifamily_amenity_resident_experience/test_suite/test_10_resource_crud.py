"""Resource CRUD corners: creation echo, required-field validation, not-found,
and the computed retention score.

Queue B (Corner): entities/*.
"""
from test_helpers import (
    fixtures as fx,
    validate_success,
    validate_error,
    ApiErrorId,
)


def test_create_property_returns_201_with_fields(api):
    """PRD §2.4: "`version`, an integer that begins at 1 on creation and
    increments by one on each mutation that changes the resource."
    PRD §3.1: "A property manager establishes a property by supplying its
    `name`, `address`, and a `guest_parking_capacity` (the maximum number of
    guest passes that may be concurrently active across the whole property at
    any instant, which must be zero or greater)."

    Design: Corner/entities/property_create_returns_201_with_fields
    """
    resp = api.create_property(
        {"name": "Harbor", "address": "10 Dock Rd", "guest_parking_capacity": 3, "guest_window_hours": 24},
        fx.PM,
    )
    data = validate_success(resp, expected_status=201)
    assert data["guest_parking_capacity"] == 3
    assert data["version"] == 1


def test_create_resident_missing_email_returns_422(api):
    """PRD §2.8: "3. **Body validation** — required fields present, correct
    types, valid enum members, numeric ranges honored ...; otherwise
    `ERR_VALIDATION` (422)."
    PRD §3.1: "When a resident is created on a unit — by supplying the
    `unit_id`, `full_name`, `email` (unique across all residents), and an
    optional `membership_tier` ..."

    Design: Corner/entities/resident_create_missing_required_field_returns_422
    """
    prop = fx.new_property(api, name="Harbor", address="10 Dock Rd", guest_parking_capacity=3)
    unit = fx.new_unit(api, prop["id"], unit_number="A1")
    resp = api.create_resident({"unit_id": unit["id"], "full_name": "NoEmail"}, fx.PM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_nonexistent_resident_returns_404(api):
    """PRD §2.8: "4. **Existence** — every path `id` and every body foreign key
    resolves to an existing resource, checked left to right along the path;
    otherwise the resource-specific not-found error (404), such as
    `ERR_PROPERTY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, ..."

    Design: Corner/entities/get_resident_nonexistent_returns_not_found
    """
    resp = api.get_resident("00000000-0000-4000-8000-000000000000", fx.PM)
    validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_FOUND.value)


def test_retention_score_computed_from_components(api):
    """PRD §3.7: "It begins from a base of 50."
    PRD §3.7: "The engagement term is three points per booking the resident
    completed whose `checked_out_at` falls within the retention window of 90
    days before the current time, capped at 30 points."
    PRD §3.7: "an open-service-request penalty of five points for each of the
    resident's service requests currently in `SUBMITTED`, `TRIAGED`,
    `ASSIGNED`, or `IN_PROGRESS`, capped at 30 points; and a no-show penalty of
    ten points for each of the resident's `no_show_strikes`."

    One survey response (score 4 -> satisfaction 16), one completed booking
    within 90d (engagement 3), one open service request (penalty 5), no strikes
    => 50 + 3 + 16 - 5 = 64.

    Design: Corner/entities/retention_score_computed_correct
    """
    prop = fx.new_property(api, name="Harbor", address="10 Dock Rd", guest_parking_capacity=3)
    unit = fx.new_unit(api, prop["id"], unit_number="A2")
    resident = fx.new_resident(api, unit["id"], full_name="Rita", email="rita@x.com")
    resident_id = resident["id"]
    fx.set_clock(api, "2026-06-01T09:00:00Z")
    amenity = fx.new_amenity(api, prop["id"], name="Gym", amenity_type="GYM", capacity=1,
                             base_rate_cents_per_hour=1000, deposit_cents=0,
                             buffer_minutes=0, open_minute=0, close_minute=1440)
    booking = fx.new_booking(api, amenity["id"], resident_id,
                             "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z",
                             expected_version=amenity["version"])
    fx.set_clock(api, "2026-06-01T10:00:00Z")
    validate_success(api.check_in_booking(booking["id"], fx.FRONT_DESK))
    fx.set_clock(api, "2026-06-01T11:00:00Z")
    validate_success(api.check_out_booking(booking["id"], fx.FRONT_DESK))
    fx.new_service_request(api, unit["id"], resident_id, trade="GENERAL", description="Squeaky door")
    survey = fx.get_success_data(api.create_survey({"property_id": prop["id"], "title": "Q2"}, fx.PM))
    fx.get_success_data(api.open_survey(survey["id"], fx.PM))
    fx.get_success_data(api.create_survey_response(
        survey["id"], {"resident_id": resident_id, "satisfaction_score": 4},
        fx.make_resident_headers(resident_id)))

    retention = validate_success(api.get_resident_retention(resident_id, fx.PM))
    assert retention["retention_score"] == 64
    assert retention["completed_bookings_90d"] == 1
    assert retention["open_service_requests"] == 1
