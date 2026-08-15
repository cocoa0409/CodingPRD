"""Aircraft grounding cascade, return-to-service gating, and the maintenance
window lifecycle including clock-driven activation."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    create_owner, create_aircraft, create_finding, resolve_finding,
    ground_aircraft, set_clock, create_window, cancel_window, complete_window,
    setup_trip_with_confirmed_aircraft, setup_dispatched_trip,
    make_ops_admin_headers, make_compliance_officer_headers,
    make_maintenance_controller_headers,
)

OPS_ADMIN = make_ops_admin_headers()
COMPLIANCE_OFFICER = make_compliance_officer_headers()
_MX = make_maintenance_controller_headers()


def _owner_and_aircraft(tail, **aircraft_overrides):
    owner = create_owner(name="Owner MX", contact_email="mx@x.com")
    return create_aircraft(owner["id"], tail_number=tail, **aircraft_overrides)


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / ground_aircraft_cascade
# ---------------------------------------------------------------------------

def test_ground_releases_confirmed_assignment(api):
    """PRD §3.5: "A `ComplianceOfficer` grounds an aircraft in `AVAILABLE` or
    `MAINTENANCE_HOLD` (grounding from `IN_TRIP` or `GROUNDED` yields
    `ERR_INVALID_STATE`), moving it to `GROUNDED`."
    PRD §3.5: "The cascade is three links deep: every `TENTATIVE` or
    `CONFIRMED` assignment on the tail is released, and every trip in
    `BOOKED` status whose `CONFIRMED` assignment was just released falls back
    to `QUOTED` — a new aircraft must be confirmed before that trip can
    dispatch."

    Design: Difficulty/transitive_cascade/ground_aircraft_cascade
    """
    ctx = setup_trip_with_confirmed_aircraft(
        aircraft_overrides={"tail_number": "N500GG"}, pay_in_full=False,
        customer_name="Cust G")
    grounded = ground_aircraft(ctx["aircraft"]["id"])
    assert grounded["status"] == "GROUNDED"
    asg_after = validate_success(
        api_client.get_aircraft_assignment(ctx["assignment"]["id"], OPS_ADMIN), 200)
    assert asg_after["status"] == "RELEASED", "link 2: ground releases the CONFIRMED assignment"


def test_ground_reverts_booked_trip_to_quoted(api):
    """PRD §3.5: "The cascade is three links deep: every `TENTATIVE` or
    `CONFIRMED` assignment on the tail is released, and every trip in
    `BOOKED` status whose `CONFIRMED` assignment was just released falls back
    to `QUOTED` — a new aircraft must be confirmed before that trip can
    dispatch."

    Design: Difficulty/transitive_cascade/ground_aircraft_cascade
    """
    ctx = setup_trip_with_confirmed_aircraft(
        aircraft_overrides={"tail_number": "N500GG"}, pay_in_full=False,
        customer_name="Cust G")
    ground_aircraft(ctx["aircraft"]["id"])
    trip_after = validate_success(
        api_client.get_trip_request(ctx["trip"]["id"], OPS_ADMIN), 200)
    assert trip_after["status"] == "QUOTED", "link 3: BOOKED trip falls back to QUOTED"
    assert trip_after["quoted_total_cents"] == 270000, "pricing snapshot retained"


# ---------------------------------------------------------------------------
# Queue B: state_machines / ground_in_trip_rejected
# ---------------------------------------------------------------------------

def test_ground_in_trip_aircraft_rejected(api):
    """PRD §3.5: "A `ComplianceOfficer` grounds an aircraft in `AVAILABLE` or
    `MAINTENANCE_HOLD` (grounding from `IN_TRIP` or `GROUNDED` yields
    `ERR_INVALID_STATE`), moving it to `GROUNDED`."

    Design: Corner/state_machines/ground_in_trip_rejected
    """
    ctx = setup_dispatched_trip(aircraft_overrides={"tail_number": "N400GT"},
                                customer_name="Cust GT")
    aircraft = validate_success(api_client.get_aircraft(ctx["aircraft"]["id"], OPS_ADMIN), 200)
    assert aircraft["status"] == "IN_TRIP"
    resp = api_client.ground_aircraft(ctx["aircraft"]["id"], COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Queue B: state_machines / return_from_available_rejected
# ---------------------------------------------------------------------------

def test_return_to_service_from_available_rejected(api):
    """PRD §3.5: "Returning the tail to service requires it to be `GROUNDED`
    (`ERR_AIRCRAFT_NOT_GROUNDED` otherwise) and requires that no compliance
    finding with `subject_type` `AIRCRAFT` pointing at this tail, flagged
    `grounding` true, remains `OPEN` (`ERR_GROUNDING_FINDING_OPEN`); a clean
    return moves the aircraft to `AVAILABLE`."

    Design: Corner/state_machines/return_from_available_rejected
    """
    aircraft = _owner_and_aircraft("N500RA")
    assert aircraft["status"] == "AVAILABLE"
    resp = api_client.return_aircraft_to_service(aircraft["id"], COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_GROUNDED)


# ---------------------------------------------------------------------------
# Queue B: errors / grounding_finding_blocks_return_until_resolved
# ---------------------------------------------------------------------------

def test_grounding_finding_blocks_return_until_resolved(api):
    """PRD §3.5: "Returning the tail to service requires it to be `GROUNDED`
    (`ERR_AIRCRAFT_NOT_GROUNDED` otherwise) and requires that no compliance
    finding with `subject_type` `AIRCRAFT` pointing at this tail, flagged
    `grounding` true, remains `OPEN` (`ERR_GROUNDING_FINDING_OPEN`); a clean
    return moves the aircraft to `AVAILABLE`."

    Design: Corner/errors/grounding_finding_blocks_return_until_resolved
    """
    aircraft = _owner_and_aircraft("N660GF")
    ground_aircraft(aircraft["id"])
    finding = create_finding("AIRCRAFT", aircraft["id"], finding_code="OPSPEC-B002",
                             grounding=True, notes="blocked")
    resp = api_client.return_aircraft_to_service(aircraft["id"], COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_GROUNDING_FINDING_OPEN)

    resolve_finding(finding["id"])
    returned = validate_success(
        api_client.return_aircraft_to_service(aircraft["id"], COMPLIANCE_OFFICER), 200)
    assert returned["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Queue B: state_machines / resolve_finding_twice_rejected
# ---------------------------------------------------------------------------

def test_resolve_finding_twice_rejected(api):
    """PRD §3.5: "A finding is born `OPEN` and is resolved by the same role;
    resolving requires `OPEN` status (`ERR_FINDING_ALREADY_RESOLVED`
    otherwise) and stamps `resolved_at` at the current clock."

    Design: Corner/state_machines/resolve_finding_twice_rejected
    """
    aircraft = _owner_and_aircraft("N300FN")
    finding = create_finding("AIRCRAFT", aircraft["id"], grounding=True, notes="test")
    resolve_finding(finding["id"])
    resp = api_client.resolve_compliance_finding(finding["id"], COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_FINDING_ALREADY_RESOLVED)


# ---------------------------------------------------------------------------
# Queue B: errors / window_overlap_rejected
# ---------------------------------------------------------------------------

def test_window_overlap_rejected(api):
    """PRD §3.5: "At creation the window is conflict-checked in both
    directions: against the raw flight intervals of the tail's `CONFIRMED`
    assignments (`ERR_MAINTENANCE_CONFLICT`) and against the tail's other
    `PLANNED` or `ACTIVE` windows (`ERR_WINDOW_OVERLAP`), both under the
    closed-interval, touching-counts rule."

    Design: Corner/errors/window_overlap_rejected
    """
    aircraft = _owner_and_aircraft("N770WO")
    create_window(aircraft["id"], window_type="ANNUAL",
                  starts_at="2026-08-05T00:00:00Z", ends_at="2026-08-05T06:00:00Z")
    resp = api_client.create_maintenance_window(
        {"aircraft_id": aircraft["id"], "window_type": "AOG_REPAIR",
         "starts_at": "2026-08-05T05:00:00Z", "ends_at": "2026-08-05T09:00:00Z"},
        _MX)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


# ---------------------------------------------------------------------------
# Queue B: state_machines / complete_planned_window_rejected
# ---------------------------------------------------------------------------

def test_complete_planned_window_rejected(api):
    """PRD §3.5: "Completing the window requires it to be `ACTIVE`
    (`ERR_WINDOW_NOT_COMPLETABLE`); completion moves it to `COMPLETED`, and
    for an `INSPECTION_100H` window it resets the tail's inspection horizon,
    setting `next_check_due_minutes` to the current `total_airframe_minutes`
    plus 6000 minutes — one hundred hours."

    Design: Corner/state_machines/complete_planned_window_rejected
    """
    aircraft = _owner_and_aircraft("N100PW")
    window = create_window(aircraft["id"], window_type="INSPECTION_100H",
                           starts_at="2026-08-05T00:00:00Z",
                           ends_at="2026-08-05T06:00:00Z")
    assert window["status"] == "PLANNED"
    resp = api_client.complete_maintenance_window(window["id"], _MX)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_COMPLETABLE)


# ---------------------------------------------------------------------------
# Queue B: errors / window_cancel_then_complete_rejected
# ---------------------------------------------------------------------------

def test_window_cancel_then_complete_rejected(api):
    """PRD §3.5: "A window still in `PLANNED` may instead be cancelled,
    moving it to `CANCELLED`; cancelling a window in any other status is
    rejected with `ERR_INVALID_STATE`."
    PRD §3.5: "Completing the window requires it to be `ACTIVE`
    (`ERR_WINDOW_NOT_COMPLETABLE`)..."

    Design: Corner/errors/window_cancel_then_complete_rejected
    """
    aircraft = _owner_and_aircraft("N880WC")
    window = create_window(aircraft["id"], window_type="ANNUAL",
                           starts_at="2026-08-06T00:00:00Z",
                           ends_at="2026-08-06T06:00:00Z")
    cancelled = cancel_window(window["id"])
    assert cancelled["status"] == "CANCELLED"
    resp = api_client.complete_maintenance_window(window["id"], _MX)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_COMPLETABLE)


# ---------------------------------------------------------------------------
# Queue B: complexity_layers / window_auto_activation_holds_aircraft
# ---------------------------------------------------------------------------

def test_window_auto_activation_holds_aircraft(api):
    """PRD §2.4: "Every clock advance runs a time-based expiry sweep in a
    pinned order — trip requests first, then passengers, then overflight
    permits, then maintenance windows."
    PRD §2.4: "a maintenance window in `PLANNED` status whose `starts_at` has
    been reached activates — provided its aircraft is not `IN_TRIP`, since
    activation is skipped while the tail is flying and re-evaluated on the
    next clock set — moving the window to `ACTIVE` and an `AVAILABLE`
    aircraft to `MAINTENANCE_HOLD`."

    Design: Corner/complexity_layers/window_auto_activation_holds_aircraft
    """
    aircraft = _owner_and_aircraft("N606WA")
    window = create_window(aircraft["id"], window_type="AOG_REPAIR",
                           starts_at="2026-08-01T00:00:00Z",
                           ends_at="2026-08-02T00:00:00Z")
    set_clock("2026-08-01T12:00:00Z")
    window_after = validate_success(
        api_client.get_maintenance_window(window["id"], OPS_ADMIN), 200)
    assert window_after["status"] == "ACTIVE"
    aircraft_after = validate_success(api_client.get_aircraft(aircraft["id"], OPS_ADMIN), 200)
    assert aircraft_after["status"] == "MAINTENANCE_HOLD"


# ---------------------------------------------------------------------------
# Queue B: complexity_layers / window_complete_resets_check_due_and_releases_aircraft
# ---------------------------------------------------------------------------

def test_window_complete_resets_check_due_and_releases_aircraft(api):
    """PRD §3.5: "Completing the window requires it to be `ACTIVE"
    (`ERR_WINDOW_NOT_COMPLETABLE`); completion moves it to `COMPLETED`, and
    for an `INSPECTION_100H` window it resets the tail's inspection horizon,
    setting `next_check_due_minutes` to the current `total_airframe_minutes`
    plus 6000 minutes — one hundred hours."
    PRD §3.5: "When the completed window was the last `ACTIVE` window on the
    tail and the accumulated airframe time sits below the check-due
    threshold, the aircraft leaves `MAINTENANCE_HOLD` for `AVAILABLE`."

    Design: Corner/complexity_layers/window_complete_resets_check_due_and_releases_aircraft
    """
    aircraft = _owner_and_aircraft("N707WC", next_check_due_minutes=500)
    window = create_window(aircraft["id"], window_type="INSPECTION_100H",
                           starts_at="2026-08-01T00:00:00Z",
                           ends_at="2026-08-02T00:00:00Z")
    set_clock("2026-08-01T12:00:00Z")  # activates the window -> MAINTENANCE_HOLD
    completed = complete_window(window["id"])
    assert completed["status"] == "COMPLETED"
    aircraft_after = validate_success(api_client.get_aircraft(aircraft["id"], OPS_ADMIN), 200)
    assert aircraft_after["next_check_due_minutes"] == 6000, "total 0 + 6000"
    assert aircraft_after["status"] == "AVAILABLE"
