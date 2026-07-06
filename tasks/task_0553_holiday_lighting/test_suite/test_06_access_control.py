"""Customer registration basics and role-based / ownership access control.

Covers customer creation and lookup, required-field and not-found handling, role
authorization (401 unauthenticated, 403 unauthorized), and the two entity-backed
ownership gates (Customer accept, CrewLead start).
"""
from test_helpers import (
    validate_success, validate_error, build_user_headers, ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    create_customer, create_crew, create_route_day, create_job, book_assignment,
    dispatch_route_day, setup_active_contract, setup_quoted_estimate,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_customer_payload
from test_helpers.test_users import make_customer_headers, make_crewlead_headers

SALES = TEST_USERS["salesrep_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]


def _route_day_version(route_day_id):
    rd = validate_success(api_client.get_route_day(route_day_id, DISPATCH), 200)
    return rd["version"]


# ── Corner/entities/customer_create_returns_all_fields ───────────────────────

def test_customer_create_returns_echoed_and_computed_fields(api):
    """PRD §3.1: "A `SalesRep` opens the relationship by registering a property owner,
    supplying the owner's `name`, the `service_address` of the property to be lit, and the
    total measured `roofline_feet` of that property (a non-negative integer)."
    PRD §3.1: "A newly registered customer starts in `ACTIVE` account `status` (the
    alternative being `INACTIVE`) and with an `outstanding_balance_cents` of 0."

    (The scaffold's version==1 assertion is omitted: PRD §2.5 pins only that version
    "begins at its initial value on creation and increments by one on every mutation",
    never the literal initial value, so a specific starting integer is not uniquely
    derivable from PRD prose.)

    Design: Corner/entities/customer_create_returns_all_fields
    """
    data = validate_success(api.create_customer(create_customer_payload(
        name="Test Owner", service_address="100 Main St", roofline_feet=200), SALES), 201)
    assert data["name"] == "Test Owner", data
    assert data["roofline_feet"] == 200, data
    assert data["outstanding_balance_cents"] == 0, data
    assert data["status"] == "ACTIVE", data


# ── Corner/entities/customer_missing_required_field_returns_invalid_request ───

def test_customer_missing_roofline_feet_rejected(api):
    """PRD §2.8: "the system validates the request body itself: required fields must be
    present, enum fields must carry one of their allowed values, and integer fields must
    satisfy their declared bounds. A failure here is reported as `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/customer_missing_required_field_returns_invalid_request
    """
    resp = api.create_customer(
        {"name": "No Roof", "service_address": "101 Main St"}, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ── Corner/entities/get_nonexistent_customer_returns_not_found ───────────────

def test_get_unknown_customer_returns_not_found(api):
    """PRD §2.7: "Each entity has its own not-found code — for example a missing customer
    yields `ERR_CUSTOMER_NOT_FOUND`"
    PRD §2.7: "each returned with HTTP 404."

    Design: Corner/entities/get_nonexistent_customer_returns_not_found
    """
    resp = api.get_customer("00000000-0000-4000-8000-000000000000", SALES)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)


# ── Corner/rbac/dispatcher_create_customer_returns_unauthorized ──────────────

def test_dispatcher_cannot_create_customer(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    POST /customers is a SalesRep operation; a Dispatcher is refused.

    Design: Corner/rbac/dispatcher_create_customer_returns_unauthorized
    """
    resp = api.create_customer(create_customer_payload(
        name="X", service_address="125 Main St", roofline_feet=100), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


# ── Corner/rbac/missing_role_create_customer_returns_unauthenticated ─────────

def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or does not name a role the system
    recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_create_customer_returns_unauthenticated
    """
    headers = {"X-User-ID": "anon", "Content-Type": "application/json"}
    resp = api.create_customer(create_customer_payload(
        name="X", service_address="126 Main St", roofline_feet=100), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ── Corner/rbac/customer_accept_estimate_not_owner_returns_unauthorized ──────

def test_non_owner_customer_cannot_accept_estimate(api):
    """PRD §2.1: "accepting a quoted estimate requires that the estimate's `customer_id`
    equal the caller's `X-User-ID`"
    PRD §3.2: "the acting `Customer`'s `X-User-ID` must equal the estimate's `customer_id`
    or the request is rejected as unauthorized."

    A different customer accepting the quoted estimate is refused, and the estimate stays
    QUOTED.

    Design: Corner/rbac/customer_accept_estimate_not_owner_returns_unauthorized
    """
    owner_id, quoted = setup_quoted_estimate(product_line="SEASONAL",
                                             estimated_footage=100,
                                             roofline_complexity="SIMPLE")
    other = create_customer(name="Owner B", service_address="128 Main St",
                            roofline_feet=100)
    resp = api.accept_estimate(quoted["id"], make_customer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    est = validate_success(api.get_estimate(quoted["id"], SALES), 200)
    assert est["status"] == "QUOTED", est


# ── Corner/rbac/crewlead_start_job_wrong_crew_returns_unauthorized ───────────

def test_wrong_crew_lead_cannot_start_job(api):
    """PRD §3.4: "the acting crew lead owns that route day's crew, meaning the route day's
    `crew_id` equals the caller's `X-User-ID`."
    PRD §2.1: "A violation of either ownership rule is reported as `ERR_UNAUTHORIZED`
    (HTTP 403)."

    A CrewLead whose X-User-ID is a different crew is refused, and the job stays SCHEDULED.

    Design: Corner/rbac/crewlead_start_job_wrong_crew_returns_unauthorized
    """
    customer, contract = setup_active_contract()
    job = create_job(contract["id"], scheduled_date="2026-12-11T09:00:00Z")
    crew_a = create_crew(name="Crew A2", home_zone="N", daily_stop_capacity=5)
    crew_b = create_crew(name="Crew B2", home_zone="S", daily_stop_capacity=5)
    rd = create_route_day(crew_a["id"], service_date="2026-12-11T00:00:00Z", zone="N",
                          max_stops=5)
    book_assignment(rd["id"], job["id"], "2026-12-11T09:00:00Z",
                    "2026-12-11T11:00:00Z", _route_day_version(rd["id"]))
    dispatch_route_day(rd["id"])
    resp = api.start_job(job["id"], make_crewlead_headers(crew_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    fetched = validate_success(api.get_job(job["id"], DISPATCH), 200)
    assert fetched["status"] == "SCHEDULED", fetched
