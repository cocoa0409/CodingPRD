"""State-machine precondition corners: invalid transitions, access-code
mismatch, closed-survey response, duplicate registration, out-of-hours booking.

Queue B (Corner): state_machines/*.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    validate_error,
    ApiErrorId,
)


def test_cancel_already_cancelled_booking_returns_409(api):
    """PRD §2.8: "7. **State** — the target resource is in a state from which
    the requested transition is defined; otherwise `ERR_INVALID_STATE` (409)."
    PRD §3.2: "A resident may cancel a `CONFIRMED` booking."

    A second cancel on an already-CANCELLED booking is rejected with
    ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_already_cancelled_booking_returns_409
    """
    base = fx.setup_amenity_booking_base(
        api, clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Sam", "email": "sam@x.com"},
        amenity_overrides={"name": "Gym", "amenity_type": "GYM", "capacity": 1,
                           "base_rate_cents_per_hour": 1000, "deposit_cents": 0,
                           "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440},
    )
    resident_id = base["resident"]["id"]
    booking = fx.new_booking(api, base["amenity"]["id"], resident_id,
                             "2026-06-09T10:00:00Z", "2026-06-09T11:00:00Z",
                             expected_version=base["amenity"]["version"])
    fx.get_success_data(api.cancel_booking(booking["id"], make_resident_headers(resident_id)))
    resp = api.cancel_booking(booking["id"], make_resident_headers(resident_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_package_pickup_wrong_code_returns_422(api):
    """PRD §3.6: "the supplied code must match the minted `access_code`, or the
    pickup is rejected with `ERR_ACCESS_CODE_MISMATCH`."

    Design: Corner/state_machines/package_pickup_wrong_code_returns_422
    """
    base = fx.setup_property_unit_resident(api, resident_overrides={"full_name": "Tao", "email": "tao@x.com"})
    resident_id = base["resident"]["id"]
    pkg = fx.get_success_data(api.create_package({"resident_id": resident_id, "carrier": "UPS"}, fx.FRONT_DESK))
    fx.get_success_data(api.notify_package(pkg["id"], fx.FRONT_DESK))
    resp = api.pickup_package(pkg["id"], {"access_code": "000000"}, make_resident_headers(resident_id))
    validate_error(resp, ApiErrorId.ERR_ACCESS_CODE_MISMATCH.value)


def test_survey_response_when_not_open_returns_409(api):
    """PRD §3.7: "A response to a survey that is not `OPEN` is rejected with
    `ERR_SURVEY_NOT_OPEN`, and a resident who has already responded to that
    survey is rejected with `ERR_DUPLICATE_SURVEY_RESPONSE`."

    Submitting a response to a DRAFT (never opened) survey returns
    ERR_SURVEY_NOT_OPEN.

    Design: Corner/state_machines/survey_respond_when_not_open_returns_409
    """
    base = fx.setup_property_unit_resident(api, resident_overrides={"full_name": "Uma", "email": "uma@x.com"})
    resident_id = base["resident"]["id"]
    survey = fx.get_success_data(api.create_survey(
        {"property_id": base["property"]["id"], "title": "Draft Survey"}, fx.PM))
    resp = api.create_survey_response(
        survey["id"], {"resident_id": resident_id, "satisfaction_score": 3},
        make_resident_headers(resident_id))
    validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_OPEN.value)


def test_duplicate_event_registration_returns_409(api):
    """PRD §3.4: "Registration is admitted only if the resident has no existing
    non-terminal registration for that event; a duplicate is rejected with
    `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/state_machines/duplicate_event_registration_returns_409
    """
    base = fx.setup_published_event(api, clock="2026-05-20T00:00:00Z", capacity=5, fee_cents=0,
                                    event_start="2026-06-18T18:00:00Z", event_end="2026-06-18T20:00:00Z")
    resident_id = base["resident"]["id"]
    fx.register_resident(api, base["event"]["id"], resident_id)
    resp = api.register_event(base["event"]["id"], {"resident_id": resident_id},
                              make_resident_headers(resident_id))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value)


def test_booking_outside_operating_hours_returns_422(api):
    """PRD §3.2: "A window outside operating hours or spanning days is rejected
    with `ERR_OUTSIDE_OPERATING_HOURS`; an occupancy conflict with
    `ERR_BOOKING_OVERLAP`."

    A booking 18:00-19:00 on an amenity open only 09:00-17:00 is rejected with
    ERR_OUTSIDE_OPERATING_HOURS at creation.

    Design: Corner/state_machines/booking_check_in_outside_hours_returns_422
    """
    base = fx.setup_amenity_booking_base(
        api, clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Wes", "email": "wes@x.com"},
        amenity_overrides={"name": "Pool", "amenity_type": "POOL", "capacity": 1,
                           "base_rate_cents_per_hour": 1000, "deposit_cents": 0,
                           "buffer_minutes": 0, "open_minute": 540, "close_minute": 1020},
    )
    resident_id = base["resident"]["id"]
    resp = api.create_booking(
        {"amenity_id": base["amenity"]["id"], "resident_id": resident_id,
         "start_at": "2026-06-07T18:00:00Z", "end_at": "2026-06-07T19:00:00Z",
         "expected_amenity_version": base["amenity"]["version"]},
        make_resident_headers(resident_id),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_OPERATING_HOURS.value)
