"""Corner section: rbac (authorization, ownership, authentication)."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    ANON_HEADERS,
    make_enforcement_officer_headers,
    setup_issuing_context,
    issue_in_context,
    create_officer,
    create_beat,
    create_violation_code,
    create_vehicle,
    open_shift,
)

ADMIN = TEST_USERS["admin_headers"]
MOTORIST = TEST_USERS["motorist_headers"]


def test_motorist_cannot_issue_citation_returns_unauthorized(api):
    """PRD §2.1: "When the role is recognized but is not permitted to perform the
    requested operation under the access matrix, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/motorist_cannot_issue_citation_returns_unauthorized
    """
    ctx = setup_issuing_context()
    validate_error(
        api.create_citation(
            {"vehicle_id": ctx["vehicle"]["id"], "shift_id": ctx["shift"]["id"],
             "violation_code_id": ctx["violation_code"]["id"], "issued_via": "LPR",
             "evidence_photo_url": "https://ev/rb1.jpg"}, MOTORIST),
        ApiErrorId.ERR_UNAUTHORIZED.value)


def test_enforcement_officer_cannot_void_returns_unauthorized(api):
    """PRD §2.1: "When the role is recognized but is not permitted to perform the
    requested operation under the access matrix, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/enforcement_officer_cannot_void_returns_unauthorized
    """
    ctx = setup_issuing_context()
    cit = issue_in_context(ctx)
    validate_error(
        api.void_citation(cit["id"], make_enforcement_officer_headers(ctx["officer"]["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value)


def test_officer_issue_on_other_officers_shift_returns_not_owner(api):
    """PRD §2.1: "an officer may only open or close a shift whose `officer_id` equals
    their `X-User-ID`, and may only issue a citation against a shift they own. A
    mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/officer_issue_on_other_officers_shift_returns_not_owner
    """
    officer_a = create_officer(badge_number="B-RB3A", full_name="Officer A")
    officer_b = create_officer(badge_number="B-RB3B", full_name="Officer B")
    beat = create_beat(patrol_zone="RESIDENTIAL", beat_code="RBB3")
    vc = create_violation_code(code="EXP_METER", base_fine_cents=5000)
    vehicle = create_vehicle(plate="RB3PLT")
    shift = open_shift(officer_a["id"], beat["id"])
    # Officer B issues against Officer A's shift.
    validate_error(
        api.create_citation(
            {"vehicle_id": vehicle["id"], "shift_id": shift["id"],
             "violation_code_id": vc["id"], "issued_via": "LPR",
             "evidence_photo_url": "https://ev/rb3.jpg"},
            make_enforcement_officer_headers(officer_b["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or does not name one of these
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    validate_error(
        api.create_officer({"badge_number": "B-RB4", "full_name": "Ghost"}, ANON_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value)
