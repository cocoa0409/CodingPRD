"""Suspension cascades: admin-triggered depth-3 chain and violation-triggered depth-2 chain."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_operator_headers,
    set_clock, create_operator, transition_operator,
    setup_dispatched_trip, setup_active_permitted_vehicle,
    create_curb_zone, create_curb_assignment,
    issue_violation, transition_violation_authority,
)

AA = TEST_USERS["airport_authority_headers"]


def _suspend_cascade_setup(api, avi_tag):
    ctx = setup_dispatched_trip(api, operator_type="TNC", clock="2026-04-05T10:00:00Z", avi_tag=avi_tag)
    zone = create_curb_zone(api, name="Z1", capacity=1)
    ca = create_curb_assignment(api, zone["id"], ctx["trip"]["id"],
                                "2026-04-05T10:00:00Z", "2026-04-05T10:30:00Z")
    transition_operator(api, ctx["operator"]["id"], "SUSPEND")
    ctx["curb_assignment"] = ca
    return ctx


def test_operator_suspend_cascades_to_vehicle_permit_trip_curb(api):
    """PRD §2.6: "When an operator leaves `ACTIVE` status through suspension or
    revocation, every one of its vehicles then in `ACTIVE` status is driven to
    `SUSPENDED`; each such vehicle in turn drives every one of its permits then in
    `permit_status` `ACTIVE` to `SUSPENDED` (recording `suspended_reason`
    `OPERATOR_SUSPENDED` on the permit), and drives every one of its trips then in
    `DISPATCHED` or `PICKED_UP` status to `CANCELLED`; and each cancelled trip
    releases any of its curb assignments still in `ACTIVE` status, moving them to
    `RELEASED`."

    Design: Difficulty/transitive_cascade/operator_suspend_cascades_vehicle_trip_curb_depth3
    """
    ctx = _suspend_cascade_setup(api, "AVI-CX1")
    vehicle = validate_success(api.get_vehicle(ctx["vehicle"]["id"], AA))
    permit = validate_success(api.get_permit(ctx["permit"]["id"], AA))
    trip = validate_success(api.get_trip(ctx["trip"]["id"], AA))
    curb = validate_success(api.get_curb_assignment(ctx["curb_assignment"]["id"], AA))
    assert vehicle["status"] == "SUSPENDED", f"vehicle should cascade to SUSPENDED, got {vehicle['status']}"
    assert permit["permit_status"] == "SUSPENDED", f"permit should cascade to SUSPENDED, got {permit['permit_status']}"
    assert trip["status"] == "CANCELLED", f"trip should cascade to CANCELLED, got {trip['status']}"
    assert curb["status"] == "RELEASED", f"curb assignment should cascade to RELEASED, got {curb['status']}"


def test_operator_suspend_cascade_sets_permit_suspended_reason(api):
    """PRD §2.6: "each such vehicle in turn drives every one of its permits then in
    `permit_status` `ACTIVE` to `SUSPENDED` (recording `suspended_reason`
    `OPERATOR_SUSPENDED` on the permit)"

    Design: Difficulty/transitive_cascade/operator_suspend_cascades_vehicle_trip_curb_depth3
    """
    ctx = _suspend_cascade_setup(api, "AVI-CX2")
    permit = validate_success(api.get_permit(ctx["permit"]["id"], AA))
    assert permit["permit_status"] == "SUSPENDED"
    assert permit["suspended_reason"] == "OPERATOR_SUSPENDED", (
        f"cascaded permit should record OPERATOR_SUSPENDED, got {permit['suspended_reason']}"
    )


def test_assess_crossing_threshold_recomputes_rolling_to_twelve(api):
    """PRD §3.7: "The regulator assesses an `OPEN` violation (`OPEN → ASSESSED`),
    which stamps `assessed_at` from the logical clock, recomputes the cited
    operator's `rolling_penalty_points` and `lifetime_penalty_points`, and, if the
    operator was `ACTIVE` and its recomputed rolling total now stands at twelve
    points or more, auto-suspends the operator with `suspended_reason`
    `PENALTY_THRESHOLD` and its cascade."

    Design: Difficulty/transitive_cascade/violation_assess_threshold_cascades_operator_suspend_depth2
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Thresh Co", activate=True)
    v1 = issue_violation(api, op["id"], "AVI_MISMATCH")
    transition_violation_authority(api, v1["id"], "ASSESS")  # rolling 6
    v2 = issue_violation(api, op["id"], "NO_DECAL")
    assessed = transition_violation_authority(api, v2["id"], "ASSESS")  # +6 -> 12
    assert assessed["status"] == "ASSESSED"
    operator = validate_success(api.get_operator(op["id"], AA))
    assert operator["rolling_penalty_points"] == 12, (
        f"crossing assessment should recompute rolling to 12, got {operator['rolling_penalty_points']}"
    )


def test_assess_crossing_threshold_auto_suspends_with_penalty_reason(api):
    """PRD §3.1: "When a violation assessment (or an appeal upheld against the
    operator) drives the operator's `rolling_penalty_points` to at least the
    suspension threshold of twelve points, and the operator is at that moment
    `ACTIVE`, the system suspends it on the spot, this time recording
    `suspended_reason` as `PENALTY_THRESHOLD`, and runs the same downward cascade as
    an administrative suspension."

    Design: Difficulty/transitive_cascade/violation_assess_threshold_cascades_operator_suspend_depth2
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Thresh2 Co", activate=True)
    v1 = issue_violation(api, op["id"], "AVI_MISMATCH")
    transition_violation_authority(api, v1["id"], "ASSESS")
    v2 = issue_violation(api, op["id"], "NO_DECAL")
    transition_violation_authority(api, v2["id"], "ASSESS")
    operator = validate_success(api.get_operator(op["id"], AA))
    assert operator["status"] == "SUSPENDED", f"expected SUSPENDED, got {operator['status']}"
    assert operator["suspended_reason"] == "PENALTY_THRESHOLD", (
        f"expected PENALTY_THRESHOLD, got {operator['suspended_reason']}"
    )


def test_queue_suspended_vehicle_returns_vehicle_not_active(api):
    """PRD §3.3: "First, the joining vehicle must itself be `ACTIVE` — a vehicle
    suspended through the operator cascade is rejected with `ERR_VEHICLE_NOT_ACTIVE`
    (this vehicle-status check runs before the permit check, because a suspended
    vehicle necessarily also has a suspended permit)."

    Design: Corner/state_machines/queue_suspended_vehicle_returns_vehicle_not_active
    """
    ctx = setup_active_permitted_vehicle(api, operator_type="TNC", clock="2026-04-07T10:00:00Z", avi_tag="AVI-SV1")
    transition_operator(api, ctx["operator"]["id"], "SUSPEND")  # cascade suspends the vehicle
    resp = api.create_queue_entry(
        {"staging_lot_id": ctx["lot"]["id"], "vehicle_id": ctx["vehicle"]["id"], "lat": 40.64, "lng": -73.78},
        make_operator_headers(ctx["operator"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_ACTIVE.value, 409)
