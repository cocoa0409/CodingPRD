"""Transitive cascades (knockdown, restoration) and posture-gated timing review."""
from test_helpers import validate_success, validate_error, validate_paginated
from test_helpers.fixtures import (
    new_intersection, new_pole, new_device, new_timing_change_request,
    new_ticket, triage, get_device, get_intersection, get_timing_change_request,
    setup_completed_work_order, setup_emergency_intersection,
)


# ── Difficulty: knockdown cascade device -> intersection -> TCR ───────────────
def _setup_knockdown_with_submitted_tcr(api):
    inter = new_intersection()
    pole = new_pole(load_capacity_units=100, intersection_id=inter["id"])
    device = new_device(inter["id"], pole_id=pole["id"], device_type="SIGNAL_CONTROLLER",
                        criticality="CRITICAL", model="C2", replacement_cost=5000.00)
    tcr = new_timing_change_request(inter["id"], proposed_cycle_length_sec=90,
                                    proposed_offset_sec=5, rationale="coordination")
    ticket = new_ticket(device["id"], source="KNOCKDOWN", reported_severity=5,
                        description="vehicle knockdown", hazard_flag=True, struck_pole=True)
    triage(ticket["id"])
    return inter, pole, device, tcr, ticket


def test_knockdown_triage_sets_device_pole_and_intersection(api, dispatcher_headers):
    """PRD §3.2: "A knockdown triage is far more consequential: the device moves to
    `KNOCKED_DOWN`; if `struck_pole` is set and the device is pole-mounted, that
    pole's `status` moves to `DOWN`; the intersection's posture recomputes to
    `EMERGENCY`; every timing change request for that intersection currently in
    `SUBMITTED` or `UNDER_REVIEW` is automatically suspended (moved to
    `SUSPENDED`); and an emergency work order is auto-created in `DRAFT` for that
    ticket and device with a `work_type` of `EMERGENCY`."

    Design: Difficulty/transitive_cascade/knockdown_cascade_device_to_intersection_to_tcr
    """
    inter, pole, device, tcr, ticket = _setup_knockdown_with_submitted_tcr(api)
    assert get_device(device["id"])["status"] == "KNOCKED_DOWN"
    assert validate_success(api.get_pole(pole["id"], dispatcher_headers), 200)["status"] == "DOWN"
    assert get_intersection(inter["id"])["operational_posture"] == "EMERGENCY"


def test_knockdown_suspends_tcr_and_creates_emergency_work_order(api, dispatcher_headers):
    """PRD §3.2: "A knockdown triage is far more consequential: the device moves to
    `KNOCKED_DOWN`; if `struck_pole` is set and the device is pole-mounted, that
    pole's `status` moves to `DOWN`; the intersection's posture recomputes to
    `EMERGENCY`; every timing change request for that intersection currently in
    `SUBMITTED` or `UNDER_REVIEW` is automatically suspended (moved to
    `SUSPENDED`); and an emergency work order is auto-created in `DRAFT` for that
    ticket and device with a `work_type` of `EMERGENCY`."

    Design: Difficulty/transitive_cascade/knockdown_cascade_device_to_intersection_to_tcr
    """
    inter, pole, device, tcr, ticket = _setup_knockdown_with_submitted_tcr(api)
    assert get_timing_change_request(tcr["id"])["status"] == "SUSPENDED"

    data, meta = validate_paginated(
        api.list_work_orders(dispatcher_headers, params={"ticket_id": ticket["id"]}))
    emergency = [wo for wo in data if wo["work_type"] == "EMERGENCY"]
    assert len(emergency) == 1, f"expected one EMERGENCY work order, got {len(emergency)}"
    assert emergency[0]["status"] == "DRAFT"


# ── Difficulty: completion restores device then intersection posture ─────────
def test_complete_restores_device_to_in_service(api, dispatcher_headers):
    """PRD §3.4: "Completion is performed by a field technician of the owning crew
    ... returns the device to `IN_SERVICE`, and recomputes the intersection
    posture, which may drop it from `EMERGENCY` or `DEGRADED` back toward
    `NORMAL`."

    Design: Difficulty/transitive_cascade/complete_restores_device_then_intersection_posture
    """
    ctx = setup_completed_work_order(work_type="REPAIR", estimated_labor_hours=1.0,
                                     actual_labor_hours=1.0, with_ticket=True)
    assert get_device(ctx["device"]["id"])["status"] == "IN_SERVICE"


def test_complete_recomputes_intersection_posture_to_normal(api, dispatcher_headers):
    """PRD §2.10: "If any of those devices is `KNOCKED_DOWN`, the posture is
    `EMERGENCY`; otherwise, if any is `OUT_OF_SERVICE` or `UNDER_MAINTENANCE`, the
    posture is `DEGRADED`; otherwise it is `NORMAL`."
    PRD §3.4: "returns the device to `IN_SERVICE`, and recomputes the intersection
    posture, which may drop it from `EMERGENCY` or `DEGRADED` back toward
    `NORMAL`."

    Design: Difficulty/transitive_cascade/complete_restores_device_then_intersection_posture
    """
    ctx = setup_completed_work_order(work_type="REPAIR", estimated_labor_hours=1.0,
                                     actual_labor_hours=1.0, with_ticket=True)
    assert get_intersection(ctx["intersection"]["id"])["operational_posture"] == "NORMAL"


# ── Difficulty: timing review blocked while intersection EMERGENCY ────────────
def test_timing_review_blocked_when_intersection_emergency(api, dispatcher_headers, traffic_engineer_headers):
    """PRD §3.6: "A traffic engineer begins review, moving it from `SUBMITTED` to
    `UNDER_REVIEW`, but only while the intersection is not in `EMERGENCY` posture;
    a review started against an intersection in emergency is rejected with
    `ERR_INTERSECTION_EMERGENCY`."

    Design: Difficulty/cross_entity_state_dependency/timing_review_blocked_when_intersection_emergency
    """
    ctx = setup_emergency_intersection()
    tcr = new_timing_change_request(ctx["intersection"]["id"], proposed_cycle_length_sec=90,
                                    proposed_offset_sec=5, rationale="x")
    assert tcr["status"] == "SUBMITTED"
    res = api.start_review_timing_change_request(tcr["id"], traffic_engineer_headers)
    validate_error(res, "ERR_INTERSECTION_EMERGENCY", expected_status=409)


def test_timing_change_stays_submitted_after_blocked_review(api, dispatcher_headers, traffic_engineer_headers):
    """PRD §3.6: "A traffic engineer begins review, moving it from `SUBMITTED` to
    `UNDER_REVIEW`, but only while the intersection is not in `EMERGENCY` posture;
    a review started against an intersection in emergency is rejected with
    `ERR_INTERSECTION_EMERGENCY`."

    Design: Difficulty/cross_entity_state_dependency/timing_review_blocked_when_intersection_emergency
    """
    ctx = setup_emergency_intersection()
    tcr = new_timing_change_request(ctx["intersection"]["id"], proposed_cycle_length_sec=90,
                                    proposed_offset_sec=5, rationale="x")
    res = api.start_review_timing_change_request(tcr["id"], traffic_engineer_headers)
    validate_error(res, "ERR_INTERSECTION_EMERGENCY", expected_status=409)
    assert get_timing_change_request(tcr["id"])["status"] == "SUBMITTED"
