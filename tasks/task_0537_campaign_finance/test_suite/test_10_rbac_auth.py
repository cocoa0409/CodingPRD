"""Authentication and role-based authorization on exclusive operations."""
from test_helpers import (
    validate_error, ApiErrorId, NO_AUTH_HEADERS,
    create_committee_payload,
    TEST_USERS, make_treasurer_headers,
    set_clock, register_committee, create_active_committee, add_contribution,
    create_closed_reporting_period, create_draft_report,
)

REGULATOR = TEST_USERS["regulator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
PUBLIC = TEST_USERS["public_headers"]
REGISTRANT = TEST_USERS["registrant_headers"]


def test_public_viewer_cannot_register_committee(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to perform
    the requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/public_viewer_cannot_register_committee
    """
    validate_error(api.create_committee(create_committee_payload(name="X", committee_type="PAC"), PUBLIC),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


def test_treasurer_cannot_approve_committee(api):
    """PRD §4: `POST /disclosure/committees/{id}/approve` is authorized for RegulatorAuditor
    only, so a Treasurer call is unauthorized per §2.1 (ERR_UNAUTHORIZED, 403).

    Design: Corner/rbac/treasurer_cannot_approve_committee
    """
    committee = register_committee(api, name="AppCo", committee_type="PAC")
    resp = api.approve_committee(committee["id"], make_treasurer_headers(committee["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_lobbyregistrant_cannot_void_contribution(api):
    """PRD §2.1: the auditor "is the agency operator responsible for approvals, compliance
    void/flag/clear actions" — a LobbyRegistrant calling void is not permitted and is
    rejected with ERR_UNAUTHORIZED.

    Design: Corner/rbac/lobbyregistrant_cannot_void_contribution
    """
    committee = create_active_committee(api, name="VoidCo", committee_type="PAC")
    con = add_contribution(api, committee["id"], amount_cents=5000)
    validate_error(api.void_contribution(con["id"], REGISTRANT), ApiErrorId.ERR_UNAUTHORIZED.value)


def test_regulator_cannot_file_report(api):
    """PRD §4: `POST /disclosure/reports/{id}/file` is authorized for Treasurer only, so a
    RegulatorAuditor call is unauthorized per §2.1 (ERR_UNAUTHORIZED, 403).

    Design: Corner/rbac/regulator_cannot_file_report
    """
    set_clock(api, "2026-04-10T00:00:00Z")
    committee = create_active_committee(api, name="FileCo", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_closed_reporting_period(api)
    report = create_draft_report(api, cid, period["id"])
    validate_error(api.file_report(report["id"], REGULATOR), ApiErrorId.ERR_UNAUTHORIZED.value)


def test_request_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of the four known
    roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/committee_create_missing_headers_unauthenticated
    """
    resp = api.create_committee(create_committee_payload(name="X", committee_type="PAC"), NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
