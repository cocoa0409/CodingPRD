"""Role-based access control, authentication, and pagination/listing."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    make_officer_headers, make_student_headers,
    build_user_headers,
    create_student, create_building, create_room, create_cycle,
    create_submitted_application, run_lottery, open_assignment,
)

OFFICER = make_officer_headers()


# ─── RBAC denials ─────────────────────────────────────────────────────────────

def test_student_cannot_run_lottery(api):
    """PRD §2.1: "When a recognized, authenticated caller attempts an operation
    their role is not permitted to perform — or attempts to act on a resource
    they do not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/student_cannot_run_lottery
    """
    student = create_student(full_name="Sneaky S", class_year="SENIOR",
                             gender_identity="MALE", lottery_number=410)
    cycle = create_cycle(term_label="RBAC_T")
    res = api.run_lottery(cycle["id"], make_student_headers(student["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_housing_officer_cannot_file_incident(api):
    """PRD §2.1: "When a recognized, authenticated caller attempts an operation
    their role is not permitted to perform — or attempts to act on a resource
    they do not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/housing_officer_cannot_file_incident
    """
    ra = create_student(full_name="RA Real", class_year="SENIOR",
                        gender_identity="MALE", lottery_number=420)
    building = create_building(name="RBAC Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="RB1", room_type="SINGLE")
    # POST /incident-reports is ResidentAdvisor-exclusive (PRD §4 table).
    res = api.create_incident_report(
        {"room_id": room["id"], "reporter_student_id": ra["id"], "severity": "MINOR"},
        OFFICER)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_student_cannot_accept_another_students_offer(api):
    """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the
    acting `Student`; ownership checks on any resource that references a `Student`
    compare the resource's student foreign key to `X-User-ID`."
    PRD §2.1: "When a recognized, authenticated caller attempts an operation their
    role is not permitted to perform — or attempts to act on a resource they do
    not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/student_cannot_accept_another_students_offer
    """
    owner = create_student(full_name="Owner A", class_year="SENIOR",
                           gender_identity="MALE", lottery_number=430)
    intruder = create_student(full_name="Intruder B", class_year="SENIOR",
                              gender_identity="MALE", lottery_number=431)
    building = create_building(name="Own Hall", building_type="TRADITIONAL")
    create_room(building["id"], room_number="OW1", room_type="SINGLE")
    cycle = create_cycle(term_label="OWN_T")
    app = create_submitted_application(cycle["id"], owner["id"],
                                       preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    current = validate_success(api.get_application(app["id"], OFFICER), 200)
    # Intruder B (different student) attempts to accept A's OFFERED application.
    res = api.accept_application(
        app["id"], {"expected_application_version": current["version"]},
        make_student_headers(intruder["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    after = validate_success(api.get_application(app["id"], OFFICER), 200)
    assert after["status"] == "OFFERED"


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role`
    that is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401); the same error applies when an entity-backed role omits `X-User-ID`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.create_building(
        {"name": "Anon Hall", "building_type": "TRADITIONAL"},
        {"Content-Type": "application/json"})  # no X-User-Role / X-User-ID
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Pagination & listing ─────────────────────────────────────────────────────

def test_pagination_limit_out_of_bounds_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative
    `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 400)."

    Design: Corner/validations/pagination_limit_out_of_bounds_rejected
    """
    res = api.list_applications(OFFICER, params={"limit": 500})
    validate_error(res, "ERR_VALIDATION_PAGINATION", expected_status=400)


def test_list_rooms_by_building_paginated(api):
    """PRD §3.1: "Rooms may be listed under their building as a convenience
    sub-resource view, and may also be listed across the system filtered by
    `building_id`; a single room may be fetched directly."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_rooms_by_building_paginated
    """
    building = create_building(name="ListB Hall", building_type="TRADITIONAL")
    create_room(building["id"], room_number="L1", room_type="SINGLE")
    create_room(building["id"], room_number="L2", room_type="DOUBLE")
    data, meta = validate_paginated(
        api.list_rooms(OFFICER, params={"building_id": building["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2
    for room in data:
        assert room["building_id"] == building["id"]
