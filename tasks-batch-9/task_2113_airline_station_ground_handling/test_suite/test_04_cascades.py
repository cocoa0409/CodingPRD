"""Cascade discipline: the equipment-quarantine and endorsement-revocation
chains, station suspension, seasonal rollover, turn completion and closure."""
from test_helpers import (
    ApiErrorId,
    add_agent_occupation,
    add_gse_occupation,
    assert_instant,
    assert_pct,
    cancel_turn,
    complete_turn,
    create_agent,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    get_agent,
    get_certification,
    get_flight_bank,
    get_gse_unit,
    get_incident,
    get_station,
    get_turn,
    get_turn_resource,
    issue_certification,
    make_station_manager_headers,
    publish_and_approve_staffing,
    publish_bank,
    report_incident,
    revoke_certification,
    roll_season,
    setup_resourced_turn,
    start_turn,
    suspend_station,
    validate_error,
)


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / critical_gse_incident_four_hop_cascade
# ---------------------------------------------------------------------------

def _setup_resourced_turn_then_quarantine_incident():
    """A RESOURCED TOWING_ONLY turn with a 40-minute agent occupation and a
    30-minute tug occupation, then a CRITICAL GSE_DAMAGE report naming the tug."""
    scenario = setup_resourced_turn(approve_plan=True)
    incident = report_incident(
        scenario["station"]["id"], user_id="safety-01", role="SafetyOfficer",
        incident_type="GSE_DAMAGE", severity="CRITICAL",
        occurred_at="2026-04-01T00:00:00Z",
        gse_unit_id=scenario["gse"]["id"], turn_id=scenario["turn"]["id"],
        description="Tug drivetrain failure with aircraft contact")
    scenario["incident"] = incident
    return scenario


def test_critical_equipment_incident_quarantines_the_unit_and_cancels_its_work(api):
    """PRD §3.6: "Quarantine works differently and is driven by safety:
    reporting a `CRITICAL` incident that names a `gse_unit_id` takes that unit
    `AVAILABLE → QUARANTINED` or `IN_MAINTENANCE → QUARANTINED`, and because
    the unit was quarantined, every occupation of it sitting at `RESERVED` or
    `COMMITTED` moves to `CANCELLED` with `cancel_reason` recorded as
    `GSE_QUARANTINED` and `committed_occupation_minutes` reduced to its new
    ledger value."

    Design: Difficulty/transitive_cascade/critical_gse_incident_four_hop_cascade
    """
    scenario = _setup_resourced_turn_then_quarantine_incident()

    gse = get_gse_unit(scenario["gse"]["id"])
    assert gse["status"] == "QUARANTINED"
    assert gse["committed_occupation_minutes"] == 0

    gse_resource = get_turn_resource(scenario["gse_resource"]["id"])
    assert gse_resource["status"] == "CANCELLED"
    assert gse_resource["cancel_reason"] == "GSE_QUARANTINED"

    agent_resource = get_turn_resource(scenario["agent_resource"]["id"])
    assert agent_resource["status"] == "RESERVED", (
        "the agent occupation on the same turn is not part of the equipment chain")
    assert get_agent(scenario["agent"]["id"])["assigned_duty_minutes"] == 40


def test_equipment_quarantine_demotes_the_turn_and_its_bank_staffing_plan(api):
    """PRD §3.8: "A `CRITICAL` report that names a `gse_unit_id` additionally
    fires the four-hop equipment cascade: the unit is quarantined, its reserved
    and committed occupations are cancelled with ledger decrements, turnarounds
    that lose coverage demote `RESOURCED → SCHEDULED`, and their `APPROVED`
    bank staffing plans drop to `REVISION_REQUIRED`."
    PRD §2.10: "The posture is then `RESTRICTED` if
    `open_critical_incident_count` is at least 1."

    Design: Difficulty/transitive_cascade/critical_gse_incident_four_hop_cascade
    """
    scenario = _setup_resourced_turn_then_quarantine_incident()

    turn = get_turn(scenario["turn"]["id"])
    assert turn["status"] == "SCHEDULED"
    assert turn["assigned_gse_count"] == 0
    assert turn["assigned_agent_count"] == 1

    bank = get_flight_bank(scenario["bank"]["id"])
    assert bank["staffing_status"] == "REVISION_REQUIRED"
    assert bank["bank_status"] == "PUBLISHED"

    station = get_station(scenario["station"]["id"])
    assert station["open_critical_incident_count"] == 1
    assert station["oversight_posture"] == "RESTRICTED"
    assert get_incident(scenario["incident"]["id"])["status"] == "REPORTED"


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / certification_revoke_four_hop_cascade
# ---------------------------------------------------------------------------

def _setup_resourced_turn_then_revoke_endorsement():
    """The same RESOURCED turn, but the chain starts from revoking the agent's
    only RAMP_SAFETY endorsement."""
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_agent(station["id"])
    certification = issue_certification(agent["id"], station["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])
    agent_resource = add_agent_occupation(
        turn["id"], agent["id"], window_start="2026-04-10T05:50:00Z",
        window_end="2026-04-10T06:30:00Z")
    gse_resource = add_gse_occupation(
        turn["id"], gse_unit_id=gse["id"],
        window_start="2026-04-10T05:55:00Z", window_end="2026-04-10T06:25:00Z")
    assert get_turn(turn["id"])["status"] == "RESOURCED"
    revoked = revoke_certification(certification["id"],
                                   reason="FALSIFIED_TRAINING_RECORD",
                                   user_id="safety-01")
    return {"station": station, "bank": bank, "turn": turn, "agent": agent,
            "gse": gse, "certification": certification,
            "agent_resource": agent_resource, "gse_resource": gse_resource,
            "revoked": revoked}


def test_revoking_the_only_ramp_safety_suspends_the_agent_and_voids_duty(api):
    """PRD §3.5: "If the revoked endorsement was that agent's only effective
    `RAMP_SAFETY` at their own station, the agent's posture becomes `LAPSED`
    and the agent moves `ACTIVE → SUSPENDED`."
    PRD §3.5: "Because the agent was suspended, every occupation of theirs
    sitting at `RESERVED` or `COMMITTED` moves to `CANCELLED` with
    `cancel_reason` recorded as `AGENT_SUSPENDED`, and `assigned_duty_minutes`
    is reduced to its new ledger value."

    Design: Difficulty/transitive_cascade/certification_revoke_four_hop_cascade
    """
    scenario = _setup_resourced_turn_then_revoke_endorsement()
    assert scenario["revoked"]["status"] == "REVOKED"
    assert scenario["revoked"]["currency_state"] == "REVOKED"
    assert get_certification(scenario["certification"]["id"])["status"] == "REVOKED"

    agent = get_agent(scenario["agent"]["id"])
    assert agent["status"] == "SUSPENDED"
    assert agent["certification_posture"] == "LAPSED"
    assert agent["assigned_duty_minutes"] == 0

    agent_resource = get_turn_resource(scenario["agent_resource"]["id"])
    assert agent_resource["status"] == "CANCELLED"
    assert agent_resource["cancel_reason"] == "AGENT_SUSPENDED"


def test_agent_suspension_demotes_the_turn_and_leaves_the_equipment_alone(api):
    """PRD §3.5: "Because those occupations were cancelled, any turnaround that
    thereby loses coverage demotes `RESOURCED → SCHEDULED`, and because it
    demoted, an owning bank at `APPROVED` on the staffing axis drops to
    `REVISION_REQUIRED`."
    PRD §2.7: "Whenever an occupation leaves the reserved-or-committed
    population, the two minute ledgers it fed must be reduced by exactly that
    occupation's minutes."

    Design: Difficulty/transitive_cascade/certification_revoke_four_hop_cascade
    """
    scenario = _setup_resourced_turn_then_revoke_endorsement()

    gse_resource = get_turn_resource(scenario["gse_resource"]["id"])
    assert gse_resource["status"] == "RESERVED", (
        "the equipment occupation is untouched by the certification chain")
    assert get_gse_unit(scenario["gse"]["id"])["committed_occupation_minutes"] == 30

    turn = get_turn(scenario["turn"]["id"])
    assert turn["status"] == "SCHEDULED"
    assert turn["assigned_agent_count"] == 0
    assert turn["assigned_gse_count"] == 1

    bank = get_flight_bank(scenario["bank"]["id"])
    assert bank["staffing_status"] == "REVISION_REQUIRED"
    assert bank["bank_status"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          station_suspend_cascades_bank_lock_turn_disruption_and_ledger_release
# ---------------------------------------------------------------------------

def test_suspending_the_station_runs_all_four_hops_in_one_request(api):
    """PRD §3.1: "First, every flight bank at the station whose `bank_status`
    is `PUBLISHED` moves to `LOCKED`. Second, because those banks became
    locked, each of them whose `staffing_status` is `APPROVED` moves to
    `REVISION_REQUIRED`. Third, because those staffing plans fell back, every
    turnaround inside those banks whose `status` is `SCHEDULED` or `RESOURCED`
    moves to `DISRUPTED`. Fourth, because those turnarounds were disrupted,
    every occupation on them whose `status` is `RESERVED` or `COMMITTED` moves
    to `CANCELLED` with its `cancel_reason` recorded as `STATION_SUSPENDED`,
    and each such cancellation reduces the affected unit's
    `committed_occupation_minutes` or the affected agent's
    `assigned_duty_minutes` by that occupation's `occupied_minutes`."

    Design: Corner/state_machines/station_suspend_cascades_bank_lock_turn_disruption_and_ledger_release
    """
    scenario = setup_resourced_turn(approve_plan=True)
    assert get_turn(scenario["turn"]["id"])["status"] == "RESOURCED"

    suspended = suspend_station(scenario["station"]["id"], reason="SNOW_CLOSURE")
    assert suspended["status"] == "SUSPENDED"

    bank = get_flight_bank(scenario["bank"]["id"])
    assert bank["bank_status"] == "LOCKED"
    assert bank["staffing_status"] == "REVISION_REQUIRED"
    assert get_turn(scenario["turn"]["id"])["status"] == "DISRUPTED"

    for key in ("agent_resource", "gse_resource"):
        resource = get_turn_resource(scenario[key]["id"])
        assert resource["status"] == "CANCELLED"
        assert resource["cancel_reason"] == "STATION_SUSPENDED"

    assert get_agent(scenario["agent"]["id"])["assigned_duty_minutes"] == 0
    gse = get_gse_unit(scenario["gse"]["id"])
    assert gse["committed_occupation_minutes"] == 0
    assert gse["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          season_rollover_archives_outgoing_banks_and_cancels_their_turns
# ---------------------------------------------------------------------------

def test_season_rollover_archives_the_outgoing_banks_and_cancels_their_work(api):
    """PRD §3.1: "Every flight bank at the station whose `season_code` equals
    the *outgoing* season and whose `bank_status` is `DRAFT`, `PUBLISHED` or
    `LOCKED` moves to `ARCHIVED`. Because those banks were archived, every
    turnaround inside them whose `status` is `SCHEDULED` or `RESOURCED` moves
    to `CANCELLED`. Because those turnarounds were cancelled, every occupation
    on them whose `status` is `RESERVED` or `COMMITTED` moves to `CANCELLED`
    with `cancel_reason` recorded as `SEASON_ROLLOVER`, decrementing the
    corresponding `committed_occupation_minutes` and `assigned_duty_minutes`
    ledgers."
    PRD §3.1: "Rolling the season is a separate manager-only capability whose
    entire value is its cascade: the station's `status` stays `OPEN`
    throughout."

    Design: Corner/state_machines/season_rollover_archives_outgoing_banks_and_cancels_their_turns
    """
    station = create_open_station(
        season_start_date="2026-03-29T00:00:00Z",
        season_end_date="2026-10-24T00:00:00Z")
    bank = create_flight_bank(station["id"], bank_code="S1", planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    publish_bank(bank["id"])
    resource = add_agent_occupation(turn["id"], agent["id"])

    rolled = roll_season(station["id"], "WINTER",
                         season_start_date="2026-10-25T00:00:00Z",
                         season_end_date="2027-03-27T00:00:00Z")
    assert rolled["season_code"] == "WINTER"
    assert rolled["status"] == "OPEN"

    assert get_flight_bank(bank["id"])["bank_status"] == "ARCHIVED"
    assert get_turn(turn["id"])["status"] == "CANCELLED"
    resource = get_turn_resource(resource["id"])
    assert resource["status"] == "CANCELLED"
    assert resource["cancel_reason"] == "SEASON_ROLLOVER"
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 0
    assert_instant(get_station(station["id"])["season_start_date"],
                   "2026-10-25T00:00:00Z", "season_start_date")


# ---------------------------------------------------------------------------
# Queue B: state_machines / season_rollover_to_the_same_season_returns_season_mismatch
# ---------------------------------------------------------------------------

def test_rolling_into_the_season_already_in_force_is_refused(api):
    """PRD §3.1: "The station must be `OPEN`, and `to_season_code` must differ
    from the `season_code` already in force — naming the season the station is
    already running is refused with `ERR_SEASON_MISMATCH`."

    Design: Corner/state_machines/season_rollover_to_the_same_season_returns_season_mismatch
    """
    station = create_open_station()

    resp = api.season_rollover(
        station["id"],
        {"to_season_code": "SUMMER", "season_start_date": "2026-03-29T00:00:00Z",
         "season_end_date": "2026-10-24T00:00:00Z"},
        make_station_manager_headers())
    validate_error(resp, ApiErrorId.ERR_SEASON_MISMATCH, 409)

    assert get_station(station["id"])["season_code"] == "SUMMER"


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          turn_completion_releases_resources_and_trips_gse_service_interval
# ---------------------------------------------------------------------------

def test_completion_releases_every_occupation_and_trips_the_service_interval(api):
    """PRD §3.4: "Every occupation on the turnaround sitting at `COMMITTED`
    moves to `RELEASED`, reducing the relevant unit's
    `committed_occupation_minutes` or agent's `assigned_duty_minutes` by that
    occupation's `occupied_minutes`. Each equipment occupation released this
    way adds 1 to its unit's `cycles_since_service`, and any unit whose
    `cycles_since_service` has thereby reached or passed its
    `service_interval_cycles` moves `AVAILABLE → IN_MAINTENANCE` and receives a
    four-hour service hold running from the current logical clock."

    Design: Corner/state_machines/turn_completion_releases_resources_and_trips_gse_service_interval
    """
    station = create_open_station(clock="2026-04-10T06:00:00Z")
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    tug = create_gse_unit(station["id"], asset_tag="TUG-01",
                          gse_type="PUSHBACK_TUG", condition_score=80,
                          service_interval_cycles=25, cycles_since_service=24)
    belt = create_gse_unit(station["id"], asset_tag="BELT-01",
                           gse_type="BELT_LOADER", condition_score=90,
                           service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])
    agent_resource = add_agent_occupation(turn["id"], agent["id"])
    tug_resource = add_gse_occupation(turn["id"], gse_unit_id=tug["id"])
    belt_resource = add_gse_occupation(turn["id"], gse_unit_id=belt["id"])
    assert start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")["status"] == \
        "IN_PROGRESS"

    completed = complete_turn(turn["id"], actual_out="2026-04-10T06:20:00Z",
                              delay_code="NONE")
    assert completed["status"] == "COMPLETED"
    assert completed["otp_result"] == "ON_TIME"
    assert completed["delay_minutes"] == 0

    tug = get_gse_unit(tug["id"])
    assert tug["cycles_since_service"] == 25
    assert tug["status"] == "IN_MAINTENANCE"
    assert_instant(tug["service_hold_start"], "2026-04-10T06:00:00Z",
                   "service_hold_start")
    assert_instant(tug["service_hold_end"], "2026-04-10T10:00:00Z",
                   "service_hold_end")
    assert tug["committed_occupation_minutes"] == 0

    belt = get_gse_unit(belt["id"])
    assert belt["cycles_since_service"] == 1
    assert belt["status"] == "AVAILABLE"

    for resource in (agent_resource, tug_resource, belt_resource):
        assert get_turn_resource(resource["id"])["status"] == "RELEASED"
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 0


# ---------------------------------------------------------------------------
# Queue B: state_machines / new_turn_drops_approved_staffing_plan_to_revision_required
# ---------------------------------------------------------------------------

def test_a_new_turn_that_drags_coverage_below_100_reopens_the_staffing_plan(api):
    """PRD §3.4: "The owning bank immediately recomputes `required_headcount`,
    `turn_count` and `staffing_coverage_pct`, and if the new turnaround drags
    coverage below 100.00 on a bank whose `staffing_status` was `APPROVED`,
    that plan drops to `REVISION_REQUIRED`."
    PRD §3.3: "Otherwise `staffing_coverage_pct` is 100 multiplied by
    `planned_headcount`, divided by `required_headcount`, rounded half up to
    two decimal places."

    Design: Corner/state_machines/new_turn_drops_approved_staffing_plan_to_revision_required
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    create_turn(station["id"], bank["id"])
    approved = publish_and_approve_staffing(bank["id"])
    assert approved["staffing_status"] == "APPROVED"
    assert_pct(approved["staffing_coverage_pct"], 100.00, "staffing_coverage_pct")

    second_turn = create_turn(station["id"], bank["id"], flight_number="LX319",
                              scheduled_in="2026-04-10T08:00:00Z",
                              scheduled_out="2026-04-10T08:20:00Z")
    assert second_turn["status"] == "SCHEDULED"

    bank = get_flight_bank(bank["id"])
    assert bank["required_headcount"] == 2
    assert_pct(bank["staffing_coverage_pct"], 50.00, "staffing_coverage_pct")
    assert bank["staffing_status"] == "REVISION_REQUIRED"
    assert bank["bank_status"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# Queue B: validations / closing_a_station_with_a_live_turn_returns_station_has_active_work
# ---------------------------------------------------------------------------

def test_closing_a_station_that_still_holds_a_live_turn_is_refused(api):
    """PRD §3.1: "The station must hold no turnaround in `SCHEDULED`,
    `RESOURCED` or `IN_PROGRESS`, and no billing period in `OPEN` or
    `PENDING_APPROVAL`; either condition refuses the close with
    `ERR_STATION_HAS_ACTIVE_WORK`."
    PRD §3.1: "When the close succeeds, `closed_at` is stamped from the logical
    clock, every flight bank at the station whose `bank_status` is not already
    `ARCHIVED` moves to `ARCHIVED`, and every GSE unit at the station whose
    `status` is not already `RETIRED` moves to `RETIRED`."

    Design: Corner/validations/closing_a_station_with_a_live_turn_returns_station_has_active_work
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    gse = create_gse_unit(station["id"])

    resp = api.station_lifecycle(station["id"], {"action": "CLOSE"},
                                 make_station_manager_headers())
    validate_error(resp, ApiErrorId.ERR_STATION_HAS_ACTIVE_WORK, 409)

    cancel_turn(turn["id"], reason="STATION_WIND_DOWN")
    closed = api.station_lifecycle(station["id"], {"action": "CLOSE"},
                                   make_station_manager_headers())
    assert closed.status_code == 200, closed.text

    assert get_station(station["id"])["status"] == "CLOSED"
    assert get_flight_bank(bank["id"])["bank_status"] == "ARCHIVED"
    assert get_gse_unit(gse["id"])["status"] == "RETIRED"
    assert get_turn(turn["id"])["status"] == "CANCELLED"
