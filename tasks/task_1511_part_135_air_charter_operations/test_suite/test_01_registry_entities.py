"""Registry entity creation defaults, request-shape checks, and the
resource-specific 404 family."""
from test_helpers import (
    api_client, validate_success, validate_error,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID, ApiErrorId,
    create_aircraft_payload,
    create_trip_request_payload, create_maintenance_window_payload,
    create_owner, create_aircraft,
    make_ops_admin_headers, make_sales_agent_headers,
    make_dispatch_manager_headers, make_maintenance_controller_headers,
    make_compliance_officer_headers,
)

OPS_ADMIN = make_ops_admin_headers()
SALES_AGENT = make_sales_agent_headers()
DISPATCH_MANAGER = make_dispatch_manager_headers()
MAINTENANCE_CONTROLLER = make_maintenance_controller_headers()
COMPLIANCE_OFFICER = make_compliance_officer_headers()


# ---------------------------------------------------------------------------
# Queue B: entities / create_aircraft_owner_defaults
# ---------------------------------------------------------------------------

def test_aircraft_owner_creation_defaults(api):
    """PRD §3.1: "An aircraft owner is registered with its legal `name`, a
    `contact_email`, the `revenue_share_pct` it earns of gross charter revenue
    (a number from 0 to 100), and optionally a `guarantee_cents_per_block_min`
    minimum guarantee per logged block minute, which defaults to 0 when
    omitted."
    PRD §4: "Operations that create a new resource return `201 Created`."

    Design: Corner/entities/create_aircraft_owner_defaults
    """
    resp = api_client.create_aircraft_owner(
        {"name": "Owner D", "contact_email": "d@x.com", "revenue_share_pct": 75},
        OPS_ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["guarantee_cents_per_block_min"] == 0, "default 0 applied when omitted"
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


# ---------------------------------------------------------------------------
# Queue B: entities / create_trip_request_initial_state
# ---------------------------------------------------------------------------

def test_trip_request_creation_initial_state(api):
    """PRD §3.2: "The trip is born in `QUOTE_DRAFT` status with its
    `payment_posture` at `UNPAID`."
    PRD §3.2: "Until the trip is priced, `quoted_total_cents`,
    `deposit_required_cents`, and `quote_valid_until` are all null"

    Design: Corner/entities/create_trip_request_initial_state
    """
    resp = api_client.create_trip_request(
        create_trip_request_payload(
            customer_name="Cust I", customer_email="i@x.com",
            requested_category="TURBOPROP", destination_icao="KLAS",
            departure_at="2026-08-09T09:00:00Z", passenger_count=3),
        SALES_AGENT)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "QUOTE_DRAFT"
    assert data["payment_posture"] == "UNPAID"
    assert data["quoted_total_cents"] is None
    assert data["deposit_required_cents"] is None
    assert data["quote_valid_until"] is None
    assert data["collected_cents"] == 0


# ---------------------------------------------------------------------------
# Queue B: entities / aircraft_total_airframe_computed_from_initial
# ---------------------------------------------------------------------------

def test_aircraft_total_airframe_initialized_from_initial(api):
    """PRD §3.1: "A new tail starts in `AVAILABLE` status, and its
    `total_airframe_minutes` is initialized to `initial_airframe_minutes`;
    thereafter the total accumulates the `actual_block_minutes` of every
    flight log from trips on which this aircraft held the `CONFIRMED`
    assignment."

    Design: Corner/entities/aircraft_total_airframe_computed_from_initial
    """
    owner = create_owner(name="Owner AC", contact_email="ac@x.com")
    resp = api_client.create_aircraft(
        create_aircraft_payload(
            owner["id"], tail_number="N111AC", category="TURBOPROP", seats=6,
            hourly_rate_cents=140000, initial_airframe_minutes=500,
            next_check_due_minutes=6000),
        OPS_ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["total_airframe_minutes"] == 500, "computed from initial, zero logs"
    assert data["status"] == "AVAILABLE", "initial state"


# ---------------------------------------------------------------------------
# Queue B: entities / create_aircraft_missing_required_field_returns_invalid_request
# ---------------------------------------------------------------------------

def test_create_aircraft_missing_tail_number_rejected(api):
    """PRD §2.11: "Request-body shape — required fields present, enum values
    valid, and amounts that must be positive (`block_minutes`, `amount_cents`,
    `actual_block_minutes`, `seats`) greater than zero; otherwise
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "Each aircraft tail is registered with its `owner_id`, a unique
    `tail_number`, a `category` of exactly one of `TURBOPROP`, `LIGHT_JET`,
    `MIDSIZE_JET`, or `HEAVY_JET`..."

    Design: Corner/entities/create_aircraft_missing_required_field_returns_invalid_request
    """
    owner = create_owner(name="Owner RF", contact_email="rf@x.com")
    payload = create_aircraft_payload(owner["id"])
    del payload["tail_number"]
    resp = api_client.create_aircraft(payload, OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Queue B: entities / create_trip_invalid_enum_category_rejected
# ---------------------------------------------------------------------------

def test_create_trip_invalid_category_enum_rejected(api):
    """PRD §2.11: "Request-body shape — required fields present, enum values
    valid, and amounts that must be positive (`block_minutes`, `amount_cents`,
    `actual_block_minutes`, `seats`) greater than zero; otherwise
    `ERR_INVALID_REQUEST`."
    PRD §3.2: "the `requested_category` (one of the four category enums)"

    Design: Corner/entities/create_trip_invalid_enum_category_rejected
    """
    payload = create_trip_request_payload(requested_category="ROCKET")
    resp = api_client.create_trip_request(payload, SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Queue B: entities / window_invalid_time_range_returns_400
# ---------------------------------------------------------------------------

def test_create_window_equal_start_end_rejected(api):
    """PRD §3.5: "A `MaintenanceController` schedules a window with the
    `aircraft_id`, a `window_type` of `INSPECTION_100H`, `ANNUAL`, or
    `AOG_REPAIR`, and a closed `starts_at`-to-`ends_at` interval whose end
    must be strictly after its start (`ERR_INVALID_TIME_RANGE` otherwise)."

    Design: Corner/entities/window_invalid_time_range_returns_400
    """
    owner = create_owner(name="Owner W", contact_email="w@x.com")
    aircraft = create_aircraft(owner["id"], tail_number="N222WW")
    resp = api_client.create_maintenance_window(
        create_maintenance_window_payload(
            aircraft["id"], window_type="ANNUAL",
            starts_at="2026-08-05T00:00:00Z", ends_at="2026-08-05T00:00:00Z"),
        MAINTENANCE_CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)


# ---------------------------------------------------------------------------
# Queue B: entities / thirteen resource-specific 404 probes
# ---------------------------------------------------------------------------

def test_get_trip_request_not_found(api):
    """PRD §2.10: "The server confirms each path identifier exists before
    looking at the next one, and the first missing identifier determines the
    error: a nonexistent owner id yields `ERR_AIRCRAFT_OWNER_NOT_FOUND`, a
    nonexistent aircraft id yields `ERR_AIRCRAFT_NOT_FOUND`, a nonexistent
    crew id yields `ERR_CREW_MEMBER_NOT_FOUND`, a nonexistent trip id yields
    `ERR_TRIP_REQUEST_NOT_FOUND`, and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/get_trip_not_found_returns_404
    """
    resp = api_client.get_trip_request(NON_EXISTENT_UUID, OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_TRIP_REQUEST_NOT_FOUND)


def test_get_aircraft_not_found(api):
    """PRD §2.10: "The server confirms each path identifier exists before
    looking at the next one, and the first missing identifier determines the
    error: a nonexistent owner id yields `ERR_AIRCRAFT_OWNER_NOT_FOUND`, a
    nonexistent aircraft id yields `ERR_AIRCRAFT_NOT_FOUND`, a nonexistent
    crew id yields `ERR_CREW_MEMBER_NOT_FOUND`, a nonexistent trip id yields
    `ERR_TRIP_REQUEST_NOT_FOUND`, and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/get_aircraft_not_found_returns_404
    """
    resp = api_client.get_aircraft(NON_EXISTENT_UUID, OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_FOUND)


def test_get_aircraft_owner_not_found(api):
    """PRD §2.10: "The server confirms each path identifier exists before
    looking at the next one, and the first missing identifier determines the
    error: a nonexistent owner id yields `ERR_AIRCRAFT_OWNER_NOT_FOUND`, a
    nonexistent aircraft id yields `ERR_AIRCRAFT_NOT_FOUND`, a nonexistent
    crew id yields `ERR_CREW_MEMBER_NOT_FOUND`, a nonexistent trip id yields
    `ERR_TRIP_REQUEST_NOT_FOUND`, and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/get_aircraft_owner_not_found_returns_404
    """
    resp = api_client.get_aircraft_owner(NON_EXISTENT_UUID, OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_OWNER_NOT_FOUND)


def test_get_crew_member_not_found(api):
    """PRD §2.10: "The server confirms each path identifier exists before
    looking at the next one, and the first missing identifier determines the
    error: a nonexistent owner id yields `ERR_AIRCRAFT_OWNER_NOT_FOUND`, a
    nonexistent aircraft id yields `ERR_AIRCRAFT_NOT_FOUND`, a nonexistent
    crew id yields `ERR_CREW_MEMBER_NOT_FOUND`, a nonexistent trip id yields
    `ERR_TRIP_REQUEST_NOT_FOUND`, and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/get_crew_member_not_found_returns_404
    """
    resp = api_client.get_crew_member(NON_EXISTENT_UUID, OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_CREW_MEMBER_NOT_FOUND)


def test_get_quote_leg_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/get_quote_leg_not_found_returns_404
    """
    resp = api_client.get_quote_leg(NON_EXISTENT_UUID, OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_QUOTE_LEG_NOT_FOUND)


def test_confirm_assignment_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/confirm_assignment_not_found_returns_404
    """
    resp = api_client.confirm_aircraft_assignment(NON_EXISTENT_UUID, DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND)


def test_vet_crew_assignment_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/vet_crew_assignment_not_found_returns_404
    """
    resp = api_client.vet_crew_assignment(NON_EXISTENT_UUID, DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CREW_ASSIGNMENT_NOT_FOUND)


def test_complete_window_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/complete_window_not_found_returns_404
    """
    resp = api_client.complete_maintenance_window(NON_EXISTENT_UUID, MAINTENANCE_CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_WINDOW_NOT_FOUND)


def test_screen_passenger_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/screen_passenger_not_found_returns_404
    """
    resp = api_client.screen_passenger(NON_EXISTENT_UUID, {"outcome": "CLEARED"}, COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_PASSENGER_NOT_FOUND)


def test_decide_permit_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/decide_permit_not_found_returns_404
    """
    resp = api_client.decide_overflight_permit(NON_EXISTENT_UUID, {"decision": "GRANTED"}, COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_OVERFLIGHT_PERMIT_NOT_FOUND)


def test_get_flight_log_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/get_flight_log_not_found_returns_404
    """
    resp = api_client.get_flight_log(NON_EXISTENT_UUID, OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_FLIGHT_LOG_NOT_FOUND)


def test_issue_statement_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/issue_statement_not_found_returns_404
    """
    resp = api_client.issue_owner_statement(NON_EXISTENT_UUID, OPS_ADMIN)
    validate_error(resp, ApiErrorId.ERR_OWNER_STATEMENT_NOT_FOUND)


def test_resolve_finding_not_found(api):
    """PRD §2.10: "and likewise `ERR_QUOTE_LEG_NOT_FOUND`,
    `ERR_AIRCRAFT_ASSIGNMENT_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
    `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_PASSENGER_NOT_FOUND`,
    `ERR_OVERFLIGHT_PERMIT_NOT_FOUND`, `ERR_FLIGHT_LOG_NOT_FOUND`,
    `ERR_OWNER_STATEMENT_NOT_FOUND`, and `ERR_COMPLIANCE_FINDING_NOT_FOUND`
    for their respective resources, each with HTTP 404."

    Design: Corner/entities/resolve_finding_not_found_returns_404
    """
    resp = api_client.resolve_compliance_finding(NON_EXISTENT_UUID, COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_FINDING_NOT_FOUND)
