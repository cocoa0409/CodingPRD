"""Timing metrics, SLA breach, priority computation, and the nearest-unit
recommendation calculation.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, boundary_precision_check.
Queue B (Corner): calculations section.
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, setup_agency_station_unit, create_incident, dispatch_unit,
    advance_assignment, get_incident_version,
    create_premise_alert_payload, create_incident_payload,
    SUP, CALL, DISP,
)


# =====================================================================
# Queue A — dual_variant_calc
# =====================================================================
def test_response_and_handle_time_diverge_by_queue_delay(api):
    """PRD §3.6: "Because the two metrics share the same `first_onscene_at`
    endpoint but start from different anchors, they diverge by exactly the
    intake-to-dispatch queue delay."
    PRD §3.6: "The dispatch-based **response time**, stored as
    `response_time_seconds`, is the whole number of seconds from the incident's
    `first_dispatch_at` to its `first_onscene_at`, with any fractional second
    discarded by flooring."
    PRD §3.6: "The call-receipt-based **total handle time**, stored as
    `total_handle_seconds`, is the whole number of seconds from the incident's
    `received_at` to its `first_onscene_at`, again floored."

    received 08:00:00, dispatched 08:02:30 (queue 150s), onscene 08:09:00:
    response_time = 09:00 - 02:30 = 390s; handle = 09:00 - 00:00 = 540s.

    Design: Difficulty/dual_variant_calc/response_vs_handle_time_diverge_on_incident
    """
    set_clock("2026-06-01T08:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", response_sla_seconds=480,
        grid_x=10, grid_y=10, call_sign="M1", name_prefix="EMS One")
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=10, ali_grid_y=10, ani="5125550001")
    set_clock("2026-06-01T08:02:30Z")
    asg = dispatch_unit(incident["id"], incident["version"], unit_id=unit["id"])
    advance_assignment(asg["id"], unit["id"], "ENROUTE")
    set_clock("2026-06-01T08:09:00Z")
    advance_assignment(asg["id"], unit["id"], "ONSCENE")

    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc["response_time_seconds"] == 390, inc["response_time_seconds"]
    assert inc["total_handle_seconds"] == 540, inc["total_handle_seconds"]
    assert inc["response_time_seconds"] != inc["total_handle_seconds"]


def test_recommendation_primary_vs_mutual_aid_pass_pick_different_units(api):
    """PRD §3.4: "The candidate pool is every unit that satisfies all of these
    conditions at once: the unit's `status` is `AVAILABLE`; the unit's agency
    `status` is `ONLINE`; the unit's agency `discipline` equals the requested
    discipline; and the unit is not already tied to this incident through a
    non-cancelled assignment."
    PRD §3.4: "If the primary pass yields no candidate, the platform runs a
    second, mutual-aid pass with the agency-status condition widened to include
    both `ONLINE` and `MUTUAL_AID_ONLY` agencies."

    Primary pass recommends the nearer ONLINE unit (A, distance 2); once A's
    agency is MUTUAL_AID_ONLY the primary pass empties and the mutual-aid pass
    recommends B (distance 9).

    Design: Difficulty/dual_variant_calc/recommendation_primary_vs_mutual_aid_pass
    """
    set_clock("2026-06-01T10:00:00Z")
    agA, _, unitA = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=52, grid_y=50,
        call_sign="A1", name_prefix="PD A")
    agB, _, unitB = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=59, grid_y=50,
        call_sign="B1", name_prefix="PD B")
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=50, ali_grid_y=50, ani="5125550010")

    primary = validate_success(
        api.get_recommendation(incident["id"], DISP, params={"discipline": "POLICE"}), 200)
    validate_success(api.set_agency_status(agA["id"], "MUTUAL_AID_ONLY", SUP), 200)
    fallback = validate_success(
        api.get_recommendation(incident["id"], DISP, params={"discipline": "POLICE"}), 200)

    assert primary["recommended_unit_id"] == unitA["id"]
    assert fallback["recommended_unit_id"] == unitB["id"]
    assert primary["recommended_unit_id"] != fallback["recommended_unit_id"]


# =====================================================================
# Queue A — combinatorial_formula
# =====================================================================
def test_priority_confidence_clamp_applied_after_premise_clamp(api):
    """PRD §3.3: "Fourth, and applied strictly after the premise clamp, if
    `ali_confidence` is `UNKNOWN` the `priority_level` is set to the smaller of
    its current value and 2 — a degrade-safe clamp that guarantees an uncertain
    fix is treated as at least moderately urgent."
    PRD §3.3: "an `ALARM` has base 4".

    ALARM (base 4), no premise alert, ali_confidence UNKNOWN → priority_level 2.

    Design: Difficulty/combinatorial_formula/priority_clamp_order_premise_then_confidence
    """
    set_clock("2026-06-02T00:00:00Z")
    inc = validate_success(api.create_incident(create_incident_payload(
        ani="5125550020", ali_grid_x=300, ali_grid_y=300,
        incident_type="ALARM", ali_confidence="UNKNOWN"), CALL), 201)
    assert inc["base_priority_level"] == 4
    assert inc["priority_level"] == 2
    assert inc["premise_alert_id"] is None


def test_governing_sla_is_max_over_assigned_required_agencies(api):
    """PRD §3.6: "The platform first determines the governing SLA as the largest
    `response_sla_seconds` among the agencies that both have a discipline within
    the incident's `required_disciplines` and have at least one non-cancelled
    assignment on this incident".
    PRD §3.6: "The incident's `sla_breached` is true only when
    `total_handle_seconds` is strictly greater than the governing SLA — a handle
    time exactly equal to the target is not a breach."

    STRUCTURE_FIRE with FIRE(sla 600) + EMS(sla 480) both assigned: governing
    SLA = max(600,480)=600; handle=540 → not breached.

    Design: Difficulty/combinatorial_formula/governing_sla_nested_aggregate_selection
    """
    set_clock("2026-06-03T08:00:00Z")
    _, _, eng = setup_agency_station_unit(
        discipline="FIRE", capability="ENGINE", response_sla_seconds=600,
        grid_x=70, grid_y=70, call_sign="E7", name_prefix="Fire Co")
    _, _, med = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", response_sla_seconds=480,
        grid_x=70, grid_y=70, call_sign="M7", name_prefix="EMS Co")
    incident = create_incident(incident_type="STRUCTURE_FIRE",
                               ali_grid_x=70, ali_grid_y=70, ani="5125550030")
    set_clock("2026-06-03T08:01:00Z")
    eng_asg = dispatch_unit(incident["id"], incident["version"], unit_id=eng["id"])
    # re-read the version after the first dispatch bumped it, then dispatch EMS
    v_after = get_incident_version(incident["id"])
    dispatch_unit(incident["id"], v_after, unit_id=med["id"])
    advance_assignment(eng_asg["id"], eng["id"], "ENROUTE")
    set_clock("2026-06-03T08:09:00Z")
    advance_assignment(eng_asg["id"], eng["id"], "ONSCENE")

    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc["total_handle_seconds"] == 540, inc["total_handle_seconds"]
    assert inc["sla_breached"] is False


# =====================================================================
# Queue A — boundary_precision_check
# =====================================================================
def test_sla_not_breached_when_handle_exactly_equals_governing_sla(api):
    """PRD §3.6: "The incident's `sla_breached` is true only when
    `total_handle_seconds` is strictly greater than the governing SLA — a handle
    time exactly equal to the target is not a breach."

    EMS sla=480; handle exactly 480 (received 08:00:00, onscene 08:08:00) →
    not a breach.

    Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_at_exact_boundary
    """
    set_clock("2026-06-10T08:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", response_sla_seconds=480,
        grid_x=12, grid_y=12, call_sign="MB1", name_prefix="EMS Bd")
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=12, ali_grid_y=12, ani="5125550100")
    set_clock("2026-06-10T08:01:00Z")
    asg = dispatch_unit(incident["id"], incident["version"], unit_id=unit["id"])
    advance_assignment(asg["id"], unit["id"], "ENROUTE")
    set_clock("2026-06-10T08:08:00Z")
    advance_assignment(asg["id"], unit["id"], "ONSCENE")

    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc["total_handle_seconds"] == 480, inc["total_handle_seconds"]
    assert inc["sla_breached"] is False


def test_auto_select_with_empty_pool_returns_no_unit_available(api):
    """PRD §3.4: "when the dispatch is an auto-selection but neither the primary
    nor the mutual-aid pass yields an eligible unit, the request is rejected with
    `ERR_NO_UNIT_AVAILABLE`."

    The only POLICE unit is OUT_OF_SERVICE so both passes are empty; auto-select
    is rejected.

    Design: Difficulty/boundary_precision_check/empty_candidate_pool_auto_select_no_unit
    """
    set_clock("2026-06-11T00:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=5, grid_y=5,
        call_sign="PE1", name_prefix="PD Empty")
    validate_success(api.set_unit_status(unit["id"], "OUT_OF_SERVICE", SUP), 200)
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=5, ali_grid_y=5, ani="5125550110")
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": incident["version"],
        "auto_select": True, "discipline": "POLICE"}, DISP)
    validate_error(res, "ERR_NO_UNIT_AVAILABLE")


# =====================================================================
# Queue B — calculations section
# =====================================================================
def test_premise_alert_clamps_priority_up_and_links_alert(api):
    """PRD §3.3: "Third, if an alert matched, the incident's `premise_alert_id`
    is set to that alert and the `priority_level` becomes the smaller of the
    `base_priority_level` and the alert's `min_priority_floor` — clamping the
    incident toward higher urgency".
    PRD §3.3: "a `WELFARE_CHECK` has base 5".

    WELFARE_CHECK (base 5) at a grid with active alert floor 3 → priority 3,
    premise_alert_id linked.

    Design: Corner/calculations/premise_alert_clamps_priority_up
    """
    set_clock("2026-06-21T07:00:00Z")
    pa = validate_success(api.create_premise_alert(create_premise_alert_payload(
        grid_x=250, grid_y=250, hazard_class="COMBATIVE_SUBJECT",
        min_priority_floor=3), SUP), 201)
    inc = validate_success(api.create_incident(create_incident_payload(
        ani="5125559014", ali_grid_x=250, ali_grid_y=250,
        incident_type="WELFARE_CHECK"), CALL), 201)
    assert inc["base_priority_level"] == 5
    assert inc["priority_level"] == 3
    assert inc["premise_alert_id"] == pa["id"]


def test_recommendation_returns_manhattan_distance_and_candidate_count(api):
    """PRD §3.4: "The first key is the Manhattan `travel_distance` from the
    unit's current grid to the incident's ALI grid."
    PRD §3.4: "The recommendation response reports `recommended_unit_id`, the
    chosen `discipline`, the winning `travel_distance`, and the `candidate_count`
    of eligible units considered".

    Two PATROL units at distances 3 and 5 → recommend the distance-3 unit,
    travel_distance 3, candidate_count 2.

    Design: Corner/calculations/recommendation_manhattan_distance_and_candidate_count
    """
    set_clock("2026-06-21T08:00:00Z")
    agency, station, near = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=12, grid_y=11,
        call_sign="PDa1", name_prefix="PD Dist")
    # station was placed at near unit grid; create a second (far) unit at dist 5
    validate_success(api.create_unit({
        "agency_id": agency["id"], "station_id": station["id"],
        "call_sign": "PDa2", "capability": "PATROL",
        "grid_x": 10, "grid_y": 15}, SUP), 201)
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559015")
    rec = validate_success(
        api.get_recommendation(incident["id"], DISP, params={"discipline": "POLICE"}), 200)
    assert rec["recommended_unit_id"] == near["id"]
    assert rec["travel_distance"] == 3
    assert rec["candidate_count"] == 2


def test_auto_select_assignment_snapshots_travel_distance_and_recommended(api):
    """PRD §3.4: "The platform records the new assignment with `status`
    `DISPATCHED`, sets its `recommended` flag true exactly when the committed
    unit was the unit the recommendation would have chosen at that moment,
    computes and stores its Manhattan `travel_distance`".

    One PATROL unit at distance 3; auto-select → travel_distance 3, recommended
    true.

    Design: Corner/calculations/assignment_travel_distance_snapshot_recommended_flag
    """
    set_clock("2026-06-21T09:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=12, grid_y=11,
        call_sign="PAu1", name_prefix="PD Auto")
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559016")
    asg = validate_success(api.create_assignment(incident["id"], {
        "expected_incident_version": incident["version"],
        "auto_select": True, "discipline": "POLICE"}, DISP), 201)
    assert asg["travel_distance"] == 3
    assert asg["recommended"] is True
    assert asg["unit_id"] == unit["id"]
