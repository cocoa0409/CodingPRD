"""Vehicle listing state machine, version increments, and optimistic concurrency.

Version literals are never asserted (PRD §2.4 does not pin the initial value);
only the per-mutation increment-by-one is checked, relative to a captured base.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_vehicle_payload, create_trip_payload, create_payout_payload,
    submit_verification_payload,
    make_host_headers, make_guest_headers, make_admin_headers, make_anonymous_headers,
    register_host, create_plan, register_verified_guest,
)

ANON = make_anonymous_headers()
ADMIN = make_admin_headers()


def test_vehicle_snooze_then_relist_returns_listed(api):
    """PRD §3.1: "listing it advances `DRAFT → LISTED` or `SNOOZED → LISTED`
    and makes it bookable; snoozing advances `LISTED → SNOOZED` while leaving
    existing bookings valid"

    Design: Corner/state_machines/vehicle_snooze_then_relist_valid
    """
    host = register_host(api, name="Host BE", email="hbe@x.com")
    h = make_host_headers(host["id"])
    created = validate_success(api.create_vehicle(create_vehicle_payload(host["id"]), h), 201)
    listed = get_success_data(api.list_vehicle(created["id"], h))
    snoozed = get_success_data(api.snooze_vehicle(created["id"], h))
    relisted = get_success_data(api.list_vehicle(created["id"], h))
    assert relisted["status"] == "LISTED"


def test_vehicle_version_increments_by_one_on_each_transition(api):
    """PRD §3.1: "Every one of these transitions requires that the acting host
    own the vehicle and increments the vehicle's `version` by one."

    Design: Corner/state_machines/vehicle_snooze_then_relist_valid
    """
    host = register_host(api, name="Host BE2", email="hbe2@x.com")
    h = make_host_headers(host["id"])
    created = validate_success(api.create_vehicle(create_vehicle_payload(host["id"]), h), 201)
    listed = get_success_data(api.list_vehicle(created["id"], h))
    snoozed = get_success_data(api.snooze_vehicle(created["id"], h))
    relisted = get_success_data(api.list_vehicle(created["id"], h))
    assert listed["version"] == created["version"] + 1
    assert snoozed["version"] == listed["version"] + 1
    assert relisted["version"] == snoozed["version"] + 1


def test_vehicle_version_increments_on_list_and_edit(api):
    """PRD §3.1: "A host may edit a vehicle's pricing and configuration ... each
    such edit increments the vehicle's `version` by one, which is exactly what
    can invalidate a guest's in-flight quote"

    Design: Corner/cross_cutting_complexity_layers/vehicle_version_increments_on_each_mutation
    """
    host = register_host(api, name="Host GC", email="hgc@x.com")
    h = make_host_headers(host["id"])
    created = validate_success(api.create_vehicle(create_vehicle_payload(host["id"]), h), 201)
    listed = get_success_data(api.list_vehicle(created["id"], h))
    edited = get_success_data(api.update_vehicle(created["id"], {"base_daily_price_cents": 11000}, h))
    assert listed["version"] == created["version"] + 1
    assert edited["version"] == listed["version"] + 1
    assert edited["base_daily_price_cents"] == 11000


def test_edit_field_persists_on_vehicle(api):
    """PRD §3.1: "A host may edit a vehicle's pricing and configuration — any of
    `base_daily_price_cents`, `daily_mileage_limit`, `weekly_discount_pct`,
    `monthly_discount_pct`, `location_city`, or `odometer_current` — while it
    exists"

    Design: Corner/cross_cutting_complexity_layers/vehicle_version_increments_on_each_mutation
    """
    host = register_host(api, name="Host GC2", email="hgc2@x.com")
    h = make_host_headers(host["id"])
    created = validate_success(api.create_vehicle(create_vehicle_payload(host["id"]), h), 201)
    api.list_vehicle(created["id"], h)
    edited = get_success_data(api.update_vehicle(created["id"], {"base_daily_price_cents": 11000}, h))
    assert edited["base_daily_price_cents"] == 11000


def test_stale_vehicle_version_booking_rejected(api):
    """PRD §2.7: "If that value does not equal the vehicle's current `version` —
    because the host has since edited the vehicle, changed a listing state, or
    another guest's booking advanced it — the guest's view is stale and the
    booking is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_vehicle_version_booking_rejected
    """
    host = register_host(api, name="Host GA", email="hga@x.com")
    guest = register_verified_guest(api, license_number="DL-36", name="Guest GA", email="gga@x.com")
    plan = create_plan(api)
    h = make_host_headers(host["id"])
    created = validate_success(api.create_vehicle(create_vehicle_payload(host["id"]), h), 201)
    listed = get_success_data(api.list_vehicle(created["id"], h))
    stale_version = listed["version"]
    # Host edits pricing -> vehicle.version advances, making the observed version stale.
    api.update_vehicle(created["id"], {"base_daily_price_cents": 12000}, h)
    payload = create_trip_payload(created["id"], guest["id"], plan["id"],
                                  "2026-06-01", "2026-06-08", stale_version)
    resp = api.create_trip(payload, make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VEHICLE_VERSION)


def test_stale_host_version_payout_rejected(api):
    """PRD §2.7: "then `expected_host_version` no longer matches the host's
    current `version`, and the request is rejected with `ERR_STALE_HOST_VERSION`
    (HTTP 412) so the draw can be recomputed against a fresh balance."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_host_version_payout_rejected
    """
    created = validate_success(api.create_host({"name": "Host GB", "email": "hgb@x.com"}, ANON), 201)
    stale_version = created["version"]
    api.suspend_host(created["id"], ADMIN)
    api.reinstate_host(created["id"], ADMIN)  # ACTIVE again, but version advanced twice
    payload = create_payout_payload(created["id"], 6000, stale_version)
    resp = api.create_payout(payload, make_host_headers(created["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_HOST_VERSION)
