"""Role-based access control (PRD §2.1, §2.7)."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, get_success_data, validate_error

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_buyer_payload,
    create_contractor_payload,
    create_landowner_payload,
    create_tract_payload,
    make_buyer_headers,
    make_contractor_headers,
    make_landowner_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_tract_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/create_tract_missing_auth_headers_unauthenticated
    """
    resp = api._request(
        "POST",
        "/forestry/tracts",
        create_tract_payload(landowner_id=NON_EXISTENT_UUID, forester_id=NON_EXISTENT_UUID),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_buyer_cannot_create_cruise(api):
    """PRD §2.1: "If the role is declared but not listed among the roles
    authorized for the target endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_create_cruise
    """
    buyer = get_success_data(api.create_buyer(create_buyer_payload(), ADMIN))
    bh = make_buyer_headers(buyer["id"])
    resp = api.create_cruise(
        {
            "stand_id": NON_EXISTENT_UUID,
            "cruise_date": "2026-03-01",
            "plots": [{"plot_number": 1, "species": "PINE", "volume_bf": 1165}],
        },
        bh,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_contractor_cannot_verify_ticket(api):
    """PRD §2.1: "If the role is declared but not listed among the roles
    authorized for the target endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/contractor_cannot_verify_ticket
    """
    contractor = get_success_data(api.create_contractor(create_contractor_payload(), ADMIN))
    ch = make_contractor_headers(contractor["id"])
    resp = api.verify_scale_ticket(NON_EXISTENT_UUID, ch)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_landowner_cannot_close_inspection(api):
    """PRD §2.1: "If the role is declared but not listed among the roles
    authorized for the target endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/landowner_cannot_close_inspection
    """
    landowner = get_success_data(api.create_landowner(create_landowner_payload(), ADMIN))
    lh = make_landowner_headers(landowner["id"])
    resp = api.close_inspection(NON_EXISTENT_UUID, {"outcome": "COMPLIANT"}, lh)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_verify_nonexistent_ticket_not_found(api):
    """PRD §2.8: "`ERR_TICKET_NOT_FOUND` for a scale ticket".

    Design: Corner/validations/verify_nonexistent_ticket_not_found
    """
    from test_helpers import create_forester_payload, make_forester_headers

    forester = get_success_data(api.create_forester(create_forester_payload(), ADMIN))
    fh = make_forester_headers(forester["id"])
    resp = api.verify_scale_ticket(NON_EXISTENT_UUID, fh)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_FOUND)
