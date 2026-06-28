"""Role-based access control: forbidden-role denial, resource-owner enforcement,
and unauthenticated requests.

All instances come from the corner-design rbac section.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_member, create_membership, register_certification, set_clock,
    grade_payload, make_member_headers, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]
EX = TEST_USERS["examiner_headers"]


# ─── Exclusive-operation denial ───────────────────────────────────────────
def test_member_cannot_create_facility(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §4: "POST /facilities | Create a climbing facility / wall | GymAdmin"

    Design: Corner/rbac/member_cannot_create_facility
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    res = api.create_facility({
        "name": "Rogue Wall", "floor_capacity": 5, "requires_belay_cert": False,
    }, make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_frontdesk_cannot_grade_certification(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §4: "POST /certifications/{id}/grade | Grade a registered certification
    (pass or fail) | Examiner"

    Design: Corner/rbac/frontdesk_cannot_grade_certification
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    cert = register_certification(member["id"], discipline="BELAY")
    res = api.grade_certification(cert["id"], grade_payload(90, 85, 70, 95), FD)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── Resource-owner enforcement ───────────────────────────────────────────
def test_member_cannot_freeze_other_members_membership(api):
    """PRD §2.1: "A Member may only act on resources they own; when a Member
    attempts a mutation on a membership or enrollment whose member_id does not
    equal their X-User-ID, the request is rejected with ERR_NOT_RESOURCE_OWNER
    (HTTP 403)."

    Design: Corner/rbac/member_cannot_freeze_other_members_membership
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_member(email="owner-b@x.com")
    intruder = create_member(email="intruder-a@x.com")
    membership = create_membership(owner["id"], plan_tier="BASIC")
    res = api.freeze_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        make_member_headers(intruder["id"]))  # acting as the wrong member
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─── Unauthenticated request ──────────────────────────────────────────────
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two headers identifying the caller:
    X-User-ID and X-User-Role. If either header is missing, the request is
    rejected with ERR_UNAUTHENTICATED (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    res = api.get_member(member["id"], headers={})  # no auth headers
    validate_error(res, "ERR_UNAUTHENTICATED")
