"""Optimistic concurrency on reservation creation and role/ownership security.

Translates queue-B Corner `cross_cutting_complexity_layers` (OCC) and `rbac`
instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, build_user_headers, make_employee_headers,
    create_reservation_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["facility_manager_headers"]


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers — optimistic concurrency
# ---------------------------------------------------------------------------
def test_stale_seat_version_rejected(api):
    """PRD §2.10: "If the supplied value does not equal the current version of
    that seat or room — meaning another writer has advanced it since the client
    read it, for instance by booking the same resource or by pulling a seat out of
    service, leaving the client's overlap check based on a stale view — the create
    is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_seat_version_rejected
    """
    env = fx.setup_floor_plan(level=22, clock_date="2026-08-19", clock_minute=500)
    seat_id = env["seat"]["id"]
    stale_version = env["seat"]["version"]  # version observed before any booking
    emp_a = fx.create_employee(team_code="ENG")
    emp_b = fx.create_employee(team_code="ENG")
    # emp_a books the seat -> its version advances past stale_version
    fx.create_seat_reservation(emp_a["id"], seat_id, "2026-08-19", 600, 660,
                               expected_seat_version=stale_version)
    # emp_b creates carrying the now-stale version
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_b["id"], resource_type="SEAT", seat_id=seat_id,
            booking_date="2026-08-19", start_minute=700, end_minute=760,
            expected_seat_version=stale_version),
        make_employee_headers(emp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_fresh_seat_version_succeeds_and_bumps(api):
    """PRD §2.10: "When the booked resource is a desk, the create request carries
    expected_seat_version, the version of the target Seat that the client last
    observed".
    PRD §3.4: "committing a SEAT reservation advances the booked seat's version by
    one".

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_seat_version_succeeds_and_bumps
    """
    env = fx.setup_floor_plan(level=23, clock_date="2026-08-20", clock_minute=500)
    seat_id = env["seat"]["id"]
    v0 = env["seat"]["version"]
    emp_id = env["employee"]["id"]
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_id, resource_type="SEAT", seat_id=seat_id,
            booking_date="2026-08-20", start_minute=600, end_minute=660,
            expected_seat_version=v0),
        make_employee_headers(emp_id))
    validate_success(resp, expected_status=201)
    seat_after = get_success_data(api.get_seat(seat_id, FM))
    assert seat_after["version"] == v0 + 1


def test_stale_room_version_rejected(api):
    """PRD §2.10: "when the booked resource is a meeting room, it instead carries
    expected_room_version, the last observed version of the target Room. If the
    supplied value does not equal the current version of that seat or room ... the
    create is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_room_version_rejected
    """
    floor, room, emp_a, emp_b = fx.setup_room_floor(
        level=24, turnover_buffer_minute=15, clock_date="2026-08-21", clock_minute=500)
    room_id = room["id"]
    stale_version = room["version"]
    fx.create_room_reservation(emp_a["id"], room_id, "2026-08-21", 600, 660,
                               expected_room_version=stale_version)
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=emp_b["id"], resource_type="ROOM", room_id=room_id, seat_id=None,
            booking_date="2026-08-21", start_minute=800, end_minute=860,
            expected_room_version=stale_version),
        make_employee_headers(emp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Corner: rbac — role / ownership / authentication
# ---------------------------------------------------------------------------
def test_employee_cannot_approve_amenity_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."
    PRD §3.5: "Approve and deny are FacilityManager-only".

    Design: Corner/rbac/employee_cannot_approve_amenity_forbidden
    """
    env, resv = fx.setup_checked_in_reservation(
        booking_date="2026-08-17", start_minute=540, end_minute=600, checkin_minute=545, level=20)
    emp_id = env["employee"]["id"]
    line = fx.add_amenity_line(resv["id"], emp_id, "MONITOR", 1000, 1)
    # an Employee (not FacilityManager) attempts to approve the line
    resp = api.approve_amenity(line["id"], make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_employee_cannot_check_in_other_employees_reservation(api):
    """PRD §2.1: "checking in, completing, or cancelling a reservation, and adding
    or cancelling an amenity line, require the parent reservation's employee_id to
    equal X-User-ID ... An ownership failure for an entity_backed actor is reported
    as ERR_FORBIDDEN."

    Design: Corner/rbac/employee_cannot_check_in_other_employees_reservation_forbidden
    """
    env = fx.setup_floor_plan(level=21, clock_date="2026-08-18", clock_minute=545)
    emp_a = env["employee"]
    emp_b = fx.create_employee(team_code="ENG")
    resv = fx.create_seat_reservation(emp_a["id"], env["seat"]["id"], "2026-08-18", 540, 600)
    # employee B (not the owner) attempts the check-in
    resp = api.checkin_reservation(resv["id"], make_employee_headers(emp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing or blank, or if X-User-Role is not
    one of the recognized roles, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    site = fx.create_site(name="HQc22")
    ghost_headers = build_user_headers("ghost-1", "Ghost")  # unrecognized role
    resp = api.get_site(site["id"], ghost_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
