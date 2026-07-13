"""Field-level constraints, payout guards, extension uniqueness, subresources.

Corner queue: validations (odometer/fuel/trip-length/payout), the duplicate-open
extension linkage, adjacent-booking endpoint behavior, and the inspection
subresource read.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_host_headers, make_guest_headers, make_admin_headers,
    register_host, register_verified_guest, register_unverified_guest,
    create_plan, create_listed_vehicle, current_vehicle_version, current_host_version,
    create_trip_payload, create_payout_payload, create_extension_payload,
    book_trip,
    setup_confirmed_trip, setup_checked_in_trip, setup_requested_extension,
)

ADMIN = make_admin_headers()


def _listed_scenario(api):
    host = register_host(api)
    guest = register_verified_guest(api)
    plan = create_plan(api)
    vehicle = create_listed_vehicle(api, host["id"])
    return {"host": host, "guest": guest, "plan": plan, "vehicle": vehicle}


# ------------------------------------------------------- field constraints
def test_checkout_odometer_below_checkin_rejected(api):
    """PRD §3.6: "the checkout `odometer_reading` must be at least the trip's
    `checkin_odometer` (a car cannot un-drive miles), else `ERR_INVALID_ODOMETER`"

    Design: Corner/validations/invalid_odometer_checkout_below_checkin
    """
    ctx = setup_checked_in_trip(api, checkin_odometer=10000)
    api.set_clock("2026-06-08T09:00:00Z", ADMIN)
    resp = api.checkout_trip(
        ctx["trip"]["id"],
        {"odometer_reading": 9000, "fuel_level_pct": 100, "photo_refs": ["out1"]},
        ctx["guest_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ODOMETER)


def test_checkin_fuel_out_of_range_rejected(api):
    """PRD §3.6: "the fuel value must lie within 0 to 100 inclusive, else
    `ERR_INVALID_FUEL_LEVEL`"

    Design: Corner/validations/invalid_fuel_level_out_of_range
    """
    ctx = setup_confirmed_trip(api)
    api.set_clock("2026-06-01T10:00:00Z", ADMIN)
    resp = api.checkin_trip(
        ctx["trip"]["id"],
        {"odometer_reading": 10000, "fuel_level_pct": 150, "photo_refs": ["in1"]},
        ctx["guest_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_FUEL_LEVEL)


def test_trip_exceeding_max_nights_rejected(api):
    """PRD §3.4: "must not exceed the maximum trip length of 90 nights, else
    `ERR_TRIP_TOO_LONG`."

    Design: Corner/validations/trip_too_long_exceeds_max_nights
    """
    sc = _listed_scenario(api)
    version = current_vehicle_version(api, sc["vehicle"]["id"])
    payload = create_trip_payload(sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
                                  "2026-06-01", "2026-08-31", version)  # 91 nights
    resp = api.create_trip(payload, make_guest_headers(sc["guest"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TRIP_TOO_LONG)


# ------------------------------------------------------------ payout guards
def test_payout_below_minimum_rejected(api):
    """PRD §3.9: "the `amount_cents` must be at least the minimum payout of
    5,000 cents, else `ERR_PAYOUT_BELOW_MINIMUM`"

    Design: Corner/validations/payout_below_minimum_rejected
    """
    host = register_host(api, name="Host DE", email="hde@x.com")
    version = current_host_version(api, host["id"])
    resp = api.create_payout(create_payout_payload(host["id"], 100, version),
                             make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYOUT_BELOW_MINIMUM)


def test_payout_insufficient_balance_rejected(api):
    """PRD §3.9: "the `amount_cents` must not exceed the host's
    `available_balance_cents`, else `ERR_INSUFFICIENT_BALANCE`."

    Design: Corner/validations/payout_insufficient_balance_rejected
    """
    host = register_host(api, name="Host DF", email="hdf@x.com")
    version = current_host_version(api, host["id"])
    resp = api.create_payout(create_payout_payload(host["id"], 6000, version),
                             make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)


def test_payout_by_suspended_host_rejected(api):
    """PRD §3.9: "the host must be `ACTIVE` — a payout against a `SUSPENDED` host
    is rejected with `ERR_HOST_SUSPENDED`"

    Design: Corner/validations/payout_host_suspended_rejected
    """
    host = register_host(api, name="Host DG", email="hdg@x.com")
    api.suspend_host(host["id"], ADMIN)
    version = current_host_version(api, host["id"])
    resp = api.create_payout(create_payout_payload(host["id"], 6000, version),
                             make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_HOST_SUSPENDED)


# ---------------------------------------------------- extension uniqueness
def test_second_open_extension_rejected(api):
    """PRD §3.7: "A trip may hold at most one `REQUESTED` extension at a time; a
    second request while one is still open is rejected with
    `ERR_DUPLICATE_OPEN_EXTENSION`."

    Design: Corner/validations/duplicate_open_extension_rejected
    """
    ctx = setup_requested_extension(api, new_end_date="2026-06-10")
    resp = api.create_extension(ctx["trip"]["id"], create_extension_payload("2026-06-12"),
                                ctx["guest_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_EXTENSION)


# ----------------------------------------------------------- endpoints
def test_adjacent_booking_allowed(api):
    """PRD §2.6: "A trip's date span and an availability block's date span are
    **half-open**: the interval runs from `start_date` inclusive to `end_date`
    exclusive"

    Design: Corner/endpoints/availability_adjacent_booking_allowed
    """
    sc = _listed_scenario(api)
    book_trip(api, sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
              "2026-06-01", "2026-06-08")
    trip2 = book_trip(api, sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
                      "2026-06-08", "2026-06-10")
    assert trip2["status"] == "REQUESTED"
    assert trip2["nights"] == 2


def test_inspections_subresource_returns_checkin_report(api):
    """PRD §3.6: "This creates an `InspectionReport` whose `phase` is
    `CHECK_IN`, capturing the `odometer_reading`, the `fuel_level_pct`, the
    `photo_refs`, and a `recorded_at` stamped from the logical clock; the trip
    copies these into its `checkin_odometer` and `checkin_fuel_pct`."

    Design: Corner/endpoints/trip_inspections_subresource_returns_checkin
    """
    ctx = setup_checked_in_trip(api, checkin_odometer=10000, checkin_fuel_pct=90)
    reports = get_success_data(api.list_inspections(ctx["trip"]["id"], ctx["host_headers"]))
    assert isinstance(reports, list) and len(reports) == 1
    assert reports[0]["phase"] == "CHECK_IN"
    assert reports[0]["odometer_reading"] == 10000
