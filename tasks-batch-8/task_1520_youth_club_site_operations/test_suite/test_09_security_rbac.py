"""Authentication, role authorization, and pipeline precedence."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    apply_for_membership,
    create_active_member,
    create_claim,
    create_site_payload,
    director_headers,
    get_member,
    make_frontline_staff_headers,
    setup_site_with_director,
    setup_site_with_director_and_frontline,
    validate_error,
    validate_success,
)


def test_unauthenticated_missing_headers(api):
    """PRD 2.1: "A request with a missing or unknown role header, a missing
    user-id header, or an entity-backed identity that does not resolve to a
    matching `ACTIVE` Staff row is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/c_unauthenticated_missing_headers
    """
    res = api.create_site(create_site_payload(name="NoAuth"), headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_unauthenticated_beats_not_found(api):
    """PRD 2.8: "Every request is validated against a fixed, ten-stage
    pipeline, and the first failing stage determines the error returned." —
    authentication (stage 1) precedes resource resolution (stage 3), so an
    unauthenticated read of a nonexistent id yields 401, never 404.

    Design: Corner/validations/c_unauthenticated_beats_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
    assert res.json()["data"]["error_id"] != "ERR_NOT_FOUND"


def test_decide_frontline_role_unauthorized(api):
    """PRD 2.1: "A request whose authenticated role is not listed among the
    endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." PRD Section 4: `POST /members/{id}/decide` is authorized for
    `SiteDirector` only.

    Design: Corner/rbac/c_decide_frontline_role_unauthorized
    """
    site, director, frontline = setup_site_with_director_and_frontline()
    member = apply_for_membership(site["id"], director["id"], legal_name="Kid A")
    res = api.decide_member(
        member["id"], {"decision": "APPROVE"},
        make_frontline_staff_headers(frontline["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert get_member(member["id"])["status"] == "APPLIED"


def test_claim_approve_by_director_role_unauthorized(api):
    """PRD 2.1: "A request whose authenticated role is not listed among the
    endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." PRD Section 4: `POST /meal-claims/{id}/approve` is authorized
    for `StateAgencyReviewer` only; the role check (stage 2) precedes the
    state check (stage 5).

    Design: Corner/rbac/c_claim_approve_by_director_role_unauthorized
    """
    site, director = setup_site_with_director()
    claim = create_claim(site["id"], director["id"], "2026-08")
    res = api.approve_meal_claim(claim["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert res.json()["data"]["error_id"] != "ERR_CLAIM_NOT_SUBMITTED"


def test_platformadmin_cannot_sign_in_members(api):
    """PRD 2.1: "A request whose authenticated role is not listed among the
    endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)." PRD Section 4: `POST /attendance-records` is authorized for
    `SiteDirector` and `FrontlineStaff` only; the role check (stage 2) precedes
    resource resolution (stage 3).

    Design: Corner/rbac/c_platformadmin_cannot_sign_in_members
    """
    res = api.create_attendance_record(
        {"club_day_id": NON_EXISTENT_UUID, "member_id": NON_EXISTENT_UUID},
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert res.json()["data"]["error_id"] != "ERR_NOT_FOUND"
