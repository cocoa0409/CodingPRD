"""Authentication and role-based access control enforcement."""
from test_helpers import (
    ApiErrorId,
    create_dust_sample_payload,
    create_site,
    create_submitted_dha,
    get_site_version,
    setup_site_with_dust,
    validate_error,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
AUDITOR = TEST_USERS["housekeeping_auditor_headers"]
PERFORMER = TEST_USERS["hot_work_performer_headers"]


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "When the `X-User-Role` header is missing or does not match
    one of the eight recognized role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    res = api.list_sites(headers={"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
    assert res.status_code == 401


def test_housekeeping_auditor_cannot_create_dust_sample(api):
    """PRD §2.1: "When the role is recognized but is not permitted to invoke
    the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: POST `/api/sites/{id}/dust-samples` is authorized for
    `ComplianceEngineer` only.

    Design: Corner/validations/wrong_role_returns_unauthorized
    """
    site = create_site(insurer_id="FM-1")
    res = api.create_dust_sample(site["id"], create_dust_sample_payload(),
                                 AUDITOR)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert res.status_code == 403


def test_housekeeping_auditor_cannot_approve_dha(api):
    """PRD §2.1: "When the role is recognized but is not permitted to invoke
    the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: POST `/api/sites/{id}/dhas/{dha_id}/approve` is authorized for
    `ComplianceManager` only.
    PRD §2.10: "**Authorization next**: the role is permitted to invoke this
    endpoint at all." — authorization runs before any state or business rule.

    Design: Corner/rbac/housekeeping_auditor_cannot_approve_dha
    """
    site, sample = setup_site_with_dust(insurer_id="FM-1")
    dha = create_submitted_dha(site["id"], sample["id"], author_id="eng-1")
    assert dha["status"] == "SUBMITTED"

    site_version = get_site_version(site["id"])
    res = api.approve_dha(site["id"], dha["id"], site_version, AUDITOR)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert res.status_code == 403


def test_hotwork_performer_cannot_issue_permit(api):
    """PRD §2.1: "When the role is recognized but is not permitted to invoke
    the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: POST `/api/sites/{id}/hot-work-permits` is authorized for
    `SafetyManager` only.

    Design: Corner/rbac/hotwork_performer_cannot_issue_permit
    """
    site = create_site(insurer_id="FM-1")
    res = api.create_hot_work_permit(
        site["id"],
        {
            "work_description": "W",
            "issuer_id": "sm-1",
            "performer_id": "hp-1",
            "valid_from": "2026-05-01T00:00:00Z",
            "valid_to": "2026-05-01T04:00:00Z",
            "fire_watch_minutes_after": 30,
        },
        PERFORMER)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    assert res.status_code == 403
