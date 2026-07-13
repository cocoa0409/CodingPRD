"""Staging-lot FIFO queue: join guards, capacity, cooldown, and position renumber."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_operator_headers,
    set_clock, create_operator, register_vehicle, issue_permit,
    create_lot, queue_vehicle, setup_active_permitted_vehicle,
)

AA = TEST_USERS["airport_authority_headers"]


def test_queue_outside_geofence_rejected(api):
    """PRD §3.3: "Third, the supplied `lat`/`lng` must fall within
    `geofence_radius_m` meters of the lot's geofence center, or the join is
    rejected with `ERR_GEOFENCE_VIOLATION`."

    Design: Corner/validations/queue_outside_geofence_returns_geofence_violation
    """
    ctx = setup_active_permitted_vehicle(api, clock="2026-04-12T10:00:00Z", avi_tag="AVI-GEV1")
    resp = api.create_queue_entry(
        {"staging_lot_id": ctx["lot"]["id"], "vehicle_id": ctx["vehicle"]["id"], "lat": 0.0, "lng": 0.0},
        make_operator_headers(ctx["operator"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GEOFENCE_VIOLATION.value, 422)


def test_queue_same_vehicle_twice_rejected(api):
    """PRD §3.3: "Fourth, the vehicle must not already have a `WAITING` entry in any
    lot, or the join is rejected with `ERR_ALREADY_IN_QUEUE`."

    Design: Corner/validations/queue_same_vehicle_twice_returns_already_in_queue
    """
    ctx = setup_active_permitted_vehicle(api, clock="2026-04-13T10:00:00Z", avi_tag="AVI-TWV1")
    queue_vehicle(api, ctx["operator"]["id"], ctx["lot"]["id"], ctx["vehicle"]["id"])
    resp = api.create_queue_entry(
        {"staging_lot_id": ctx["lot"]["id"], "vehicle_id": ctx["vehicle"]["id"], "lat": 40.64, "lng": -73.78},
        make_operator_headers(ctx["operator"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_IN_QUEUE.value, 409)


def test_queue_requires_active_permit(api):
    """PRD §3.3: "Second, the vehicle must currently hold a permit in
    `permit_status` `ACTIVE`; otherwise the join is rejected with
    `ERR_VEHICLE_PERMIT_INVALID`."

    Design: Corner/state_machines/queue_entry_requires_active_permit_guarded
    """
    set_clock(api, "2026-04-06T10:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Grd Co", activate=True)
    veh = register_vehicle(api, op["id"], plate="GV1")
    issue_permit(api, veh["id"], veh["version"], avi_tag_id="AVI-GV1")  # left ISSUED, not activated
    lot = create_lot(api)
    resp = api.create_queue_entry(
        {"staging_lot_id": lot["id"], "vehicle_id": veh["id"], "lat": 40.64, "lng": -73.78},
        make_operator_headers(op["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_PERMIT_INVALID.value, 409)


def test_lot_capacity_exceeded_rejected(api):
    """PRD §3.3: "Finally, the lot must have room — the count of `WAITING` entries
    already in the lot must be below its `capacity`, or the join is rejected with
    `ERR_LOT_CAPACITY_EXCEEDED`."

    Design: Corner/validations/lot_capacity_exceeded_returns_conflict
    """
    set_clock(api, "2026-04-14T10:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Cap Co", activate=True)
    lot = create_lot(api, capacity=1)
    va = register_vehicle(api, op["id"], plate="CPA")
    issue_permit(api, va["id"], va["version"], avi_tag_id="AVI-CPA", activate=True)
    vb = register_vehicle(api, op["id"], plate="CPB")
    issue_permit(api, vb["id"], vb["version"], avi_tag_id="AVI-CPB", activate=True)
    queue_vehicle(api, op["id"], lot["id"], va["id"])
    resp = api.create_queue_entry(
        {"staging_lot_id": lot["id"], "vehicle_id": vb["id"], "lat": 40.64, "lng": -73.78},
        make_operator_headers(op["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LOT_CAPACITY_EXCEEDED.value, 409)


def test_cancel_head_entry_renumbers_following_position(api):
    """PRD §3.3: "When an entry leaves `WAITING` — whether it is released by a
    dispatch, exited, or cancelled — its `exit_ts` is stamped and every surviving
    `WAITING` entry in the same lot whose `position` is greater than the departed
    entry's decrements its `position` by one, keeping the remaining positions a
    contiguous block."

    Design: Corner/state_machines/cancel_head_queue_entry_renumbers_fifo
    """
    set_clock(api, "2026-04-08T10:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Fifo Co", activate=True)
    lot = create_lot(api)
    va = register_vehicle(api, op["id"], plate="FA")
    issue_permit(api, va["id"], va["version"], avi_tag_id="AVI-FA", activate=True)
    vb = register_vehicle(api, op["id"], plate="FB")
    issue_permit(api, vb["id"], vb["version"], avi_tag_id="AVI-FB", activate=True)
    qa = queue_vehicle(api, op["id"], lot["id"], va["id"])
    qb = queue_vehicle(api, op["id"], lot["id"], vb["id"])
    assert qb["position"] == 2, f"expected B at position 2, got {qb['position']}"
    cancelled = validate_success(
        api.transition_queue_entry(qa["id"], {"action": "CANCEL"}, make_operator_headers(op["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    b_after = validate_success(api.get_queue_entry(qb["id"], AA))
    assert b_after["position"] == 1, f"expected B renumbered to position 1, got {b_after['position']}"


def test_staging_cooldown_reentry_within_30_min_rejected(api):
    """PRD §3.3: "Fifth, a staging cooldown applies: the logical clock must be at
    least 30 minutes past the `exit_ts` of the vehicle's most recent prior queue
    entry across the `RELEASED`, `EXITED`, and `CANCELLED` statuses, or the join is
    rejected with `ERR_STAGING_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/staging_cooldown_buffer_conflict
    """
    set_clock(api, "2026-04-28T08:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Cool Co", activate=True)
    veh = register_vehicle(api, op["id"], plate="BV1")
    issue_permit(api, veh["id"], veh["version"], avi_tag_id="AVI-BV1", activate=True)
    lot = create_lot(api)
    qe = queue_vehicle(api, op["id"], lot["id"], veh["id"])
    validate_success(
        api.transition_queue_entry(qe["id"], {"action": "EXIT"}, make_operator_headers(op["id"]))
    )
    set_clock(api, "2026-04-28T08:10:00Z")  # only 10 minutes later
    resp = api.create_queue_entry(
        {"staging_lot_id": lot["id"], "vehicle_id": veh["id"], "lat": 40.64, "lng": -73.78},
        make_operator_headers(op["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STAGING_BUFFER_VIOLATION.value, 409)


def test_staging_cooldown_reentry_at_exactly_30_min_allowed(api):
    """PRD §3.3: "Fifth, a staging cooldown applies: the logical clock must be at
    least 30 minutes past the `exit_ts` of the vehicle's most recent prior queue
    entry across the `RELEASED`, `EXITED`, and `CANCELLED` statuses, or the join is
    rejected with `ERR_STAGING_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/staging_cooldown_buffer_conflict
    """
    set_clock(api, "2026-04-28T08:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Cool2 Co", activate=True)
    veh = register_vehicle(api, op["id"], plate="BV2")
    issue_permit(api, veh["id"], veh["version"], avi_tag_id="AVI-BV2", activate=True)
    lot = create_lot(api)
    qe = queue_vehicle(api, op["id"], lot["id"], veh["id"])
    validate_success(
        api.transition_queue_entry(qe["id"], {"action": "EXIT"}, make_operator_headers(op["id"]))
    )
    set_clock(api, "2026-04-28T08:30:00Z")  # exactly 30 minutes later — at least 30
    reentry = validate_success(
        api.create_queue_entry(
            {"staging_lot_id": lot["id"], "vehicle_id": veh["id"], "lat": 40.64, "lng": -73.78},
            make_operator_headers(op["id"]),
        ),
        201,
    )
    assert reentry["status"] == "WAITING", f"expected WAITING re-entry, got {reentry['status']}"
