"""Role-based access control: forbidden-role denials, ownership denial on
guardian-owned resources, and unauthenticated rejection.

Covers corner rbac instances guardian_cannot_create_session,
instructor_cannot_accept_showcase_entry, guardian_cannot_act_on_other_guardians_member,
and missing_auth_headers_unauthenticated.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    create_accept_payload, build_user_headers,
    setup_catalogue, create_guardian, create_member, submit_entry,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


# ─── Corner / rbac / guardian_cannot_create_session ─
def test_guardian_cannot_create_session(api):
    """PRD §2.1: "When an authenticated caller attempts an operation that its role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /sessions is authorized for CenterAdmin only.

    Design: Corner/rbac/guardian_cannot_create_session
    """
    center = get_success_data(api.create_center(
        {"name": "C1", "device_count": 20, "min_student_instructor_ratio": 6}, ADMIN))
    program = get_success_data(api.create_program(
        {"name": "P", "code": "RB1", "min_age": 4, "max_age": 18, "drop_in_fee_cents": 4000},
        ADMIN))
    guardian = create_guardian()
    res = api.create_session(
        {"center_id": center["id"], "program_id": program["id"], "format": "AFTER_SCHOOL",
         "week_count": 1, "starts_at": "2026-05-01T16:00:00Z", "ends_at": "2026-05-01T18:00:00Z",
         "device_seats_requested": 1, "assigned_instructor_count": 2},
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── Corner / rbac / instructor_cannot_accept_showcase_entry ─
def test_instructor_cannot_accept_showcase_entry(api):
    """PRD §2.1: "When an authenticated caller attempts an operation that its role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /showcase-entries/{id}/accept is authorized for CenterAdmin only.

    Design: Corner/rbac/instructor_cannot_accept_showcase_entry
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 5, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    opened = get_success_data(api.open_showcase(created["id"], ADMIN))
    entry = submit_entry(guardian["id"], opened["id"], member["id"])
    res = api.accept_showcase_entry(entry["id"], create_accept_payload(opened["version"]),
                                    INSTRUCTOR)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── Corner / rbac / guardian_cannot_act_on_other_guardians_member ─
def test_guardian_cannot_read_other_guardians_member_progress(api):
    """PRD §2.1: "When a guardian acts on a resource it does not own under any of these
    chains, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "This ownership check guards the following guardian-scoped operations
    specifically: creating an enrollment, cancelling an enrollment, creating a membership,
    activating, pausing, resuming, or cancelling a membership, creating a member, reading a
    member's progress, creating a showcase entry, and withdrawing a showcase entry."

    Design: Corner/rbac/guardian_cannot_act_on_other_guardians_member
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    g1 = create_guardian()
    g2 = create_guardian()
    member = create_member(g1["id"], program["id"])
    res = api.get_member_progress(member["id"], make_guardian_headers(g2["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─── Corner / rbac / missing_auth_headers_unauthenticated ─
def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a
    recognized role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The
    system recognizes exactly three roles, spelled precisely as follows: `CenterAdmin`,
    `Instructor`, and `Guardian`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.create_center(
        {"name": "C1", "device_count": 20, "min_student_instructor_ratio": 6},
        build_user_headers("nobody-1", "NobodyRole"),
    )
    validate_error(res, "ERR_UNAUTHENTICATED")
