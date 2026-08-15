"""Machine breakdown/repair cycle, breakdown cascade to stops, half-open
assignment overlap semantics, and machine-allocation conservation."""
from test_helpers import (
    ApiErrorId,
    cancel_assignment,
    create_active_season,
    create_committed_contract,
    create_route_stop,
    dispatch_repair,
    drive_stop_to_en_route,
    get_assignment,
    get_machine,
    get_stop,
    report_breakdown,
    reserve_machine,
    return_to_service,
    setup_cutting_stop,
    validate_error,
    validate_success,
)


def test_machine_breakdown_repair_cycle(api, crew_boss_headers, harvest_operator_headers):
    """PRD section 3.5: "A `CrewBoss` reports a breakdown on a machine that is
    `IN_FIELD` (otherwise `ERR_MACHINE_NOT_IN_FIELD`, HTTP 409), moving it
    `IN_FIELD → DOWN`."
    PRD section 3.5: "dispatching a repair moves the machine `DOWN →
    REPAIRING` (it must be `DOWN`, otherwise `ERR_MACHINE_NOT_DOWN`, HTTP
    409), and returning it to service moves it `REPAIRING → AVAILABLE` (it
    must be `REPAIRING`, otherwise `ERR_MACHINE_NOT_REPAIRING`, HTTP 409)."

    Design: Difficulty/non_linear_state_machine/machine_in_field_down_repairing_available_cycle
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    drive_stop_to_en_route(stop["id"], ctx["machine"]["id"])
    machine_id = ctx["machine"]["id"]

    down = validate_success(api.report_breakdown(machine_id, crew_boss_headers))
    assert down["status"] == "DOWN", f"breakdown must yield DOWN, got {down['status']!r}"
    repairing = validate_success(api.dispatch_repair(machine_id, harvest_operator_headers))
    assert repairing["status"] == "REPAIRING", (
        f"dispatch-repair must yield REPAIRING, got {repairing['status']!r}"
    )
    available = validate_success(api.return_to_service(machine_id, harvest_operator_headers))
    assert available["status"] == "AVAILABLE", (
        f"return-to-service must yield AVAILABLE, got {available['status']!r}"
    )


def test_machine_transition_guards(api, crew_boss_headers, harvest_operator_headers):
    """PRD section 3.5: "A `CrewBoss` reports a breakdown on a machine that is
    `IN_FIELD` (otherwise `ERR_MACHINE_NOT_IN_FIELD`, HTTP 409)"; "dispatching
    a repair moves the machine `DOWN → REPAIRING` (it must be `DOWN`,
    otherwise `ERR_MACHINE_NOT_DOWN`, HTTP 409), and returning it to service
    moves it `REPAIRING → AVAILABLE` (it must be `REPAIRING`, otherwise
    `ERR_MACHINE_NOT_REPAIRING`, HTTP 409)."

    Design: Difficulty/non_linear_state_machine/machine_in_field_down_repairing_available_cycle
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    drive_stop_to_en_route(stop["id"], ctx["machine"]["id"])
    machine_id = ctx["machine"]["id"]

    # Machine is IN_FIELD: repair dispatch requires DOWN.
    validate_error(api.dispatch_repair(machine_id, harvest_operator_headers),
                   ApiErrorId.ERR_MACHINE_NOT_DOWN)
    report_breakdown(machine_id)
    # Machine is DOWN: another breakdown requires IN_FIELD.
    validate_error(api.report_breakdown(machine_id, crew_boss_headers),
                   ApiErrorId.ERR_MACHINE_NOT_IN_FIELD)
    # Machine is DOWN: return-to-service requires REPAIRING.
    validate_error(api.return_to_service(machine_id, harvest_operator_headers),
                   ApiErrorId.ERR_MACHINE_NOT_REPAIRING)
    dispatch_repair(machine_id)
    # Machine is REPAIRING: repair dispatch again requires DOWN.
    validate_error(api.dispatch_repair(machine_id, harvest_operator_headers),
                   ApiErrorId.ERR_MACHINE_NOT_DOWN)
    back = return_to_service(machine_id)
    assert back["status"] == "AVAILABLE"


def test_report_breakdown_pauses_cutting_stop(api, crew_boss_headers):
    """PRD section 3.5: "The breakdown has an immediate operational cascade:
    every route stop that currently holds a `DEPLOYED` assignment for this
    machine and is itself in `CUTTING` or `PAUSED_WEATHER` transitions to
    `PAUSED_WEATHER`."

    Design: Difficulty/transitive_cascade/report_breakdown_cascades_machine_to_stop_pause
    """
    ctx = setup_cutting_stop()
    machine_id = ctx["machine"]["id"]
    stop_id = ctx["stop"]["id"]

    down = validate_success(api.report_breakdown(machine_id, crew_boss_headers))
    assert down["status"] == "DOWN"

    stop_now = get_stop(stop_id)
    assert stop_now["status"] == "PAUSED_WEATHER", (
        f"breakdown must pause a CUTTING stop, got {stop_now['status']!r}"
    )


def test_resume_after_repair_is_manual(api, crew_boss_headers, harvest_operator_headers):
    """PRD section 3.5: "When a machine returns to service, any stop that was
    pushed into `PAUSED_WEATHER` by the breakdown cascade and still has at
    least one other deployed combine available becomes eligible to resume —
    but resumption is never automatic; the crew boss must explicitly resume
    the stop."

    Design: Difficulty/transitive_cascade/report_breakdown_cascades_machine_to_stop_pause
    """
    ctx = setup_cutting_stop()
    machine_id = ctx["machine"]["id"]
    stop_id = ctx["stop"]["id"]

    report_breakdown(machine_id)
    dispatch_repair(machine_id)
    validate_success(api.return_to_service(machine_id, harvest_operator_headers))

    stop_after_repair = get_stop(stop_id)
    assert stop_after_repair["status"] == "PAUSED_WEATHER", (
        "return-to-service must not auto-resume the stop; "
        f"got {stop_after_repair['status']!r}"
    )
    resumed = validate_success(api.resume_route_stop(stop_id, crew_boss_headers))
    assert resumed["status"] == "CUTTING"


def test_machine_assignment_adjacency_allowed(api, crew_boss_headers):
    """PRD section 3.4: "Under half-open semantics, pure adjacency — the new
    start equal to an existing end, or the new end equal to an existing start
    — is allowed."

    Design: Difficulty/resource_temporal_overlap/machine_assignment_half_open_interval_adjacency_allowed
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)
    stop1 = create_route_stop(contract["id"], sequence_index=1)
    stop2 = create_route_stop(contract["id"], sequence_index=2,
                              planned_start_date="2026-08-08", planned_end_date="2026-08-10")
    reserve_machine(stop1["id"], ctx["machine"]["id"],
                    assigned_start_date="2026-08-05", assigned_end_date="2026-08-08")

    resp = api.create_machine_assignment(
        {"route_stop_id": stop2["id"], "machine_id": ctx["machine"]["id"],
         "assigned_start_date": "2026-08-08", "assigned_end_date": "2026-08-11"},
        crew_boss_headers,
    )
    adjacent = validate_success(resp, 201)
    assert adjacent["status"] == "RESERVED"


def test_machine_assignment_adjacent_before_allowed(api, crew_boss_headers):
    """PRD section 3.4: "Under half-open semantics, pure adjacency — the new
    start equal to an existing end, or the new end equal to an existing start
    — is allowed."

    Design: Difficulty/resource_temporal_overlap/machine_assignment_half_open_interval_adjacency_allowed
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)
    stop1 = create_route_stop(contract["id"], sequence_index=1,
                              planned_start_date="2026-08-05", planned_end_date="2026-08-07")
    stop2 = create_route_stop(contract["id"], sequence_index=2,
                              planned_start_date="2026-08-08", planned_end_date="2026-08-10")
    reserve_machine(stop1["id"], ctx["machine"]["id"],
                    assigned_start_date="2026-08-05", assigned_end_date="2026-08-08")

    resp = api.create_machine_assignment(
        {"route_stop_id": stop2["id"], "machine_id": ctx["machine"]["id"],
         "assigned_start_date": "2026-08-01", "assigned_end_date": "2026-08-05"},
        crew_boss_headers,
    )
    adjacent = validate_success(resp, 201)
    assert adjacent["status"] == "RESERVED"


def test_machine_assignment_overlap_rejected(api, crew_boss_headers):
    """PRD section 3.4: "the request is rejected with `ERR_MACHINE_OVERLAP`
    (HTTP 409) if any existing assignment for the same machine in `RESERVED`
    or `DEPLOYED` status has a start date earlier than the new assignment's
    end date while the new assignment's start date is earlier than that
    existing assignment's end date."

    Design: Difficulty/resource_temporal_overlap/machine_assignment_half_open_interval_adjacency_allowed
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=250)
    stop1 = create_route_stop(contract["id"], sequence_index=1)
    stop2 = create_route_stop(contract["id"], sequence_index=2,
                              planned_start_date="2026-08-08", planned_end_date="2026-08-10")
    stop3 = create_route_stop(contract["id"], sequence_index=3,
                              planned_start_date="2026-08-12", planned_end_date="2026-08-13")
    reserve_machine(stop1["id"], ctx["machine"]["id"],
                    assigned_start_date="2026-08-05", assigned_end_date="2026-08-08")
    reserve_machine(stop2["id"], ctx["machine"]["id"],
                    assigned_start_date="2026-08-08", assigned_end_date="2026-08-11")

    resp = api.create_machine_assignment(
        {"route_stop_id": stop3["id"], "machine_id": ctx["machine"]["id"],
         "assigned_start_date": "2026-08-07", "assigned_end_date": "2026-08-13"},
        crew_boss_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MACHINE_OVERLAP)


def test_machine_allocation_conserved_through_assignment_cancel(api, crew_boss_headers):
    """PRD section 3.5: "the first `RESERVED` assignment against an
    `AVAILABLE` machine moves it to `ASSIGNED`" and "Cancelling an individual
    assignment — a `CrewBoss` action allowed only while the assignment is
    `RESERVED` (otherwise `ERR_ASSIGNMENT_NOT_RESERVED`, HTTP 409) — moves it
    to `CANCELLED`, and if that was the machine's last non-cancelled
    assignment and the machine was `ASSIGNED`, the machine returns to
    `AVAILABLE`."

    Design: Difficulty/compensating_invariant/machine_allocation_conserved_through_assignment_cancel
    """
    ctx = create_active_season()
    machine_id = ctx["machine"]["id"]
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)

    resp = api.create_machine_assignment(
        {"route_stop_id": stop["id"], "machine_id": machine_id,
         "assigned_start_date": "2026-08-05", "assigned_end_date": "2026-08-08"},
        crew_boss_headers,
    )
    assignment = validate_success(resp, 201)
    assert assignment["status"] == "RESERVED"
    assert get_machine(machine_id)["status"] == "ASSIGNED", (
        "first reservation must move the machine to ASSIGNED"
    )

    validate_success(api.cancel_machine_assignment(assignment["id"], crew_boss_headers))
    assert get_assignment(assignment["id"])["status"] == "CANCELLED"
    assert get_machine(machine_id)["status"] == "AVAILABLE", (
        "cancelling the last reservation must return the machine to AVAILABLE"
    )


def test_machine_stays_assigned_until_last_reservation_cancelled(api, crew_boss_headers):
    """PRD section 3.5: "if that was the machine's last non-cancelled
    assignment and the machine was `ASSIGNED`, the machine returns to
    `AVAILABLE`" — with two live reservations, cancelling only the first
    leaves the machine `ASSIGNED`.

    Design: Difficulty/compensating_invariant/machine_allocation_conserved_through_assignment_cancel
    """
    ctx = create_active_season()
    machine_id = ctx["machine"]["id"]
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)
    stop1 = create_route_stop(contract["id"], sequence_index=1)
    stop2 = create_route_stop(contract["id"], sequence_index=2,
                              planned_start_date="2026-08-08", planned_end_date="2026-08-09")
    asg1 = reserve_machine(stop1["id"], machine_id,
                           assigned_start_date="2026-08-05", assigned_end_date="2026-08-07")
    asg2 = reserve_machine(stop2["id"], machine_id,
                           assigned_start_date="2026-08-08", assigned_end_date="2026-08-10")

    cancel_assignment(asg1["id"])
    assert get_machine(machine_id)["status"] == "ASSIGNED", (
        "machine with a surviving reservation must stay ASSIGNED"
    )
    cancel_assignment(asg2["id"])
    assert get_machine(machine_id)["status"] == "AVAILABLE", (
        "cancelling the last non-cancelled assignment must free the machine"
    )
