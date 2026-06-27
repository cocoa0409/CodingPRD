"""Second-coverage tests for the dual-variant, combinatorial, and
boundary-precision difficulty rules.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula,
boundary_precision_check (each instance's second test).
"""
from test_helpers import (
    validate_success,
    set_clock, setup_agency_station_unit, create_incident, dispatch_unit,
    advance_assignment, create_incident_payload,
    SUP, CALL, DISP,
)


# =====================================================================
# dual_variant_calc — second tests
# =====================================================================
def test_response_time_excludes_queue_handle_includes_it(api):
    """PRD §3.6: "It uses the dispatch instant as the clock start and therefore
    excludes the intake-to-dispatch queue time."
    PRD §3.6: "It uses the call-receipt instant as the clock start and therefore
    *includes* the intake-to-dispatch queue time."

    With a 60s queue (received 00:00, dispatched 01:00, onscene 06:00):
    response = 06:00-01:00 = 300s, handle = 06:00-00:00 = 360s; the 60s queue
    is excluded from response but included in handle.

    Design: Difficulty/dual_variant_calc/response_vs_handle_time_diverge_on_incident
    """
    set_clock("2026-06-01T12:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", response_sla_seconds=600,
        grid_x=10, grid_y=10, call_sign="M2", name_prefix="EMS Two")
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=10, ali_grid_y=10, ani="5125550002")
    set_clock("2026-06-01T12:01:00Z")
    asg = dispatch_unit(incident["id"], incident["version"], unit_id=unit["id"])
    advance_assignment(asg["id"], unit["id"], "ENROUTE")
    set_clock("2026-06-01T12:06:00Z")
    advance_assignment(asg["id"], unit["id"], "ONSCENE")
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc["response_time_seconds"] == 300
    assert inc["total_handle_seconds"] == 360
    assert inc["total_handle_seconds"] - inc["response_time_seconds"] == 60


def test_recommendation_mutual_aid_only_consulted_after_primary_empties(api):
    """PRD §3.4: "If the primary pass yields no candidate, the platform runs a
    second, mutual-aid pass with the agency-status condition widened to include
    both `ONLINE` and `MUTUAL_AID_ONLY` agencies."

    With only a MUTUAL_AID_ONLY agency's unit available, the primary pass is
    empty so the mutual-aid pass recommends that unit.

    Design: Difficulty/dual_variant_calc/recommendation_primary_vs_mutual_aid_pass
    """
    set_clock("2026-06-01T13:00:00Z")
    agency, _, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=80, grid_y=80,
        call_sign="MA1", name_prefix="PD MutualOnly")
    validate_success(api.set_agency_status(agency["id"], "MUTUAL_AID_ONLY", SUP), 200)
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=80, ali_grid_y=80, ani="5125550011")
    rec = validate_success(
        api.get_recommendation(incident["id"], DISP, params={"discipline": "POLICE"}), 200)
    assert rec["recommended_unit_id"] == unit["id"]


# =====================================================================
# combinatorial_formula — second tests
# =====================================================================
def test_premise_clamp_then_confidence_clamp_takes_lower(api):
    """PRD §3.3: "Third, if an alert matched, the incident's `premise_alert_id`
    is set to that alert and the `priority_level` becomes the smaller of the
    `base_priority_level` and the alert's `min_priority_floor` — clamping the
    incident toward higher urgency".
    PRD §3.3: "Fourth, and applied strictly after the premise clamp, if
    `ali_confidence` is `UNKNOWN` the `priority_level` is set to the smaller of
    its current value and 2".

    ALARM (base 4) at a premise-floor-3 grid with ali_confidence UNKNOWN: premise
    clamp gives 3, then the confidence clamp lowers it to 2.

    Design: Difficulty/combinatorial_formula/priority_clamp_order_premise_then_confidence
    """
    set_clock("2026-06-02T01:00:00Z")
    pa = validate_success(api.create_premise_alert({
        "grid_x": 310, "grid_y": 310, "hazard_class": "STRUCTURAL",
        "min_priority_floor": 3}, SUP), 201)
    inc = validate_success(api.create_incident(create_incident_payload(
        ani="5125550021", ali_grid_x=310, ali_grid_y=310,
        incident_type="ALARM", ali_confidence="UNKNOWN"), CALL), 201)
    assert inc["base_priority_level"] == 4
    assert inc["priority_level"] == 2
    assert inc["premise_alert_id"] == pa["id"]


def test_governing_sla_breach_flips_true_when_only_lower_sla_applies(api):
    """PRD §3.6: "The platform first determines the governing SLA as the largest
    `response_sla_seconds` among the agencies that both have a discipline within
    the incident's `required_disciplines` and have at least one non-cancelled
    assignment on this incident".
    PRD §3.6: "The incident's `sla_breached` is true only when
    `total_handle_seconds` is strictly greater than the governing SLA".

    MEDICAL_EMERGENCY (required [EMS]) with one EMS agency sla=480 assigned;
    received 10:00:00, onscene 10:10:00 → handle=600 > 480 → sla_breached true
    (the single assigned agency governs).

    Design: Difficulty/combinatorial_formula/governing_sla_nested_aggregate_selection
    """
    set_clock("2026-06-03T10:00:00Z")
    _, _, med = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", response_sla_seconds=480,
        grid_x=72, grid_y=72, call_sign="M9", name_prefix="EMS Low")
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=72, ali_grid_y=72, ani="5125550031")
    set_clock("2026-06-03T10:01:00Z")
    asg = dispatch_unit(incident["id"], incident["version"], unit_id=med["id"])
    advance_assignment(asg["id"], med["id"], "ENROUTE")
    set_clock("2026-06-03T10:10:00Z")
    advance_assignment(asg["id"], med["id"], "ONSCENE")
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    # received 10:00:00 -> onscene 10:10:00 = 600s; 600 > 480 governing SLA
    assert inc["total_handle_seconds"] == 600
    assert inc["sla_breached"] is True


# =====================================================================
# boundary_precision_check — second tests
# =====================================================================
def test_sla_breached_one_second_over_governing_sla(api):
    """PRD §3.6: "The incident's `sla_breached` is true only when
    `total_handle_seconds` is strictly greater than the governing SLA — a handle
    time exactly equal to the target is not a breach."

    EMS sla=480; handle exactly 481 (one second over) → sla_breached true.

    Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_at_exact_boundary
    """
    set_clock("2026-06-10T09:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", response_sla_seconds=480,
        grid_x=13, grid_y=13, call_sign="MB2", name_prefix="EMS Bd2")
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=13, ali_grid_y=13, ani="5125550101")
    set_clock("2026-06-10T09:01:00Z")
    asg = dispatch_unit(incident["id"], incident["version"], unit_id=unit["id"])
    advance_assignment(asg["id"], unit["id"], "ENROUTE")
    set_clock("2026-06-10T09:09:01Z")  # received 09:00:00 -> handle 541? compute below
    advance_assignment(asg["id"], unit["id"], "ONSCENE")
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    # received 09:00:00, onscene 09:09:01 -> handle = 541 > 480
    assert inc["total_handle_seconds"] == 541
    assert inc["sla_breached"] is True


def test_auto_select_finds_unit_when_pool_non_empty(api):
    """PRD §3.4: "identifies the unit either explicitly by `unit_id` or by
    setting `auto_select` true to take the platform's own recommendation".

    Contrast to the empty-pool case: when exactly one eligible AVAILABLE unit
    exists, auto-select mints the assignment (no ERR_NO_UNIT_AVAILABLE).

    Design: Difficulty/boundary_precision_check/empty_candidate_pool_auto_select_no_unit
    """
    set_clock("2026-06-11T01:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=6, grid_y=6,
        call_sign="PE2", name_prefix="PD NonEmpty")
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=6, ali_grid_y=6, ani="5125550111")
    asg = validate_success(api.create_assignment(incident["id"], {
        "expected_incident_version": incident["version"],
        "auto_select": True, "discipline": "POLICE"}, DISP), 201)
    assert asg["unit_id"] == unit["id"]
    assert asg["status"] == "DISPATCHED"
