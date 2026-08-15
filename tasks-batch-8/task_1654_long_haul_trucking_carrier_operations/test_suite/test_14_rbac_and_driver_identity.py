"""Role-based access control and Driver identity matching (PRD §2.1, §4)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_driver,
    create_manual_accessorial,
    make_driver_headers,
    make_payroll_clerk_headers,
    make_safety_officer_headers,
    set_clock,
    setup_dispatched_trip,
    setup_planned_trip,
    setup_refdata,
    tender_load,
    validate_error,
    validate_paginated,
    validate_success,
)

SAFETY_OFFICER = make_safety_officer_headers()
PAYROLL_1 = make_payroll_clerk_headers("payroll-1")


def test_missing_identity_headers_rejected(api):
    """PRD §2.1: "A request that is missing either header, or whose role is not
    one of the six recognized values, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    (The request is sent with neither X-User-ID nor X-User-Role.)

    Design: Corner/validations/missing_auth_header_rejected
    """
    driver = create_driver(cdl_number="CDL-V1")
    resp = api_client.get_driver(driver["id"], headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_driver_cannot_check_call_foreign_trip(api):
    """PRD §2.1: "a caller in the `Driver` role may append duty events only to
    their own driver record, record check calls only against a trip whose
    `driver_id` equals `X-User-ID`, record a fuel purchase only when the
    payload's `driver_id` equals both the trip's driver and `X-User-ID`, and
    capture or submit accessorials only for loads with a trip driven by
    `X-User-ID`; any mismatch is rejected with `ERR_DRIVER_MISMATCH`
    (HTTP 403)."

    Design: Corner/validations/driver_cannot_check_call_foreign_trip
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-V4A", unit_number="T-V4")
    other = create_driver(cdl_number="CDL-V4B")
    set_clock("2026-08-02T12:00:00Z")
    payload = {"kind": "ARRIVED_PICKUP", "occurred_at": "2026-08-02T10:00:00Z",
               "state_code": "TX", "odometer_miles": 100120}
    resp = api_client.create_trip_check_call(
        ctx["trip"]["id"], payload, make_driver_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_DRIVER_MISMATCH)
    own = validate_success(api_client.create_trip_check_call(
        ctx["trip"]["id"], payload,
        make_driver_headers(ctx["driver"]["id"])), expected_status=201)
    assert own["kind"] == "ARRIVED_PICKUP"


def test_driver_role_cannot_create_load(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    targeted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    (PRD §4's table authorizes only LoadPlanner for load tender.)

    Design: Corner/rbac/driver_role_cannot_create_load_rejected
    """
    ctx = setup_refdata(with_national_rate=False)
    driver = create_driver(cdl_number="CDL-B1")
    resp = api_client.create_load(
        {"customer_id": ctx["customer"]["id"], "lane_id": ctx["lane"]["id"],
         "rate_cents": 250000, "weight_lbs": 42000,
         "pickup_appt_at": "2026-08-02T08:00:00Z",
         "delivery_appt_at": "2026-08-03T18:00:00Z"},
        make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_safety_officer_cannot_approve_accessorial(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    targeted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    (PRD §4's table authorizes only LoadPlanner for accessorial approval.)

    Design: Corner/rbac/safety_officer_cannot_approve_accessorial_rejected
    """
    ctx = setup_refdata()
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    charge = create_manual_accessorial(load["id"], type="LUMPER", quantity=3013)
    validate_success(api_client.submit_accessorial(
        charge["id"], {"X-User-ID": "dispatcher-1", "X-User-Role": "Dispatcher"}))
    resp = api_client.approve_accessorial(charge["id"], SAFETY_OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_payroll_clerk_cannot_dispatch_trip(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    targeted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    (PRD §4's table authorizes only Dispatcher for trip dispatch.)

    Design: Corner/rbac/payroll_cannot_dispatch_trip_rejected
    """
    ctx = setup_planned_trip(cdl_number="CDL-B3", unit_number="T-B3")
    resp = api_client.dispatch_trip(ctx["trip"]["id"], PAYROLL_1)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_driver_shared_reads_allowed(api):
    """PRD §2.1: "`Driver` — the driver self-service role: records their own
    duty events, check calls, fuel purchases, and accessorial claims, and reads
    their own settlements and safety record."
    PRD §4: "All roles" means `FleetAdmin`, `LoadPlanner`, `Dispatcher`,
    `SafetyOfficer`, `PayrollClerk`, and `Driver`.

    Design: Corner/rbac/driver_shared_reads_allowed
    """
    driver = create_driver(cdl_number="CDL-B4")
    headers = make_driver_headers(driver["id"])
    fetched = validate_success(api_client.get_driver(driver["id"], headers))
    assert fetched["id"] == driver["id"]
    rows, meta = validate_paginated(api_client.list_loads(headers))
    assert meta["total_count"] == 0
