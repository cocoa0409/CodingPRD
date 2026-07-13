"""Role-based access control and ownership enforcement."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    make_passenger_headers,
)
from test_helpers import fixtures as fx
from test_helpers.fixtures import CONDUCTOR


def test_conductor_cannot_purchase_ticket_returns_unauthorized(api):
    """PRD 2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/conductor_cannot_purchase_ticket_returns_unauthorized
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    resp = api.create_ticket(
        {"passenger_id": pax["id"], "fare_product_id": fp["id"], "travel_period": "PEAK"},
        CONDUCTOR,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_passenger_cannot_issue_citation_returns_unauthorized(api):
    """PRD 2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/passenger_cannot_issue_citation_returns_unauthorized
    """
    fx.set_clock(api)
    pax = fx.create_passenger(api)
    insp = fx.create_inspection(api, pax["id"], 3)  # EVASION (no ticket)
    resp = api.create_citation(
        {"inspection_id": insp["id"], "passenger_id": pax["id"]},
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_passenger_cannot_activate_others_ticket_returns_not_owner(api):
    """PRD 2.1: "a rider may act only on their own tickets, applications, refund requests,
    and citations. When a passenger acts on a resource owned by a different passenger, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/passenger_cannot_activate_others_ticket_returns_not_owner
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax_a = fx.create_passenger(api)
    pax_b = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax_a["id"], fp["id"], "PEAK")
    resp = api.activate_ticket(tkt["id"], make_passenger_headers(pax_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    fx.set_clock(api)
    pax = fx.create_passenger(api)
    resp = api.get_passenger(pax["id"], {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
