"""Cross-entity gates: a record whose own state is impeccable is still refused
because a sibling record — bank, station, subcontractor or posture — says no."""
from test_helpers import (
    ApiErrorId,
    add_agent_occupation,
    add_gse_occupation,
    approve_staffing,
    assert_instant,
    close_out_incident,
    create_approved_subcontractor,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    decide_oversight,
    get_agent,
    get_flight_bank,
    get_station,
    get_turn,
    get_turn_resource,
    issue_certification,
    make_duty_officer_headers,
    publish_bank,
    report_incident,
    resume_station,
    submit_staffing,
    suspend_station,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency /
#          turn_start_blocked_by_flight_bank_staffing_status
# ---------------------------------------------------------------------------

def _setup_resourced_turn_under_an_unapproved_plan():
    """A RESOURCED turn inside a PUBLISHED bank whose staffing plan is only
    SUBMITTED."""
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_bank(bank["id"])
    submit_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"])
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"])
    assert get_turn(turn["id"])["status"] == "RESOURCED"
    return station, bank, turn


def test_start_is_refused_while_the_bank_staffing_plan_is_unapproved(api):
    """PRD §3.4: "Starting the turnaround with `START` moves it `RESOURCED →
    IN_PROGRESS`; it must be `RESOURCED`, the station must be `OPEN`, the
    owning bank's `bank_status` must be `PUBLISHED` or `LOCKED` (otherwise
    `ERR_BANK_NOT_PUBLISHED`), and its `staffing_status` must be `APPROVED`
    (otherwise `ERR_STAFFING_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/turn_start_blocked_by_flight_bank_staffing_status
    """
    _station, bank, turn = _setup_resourced_turn_under_an_unapproved_plan()
    assert get_flight_bank(bank["id"])["staffing_status"] == "SUBMITTED"

    resp = api.turn_lifecycle(
        turn["id"], {"action": "START", "actual_in": "2026-04-10T06:00:00Z"},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_STAFFING_NOT_APPROVED, 409)
    assert get_turn(turn["id"])["status"] == "RESOURCED"


def test_the_identical_start_succeeds_once_the_plan_is_approved(api):
    """PRD §3.4: "On success `actual_in` takes the supplied value, or the
    current logical clock when the field is omitted, and every occupation on
    the turnaround sitting at `RESERVED` moves to `COMMITTED`."
    PRD §3.3: "A `StationManager` approves the plan with `APPROVE`, moving
    `staffing_status` `SUBMITTED → APPROVED`; approval requires the station to
    be `OPEN` and requires `staffing_coverage_pct` to be at least 100.00, with
    a shortfall refused as `ERR_STAFFING_COVERAGE_INSUFFICIENT`."

    Design: Difficulty/cross_entity_state_dependency/turn_start_blocked_by_flight_bank_staffing_status
    """
    _station, bank, turn = _setup_resourced_turn_under_an_unapproved_plan()
    api.turn_lifecycle(
        turn["id"], {"action": "START", "actual_in": "2026-04-10T06:00:00Z"},
        make_duty_officer_headers())
    approve_staffing(bank["id"], user_id="sm-01")

    started = validate_success(api.turn_lifecycle(
        turn["id"], {"action": "START", "actual_in": "2026-04-10T06:00:00Z"},
        make_duty_officer_headers()))
    assert started["status"] == "IN_PROGRESS"
    assert_instant(get_turn(turn["id"])["actual_in"], "2026-04-10T06:00:00Z",
                   "actual_in")

    bank = get_flight_bank(bank["id"])
    assert bank["staffing_status"] == "APPROVED"
    assert bank["bank_status"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / resource_create_blocked_by_suspended_station
# ---------------------------------------------------------------------------

def _setup_scheduled_turn_at_a_suspended_station():
    """The bank never left DRAFT, so the suspension cascade never reached the
    turn: it is still SCHEDULED at a SUSPENDED station."""
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    suspended = suspend_station(station["id"], reason="RUNWAY_CLOSURE")
    assert suspended["status"] == "SUSPENDED"
    return station, bank, turn, agent


def test_committing_a_resource_at_a_suspended_station_is_refused(api):
    """PRD §3.7: "The owning station must be `OPEN`, and a station that is
    `PLANNED`, `SUSPENDED` or `CLOSED` refuses the commitment with
    `ERR_STATION_NOT_OPEN`."
    PRD §3.1: "Third, because those staffing plans fell back, every turnaround
    inside those banks whose `status` is `SCHEDULED` or `RESOURCED` moves to
    `DISRUPTED`."

    Design: Difficulty/cross_entity_state_dependency/resource_create_blocked_by_suspended_station
    """
    _station, _bank, turn, agent = _setup_scheduled_turn_at_a_suspended_station()
    assert get_turn(turn["id"])["status"] == "SCHEDULED", (
        "the cascade only touches turns inside PUBLISHED banks")

    resp = api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_OPEN, 409)
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 0


def test_resuming_the_station_admits_the_identical_commitment(api):
    """PRD §3.1: "Resuming with `RESUME` moves it `SUSPENDED → OPEN`, but only
    while `open_critical_incident_count` is exactly zero; on success the
    posture is recomputed."
    PRD §3.7: "An accepted occupation lands at `RESERVED`. Its
    `occupied_minutes` is the elapsed time from `window_start` to `window_end`
    in whole minutes, rounded down."

    Design: Difficulty/cross_entity_state_dependency/resource_create_blocked_by_suspended_station
    """
    station, bank, turn, agent = _setup_scheduled_turn_at_a_suspended_station()
    payload = {"turn_id": turn["id"], "resource_kind": "AGENT",
               "agent_id": agent["id"], "role_on_turn": "RAMP",
               "window_start": "2026-04-10T05:50:00Z",
               "window_end": "2026-04-10T06:30:00Z",
               "expected_turn_version": turn["version"]}
    api.create_turn_resource(payload, make_duty_officer_headers())

    resumed = resume_station(station["id"])
    assert resumed["status"] == "OPEN"

    accepted = validate_success(
        api.create_turn_resource(payload, make_duty_officer_headers()), 201)
    assert accepted["status"] == "RESERVED"
    assert accepted["occupied_minutes"] == 40
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 40
    assert get_flight_bank(bank["id"])["bank_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency /
#          agent_assignment_blocked_by_suspended_subcontractor
# ---------------------------------------------------------------------------

def _setup_active_agent_of_a_suspended_firm():
    """The agent is ACTIVE and fully endorsed, but the firm that employs it
    moved APPROVED → SUSPENDED after the hire."""
    station = create_open_station()
    firm = create_approved_subcontractor(station["id"],
                                         legal_name="Alpine Ramp AG")
    agent = create_certified_agent(station["id"], employee_code="E010",
                                   full_name="Cleo Marin",
                                   subcontractor_id=firm["id"])
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    suspended = decide_oversight(firm["id"], "SUSPEND",
                                 note="Audit findings outstanding")
    assert suspended["status"] == "SUSPENDED"
    return station, firm, agent, turn


def test_committing_an_agent_of_a_suspended_firm_is_refused(api):
    """PRD §3.5: "An attempt to commit an agent whose `status` is `SUSPENDED`
    or `TERMINATED` is refused with `ERR_AGENT_NOT_ACTIVE`; an attempt to
    commit an agent whose employing firm is in any status other than `APPROVED`
    or `PROBATION` is refused with `ERR_SUBCONTRACTOR_NOT_APPROVED`."
    PRD §3.2: "Suspending a firm with `SUSPEND` moves it `APPROVED →
    SUSPENDED` or `PROBATION → SUSPENDED` — the decision is admissible from
    either of those two statuses — and once suspended, no new occupation may be
    created for any agent that firm employs."

    Design: Difficulty/cross_entity_state_dependency/agent_assignment_blocked_by_suspended_subcontractor
    """
    _station, _firm, agent, turn = _setup_active_agent_of_a_suspended_firm()

    resp = api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_SUBCONTRACTOR_NOT_APPROVED, 409)


def test_the_agent_itself_is_untouched_by_its_employers_suspension(api):
    """PRD §3.5: "The derived `employment_type` reads `SUBCONTRACTED` when
    `subcontractor_id` is non-null and `DIRECT` otherwise, and it is never
    supplied by the client."
    PRD §3.2: "Termination cascades. Every agent whose `subcontractor_id` names
    the terminated firm and whose `status` is not already `TERMINATED` moves to
    `TERMINATED`; because those agents were terminated, every occupation of
    theirs whose `status` is `RESERVED` or `COMMITTED` moves to `CANCELLED`
    with `cancel_reason` recorded as `SUBCONTRACTOR_TERMINATED`, and each
    cancellation reduces that agent's `assigned_duty_minutes` by the
    occupation's `occupied_minutes`."

    Design: Difficulty/cross_entity_state_dependency/agent_assignment_blocked_by_suspended_subcontractor
    """
    _station, _firm, agent, turn = _setup_active_agent_of_a_suspended_firm()
    api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())

    agent = get_agent(agent["id"])
    assert agent["status"] == "ACTIVE", (
        "suspension of the firm does not terminate its agents")
    assert agent["employment_type"] == "SUBCONTRACTED"
    assert agent["assigned_duty_minutes"] == 0
    turn = get_turn(turn["id"])
    assert turn["assigned_agent_count"] == 0
    assert turn["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue B: validations / staffing_submit_on_draft_bank_returns_bank_not_published
# ---------------------------------------------------------------------------

def test_staffing_submit_before_publication_is_refused(api):
    """PRD §3.3: "A `DutyOfficer` submits the plan with `SUBMIT`, moving
    `staffing_status` `DRAFT → SUBMITTED`; submission requires the staffing
    axis to be `DRAFT` and requires `bank_status` to be exactly `PUBLISHED`,
    and a submission attempted while the bank is not published is refused with
    `ERR_BANK_NOT_PUBLISHED`."

    Design: Corner/validations/staffing_submit_on_draft_bank_returns_bank_not_published
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    create_turn(station["id"], bank["id"])

    resp = api.staffing_transition(bank["id"], {"action": "SUBMIT"},
                                   make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_BANK_NOT_PUBLISHED, 409)

    bank = get_flight_bank(bank["id"])
    assert bank["bank_status"] == "DRAFT"
    assert bank["staffing_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B: validations / restricted_posture_blocks_new_turn_creation
# ---------------------------------------------------------------------------

def test_restricted_posture_blocks_new_turns_until_the_incident_closes(api):
    """PRD §2.10: "While a station is `RESTRICTED`, no new turnaround and no
    new flight bank may be created there; both are refused with
    `ERR_STATION_POSTURE_RESTRICTED` and HTTP 409."
    PRD §3.8: "The station's two open-incident counters and its
    `oversight_posture` are recomputed, and because a `CLOSED` incident no
    longer counts as open, this is typically the moment a `RESTRICTED` station
    comes back to `ENHANCED` or `NORMAL`."

    Design: Corner/validations/restricted_posture_blocks_new_turn_creation
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    incident = report_incident(
        station["id"], user_id="duty-01", incident_type="PERSONAL_INJURY",
        severity="CRITICAL", occurred_at="2026-03-31T12:00:00Z")
    before = get_station(station["id"])
    assert before["open_critical_incident_count"] == 1
    assert before["oversight_posture"] == "RESTRICTED"

    payload = {"station_id": station["id"], "flight_bank_id": bank["id"],
               "flight_number": "LX318", "turn_type": "TOWING_ONLY",
               "scheduled_in": "2026-04-10T06:00:00Z",
               "scheduled_out": "2026-04-10T06:20:00Z"}
    resp = api.create_turn(payload, make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_STATION_POSTURE_RESTRICTED, 409)

    close_out_incident(incident["id"], liability_party="HANDLER",
                       root_cause_code="PPE_NOT_WORN")
    created = validate_success(
        api.create_turn(payload, make_duty_officer_headers()), 201)
    assert created["status"] == "SCHEDULED"

    after = get_station(station["id"])
    assert after["open_critical_incident_count"] == 0
    assert after["oversight_posture"] == "NORMAL"
    assert get_flight_bank(bank["id"])["turn_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: validations /
#          enhanced_posture_blocks_subcontracted_agent_but_allows_direct_agent
# ---------------------------------------------------------------------------

def test_enhanced_posture_blocks_only_the_subcontracted_agent(api):
    """PRD §2.10: "While a station is `ENHANCED`, an occupation may not be
    created for an agent whose `employment_type` is `SUBCONTRACTED`; that too
    is refused with `ERR_STATION_POSTURE_RESTRICTED`."
    PRD §2.10: "Otherwise it is `ENHANCED` if either `open_major_incident_count`
    is at least 1, or the station has completed at least 3 turnarounds and its
    `otp_rolling_pct` is strictly below its `otp_target_pct`."

    Design: Corner/validations/enhanced_posture_blocks_subcontracted_agent_but_allows_direct_agent
    """
    station = create_open_station()
    firm = create_approved_subcontractor(station["id"],
                                         legal_name="Alpine Ramp AG")
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    sub_agent = create_certified_agent(station["id"], employee_code="E010",
                                       full_name="Cleo Marin",
                                       subcontractor_id=firm["id"])
    direct_agent = create_certified_agent(station["id"], employee_code="E001",
                                          full_name="Ana Ruiz")
    report_incident(station["id"], user_id="duty-01", incident_type="NEAR_MISS",
                    severity="MAJOR", occurred_at="2026-03-31T12:00:00Z")
    posture = get_station(station["id"])
    assert posture["open_major_incident_count"] == 1
    assert posture["oversight_posture"] == "ENHANCED"

    def occupation_payload(agent_id):
        return {"turn_id": turn["id"], "resource_kind": "AGENT",
                "agent_id": agent_id, "role_on_turn": "RAMP",
                "window_start": "2026-04-10T05:50:00Z",
                "window_end": "2026-04-10T06:30:00Z",
                "expected_turn_version": turn["version"]}

    refused = api.create_turn_resource(occupation_payload(sub_agent["id"]),
                                       make_duty_officer_headers())
    validate_error(refused, ApiErrorId.ERR_STATION_POSTURE_RESTRICTED, 409)
    assert get_agent(sub_agent["id"])["assigned_duty_minutes"] == 0

    accepted = validate_success(api.create_turn_resource(
        occupation_payload(direct_agent["id"]), make_duty_officer_headers()), 201)
    assert get_turn_resource(accepted["id"])["status"] == "RESERVED"
    assert get_agent(direct_agent["id"])["assigned_duty_minutes"] == 40
    assert get_turn(turn["id"])["assigned_agent_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: validations / loader_role_without_belt_loader_endorsement_is_rejected
# ---------------------------------------------------------------------------

def test_loader_role_needs_a_belt_loader_endorsement_as_well(api):
    """PRD §3.5: "A `LOADER` needs `RAMP_SAFETY` and `BELT_LOADER`."
    PRD §3.5: "Every one of the required endorsements must be held by the agent
    at the turnaround's station and be effective at the occupation's start; if
    even one is missing, expired, not yet issued or revoked, the commitment is
    refused with `ERR_CERT_NOT_CURRENT` and HTTP 422."

    Design: Corner/validations/loader_role_without_belt_loader_endorsement_is_rejected
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=2)
    turn = create_turn(station["id"], bank["id"], turn_type="NARROWBODY_QUICK",
                       scheduled_out="2026-04-10T06:30:00Z")
    agent = create_certified_agent(station["id"])

    payload = {"turn_id": turn["id"], "resource_kind": "AGENT",
               "agent_id": agent["id"], "role_on_turn": "LOADER",
               "window_start": "2026-04-10T05:50:00Z",
               "window_end": "2026-04-10T06:40:00Z",
               "expected_turn_version": turn["version"]}
    refused = api.create_turn_resource(payload, make_duty_officer_headers())
    validate_error(refused, ApiErrorId.ERR_CERT_NOT_CURRENT, 422)

    belt = issue_certification(agent["id"], station["id"],
                               cert_type="BELT_LOADER")
    assert belt["currency_state"] == "CURRENT"

    accepted = validate_success(
        api.create_turn_resource(payload, make_duty_officer_headers()), 201)
    assert accepted["role_on_turn"] == "LOADER"
    assert accepted["status"] == "RESERVED"
    assert get_turn(turn["id"])["assigned_agent_count"] == 1
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 50


# ---------------------------------------------------------------------------
# Queue B: validations / flight_bank_season_differing_from_station_returns_season_mismatch
# ---------------------------------------------------------------------------

def test_bank_season_must_match_the_station_season_at_creation(api):
    """PRD §3.3: "The `season_code` supplied must equal the station's own
    `season_code` at the moment of creation; a mismatch is refused with
    `ERR_SEASON_MISMATCH`."

    Design: Corner/validations/flight_bank_season_differing_from_station_returns_season_mismatch
    """
    station = create_open_station(season_code="SUMMER")

    resp = api.create_flight_bank(
        {"station_id": station["id"], "bank_code": "W1",
         "season_code": "WINTER", "window_start": "2026-04-10T04:00:00Z",
         "window_end": "2026-04-10T22:00:00Z", "planned_headcount": 1},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_SEASON_MISMATCH, 409)

    rows, meta = validate_paginated(api.list_flight_banks(
        make_duty_officer_headers(), {"station_id": station["id"]}))
    assert meta["total_count"] == 0
    assert rows == []
