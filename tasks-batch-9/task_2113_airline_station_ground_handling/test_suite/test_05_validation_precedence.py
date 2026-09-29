"""Order of evaluation: which failure a request that violates several rules at
once must actually report."""
from test_helpers import (
    ApiErrorId,
    add_billing_line,
    add_agent_occupation,
    add_gse_occupation,
    assert_instant,
    cancel_turn,
    close_out_incident,
    complete_turn,
    create_agent,
    create_billing_period,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    complete_service,
    get_agent,
    get_billing_line,
    get_billing_period,
    get_certification,
    get_gse_unit,
    get_turn,
    get_turn_resource,
    issue_certification,
    make_billing_controller_headers,
    make_duty_officer_headers,
    publish_and_approve_staffing,
    report_incident,
    revoke_certification,
    schedule_service_hold,
    start_turn,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict /
#          cancelled_turn_state_beats_lapsed_certification_safety
# ---------------------------------------------------------------------------

def _setup_cancelled_turn_and_lapsed_agent():
    """A CANCELLED turn plus an agent whose only RAMP_SAFETY endorsement ran
    2026-01-01 to 2026-02-01, so both the state rule and the currency rule
    would refuse the same occupation."""
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_agent(station["id"])
    certification = issue_certification(
        agent["id"], station["id"], issued_at="2026-01-01T00:00:00Z",
        expires_at="2026-02-01T00:00:00Z")
    cancelled = cancel_turn(turn["id"], reason="SLOT_WITHDRAWN")
    assert cancelled["status"] == "CANCELLED"
    return station, get_turn(turn["id"]), agent, certification


def test_cancelled_turn_state_check_precedes_the_certification_safety_gate(api):
    """PRD §2.6: "This ordering is normative: a request that violates checks at
    positions 4 and 12 must report the position-4 error, never the position-12
    one."
    PRD §3.7: "Its `status` must be `SCHEDULED` or `RESOURCED`; a turnaround
    that is `IN_PROGRESS`, `COMPLETED`, `CANCELLED` or `DISRUPTED` is refused
    with `ERR_TURN_NOT_ASSIGNABLE`."
    PRD §3.5: "Every one of the required endorsements must be held by the agent
    at the turnaround's station and be effective at the occupation's start; if
    even one is missing, expired, not yet issued or revoked, the commitment is
    refused with `ERR_CERT_NOT_CURRENT` and HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_turn_state_beats_lapsed_certification_safety
    """
    _station, turn, agent, _certification = _setup_cancelled_turn_and_lapsed_agent()

    resp = api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())
    error = validate_error(resp, ApiErrorId.ERR_TURN_NOT_ASSIGNABLE, 409)
    assert error["error_id"] != ApiErrorId.ERR_CERT_NOT_CURRENT.value
    assert resp.status_code == 409, (
        "the position-10 state failure carries 409, not the certification 422")


def test_the_certification_violation_was_live_but_never_reported(api):
    """PRD §3.5: "The published `currency_state` applies that primitive at the
    current logical clock: it reads `REVOKED` when the endorsement's `status`
    is `REVOKED`; otherwise `LAPSED` when the endorsement is not effective at
    the clock; otherwise `EXPIRING` when the time remaining from the clock to
    `expires_at` is 30 days or less; otherwise `CURRENT`."
    PRD §3.7: "An accepted occupation lands at `RESERVED`."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_turn_state_beats_lapsed_certification_safety
    """
    _station, turn, agent, certification = _setup_cancelled_turn_and_lapsed_agent()
    api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())

    assert get_certification(certification["id"])["currency_state"] == "LAPSED", (
        "the endorsement really had lapsed, so both rules were violated at once")
    assert get_turn(turn["id"])["assigned_agent_count"] == 0
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 0


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict /
#          open_critical_incident_safety_beats_penalty_cap_fiscal
# ---------------------------------------------------------------------------

def _setup_period_breaching_cap_with_open_critical_incident():
    """A period whose finalization would produce a 4284-cent OTP penalty
    against a 1000-cent cap, at a station that also carries an open CRITICAL
    incident."""
    station = create_open_station(penalty_cap_cents=1000,
                                  otp_tolerance_minutes=15,
                                  otp_target_pct=85.00,
                                  gse_reposition_buffer_minutes=20,
                                  damage_penalty_multiplier=1.00)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"])
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"])
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")
    complete_turn(turn["id"], actual_out="2026-04-10T06:38:00Z",
                  delay_code="GH_EQUIPMENT")
    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    incident = report_incident(
        station["id"], user_id="duty-01", incident_type="PERSONAL_INJURY",
        severity="CRITICAL", occurred_at="2026-04-01T00:00:00Z",
        description="Loader operator hospitalised")
    return station, period, line, incident


def test_open_critical_incident_is_reported_before_the_penalty_cap(api):
    """PRD §3.9: "Four preconditions guard the move: the period must hold at
    least one line; every turnaround referenced by a non-void line must have
    `status` `COMPLETED` or `CANCELLED`; the station must hold no incident
    whose `severity` is `CRITICAL` and whose `status` is anything other than
    `CLOSED`, or the request is refused with `ERR_OPEN_CRITICAL_INCIDENT`; and
    the combined `otp_penalty_cents` plus `damage_penalty_cents` that
    finalization would produce must not exceed the station's
    `penalty_cap_cents`, or the request is refused with
    `ERR_PENALTY_CAP_BREACHED` and HTTP 422."
    PRD §2.6: "The codes are `ERR_STATION_POSTURE_RESTRICTED` (409),
    `ERR_OPEN_CRITICAL_INCIDENT` (409) and `ERR_CERT_NOT_CURRENT` (422)."

    Design: Difficulty/priority_pair_validation_conflict/open_critical_incident_safety_beats_penalty_cap_fiscal
    """
    _station, period, line, _incident = (
        _setup_period_breaching_cap_with_open_critical_incident())

    resp = api.billing_period_transition(
        period["id"], {"action": "FINALIZE"},
        make_billing_controller_headers("bc-01"))
    error = validate_error(resp, ApiErrorId.ERR_OPEN_CRITICAL_INCIDENT, 409)
    assert error["error_id"] != ApiErrorId.ERR_PENALTY_CAP_BREACHED.value

    period = get_billing_period(period["id"])
    assert period["status"] == "OPEN"
    assert period["finalized_by_user_id"] is None
    assert get_billing_line(line["id"])["status"] == "PROVISIONAL"


def test_penalty_cap_breach_surfaces_only_once_the_incident_is_closed(api):
    """PRD §3.9: "Four preconditions guard the move: the period must hold at
    least one line; every turnaround referenced by a non-void line must have
    `status` `COMPLETED` or `CANCELLED`; the station must hold no incident
    whose `severity` is `CRITICAL` and whose `status` is anything other than
    `CLOSED`, or the request is refused with `ERR_OPEN_CRITICAL_INCIDENT`; and
    the combined `otp_penalty_cents` plus `damage_penalty_cents` that
    finalization would produce must not exceed the station's
    `penalty_cap_cents`, or the request is refused with
    `ERR_PENALTY_CAP_BREACHED` and HTTP 422."
    PRD §3.8: "Closing the file with `CLOSE` moves it `FINDINGS_ISSUED →
    CLOSED`, stamps `closed_by_user_id`, and requires that the acting
    `X-User-ID` differ from `findings_issued_by_user_id`."

    Design: Difficulty/priority_pair_validation_conflict/open_critical_incident_safety_beats_penalty_cap_fiscal
    """
    _station, period, line, incident = (
        _setup_period_breaching_cap_with_open_critical_incident())
    api.billing_period_transition(period["id"], {"action": "FINALIZE"},
                                  make_billing_controller_headers("bc-01"))
    close_out_incident(incident["id"], liability_party="CARRIER",
                       root_cause_code="LOAD_SHIFT")

    resp = api.billing_period_transition(
        period["id"], {"action": "FINALIZE"},
        make_billing_controller_headers("bc-01"))
    validate_error(resp, ApiErrorId.ERR_PENALTY_CAP_BREACHED, 422)

    period = get_billing_period(period["id"])
    assert period["status"] == "OPEN"
    assert period["finalized_by_user_id"] is None
    line = get_billing_line(line["id"])
    assert line["status"] == "PROVISIONAL"
    assert line["gross_amount_cents"] == 18000


# ---------------------------------------------------------------------------
# Queue B: validations / turn_referencing_bank_of_another_station_is_rejected
# ---------------------------------------------------------------------------

def test_station_scope_is_checked_before_the_bank_window_geometry(api):
    """PRD §2.4: "A turnaround's flight bank must sit at the turnaround's
    station; an agent assigned to a turnaround must be homed at that
    turnaround's station; a GSE unit committed to a turnaround must be based at
    that turnaround's station; an endorsement must be issued at its agent's
    station; a subcontractor must be registered at its agent's station; a
    tier-2 subcontractor's sponsor must be registered at the same station as
    the tier-2 firm itself; the turnaround a billing line charges must belong
    to the same station as the billing period the line accrues into; and an
    incident's referenced turnaround, GSE unit and agent must all belong to the
    incident's own station."
    PRD §2.6: "**Station-scope coherence.** The cross-record station checks
    listed in Section 2.4, otherwise `ERR_STATION_SCOPE_MISMATCH` (409)."

    Design: Corner/validations/turn_referencing_bank_of_another_station_is_rejected
    """
    zurich = create_open_station(iata_code="ZRH", name="Zurich")
    geneva = create_open_station(clock=None, iata_code="GVA", name="Geneva")
    geneva_bank = create_flight_bank(
        geneva["id"], bank_code="GVA-1", planned_headcount=1,
        window_start="2026-04-10T04:00:00Z", window_end="2026-04-10T10:00:00Z")

    resp = api.create_turn(
        {"station_id": zurich["id"], "flight_bank_id": geneva_bank["id"],
         "flight_number": "LX318", "turn_type": "TOWING_ONLY",
         "scheduled_in": "2026-04-10T18:00:00Z",
         "scheduled_out": "2026-04-10T18:20:00Z"},
        make_duty_officer_headers())
    error = validate_error(resp, ApiErrorId.ERR_STATION_SCOPE_MISMATCH, 409)
    assert error["error_id"] != ApiErrorId.ERR_TURN_WINDOW_OUTSIDE_BANK.value, (
        "scope coherence at position 6 pre-empts the position-13 geometry test")

    rows, meta = validate_paginated(api.list_turns(
        make_duty_officer_headers(), {"flight_bank_id": geneva_bank["id"]}))
    assert meta["total_count"] == 0
    assert rows == []


# ---------------------------------------------------------------------------
# Queue B: validations / assigning_a_suspended_agent_returns_agent_not_active
# ---------------------------------------------------------------------------

def test_suspended_agent_is_refused_before_the_certification_gate(api):
    """PRD §3.5: "An attempt to commit an agent whose `status` is `SUSPENDED`
    or `TERMINATED` is refused with `ERR_AGENT_NOT_ACTIVE`; an attempt to
    commit an agent whose employing firm is in any status other than `APPROVED`
    or `PROBATION` is refused with `ERR_SUBCONTRACTOR_NOT_APPROVED`."
    PRD §2.6: "The codes are `ERR_STATION_NOT_OPEN`, `ERR_BANK_NOT_PUBLISHED`,
    `ERR_STAFFING_NOT_APPROVED`, `ERR_AGENT_NOT_ACTIVE`,
    `ERR_SUBCONTRACTOR_NOT_APPROVED` and `ERR_GSE_NOT_SERVICEABLE`, all HTTP
    409."

    Design: Corner/validations/assigning_a_suspended_agent_returns_agent_not_active
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_agent(station["id"])
    certification = issue_certification(agent["id"], station["id"])
    revoke_certification(certification["id"], reason="TRAINING_AUDIT_FAILURE",
                         user_id="safety-01")
    assert get_agent(agent["id"])["status"] == "SUSPENDED"

    resp = api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())
    error = validate_error(resp, ApiErrorId.ERR_AGENT_NOT_ACTIVE, 409)
    assert error["error_id"] != ApiErrorId.ERR_CERT_NOT_CURRENT.value
    assert get_turn(turn["id"])["assigned_agent_count"] == 0


# ---------------------------------------------------------------------------
# Queue B: validations / named_gse_unit_in_maintenance_returns_not_serviceable
# ---------------------------------------------------------------------------

def test_named_unit_on_an_immediate_hold_is_not_serviceable_until_serviced(api):
    """PRD §3.6: "When a request does name a specific unit, that unit's
    `status` must be exactly `AVAILABLE`; a unit that is `IN_MAINTENANCE`,
    `QUARANTINED` or `RETIRED` is refused with `ERR_GSE_NOT_SERVICEABLE`."
    PRD §3.6: "Scheduling a hold with `HOLD_SCHEDULED` whose `hold_start` is at
    or before the current logical clock takes the unit `AVAILABLE →
    IN_MAINTENANCE` and records the supplied window into `service_hold_start`
    and `service_hold_end`; the unit stops being eligible for selection."
    PRD §3.6: "Recording a completed service with `SERVICE_COMPLETED` returns
    the unit to `AVAILABLE` from either `IN_MAINTENANCE` or `QUARANTINED` —
    both `IN_MAINTENANCE → AVAILABLE` and `QUARANTINED → AVAILABLE` are
    admissible — resets `cycles_since_service` to 0, stamps `last_service_at`
    from the logical clock, and clears both hold boundaries."

    Design: Corner/validations/named_gse_unit_in_maintenance_returns_not_serviceable
    """
    station = create_open_station(clock="2026-04-10T05:00:00Z")
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    gse = create_gse_unit(station["id"])
    held = schedule_service_hold(gse["id"], hold_start="2026-04-10T05:00:00Z",
                                 hold_end="2026-04-10T05:30:00Z")
    assert held["status"] == "IN_MAINTENANCE"

    payload = {"turn_id": turn["id"], "resource_kind": "GSE",
               "gse_unit_id": gse["id"],
               "window_start": "2026-04-10T09:00:00Z",
               "window_end": "2026-04-10T09:30:00Z",
               "expected_turn_version": turn["version"]}
    resp = api.create_turn_resource(payload, make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_GSE_NOT_SERVICEABLE, 409)

    serviced = complete_service(gse["id"])
    assert serviced["status"] == "AVAILABLE"
    assert serviced["cycles_since_service"] == 0
    assert serviced["service_hold_start"] is None
    assert_instant(serviced["last_service_at"], "2026-04-10T05:00:00Z",
                   "last_service_at")

    accepted = validate_success(
        api.create_turn_resource(payload, make_duty_officer_headers()), 201)
    assert get_turn_resource(accepted["id"])["status"] == "RESERVED"
    assert get_gse_unit(gse["id"])["committed_occupation_minutes"] == 30
