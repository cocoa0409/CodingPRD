"""Authentication, endpoint authorisation and the cross-client ownership gate."""
from test_helpers import (
    DE_RULE_MIN,
    NO_AUTH_HEADERS,
    OFFICER,
    ApiErrorId,
    create_client_payload,
    draft_obligation_filing,
    headers_with_role,
    make_client_contact_headers,
    new_client,
    new_entity,
    new_obligation,
    read_filing,
    setup_pending_home_registration,
    validate_error,
    validate_success,
)


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint, without exception, must carry two
    headers: `X-User-ID` and `X-User-Role`. If either header is absent, or present but
    blank, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/corner_missing_auth_headers_returns_unauthenticated
    """
    response = api.create_client(create_client_payload(), NO_AUTH_HEADERS)

    assert response.status_code == 401
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_role_outside_the_declared_five_is_unauthenticated(api):
    """PRD §2.1: "The same `ERR_UNAUTHENTICATED` and HTTP 401 is returned when
    `X-User-Role` carries a string that is not one of the five declared roles."
    PRD §2.9: "`X-User-Role` carries one of the five declared roles: `PlatformAdmin`,
    `ComplianceOfficer`, `FilingAgent`, `SopHandler` or `ClientContact`. Applies to
    every endpoint. Failure returns `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_unknown_role_value_returns_unauthenticated
    """
    response = api.create_client(
        create_client_payload(), headers_with_role("Auditor", "auditor-1")
    )

    assert response.status_code == 401
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_sop_handler_is_not_permitted_on_the_admin_surface(api):
    """PRD §2.1: "If the acting role is well formed but is not listed among the roles
    permitted for the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403."
    PRD §2.1: "**`SopHandler`** runs the service-of-process mailroom: it records receipt
    of served papers, scans them, forwards them to the client, and raises escalations
    when the client does not acknowledge."

    Design: Corner/rbac/corner_sop_handler_cannot_create_a_client
    """
    handler = headers_with_role("SopHandler", "sop-3")

    creation = api.create_client(create_client_payload(), handler)
    assert creation.status_code == 403
    validate_error(creation, ApiErrorId.ERR_UNAUTHORIZED.value)

    listing = api.list_state_rules(handler)
    assert listing.status_code == 403
    validate_error(listing, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_compliance_officer_may_never_lodge_a_filing(api):
    """PRD §2.1: "It may never lodge with a jurisdiction a filing it prepared."
    PRD §2.1: "If the acting role is well formed but is not listed among the roles
    permitted for the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/corner_compliance_officer_cannot_submit_a_filing
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    filing = draft_obligation_filing(obligation, "ANNUAL_REPORT")

    response = api.submit_filing(filing["id"], OFFICER)

    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert read_filing(filing["id"])["status"] == "DRAFT"


def test_client_contact_cannot_reach_another_clients_entity(api):
    """PRD §2.1: "When a `ClientContact` addresses a resource that resolves to a
    different client, the request is rejected with `ERR_CROSS_CLIENT_ACCESS` and HTTP
    403."
    PRD §2.9: "when the acting role is `ClientContact`, `X-User-ID` equals the `id` of
    the `Client` that owns the addressed resource, resolved through the legal-entity and
    registration chain."

    Design: Corner/rbac/corner_client_contact_cannot_read_another_clients_entity
    """
    client_a = new_client()
    client_b = new_client(legal_name="Beacon Holdings", billing_email="ap@beacon.example")
    entity_a = new_entity(client_a["id"])
    entity_b = new_entity(
        client_b["id"], legal_name="Southwind Widgets LLC", formation_date="2026-02-15"
    )
    contact_a = make_client_contact_headers(client_a["id"])

    blocked = api.get_legal_entity(entity_b["id"], contact_a)
    assert blocked.status_code == 403
    validate_error(blocked, ApiErrorId.ERR_CROSS_CLIENT_ACCESS.value)

    own = validate_success(api.get_legal_entity(entity_a["id"], contact_a))
    assert own["legal_name"] == "Northwind Widgets LLC"
