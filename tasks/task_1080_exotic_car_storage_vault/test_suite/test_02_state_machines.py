"""State-machine transitions: cyclic agreement in/out, service-order branch+revert,
guarded transitions, and terminal-state lockdown (PRD §3.3, §3.5, §3.8)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

VM = TEST_USERS["vault_manager_headers"]
CT = TEST_USERS["concierge_tech_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / agreement_in_out_cycle
# ---------------------------------------------------------------------------
def test_agreement_check_out_then_check_in_returns_to_in_storage(api):
    """PRD §3.3: "**Checking out** advances the agreement `IN_STORAGE → CHECKED_OUT`
    and represents the car physically leaving while the unit stays `OCCUPIED`, held
    for its return; **checking in** advances `CHECKED_OUT → IN_STORAGE`."

    Design: Difficulty/non_linear_state_machine/agreement_in_out_cycle
    """
    ctx = fx.setup_stored_agreement(api)
    aid = ctx["agreement_id"]
    out1 = validate_success(api.check_out(aid, CT))
    assert out1["status"] == "CHECKED_OUT"
    back = validate_success(api.check_in(aid, CT))
    assert back["status"] == "IN_STORAGE"


def test_agreement_in_out_cycle_reenters_checked_out(api):
    """PRD §3.3: "Once in storage, the vehicle cycles in and out. **Checking out**
    advances the agreement `IN_STORAGE → CHECKED_OUT` ... **checking in** advances
    `CHECKED_OUT → IN_STORAGE`."

    Design: Difficulty/non_linear_state_machine/agreement_in_out_cycle
    """
    ctx = fx.setup_stored_agreement(api)
    aid = ctx["agreement_id"]
    validate_success(api.check_out(aid, CT))
    validate_success(api.check_in(aid, CT))
    out2 = validate_success(api.check_out(aid, CT))
    assert out2["status"] == "CHECKED_OUT", "the same CHECKED_OUT state is re-entered"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / service_order_hold_resume_and_reject_branch
# ---------------------------------------------------------------------------
def test_service_order_hold_then_resume_reverts_to_in_progress(api):
    """PRD §3.5: "A technician may **hold** work in progress, advancing
    `IN_PROGRESS → ON_HOLD`; a held order still counts toward the member's held
    funds."
    PRD §3.5: "The same start action also resumes a paused order, advancing
    `ON_HOLD → IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/service_order_hold_resume_and_reject_branch
    """
    ctx = fx.setup_in_progress_service_order(api)
    sid = ctx["service_order_id"]
    held = validate_success(api.hold_service_order(sid, CT))
    assert held["status"] == "ON_HOLD"
    resumed = validate_success(api.start_service_order(sid, CT))
    assert resumed["status"] == "IN_PROGRESS", "revert cycle IN_PROGRESS<->ON_HOLD closed"


def test_service_order_reject_branch_from_requested(api):
    """PRD §3.5: "**Rejection** advances `REQUESTED → REJECTED` and has no financial
    effect."

    Design: Difficulty/non_linear_state_machine/service_order_hold_resume_and_reject_branch
    """
    ctx = fx.setup_stored_agreement(api)
    so = validate_success(api.create_service_order(
        {"agreement_id": ctx["agreement_id"], "service_type": "FUEL",
         "estimated_labor_hours": 0.5}, VM), 201)
    rejected = validate_success(api.reject_service_order(so["id"], VM))
    assert rejected["status"] == "REJECTED", "branch other than APPROVED"


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_cancel_in_storage_agreement_rejected_invalid_state(api):
    """PRD §3.3: "Cancelling from any status other than `PENDING` is an
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_in_storage_agreement_rejected_invalid_state
    """
    ctx = fx.setup_stored_agreement(api)
    aid = ctx["agreement_id"]
    resp = api.cancel_agreement(aid, VM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    unchanged = validate_success(api.get_agreement(aid, VM))
    assert unchanged["status"] == "IN_STORAGE"


def test_double_terminate_agreement_rejected_invalid_state(api):
    """PRD §3.3: "A vault manager **terminates** an agreement to close it out,
    transitioning from either `IN_STORAGE` or `CHECKED_OUT` to `CLOSED`."
    PRD §2.8: "State validity — the target resource is in a legal state for the
    requested transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/double_terminate_agreement_rejected_invalid_state
    """
    ctx = fx.setup_stored_agreement(api)
    aid = ctx["agreement_id"]
    closed = validate_success(api.terminate(aid, VM))
    assert closed["status"] == "CLOSED"
    resp = api.terminate(aid, VM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert validate_success(api.get_agreement(aid, VM))["status"] == "CLOSED"


def test_move_in_without_documented_vehicle_rejected_cross_entity(api):
    """PRD §3.3: "and that the vehicle's `condition_status` is `DOCUMENTED`, else the
    cross-entity precondition fails with `ERR_CROSS_ENTITY_STATE` (409)."

    Design: Corner/state_machines/move_in_without_documented_vehicle_rejected_cross_entity
    """
    ctx = fx.setup_pending_agreement(api, document=False)
    aid = ctx["agreement_id"]
    resp = api.move_in(aid, VM)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE.value)
    assert validate_success(api.get_agreement(aid, VM))["status"] == "PENDING"


def test_inspection_fail_sets_vehicle_damage_hold(api):
    """PRD §3.8: "**Failing** advances `SCHEDULED → FAILED` and drives the vehicle's
    `condition_status` to `DAMAGE_HOLD`, which blocks service starts and move-in
    until a subsequent intake inspection passes."

    Design: Corner/state_machines/inspection_fail_sets_vehicle_damage_hold
    """
    mem = fx.create_member(api)
    veh = fx.create_vehicle(api, mem["id"])
    insp = validate_success(api.create_inspection(
        {"vehicle_id": veh["id"], "inspection_type": "PERIODIC"}, VM), 201)
    failed = validate_success(api.fail_inspection(insp["id"],
                                                  {"damage_noted": True, "findings": "scratch"}, CT))
    assert failed["status"] == "FAILED"
    v = validate_success(api.get_vehicle(veh["id"], VM))
    assert v["condition_status"] == "DAMAGE_HOLD"
