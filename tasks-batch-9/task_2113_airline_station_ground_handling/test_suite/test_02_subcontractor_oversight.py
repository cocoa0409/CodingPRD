"""Subcontractor oversight: the two compliance figures, tier-2 sponsorship,
the termination cascade and the incident snapshot that links a firm to events."""
from test_helpers import (
    add_agent_occupation,
    assert_pct,
    close_out_incident,
    create_agent,
    create_approved_subcontractor,
    create_certified_agent,
    create_flight_bank,
    create_open_station,
    create_subcontractor,
    create_turn,
    decide_oversight,
    get_agent,
    get_incident,
    get_station,
    get_subcontractor,
    get_turn,
    get_turn_resource,
    make_safety_officer_headers,
    make_station_manager_headers,
    report_incident,
    set_clock,
    validate_error,
    validate_paginated,
    ApiErrorId,
)


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc /
#          subcontractor_rolling_vs_audit_compliance_score_diverges
# ---------------------------------------------------------------------------

def _setup_three_incident_history():
    """Alpine Ramp AG carries three incidents against agent E900: a MINOR
    closed-liable one from 2025-08-01, a MAJOR closed-liable one from
    2026-01-05 and a CRITICAL one still REPORTED. The clock ends at
    2026-04-15, so the first is 257 days old and the second 100 days old."""
    station = create_open_station(
        clock="2025-07-01T00:00:00Z", iata_code="ZRH", name="Zurich",
        handler_code="SWP", season_code="SUMMER")
    subcontractor = create_approved_subcontractor(
        station["id"], legal_name="Alpine Ramp AG")
    agent = create_agent(station["id"], employee_code="E900",
                         full_name="Bruno Sub",
                         subcontractor_id=subcontractor["id"])

    set_clock("2025-08-02T00:00:00Z")
    incident_a = report_incident(
        station["id"], user_id="duty-01", incident_type="NEAR_MISS",
        severity="MINOR", occurred_at="2025-08-01T00:00:00Z",
        agent_id=agent["id"], description="Wingtip clearance call")
    close_out_incident(incident_a["id"], liability_party="SUBCONTRACTOR",
                       root_cause_code="SOP_DEVIATION")

    set_clock("2026-01-06T00:00:00Z")
    incident_b = report_incident(
        station["id"], user_id="duty-01", incident_type="PERSONAL_INJURY",
        severity="MAJOR", occurred_at="2026-01-05T00:00:00Z",
        agent_id=agent["id"], description="Belt loader crush injury")
    close_out_incident(incident_b["id"], liability_party="SUBCONTRACTOR",
                       root_cause_code="PPE_NOT_WORN")

    set_clock("2026-04-15T00:00:00Z")
    incident_c = report_incident(
        station["id"], user_id="duty-01", incident_type="PERSONAL_INJURY",
        severity="CRITICAL", occurred_at="2026-04-01T00:00:00Z",
        agent_id=agent["id"], description="Fall from stand")
    return station, subcontractor, agent, incident_c


def test_rolling_compliance_score_decays_closed_liable_incidents_by_age(api):
    """PRD §3.2: "The **rolling** figure, published as `compliance_score`,
    reads only those incidents that are both `CLOSED` and attributed to
    `liability_party` `SUBCONTRACTOR`, and it decays each one by age."
    PRD §3.2: "An incident aged 90 days or fewer contributes its full severity
    weight; one aged more than 90 days but no more than 180 days contributes
    half its severity weight; one aged more than 180 days contributes nothing
    at all."
    PRD §3.2: "Its `closed_liable_incident_count` is the number of those
    incidents whose `status` is `CLOSED` **and** whose `liability_party` is
    `SUBCONTRACTOR`."

    Design: Difficulty/dual_variant_calc/subcontractor_rolling_vs_audit_compliance_score_diverges
    """
    _station, subcontractor, _agent, _incident_c = _setup_three_incident_history()
    firm = get_subcontractor(subcontractor["id"])
    # MINOR at 257 days contributes nothing; MAJOR at 100 days contributes 7.5.
    assert_pct(firm["compliance_score"], 92.50, "compliance_score")
    assert firm["closed_liable_incident_count"] == 2
    assert float(firm["compliance_score"]) != float(firm["audit_compliance_score"]), (
        "the rolling and audit variants must diverge on this history")


def test_audit_compliance_score_counts_every_linked_incident_without_decay(api):
    """PRD §3.2: "It reads every incident whose `subcontractor_id` points at
    the firm — any `status`, any `liability_party`, including incidents still
    under investigation and incidents where a carrier or third party was
    ultimately blamed — and applies no decay whatsoever."
    PRD §3.2: "Its `total_incident_count` is the number of incidents whose
    `subcontractor_id` points at it, regardless of investigation status or of
    who was found liable."
    PRD §3.2: "A firm whose `compliance_score` falls strictly below 60.00 has
    its `oversight_flag` set to true; at exactly 60.00 the flag stays false."
    PRD §3.8: "if the recomputed `audit_compliance_score` is strictly below
    40.00 while the firm's `status` is `APPROVED`, the firm is automatically
    moved `APPROVED → PROBATION` without anyone requesting it."

    Design: Difficulty/dual_variant_calc/subcontractor_rolling_vs_audit_compliance_score_diverges
    """
    station, subcontractor, _agent, incident_c = _setup_three_incident_history()
    firm = get_subcontractor(subcontractor["id"])
    # 100 - (5 + 15 + 40) with no decay at all.
    assert_pct(firm["audit_compliance_score"], 40.00, "audit_compliance_score")
    assert firm["total_incident_count"] == 3
    assert firm["oversight_flag"] is False
    assert firm["status"] == "APPROVED", (
        "40.00 is not strictly below the 40.00 auto-probation threshold")

    assert get_incident(incident_c["id"])["status"] == "REPORTED"
    assert get_station(station["id"])["oversight_posture"] == "RESTRICTED"



# ---------------------------------------------------------------------------
# Queue B: entities / agent_employment_type_and_subcontractor_tier_are_derived
# ---------------------------------------------------------------------------

def test_employment_type_and_subcontractor_tier_are_derived_never_supplied(api):
    """PRD §3.2: "The `tier` attribute is never supplied: it reads `TIER_2`
    when `parent_subcontractor_id` is non-null and `TIER_1` otherwise."
    PRD §3.5: "The derived `employment_type` reads `SUBCONTRACTED` when
    `subcontractor_id` is non-null and `DIRECT` otherwise, and it is never
    supplied by the client."
    PRD §3.5: "A new agent lands `ACTIVE` with `assigned_duty_minutes` at zero
    and `certification_posture` at `LAPSED`, because an agent who holds no
    ramp-safety endorsement yet is not current for anything."

    Design: Corner/entities/agent_employment_type_and_subcontractor_tier_are_derived
    """
    station = create_open_station()
    sponsor = create_subcontractor(station["id"], legal_name="Alpine Ramp AG")
    assert sponsor["tier"] == "TIER_1"
    assert sponsor["status"] == "PENDING_VETTING"
    assert_pct(sponsor["compliance_score"], 100.00, "compliance_score")

    child = create_subcontractor(station["id"], legal_name="Alpine Deicing GmbH",
                                 parent_subcontractor_id=sponsor["id"])
    assert child["tier"] == "TIER_2"

    direct_agent = create_agent(station["id"], employee_code="E001",
                                full_name="Ana Ruiz")
    assert direct_agent["employment_type"] == "DIRECT"
    assert direct_agent["certification_posture"] == "LAPSED"

    sub_agent = create_agent(station["id"], employee_code="E010",
                             full_name="Cleo Marin",
                             subcontractor_id=sponsor["id"])
    assert sub_agent["employment_type"] == "SUBCONTRACTED"

    rows, meta = validate_paginated(api.list_subcontractors(
        make_station_manager_headers(),
        {"station_id": station["id"], "parent_subcontractor_id": sponsor["id"]}))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == child["id"]


# ---------------------------------------------------------------------------
# Queue B: validations / tier2_subcontractor_approval_requires_an_approved_sponsor
# ---------------------------------------------------------------------------

def test_tier2_approval_is_refused_while_its_sponsor_is_not_approved(api):
    """PRD §3.2: "Approving a firm with `APPROVE` moves it `PENDING_VETTING →
    APPROVED`; when the firm is `TIER_2`, its sponsor must itself be `APPROVED`
    at that moment, and a sponsor in any other status refuses the approval with
    `ERR_SUBCONTRACTOR_NOT_APPROVED`."

    Design: Corner/validations/tier2_subcontractor_approval_requires_an_approved_sponsor
    """
    station = create_open_station()
    sponsor = create_subcontractor(station["id"], legal_name="Alpine Ramp AG")
    child = create_subcontractor(station["id"], legal_name="Alpine Deicing GmbH",
                                 parent_subcontractor_id=sponsor["id"])
    assert child["tier"] == "TIER_2"

    resp = api.oversight_decision(child["id"], {"decision": "APPROVE"},
                                  make_station_manager_headers())
    validate_error(resp, ApiErrorId.ERR_SUBCONTRACTOR_NOT_APPROVED, 409)

    assert decide_oversight(sponsor["id"], "APPROVE")["status"] == "APPROVED"
    assert decide_oversight(child["id"], "APPROVE")["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Queue B: state_machines / subcontractor_terminate_cascades_agents_and_duty_ledger
# ---------------------------------------------------------------------------

def test_terminating_a_firm_terminates_its_agents_and_unwinds_their_duty(api):
    """PRD §3.2: "Every agent whose `subcontractor_id` names the terminated
    firm and whose `status` is not already `TERMINATED` moves to `TERMINATED`;
    because those agents were terminated, every occupation of theirs whose
    `status` is `RESERVED` or `COMMITTED` moves to `CANCELLED` with
    `cancel_reason` recorded as `SUBCONTRACTOR_TERMINATED`, and each
    cancellation reduces that agent's `assigned_duty_minutes` by the
    occupation's `occupied_minutes`."
    PRD §3.2: "Terminating a firm with `TERMINATE` moves it `SUSPENDED →
    TERMINATED`, which is terminal."

    Design: Corner/state_machines/subcontractor_terminate_cascades_agents_and_duty_ledger
    """
    station = create_open_station()
    firm = create_approved_subcontractor(station["id"], legal_name="Alpine Ramp AG")
    bank = create_flight_bank(station["id"], planned_headcount=2)
    turn = create_turn(station["id"], bank["id"], turn_type="NARROWBODY_QUICK",
                       scheduled_out="2026-04-10T06:30:00Z")
    sub_agent = create_certified_agent(
        station["id"], employee_code="E010", full_name="Cleo Marin",
        subcontractor_id=firm["id"])
    direct_agent = create_certified_agent(station["id"], employee_code="E001",
                                          full_name="Ana Ruiz")
    sub_resource = add_agent_occupation(
        turn["id"], sub_agent["id"], window_start="2026-04-10T05:50:00Z",
        window_end="2026-04-10T06:30:00Z")
    direct_resource = add_agent_occupation(
        turn["id"], direct_agent["id"], window_start="2026-04-10T05:50:00Z",
        window_end="2026-04-10T06:30:00Z")
    decide_oversight(firm["id"], "SUSPEND")

    terminated = decide_oversight(firm["id"], "TERMINATE", note="Contract ended")
    assert terminated["status"] == "TERMINATED"

    sub_agent = get_agent(sub_agent["id"])
    assert sub_agent["status"] == "TERMINATED"
    assert sub_agent["assigned_duty_minutes"] == 0
    sub_resource = get_turn_resource(sub_resource["id"])
    assert sub_resource["status"] == "CANCELLED"
    assert sub_resource["cancel_reason"] == "SUBCONTRACTOR_TERMINATED"

    direct_agent = get_agent(direct_agent["id"])
    assert direct_agent["status"] == "ACTIVE", (
        "a directly employed agent on the same turn is untouched")
    assert direct_agent["assigned_duty_minutes"] == 40
    assert get_turn_resource(direct_resource["id"])["status"] == "RESERVED"
    assert get_turn(turn["id"])["assigned_agent_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: endpoints / incidents_filtered_by_subcontractor_id_snapshot
# ---------------------------------------------------------------------------

def test_incident_subcontractor_snapshot_drives_the_filtered_incident_list(api):
    """PRD §3.8: "If an `agent_id` was supplied, the incident takes a snapshot
    of that agent's `subcontractor_id` into its own `subcontractor_id`; the
    snapshot is null when the agent is directly employed or when no agent was
    named, and it is a snapshot, so later changes to the agent's employment do
    not move it."
    PRD §2.3: "Incidents accept `station_id`, `turn_id`, `gse_unit_id`,
    `agent_id`, `subcontractor_id`, `status` and `severity`."

    Design: Corner/endpoints/incidents_filtered_by_subcontractor_id_snapshot
    """
    station = create_open_station()
    firm = create_approved_subcontractor(station["id"], legal_name="Alpine Ramp AG")
    sub_agent = create_agent(station["id"], employee_code="E010",
                             full_name="Cleo Marin", subcontractor_id=firm["id"])
    direct_agent = create_agent(station["id"], employee_code="E001",
                                full_name="Ana Ruiz")

    sub_incident = report_incident(
        station["id"], user_id="duty-01", incident_type="NEAR_MISS",
        severity="MINOR", occurred_at="2026-03-30T09:00:00Z",
        agent_id=sub_agent["id"])
    direct_incident = report_incident(
        station["id"], user_id="duty-01", incident_type="NEAR_MISS",
        severity="MINOR", occurred_at="2026-03-30T10:00:00Z",
        agent_id=direct_agent["id"])
    assert sub_incident["subcontractor_id"] == firm["id"]
    assert direct_incident["subcontractor_id"] is None

    rows, meta = validate_paginated(api.list_incidents(
        make_safety_officer_headers(), {"subcontractor_id": firm["id"]}))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == sub_incident["id"]

    firm = get_subcontractor(firm["id"])
    assert firm["total_incident_count"] == 1
    assert firm["closed_liable_incident_count"] == 0
    assert_pct(firm["compliance_score"], 100.00, "compliance_score")
    assert_pct(firm["audit_compliance_score"], 95.00, "audit_compliance_score")
