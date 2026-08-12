"""Field execution through handover: the work-item rework loop, invalid and
terminal transitions, the permit-revoke cascade into slip and posture,
startup gate ordering, the cancel cascade, the ops-run checkpoint, and the
zero-open-category-A handover boundary."""
from test_helpers import (
    ApiErrorId,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
    complete_work_item,
    create_laydown_area,
    create_permit_for_item,
    create_reservation,
    create_turnaround,
    create_verified_isolation,
    create_work_item_payload,
    freeze_turnaround,
    issue_permit,
    schedule_and_start_work_item,
    set_clock,
    setup_active_permit_scenario,
    setup_execution_turnaround,
    setup_startup_turnaround,
    verify_work_item,
    walk_work_item_to_verified,
    make_supervisor_headers,
)


def test_start_from_frozen_rejected(api, planner_headers):
    """PRD §3.5: "Starting work is the field supervisor's action, and the same
    start action serves three source states: `SCHEDULED` to `IN_PROGRESS` for
    first mobilization of the job, `ON_HOLD` to `IN_PROGRESS` for resumption,
    and `REOPENED` to `IN_PROGRESS` for rework."
    PRD §2.8: "7. State legality: the target resource is in a legal state for
    the operation per its state machine — this tier also covers scope-frozen
    edits, since work-item creation, re-estimation, and dependency edits are
    only legal while the turnaround is `PLANNING`; failure yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/work_item_start_from_frozen_rejected
    """
    ctx = setup_execution_turnaround()
    # ctx["items"] holds the creation-time (PROPOSED) snapshot; re-fetch the
    # post-freeze state.
    w1 = validate_success(api.get_work_item(ctx["items"][0]["id"], planner_headers))
    assert w1["status"] == "FROZEN"

    resp = api.start_work_item(w1["id"], make_supervisor_headers(ctx["contractor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_work_item(w1["id"], planner_headers))
    assert after["status"] == "FROZEN"


def test_terminal_states_reject_further_transitions(
    api, coordinator_headers, operations_headers
):
    """PRD §3.5: "An `outcome` of `VERIFIED` closes the item — `VERIFIED` is
    terminal."
    PRD §3.2: "A worker's badge lifecycle runs `REGISTERED`, `VETTED`,
    `BADGED`, `SUSPENDED`, and ends at `DEBADGED`."

    Design: Corner/state_machines/terminal_state_lockdown
    """
    ctx = setup_execution_turnaround()
    w1 = ctx["items"][0]
    contractor = ctx["contractor"]
    worker = ctx["workers"][0]
    walk_work_item_to_verified(w1["id"], contractor["id"])
    validate_success(
        api.badge_transition_worker(worker["id"], {"to": "DEBADGED"}, coordinator_headers)
    )

    resp_verify = api.verify_work_item(w1["id"], {"outcome": "VERIFIED"}, operations_headers)
    validate_error(resp_verify, ApiErrorId.ERR_INVALID_STATE)

    resp_badge = api.badge_transition_worker(
        worker["id"], {"to": "BADGED"}, coordinator_headers
    )
    validate_error(resp_badge, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_cascades_to_proposed_and_frozen_only(
    api, manager_headers, planner_headers
):
    """PRD §3.9: "Cancellation runs the other direction: from `PLANNING` or
    `SCOPE_FROZEN` the `TurnaroundManager` may cancel the turnaround outright,
    which cancels every work item standing in `PROPOSED` or `FROZEN` —
    recomputing `committed_cost_cents` as the frozen items leave the committed
    set — while `DEFERRED` items are left untouched; cancellation from any
    later phase is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/turnaround_cancel_cascades_conditional
    """
    ta = create_turnaround(name="TA-CN", authorized_budget_cents=500000,
                           contingency_budget_cents=100000)
    wa = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="High risk", system_area="A", risk_class="A",
                estimated_hours=10, estimated_cost_cents=120000,
            ),
            planner_headers,
        ),
        201,
    )
    wb = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="Low risk", system_area="B", work_type="PREVENTIVE",
                risk_class="C", estimated_hours=20, estimated_cost_cents=40000,
            ),
            planner_headers,
        ),
        201,
    )
    freeze_turnaround(ta["id"], scope_cutoff_count=1)

    cancelled = validate_success(api.cancel_turnaround(ta["id"], manager_headers))
    assert cancelled["status"] == "CANCELLED"

    wa = validate_success(api.get_work_item(wa["id"], planner_headers))
    wb = validate_success(api.get_work_item(wb["id"], planner_headers))
    assert wa["status"] == "CANCELLED", "FROZEN item must be cancelled with the turnaround"
    assert wb["status"] == "DEFERRED", "DEFERRED items are untouched by the cascade"

    resp = api.advance_turnaround(ta["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_startup_advance_blocked_by_active_permit(api, manager_headers):
    """PRD §3.9: "Moving from `EXECUTION` to `STARTUP` enforces three gates,
    evaluated in order so that the earliest failure is the one reported:
    first, every scope work item — any item not `DEFERRED` or `CANCELLED` —
    must stand in `VERIFIED`, failing with `ERR_WORK_ITEMS_OPEN`; second, no
    permit may remain in `REQUESTED`, `ISSUED`, `ACTIVE`, or `SUSPENDED`,
    failing with `ERR_PERMITS_STILL_ACTIVE`; third, no isolation may remain in
    `PLANNED`, `ISOLATED`, or `VERIFIED`, failing with
    `ERR_ISOLATIONS_ENGAGED`."

    Design: Corner/state_machines/advance_gate_permits_still_active
    """
    ctx = setup_active_permit_scenario()
    w1 = ctx["items"][0]
    contractor = ctx["contractor"]
    # work the item to VERIFIED while its permit stays ACTIVE
    validate_success(
        api.start_work_item(w1["id"], make_supervisor_headers(contractor["id"]))
    )
    complete_work_item(w1["id"], contractor["id"], 88)
    verify_work_item(w1["id"], "VERIFIED")

    # gate 1 passes (item VERIFIED); gate 2 must fire on the ACTIVE permit
    resp = api.advance_turnaround(ctx["turnaround"]["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_PERMITS_STILL_ACTIVE)

    after = validate_success(api.get_turnaround(ctx["turnaround"]["id"], manager_headers))
    assert after["status"] == "EXECUTION"


def test_startup_advance_blocked_by_engaged_isolation(api, manager_headers, coordinator_headers):
    """PRD §3.9: "Moving from `EXECUTION` to `STARTUP` enforces three gates,
    evaluated in order so that the earliest failure is the one reported:
    first, every scope work item — any item not `DEFERRED` or `CANCELLED` —
    must stand in `VERIFIED`, failing with `ERR_WORK_ITEMS_OPEN`; second, no
    permit may remain in `REQUESTED`, `ISSUED`, `ACTIVE`, or `SUSPENDED`,
    failing with `ERR_PERMITS_STILL_ACTIVE`; third, no isolation may remain in
    `PLANNED`, `ISOLATED`, or `VERIFIED`, failing with
    `ERR_ISOLATIONS_ENGAGED`."

    Design: Corner/state_machines/advance_gate_isolations_engaged
    """
    ctx = setup_active_permit_scenario()
    w1 = ctx["items"][0]
    contractor = ctx["contractor"]
    permit = ctx["permit"]
    validate_success(
        api.start_work_item(w1["id"], make_supervisor_headers(contractor["id"]))
    )
    complete_work_item(w1["id"], contractor["id"], 88)
    verify_work_item(w1["id"], "VERIFIED")
    # close the permit (gate 2 passes); the VERIFIED isolation stays engaged
    validate_success(
        api.transition_permit(permit["id"], {"to": "CLOSED"}, coordinator_headers)
    )

    resp = api.advance_turnaround(ctx["turnaround"]["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_ISOLATIONS_ENGAGED)

    after = validate_success(api.get_turnaround(ctx["turnaround"]["id"], manager_headers))
    assert after["status"] == "EXECUTION"


def test_run_ops_expires_permits_and_releases_reservations(
    api, manager_headers, coordinator_headers, planner_headers
):
    """PRD §3.8: "It expires every permit standing in `ISSUED`, `ACTIVE`, or
    `SUSPENDED` whose `valid_until` has been reached, with the hold cascade of
    §3.4 firing for any `ACTIVE` permit so caught; it auto-releases every
    reservation still `RESERVED` or `STAGED` whose `window_until` has been
    reached, with the occupancy decrement of §3.7; and it increments the
    turnaround's `schedule_run_index` — the monotone counter of ops runs that
    started at zero — while bumping the turnaround's `version`."

    Design: Corner/cross_cutting_layers/run_ops_expires_permit_and_releases_reservation
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Bundle pull", "estimated_hours": 100,
            "estimated_cost_cents": 200000, "requires_permit": True,
        }
    )
    t_id = ctx["turnaround"]["id"]
    w1 = ctx["items"][0]  # stays FROZEN (never scheduled): no hold cascade
    iso = create_verified_isolation(t_id)
    permit = create_permit_for_item(
        w1["id"], isolation_ids=[iso["id"]], valid_until="2026-06-16T00:00:00Z"
    )
    issue_permit(permit["id"])  # default clock 2026-05-01 < valid_until

    area = create_laydown_area(t_id, capacity_sqm=500)
    reservation = create_reservation(
        area["id"], area["version"], material_description="Blind stock",
        area_sqm=120, window_until="2026-06-16T00:00:00Z",
    )
    assert reservation["status"] == "RESERVED"

    set_clock("2026-06-17T00:00:00Z")
    turned = validate_success(api.run_ops(t_id, manager_headers))
    assert turned["schedule_run_index"] == 1

    expired = validate_success(api.get_permit(permit["id"], coordinator_headers))
    assert expired["status"] == "EXPIRED", "valid_until 2026-06-16 <= logical now"

    reservations = validate_success(api.list_reservations(area["id"], planner_headers))
    by_id = {r["id"]: r for r in reservations}
    assert by_id[reservation["id"]]["status"] == "RELEASED"
    area = validate_success(api.get_laydown_area(area["id"], planner_headers))
    assert area["occupied_sqm"] == 0

    untouched = validate_success(api.get_work_item(w1["id"], planner_headers))
    assert untouched["status"] == "FROZEN", (
        "the conditional hold cascade fires only for IN_PROGRESS items"
    )


def test_contractor_supervisor_cannot_verify_work_item(api, planner_headers):
    """PRD §4: "| POST | `/work-items/{id}/verify` | Verify completed work to
    `VERIFIED`, or reopen it for rework | OperationsRep |"
    PRD §2.1: "A request whose role is not permitted for the endpoint, or that
    fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/contractor_supervisor_cannot_verify_work_item
    """
    ctx = setup_execution_turnaround()
    w1 = ctx["items"][0]
    contractor = ctx["contractor"]
    schedule_and_start_work_item(w1["id"], contractor["id"])
    complete_work_item(w1["id"], contractor["id"], 9)

    resp = api.verify_work_item(
        w1["id"], {"outcome": "VERIFIED"}, make_supervisor_headers(contractor["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = validate_success(api.get_work_item(w1["id"], planner_headers))
    assert after["status"] == "COMPLETE"


def _walk_through_rework_loop(api, ctx):
    """Drive W1 (estimated_hours 100) FROZEN -> SCHEDULED -> IN_PROGRESS ->
    COMPLETE with a first actual_hours recording of 40. Returns (item, contractor_id)."""
    w1 = ctx["items"][0]
    contractor_id = ctx["contractor"]["id"]
    schedule_and_start_work_item(w1["id"], contractor_id)
    complete_work_item(w1["id"], contractor_id, 40)
    return w1, contractor_id


def test_rework_loop_reopened_to_verified(api, operations_headers):
    """PRD §3.5: "An `outcome` of `VERIFIED` closes the item — `VERIFIED` is
    terminal. An `outcome` of `REOPENED` loops the item back for rework: it
    re-enters the committed input set, so `committed_cost_cents` is recomputed
    upward again, and the item may be started once more through the normal
    start path."

    Design: Difficulty/non_linear_state_machine/work_item_rework_loop_cycle
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Pump rebuild", "system_area": "CRU-2-P", "risk_class": "A",
            "estimated_hours": 100, "estimated_cost_cents": 150000,
        }
    )
    w1, contractor_id = _walk_through_rework_loop(api, ctx)

    reopened = validate_success(
        api.verify_work_item(w1["id"], {"outcome": "REOPENED"}, operations_headers)
    )
    assert reopened["status"] == "REOPENED", "rework loop, not an error"

    restarted = validate_success(
        api.start_work_item(w1["id"], make_supervisor_headers(contractor_id))
    )
    assert restarted["status"] == "IN_PROGRESS"

    completed = validate_success(
        api.complete_work_item(w1["id"], {"actual_hours": 60},
                               make_supervisor_headers(contractor_id))
    )
    assert completed["status"] == "COMPLETE"

    verified = validate_success(
        api.verify_work_item(w1["id"], {"outcome": "VERIFIED"}, operations_headers)
    )
    assert verified["status"] == "VERIFIED"


def test_rework_remaining_hours_tracks_latest_actuals(api, operations_headers, planner_headers):
    """PRD §3.5: "Completion records reality: the supervisor supplies the
    item's `actual_hours`, the item moves from `IN_PROGRESS` to `COMPLETE`, and
    its `remaining_hours` is recomputed as the `estimated_hours` minus the
    recorded `actual_hours` — absent actuals counting as zero — but never below
    zero."

    Design: Difficulty/non_linear_state_machine/work_item_rework_loop_cycle
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Pump rebuild", "system_area": "CRU-2-P", "risk_class": "A",
            "estimated_hours": 100, "estimated_cost_cents": 150000,
        }
    )
    w1, contractor_id = _walk_through_rework_loop(api, ctx)

    validate_success(
        api.verify_work_item(w1["id"], {"outcome": "REOPENED"}, operations_headers)
    )
    validate_success(
        api.start_work_item(w1["id"], make_supervisor_headers(contractor_id))
    )
    completed = validate_success(
        api.complete_work_item(w1["id"], {"actual_hours": 60},
                               make_supervisor_headers(contractor_id))
    )
    # the second actual_hours recording REPLACES the first: 100 - 60
    assert completed["actual_hours"] == 60
    assert completed["remaining_hours"] == 40, (
        f"remaining_hours must be 100 - 60: {completed['remaining_hours']} != 40"
    )

    verified = validate_success(
        api.verify_work_item(w1["id"], {"outcome": "VERIFIED"}, operations_headers)
    )
    assert verified["status"] == "VERIFIED"
    assert verified["remaining_hours"] == 40


def _setup_revoke_cascade(api):
    """EXECUTION turnaround (budget 400000) with the single critical-path item
    W1 (100h, 200000 cents, requires_permit) IN_PROGRESS under an ACTIVE
    permit. Returns the context dict."""
    ctx = setup_active_permit_scenario(authorized_budget_cents=400000)
    w1 = ctx["items"][0]
    validate_success(
        api.start_work_item(w1["id"], make_supervisor_headers(ctx["contractor"]["id"]))
    )
    return ctx


def test_permit_revocation_forces_hold_on_in_progress_item(
    api, coordinator_headers, planner_headers
):
    """PRD §3.4: "Revocation moves an `ISSUED`, `ACTIVE`, or `SUSPENDED` permit
    to `REVOKED`; revoking an `ACTIVE` permit fires the first link of a cascade
    — the covered work item, if `IN_PROGRESS`, is forced `ON_HOLD`, and that
    hold in turn recomputes the turnaround's critical-path slip and cost
    forecast as described in §3.5."

    Design: Difficulty/transitive_cascade/permit_revoke_hold_slip_posture_cascade
    """
    ctx = _setup_revoke_cascade(api)
    w1 = ctx["items"][0]
    permit = ctx["permit"]

    revoked = validate_success(
        api.transition_permit(permit["id"], {"to": "REVOKED"}, coordinator_headers)
    )
    assert revoked["status"] == "REVOKED"

    item = validate_success(api.get_work_item(w1["id"], planner_headers))
    assert item["status"] == "ON_HOLD", (
        "the hold is caused by the permit mutation, not the caller"
    )
    assert item["is_critical_path"] is True


def test_permit_revocation_recomputes_slip_and_posture(api, coordinator_headers, manager_headers):
    """PRD §3.5: "the turnaround's `critical_path_slip_hours` — the sum of
    `remaining_hours` over all critical-path items currently sitting in
    `ON_HOLD`, recomputed on every transition of an item into or out of that
    set".
    PRD §3.8: "The schedule-overrun figure prices critical-path slip: the whole
    number of eight-hour slip days contained in `critical_path_slip_hours` —
    fractional days are discarded by floor division — multiplied by a daily
    overhead of 50000 cents."
    PRD §3.8: "`cost_posture` is `OVERRUN` when `committed_cost_cents` exceeds
    `authorized_budget_cents`, otherwise `AT_RISK` when
    `forecast_provisional_cents` exceeds `authorized_budget_cents`, otherwise
    `WITHIN_BUDGET`."

    Design: Difficulty/transitive_cascade/permit_revoke_hold_slip_posture_cascade
    """
    ctx = _setup_revoke_cascade(api)
    permit = ctx["permit"]

    before = validate_success(api.get_turnaround(ctx["turnaround"]["id"], manager_headers))
    assert before["critical_path_slip_hours"] == 0

    validate_success(
        api.transition_permit(permit["id"], {"to": "REVOKED"}, coordinator_headers)
    )

    after = validate_success(api.get_turnaround(ctx["turnaround"]["id"], manager_headers))
    # single critical-path item ON_HOLD with remaining 100h
    assert after["critical_path_slip_hours"] == 100, (
        f"{after['critical_path_slip_hours']} != 100"
    )
    # provisional = 200000 committed + floor(100/8)*50000 overrun = 800000 > 400000;
    # committed 200000 <= 400000 -> AT_RISK
    assert after["cost_posture"] == "AT_RISK", (
        f"posture {after['cost_posture']} != AT_RISK"
    )


def _setup_startup_gate_scenario(api):
    """EXECUTION turnaround with two FROZEN items (cutoff 2): W1 VERIFIED, W2
    IN_PROGRESS. Returns (ctx, w1, w2)."""
    ctx = setup_execution_turnaround(num_items=2, scope_cutoff_count=2)
    w1, w2 = ctx["items"]
    contractor_id = ctx["contractor"]["id"]
    walk_work_item_to_verified(w1["id"], contractor_id, actual_hours=95)
    schedule_and_start_work_item(w2["id"], contractor_id)
    return ctx, w1, w2


def test_startup_advance_rejected_while_scope_item_open(api, manager_headers):
    """PRD §3.9: "Moving from `EXECUTION` to `STARTUP` enforces three gates,
    evaluated in order so that the earliest failure is the one reported:
    first, every scope work item — any item not `DEFERRED` or `CANCELLED` —
    must stand in `VERIFIED`, failing with `ERR_WORK_ITEMS_OPEN`; second, no
    permit may remain in `REQUESTED`, `ISSUED`, `ACTIVE`, or `SUSPENDED`,
    failing with `ERR_PERMITS_STILL_ACTIVE`; third, no isolation may remain in
    `PLANNED`, `ISOLATED`, or `VERIFIED`, failing with
    `ERR_ISOLATIONS_ENGAGED`."

    Design: Difficulty/cross_entity_state_dependency/startup_advance_blocked_until_all_scope_items_verified
    """
    ctx, _w1, w2 = _setup_startup_gate_scenario(api)
    check = validate_success(api.get_work_item(w2["id"], manager_headers))
    assert check["status"] == "IN_PROGRESS"

    resp = api.advance_turnaround(ctx["turnaround"]["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_WORK_ITEMS_OPEN)

    after = validate_success(api.get_turnaround(ctx["turnaround"]["id"], manager_headers))
    assert after["status"] == "EXECUTION"


def test_startup_advance_succeeds_once_all_items_verified(api, manager_headers, operations_headers):
    """PRD §3.9: "Moving from `EXECUTION` to `STARTUP` enforces three gates,
    evaluated in order so that the earliest failure is the one reported:
    first, every scope work item — any item not `DEFERRED` or `CANCELLED` —
    must stand in `VERIFIED`, failing with `ERR_WORK_ITEMS_OPEN`; second, no
    permit may remain in `REQUESTED`, `ISSUED`, `ACTIVE`, or `SUSPENDED`,
    failing with `ERR_PERMITS_STILL_ACTIVE`; third, no isolation may remain in
    `PLANNED`, `ISOLATED`, or `VERIFIED`, failing with
    `ERR_ISOLATIONS_ENGAGED`."

    Design: Difficulty/cross_entity_state_dependency/startup_advance_blocked_until_all_scope_items_verified
    """
    ctx, _w1, w2 = _setup_startup_gate_scenario(api)
    resp = api.advance_turnaround(ctx["turnaround"]["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_WORK_ITEMS_OPEN)

    complete_work_item(w2["id"], ctx["contractor"]["id"], 18)
    verify_work_item(w2["id"], "VERIFIED")

    advanced = validate_success(
        api.advance_turnaround(ctx["turnaround"]["id"], manager_headers)
    )
    assert advanced["status"] == "STARTUP"


def _setup_startup_with_open_punch(api):
    """STARTUP turnaround (W1 VERIFIED, no permits or isolations) carrying one
    OPEN category-A punch item on W1."""
    ctx = setup_startup_turnaround()
    assert ctx["turnaround"]["status"] == "STARTUP"
    return ctx


def test_handover_blocked_by_single_open_category_a_punch(api, manager_headers, operations_headers):
    """PRD §3.9: "The gate is precise: the count of punch items with `category`
    of `A` standing in `OPEN`, `READY`, or `REOPENED` must be exactly zero, and
    any such straggler blocks the handover with `ERR_OPEN_PUNCH_ITEMS`;
    category-`B` items impose no constraint."

    Design: Difficulty/boundary_precision_check/handover_requires_exactly_zero_open_category_a_punch
    """
    ctx = _setup_startup_with_open_punch(api)
    w1 = ctx["items"][0]
    punch = validate_success(
        api.create_punch_item(
            ctx["turnaround"]["id"],
            {"work_item_id": w1["id"], "category": "A",
             "description": "Weep-hole plug weeping"},
            operations_headers,
        ),
        201,
    )
    assert punch["status"] == "OPEN"

    resp = api.handover_turnaround(
        ctx["turnaround"]["id"], {"operations_acknowledged": True}, manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_PUNCH_ITEMS)

    after = validate_success(api.get_turnaround(ctx["turnaround"]["id"], manager_headers))
    assert after["status"] == "STARTUP"


def test_handover_succeeds_at_exactly_zero_open_category_a(
    api, manager_headers, operations_headers
):
    """PRD §3.9: "The gate is precise: the count of punch items with `category`
    of `A` standing in `OPEN`, `READY`, or `REOPENED` must be exactly zero, and
    any such straggler blocks the handover with `ERR_OPEN_PUNCH_ITEMS`;
    category-`B` items impose no constraint. A successful handover moves the
    turnaround to `HANDED_OVER`, stamps `handed_over_at`, and increments the
    turnaround's `version` one final time."

    Design: Difficulty/boundary_precision_check/handover_requires_exactly_zero_open_category_a_punch
    """
    ctx = _setup_startup_with_open_punch(api)
    w1 = ctx["items"][0]
    contractor = ctx["contractor"]
    punch = validate_success(
        api.create_punch_item(
            ctx["turnaround"]["id"],
            {"work_item_id": w1["id"], "category": "A",
             "description": "Weep-hole plug weeping"},
            operations_headers,
        ),
        201,
    )
    resp = api.handover_turnaround(
        ctx["turnaround"]["id"], {"operations_acknowledged": True}, manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_PUNCH_ITEMS)

    # walk the only category-A straggler to VERIFIED: count becomes exactly 0
    validate_success(
        api.ready_punch_item(punch["id"], make_supervisor_headers(contractor["id"]))
    )
    closed = validate_success(
        api.verify_punch_item(punch["id"], {"outcome": "VERIFIED"}, operations_headers)
    )
    assert closed["status"] == "VERIFIED"

    handed = validate_success(
        api.handover_turnaround(
            ctx["turnaround"]["id"], {"operations_acknowledged": True}, manager_headers
        )
    )
    assert handed["status"] == "HANDED_OVER"
    assert handed["handed_over_at"] is not None
    assert is_iso8601_timestamp(handed["handed_over_at"])
