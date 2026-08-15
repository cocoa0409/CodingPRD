"""Role-based access control: auth-context rejection, exclusive-operation
denials, and the two entity-backed ownership rules."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_owner, create_aircraft, create_crew, add_passenger,
    setup_quoted_trip, setup_dispatched_trip, setup_completed_trip,
    make_aircraft_owner_headers, make_crew_member_headers,
    make_sales_agent_headers, make_maintenance_controller_headers,
    make_ops_admin_headers,
)

OPS_ADMIN = make_ops_admin_headers()
SALES_AGENT = make_sales_agent_headers()
MAINTENANCE_CONTROLLER = make_maintenance_controller_headers()


# ---------------------------------------------------------------------------
# Queue B: validations / missing_auth_headers_returns_unauthenticated
# ---------------------------------------------------------------------------

def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the capacity in
    which they act."
    PRD §2.1: "A request missing either header, or presenting a role outside
    this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP
    400)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.list_trip_requests(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


# ---------------------------------------------------------------------------
# Queue B: validations / sales_agent_cannot_ground_aircraft_returns_forbidden
# ---------------------------------------------------------------------------

def test_sales_agent_cannot_ground_aircraft(api):
    """PRD §2.1: "A request whose role is not permitted on the target
    endpoint, or that fails an entity-backed ownership check, is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the endpoint table lists "Ground an aircraft" as
    ComplianceOfficer-only.

    Design: Corner/validations/sales_agent_cannot_ground_aircraft_returns_forbidden
    """
    owner = create_owner(name="Owner RB", contact_email="rb@x.com")
    aircraft = create_aircraft(owner["id"], tail_number="N600RB")
    resp = api_client.ground_aircraft(aircraft["id"], SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# Queue B: validations / maintenance_controller_cannot_screen_passenger
# ---------------------------------------------------------------------------

def test_maintenance_controller_cannot_screen_passenger(api):
    """PRD §2.1: "A request whose role is not permitted on the target
    endpoint, or that fails an entity-backed ownership check, is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the endpoint table lists "Record a TSA program screening
    decision" as ComplianceOfficer-only.

    Design: Corner/validations/maintenance_controller_cannot_screen_passenger
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), passenger_count=1,
                                    customer_name="Cust MC")
    pax = add_passenger(trip["id"], full_name="Pax MC", date_of_birth="1988-08-08")
    resp = api_client.screen_passenger(pax["id"], {"outcome": "CLEARED"}, MAINTENANCE_CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# Queue B: rbac / flight_log_by_non_pic_crew_forbidden
# ---------------------------------------------------------------------------

def test_flight_log_by_non_pic_crew_forbidden(api):
    """PRD §3.9: "Recording a log is the one write a `CrewMember` may
    perform, and it is identity-bound per §2.1: `X-User-ID` must equal the
    `crew_member_id` of a `VETTED` `PIC` crew assignment on the trip, or the
    request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/flight_log_by_non_pic_crew_forbidden
    """
    other_crew = create_crew(name="Other NP")
    ctx = setup_dispatched_trip(aircraft_overrides={"tail_number": "N303NP"},
                                customer_name="Cust NP")
    # The acting crew id is registered and qualified but is NOT the trip's
    # VETTED PIC.
    assert other_crew["id"] != ctx["crew"]["id"]
    resp = api_client.create_flight_log(
        {"trip_request_id": ctx["trip"]["id"], "quote_leg_id": ctx["legs"][0]["id"],
         "actual_block_minutes": 60, "departed_at": "2026-08-10T10:00:00Z",
         "arrived_at": "2026-08-10T11:00:00Z"},
        make_crew_member_headers(other_crew["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# Queue B: rbac / owner_reads_own_statements_ok
# ---------------------------------------------------------------------------

def test_owner_reads_own_statements(api):
    """PRD §2.1: "When `X-User-Role` is `AircraftOwner`, `X-User-ID` is the
    `id` of the acting `AircraftOwner`; ownership checks on any resource that
    references an `AircraftOwner` compare the resource's owner reference to
    `X-User-ID` — concretely, an owner listing revenue-share statements may
    read only its own, and any other owner's statements yield
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/owner_reads_own_statements_ok
    """
    ctx = setup_completed_trip(
        owner_overrides={"name": "Owner OSR", "contact_email": "osr@x.com",
                         "revenue_share_pct": 80, "guarantee_cents_per_block_min": 0},
        aircraft_overrides={"tail_number": "N404OS"}, customer_name="Cust OSR")
    rows, meta = validate_paginated(api_client.list_owner_statements(
        ctx["owner"]["id"], make_aircraft_owner_headers(ctx["owner"]["id"])))
    assert meta["total_count"] == 1
    assert rows[0]["gross_cents"] == 240000, "60 logged minutes at 240000/h"
    assert rows[0]["owner_share_cents"] == 192000, "80% of gross"
    assert rows[0]["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B: rbac / owner_cannot_read_other_owner_statements
# ---------------------------------------------------------------------------

def test_owner_cannot_read_other_owners_statements(api):
    """PRD §2.1: "an owner listing revenue-share statements may read only its
    own, and any other owner's statements yield `ERR_FORBIDDEN`."
    PRD §3.9: "an `AircraftOwner` may list the statements on its own record —
    attempting to list another owner's statements is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/owner_cannot_read_other_owner_statements
    """
    owner1 = create_owner(name="Owner One", contact_email="o1@x.com", revenue_share_pct=80)
    owner2 = create_owner(name="Owner Two", contact_email="o2@x.com", revenue_share_pct=70)
    resp = api_client.list_owner_statements(
        owner1["id"], make_aircraft_owner_headers(owner2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
