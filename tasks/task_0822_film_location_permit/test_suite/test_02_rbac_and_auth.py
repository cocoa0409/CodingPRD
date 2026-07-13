"""Authentication and role-based access control, translated from the corner-design index."""
import test_helpers as th
from test_helpers import validate_error, ApiErrorId, NO_AUTH_HEADERS


def test_production_company_denied_creating_department(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to invoke the
    requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "FilmOfficeCoordinator — the municipal film-office operator who onboards
    companies, officers, departments, and street segments ..."

    Design: Corner/rbac/peer_role_denied_creating_department
    """
    pc = th.make_company(api, legal_name="Rbac Co", contact_email="rb@x.test", primary_contact="HH")
    resp = api.create_department(
        {"code": "PARKING", "name": "Parking", "trigger_condition": "PARKING_ONLY"},
        th.make_production_company_headers(pc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_unauthenticated_missing_headers_on_create(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role is not one of the four roles
    below, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_headers_on_create
    """
    resp = api.create_production_company(
        {"legal_name": "NoAuth", "contact_email": "na@x.test", "primary_contact": "II"},
        NO_AUTH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
