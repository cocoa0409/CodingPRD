"""Item intake gating: state-vs-safety priority, waiver rules, posture gating
and recovery, intake capacity (PRD §2.5, §2.9, §3.2, §3.3, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId, make_fixer_headers, make_safety_officer_headers,
    create_repair_item_payload,
    set_logical_clock, create_event, create_station, register_visitor,
    sign_waiver, publish_event, setup_intake_open_event, pause_station,
    intake_item, triage_item,
)

COORD = TEST_USERS["coordinator_headers"]
INTAKE = TEST_USERS["intake_volunteer_headers"]


def test_intake_state_beats_safety_when_event_not_intake_open(api):
    """PRD §3.2: "The event must be in `INTAKE_OPEN` status
    (`ERR_EVENT_NOT_ACCEPTING_INTAKE`), and its derived `posture` must be
    `ACCEPTING` — intake during a `RESTRICTED` posture, whether caused by the
    absence of any open station or by an open `CRITICAL` incident, is refused
    with `ERR_POSTURE_RESTRICTED`."
    PRD §2.5: "When several rules could reject the same request, checks fire in
    a fixed priority order, and the first failure determines the error
    returned."

    Design: Difficulty/priority_pair_validation_conflict/intake_state_beats_safety
    """
    set_logical_clock()
    event = create_event(name="Cafe Iota")
    create_station(event["id"])
    publish_event(event["id"])  # PUBLISHED, intake never opened
    visitor = register_visitor()  # NO waiver at all

    # Violates BOTH the state gate (event not INTAKE_OPEN) and the waiver
    # safety gates (hazard item, no waiver); the state check fires first.
    res = api.create_repair_item(
        create_repair_item_payload(event["id"], visitor["id"],
                                   category="ELECTRONICS",
                                   description="Fuel generator",
                                   hazard_flag=True, weight_kg_estimated=12.0),
        INTAKE)
    validate_error(res, ApiErrorId.ERR_EVENT_NOT_ACCEPTING_INTAKE)


def test_intake_state_beats_safety_when_posture_restricted(api):
    """PRD §3.2: "The event must be in `INTAKE_OPEN` status
    (`ERR_EVENT_NOT_ACCEPTING_INTAKE`), and its derived `posture` must be
    `ACCEPTING` — intake during a `RESTRICTED` posture, whether caused by the
    absence of any open station or by an open `CRITICAL` incident, is refused
    with `ERR_POSTURE_RESTRICTED`."
    PRD §2.9: "An event is `ACCEPTING` if and only if all three conditions
    hold: its `status` is `INTAKE_OPEN`, at least one of its stations is
    `OPEN`, and no `SafetyIncident` of severity `CRITICAL` in status `REPORTED`
    exists for that event. Otherwise the posture is `RESTRICTED`."
    PRD §2.5: "When several rules could reject the same request, checks fire in
    a fixed priority order, and the first failure determines the error
    returned."

    Design: Difficulty/priority_pair_validation_conflict/intake_state_beats_safety
    """
    ctx = setup_intake_open_event(event_name="Cafe Iota-2")
    # Pause the only OPEN station -> posture flips to RESTRICTED.
    pause_station(ctx["station"]["id"])
    event = validate_success(api.get_repair_event(ctx["event"]["id"], COORD), 200)
    assert event["status"] == "INTAKE_OPEN"
    assert event["posture"] == "RESTRICTED"

    visitor = register_visitor()  # NO waiver at all
    # Both the posture state gate and the waiver safety gates are violated;
    # the state gate (priority 4) must win over the safety gates (priority 5).
    res = api.create_repair_item(
        create_repair_item_payload(event["id"], visitor["id"],
                                   category="ELECTRONICS",
                                   description="Fuel generator",
                                   hazard_flag=True, weight_kg_estimated=12.0),
        INTAKE)
    validate_error(res, ApiErrorId.ERR_POSTURE_RESTRICTED)


def test_hazard_intake_without_safety_clause_rejected(api):
    """PRD §3.2: "When `hazard_flag` is true, the waiver must additionally have
    `safety_clause_accepted` set, else `ERR_WAIVER_SAFETY_CLAUSE_REQUIRED`."

    Design: Corner/validations/hazard_intake_without_safety_clause_rejected
    """
    ctx = setup_intake_open_event(event_name="Cafe Tet")
    # Waiver exists but the hazardous-item safety clause was not accepted.
    visitor = register_visitor()
    sign_waiver(visitor["id"], safety_clause=False)

    res = api.create_repair_item(
        create_repair_item_payload(ctx["event"]["id"], visitor["id"],
                                   category="ELECTRONICS",
                                   description="Fuel generator",
                                   hazard_flag=True, weight_kg_estimated=12.0),
        INTAKE)
    validate_error(res, ApiErrorId.ERR_WAIVER_SAFETY_CLAUSE_REQUIRED)


def test_expired_waiver_intake_rejected_and_lazily_expired(api):
    """PRD §3.2: "The visitor must hold a valid `ACTIVE` waiver: no such waiver
    at all yields `ERR_WAIVER_REQUIRED`, while a waiver whose 365-day validity
    has lapsed yields `ERR_WAIVER_EXPIRED` (the lazy `EXPIRED` transition fires
    as part of this check)."
    PRD §3.2: "A waiver observed past that point lazily transitions to
    `EXPIRED`."

    Design: Corner/validations/expired_waiver_intake_rejected_and_lazily_expired
    """
    # The clock starts at 2026-05-01T00:00:00Z and may only move forward
    # (PRD §2.4), so the waiver is signed at the startup instant and the
    # intake attempt happens more than 365 days later.
    visitor = register_visitor(full_name="Visitor Old")
    waiver = sign_waiver(visitor["id"], safety_clause=True)

    ctx = setup_intake_open_event(category="TEXTILE", skill_level=3,
                                  event_name="Cafe Yod",
                                  clock="2027-06-01T09:00:00Z",
                                  starts_at="2027-06-01T08:00:00Z",
                                  ends_at="2027-06-01T16:00:00Z",
                                  shift_start="2027-06-01T08:00:00Z",
                                  shift_end="2027-06-01T12:00:00Z",
                                  induction="2027-01-01T00:00:00Z")
    res = api.create_repair_item(
        create_repair_item_payload(ctx["event"]["id"], visitor["id"],
                                   category="TEXTILE", description="Coat",
                                   weight_kg_estimated=1.0),
        INTAKE)
    validate_error(res, ApiErrorId.ERR_WAIVER_EXPIRED)

    waiver_after = validate_success(api.get_waiver(waiver["id"], COORD), 200)
    assert waiver_after["status"] == "EXPIRED", (
        "the lazy EXPIRED transition fires as part of the intake check")


def test_intake_cap_reached_at_boundary(api):
    """PRD §3.2: "Finally, capacity is enforced: the event's
    `active_item_count` — the count of its items in `REGISTERED`, `TRIAGED`,
    `QUEUED`, `ASSIGNED`, `IN_REPAIR`, or `OUTCOME_RECORDED` — must be below
    `intake_item_cap`, or intake fails with `ERR_INTAKE_CAP_REACHED`."

    Design: Corner/validations/intake_cap_reached_at_boundary
    """
    ctx = setup_intake_open_event(category="BIKE", skill_level=3,
                                  event_name="Cafe Kaf", intake_item_cap=1)
    first = intake_item(ctx["event"]["id"], ctx["visitor"]["id"],
                        category="BIKE", description="Brake pads",
                        weight_kg_estimated=9.0)
    assert first["status"] == "REGISTERED"
    event = validate_success(api.get_repair_event(ctx["event"]["id"], COORD), 200)
    assert event["active_item_count"] == 1, (
        "a successfully accepted item raises active_item_count by one")

    res = api.create_repair_item(
        create_repair_item_payload(ctx["event"]["id"], ctx["visitor"]["id"],
                                   category="BIKE", description="Chain",
                                   weight_kg_estimated=9.5),
        INTAKE)
    # count 1 >= cap 1 -> rejected (boundary: count == cap is not below cap).
    validate_error(res, ApiErrorId.ERR_INTAKE_CAP_REACHED)


def test_posture_gate_blocks_intake_on_critical_incident(api):
    """PRD §3.3: "Whenever a triage record's `severity` is 8 or higher, the
    system automatically creates a `SafetyIncident` of severity `CRITICAL`
    linked to the item and its event, with `reported_by_user_id` set to the
    acting fixer's id, and recomputes the event's `posture` — which, since a
    `CRITICAL` reported incident now exists, flips intake to `RESTRICTED`."
    PRD §3.2: "The event must be in `INTAKE_OPEN` status
    (`ERR_EVENT_NOT_ACCEPTING_INTAKE`), and its derived `posture` must be
    `ACCEPTING` — intake during a `RESTRICTED` posture, whether caused by the
    absence of any open station or by an open `CRITICAL` incident, is refused
    with `ERR_POSTURE_RESTRICTED`."

    Design: Corner/endpoints/posture_gate_blocks_intake_on_critical_incident
    """
    ctx = setup_intake_open_event(event_name="Cafe Tsadi")
    item = intake_item(ctx["event"]["id"], ctx["visitor"]["id"],
                       category="ELECTRONICS", description="Mains heater",
                       weight_kg_estimated=6.0, hazard_flag=True)
    # Severity 8 -> auto-creates a CRITICAL REPORTED incident for the event.
    triage_item(item["id"], ctx["fixer"]["id"], severity=8,
                estimated_difficulty=4, diagnosis="cracked element")

    event = validate_success(api.get_repair_event(ctx["event"]["id"], COORD), 200)
    assert event["status"] == "INTAKE_OPEN"
    assert event["posture"] == "RESTRICTED", (
        "an open CRITICAL incident flips posture to RESTRICTED")

    # Visitor has a valid safety-clause waiver, so only posture can block this.
    res = api.create_repair_item(
        create_repair_item_payload(ctx["event"]["id"], ctx["visitor"]["id"],
                                   category="ELECTRONICS", description="Lamp",
                                   weight_kg_estimated=0.9),
        INTAKE)
    validate_error(res, ApiErrorId.ERR_POSTURE_RESTRICTED)


def test_posture_recovers_after_incident_dismissed(api):
    """PRD §3.6: "Dismissal (`REPORTED → DISMISSED`) carries the same
    not-the-reporter rule. Either terminal transition recomputes the event's
    `posture`, so clearing the last open `CRITICAL` incident can return intake
    to `ACCEPTING`."

    Design: Corner/endpoints/posture_recovers_after_incident_dismissed
    """
    ctx = setup_intake_open_event(event_name="Cafe Qof")
    item = intake_item(ctx["event"]["id"], ctx["visitor"]["id"],
                       category="ELECTRONICS", description="Mains heater",
                       weight_kg_estimated=6.0, hazard_flag=True)
    triage_item(item["id"], ctx["fixer"]["id"], severity=8,
                estimated_difficulty=4, diagnosis="cracked element")

    incidents, meta = validate_paginated(
        api.list_safety_incidents(COORD, params={"item_id": item["id"]}))
    assert meta["total_count"] == 1
    incident = incidents[0]
    assert incident["severity"] == "CRITICAL"
    assert incident["status"] == "REPORTED"

    # The auto-incident was reported by the triaging fixer, so a SafetyOfficer
    # is not the reporter and may dismiss it.
    dismissed = validate_success(api.dismiss_incident(
        incident["id"], make_safety_officer_headers("so-1")), 200)
    assert dismissed["status"] == "DISMISSED"

    # Posture recomputed: no open CRITICAL incident remains, so intake works.
    item2 = validate_success(api.create_repair_item(
        create_repair_item_payload(ctx["event"]["id"], ctx["visitor"]["id"],
                                   category="ELECTRONICS", description="Lamp",
                                   weight_kg_estimated=0.9),
        INTAKE), 201)
    assert item2["status"] == "REGISTERED", (
        "clearing the last open CRITICAL incident returns intake to ACCEPTING")


def test_waiver_revoke_non_active_returns_invalid_waiver_state(api):
    """PRD §3.2: "A `SafetyOfficer` or `Coordinator` may revoke an `ACTIVE`
    waiver (`ACTIVE → REVOKED`); revoking one that is not `ACTIVE` fails with
    `ERR_INVALID_WAIVER_STATE`."

    Design: Corner/state_machines/waiver_revoke_non_active_returns_invalid_waiver_state
    """
    set_logical_clock()
    visitor = register_visitor()
    waiver = sign_waiver(visitor["id"], safety_clause=True)
    revoked = validate_success(
        api.revoke_waiver(waiver["id"], make_safety_officer_headers("so-1")),
        200)
    assert revoked["status"] == "REVOKED"

    res = api.revoke_waiver(waiver["id"], make_safety_officer_headers("so-1"))
    validate_error(res, ApiErrorId.ERR_INVALID_WAIVER_STATE)
    waiver_after = validate_success(api.get_waiver(waiver["id"], COORD), 200)
    assert waiver_after["status"] == "REVOKED"
