"""CRUD, input validation, pagination, and RBAC.

Translations of SCAFFOLD_CORNER_DESIGN.yaml queue B sections `entities` and `rbac`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, TEST_USERS, build_user_headers,
    create_client_payload, create_asset_payload,
    assert_client,
)
from test_helpers import create_client, create_draft_engagement, create_asset

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
SOC = TEST_USERS["soc_analyst_headers"]
CONTACT = TEST_USERS["client_contact_headers"]


def test_create_client_opens_period_zero_ledger(api):
    """PRD §3.1: "Creating the client also opens the first retainer ledger: an
    OPEN RetainerLedger for period 0 whose hours_granted equals the client's
    retainer_hours_per_period."
    PRD §3.1: "The new client starts with status ACTIVE, a current_period_index
    of 0, a posture of OPEN, and an open_critical_findings count of 0."

    Design: Corner/entities/create_client_returns_201_with_open_ledger
    """
    res = api.create_client(
        create_client_payload(name="Acme", tier="ADVANCED", retainer_hours_per_period=80),
        ADMIN)
    client = validate_success(res, 201)
    assert_client(client)
    assert client["tier"] == "ADVANCED"
    assert client["current_period_index"] == 0
    assert client["status"] == "ACTIVE"

    led = api.list_retainer_ledgers(
        ADMIN, params={"client_id": client["id"], "period_index": 0})
    rows, _meta = validate_paginated(led)
    assert len(rows) == 1, "exactly one period-0 ledger must exist"
    assert rows[0]["hours_granted"] == 80
    assert rows[0]["status"] == "OPEN"


def test_get_client_nonexistent_returns_not_found(api):
    """PRD §2.5: "When a request carries a resource id in its path, that id must
    resolve to an existing resource or the request is rejected with ERR_NOT_FOUND
    (HTTP 404)."

    Design: Corner/entities/get_client_nonexistent_returns_not_found
    """
    res = api.get_client("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_asset_missing_hostname_returns_invalid_request(api):
    """PRD §3.2: "An asset is registered by a PlatformAdmin or EngagementLead
    against a client, carrying the asset's client_id, hostname, ip_address,
    business criticality ... and optionally its exposure."
    PRD §2.10: "a malformed body surfaces as ERR_INVALID_REQUEST."

    Design: Corner/entities/create_asset_missing_required_field_returns_invalid_request
    """
    client = create_client()
    payload = create_asset_payload(client["id"])
    del payload["hostname"]
    res = api.create_asset(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_asset_invalid_criticality_enum_returns_invalid_request(api):
    """PRD §3.2: "business criticality — one of LOW, MEDIUM, HIGH, or CROWN_JEWEL."
    PRD §2.10: "then request-body shape and enum validity ... a malformed body
    surfaces as ERR_INVALID_REQUEST."

    Design: Corner/entities/create_asset_invalid_enum_criticality_returns_invalid_request
    """
    client = create_client()
    res = api.create_asset(
        create_asset_payload(client["id"], hostname="h1", criticality="SUPREME"), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_asset_default_exposure_is_internal(api):
    """PRD §3.2: "optionally its exposure, which is INTERNAL by default but may be
    EXTERNAL."

    Design: Corner/entities/asset_default_exposure_internal_applied
    """
    client = create_client()
    res = api.create_asset(
        create_asset_payload(client["id"], hostname="h-def", criticality="LOW"), ADMIN)
    asset = validate_success(res, 201)
    assert asset["exposure"] == "INTERNAL"


def test_create_finding_nonexistent_scan_returns_fk_not_found(api):
    """PRD §2.5: "When a create request carries a foreign-key field in its body,
    that key must reference an existing resource owned by the same client, or the
    request is rejected with ERR_FK_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/create_finding_fk_not_found_wrong_client_scan
    """
    client = create_client()
    asset = create_asset(client["id"], hostname="fk-01", criticality="LOW")
    res = api.create_finding(
        {"scan_id": "00000000-0000-4000-8000-000000000001",
         "asset_id": asset["id"], "title": "x", "cvss_base": 5.0},
        TEST_USERS["soc_analyst_headers"])
    validate_error(res, "ERR_FK_NOT_FOUND")


def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "The pagination fields surfaced in the response meta are limit,
    offset, total_count, and has_more, where total_count is the count of all
    matching rows before the page window is applied and has_more is true when rows
    remain beyond the returned page."

    Design: Corner/entities/list_clients_pagination_envelope_fields
    """
    create_client(name="C1", retainer_hours_per_period=10)
    create_client(name="C2", retainer_hours_per_period=10)
    rows, meta = validate_paginated(api.list_clients(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(rows) == 1


def test_list_clients_limit_over_max_returns_invalid_pagination(api):
    """PRD §2.3: "A limit outside the inclusive range of 1 through 100, or a
    negative offset, is rejected with ERR_INVALID_PAGINATION (HTTP 400)."

    Design: Corner/entities/list_clients_invalid_pagination_returns_error
    """
    res = api.list_clients(ADMIN, params={"limit": 500, "offset": 0})
    validate_error(res, "ERR_INVALID_PAGINATION")


# ─── RBAC ──────────────────────────────────────────────────────────────────

def test_socanalyst_cannot_create_client(api):
    """PRD §4 endpoint table: POST /clients authorized role is PlatformAdmin.
    PRD §2.1: "If the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/socanalyst_cannot_create_client
    """
    res = api.create_client(
        create_client_payload(name="Nope", retainer_hours_per_period=10), SOC)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_engagementlead_cannot_authorize_engagement(api):
    """PRD §3.3: "Authorization is the gate that commits budget, and only a
    ClientContact may sign it, advancing the engagement DRAFT → AUTHORIZED."
    PRD §2.1: "the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/engagementlead_cannot_authorize_engagement
    """
    client = create_client()
    asset = create_asset(client["id"], hostname="rb2-01", criticality="MEDIUM")
    eng = create_draft_engagement(client["id"], [asset["id"]])
    res = api.authorize_engagement(eng["id"], LEAD)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    known roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_clients(build_user_headers("nobody-1", "NobodyRole"))
    validate_error(res, "ERR_UNAUTHENTICATED")
