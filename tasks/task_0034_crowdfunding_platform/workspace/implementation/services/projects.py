"""Project domain operations: funding aggregation, status cascades, deadline resolution."""

from clock import CLOCK
from db import DB, new_id
from services.audit import append_audit, append_escrow
from services.common import bump_version


AUTHORIZED_STATES_FOR_PROVISIONAL = {"AUTHORIZED"}
FINAL_PAYMENT_STATES = {"CHARGED", "PARTIALLY_REFUNDED"}


def recompute_provisional(project):
    total = 0
    for o in DB.orders.values():
        if o["project_id"] == project["id"] and o["payment_status"] in AUTHORIZED_STATES_FOR_PROVISIONAL:
            total += int(o.get("order_total_cents", 0))
    project["provisional_raised_cents"] = total
    bump_version(project)
    return total


def recompute_final(project):
    total = 0
    for o in DB.orders.values():
        if o["project_id"] == project["id"] and o["payment_status"] in FINAL_PAYMENT_STATES:
            total += int(o.get("order_total_cents", 0))
    project["final_raised_cents"] = total
    bump_version(project)
    return total


def transition_project_status(project, to_status, actor_role, actor_id, payload=None):
    from_status = project["status"]
    project["status"] = to_status
    bump_version(project)
    append_audit(
        subject_type="PROJECT",
        subject_id=project["id"],
        event_type="STATUS_CHANGE",
        payload={"from": from_status, "to": to_status, **(payload or {})},
        actor_role=actor_role,
        actor_id=actor_id,
    )


def auto_resolve_deadline(project):
    """Resolve a LIVE project whose deadline has passed.

    Returns True if a transition fired, else False. Only call while holding DB.LOCK.
    """
    if project["status"] != "LIVE":
        return False
    deadline = project.get("deadline")
    if deadline is None:
        return False
    now = CLOCK.now()
    if now < deadline:
        return False

    # Decide success vs failure
    funding_model = project["funding_model"]
    raised = int(project.get("provisional_raised_cents", 0))
    target = int(project.get("funding_target_cents", 0))

    if funding_model == "KEEP_IT_ALL" or (funding_model == "ALL_OR_NOTHING" and raised >= target):
        _do_succeed(project)
    else:
        _do_fail(project)
    return True


def _do_succeed(project):
    transition_project_status(project, "SUCCEEDED", actor_role="SYSTEM", actor_id="SYSTEM",
                              payload={"trigger": "deadline_reached"})
    # Charge wave: every AUTHORIZED order on this project enters CHARGE_PENDING
    for o in list(DB.orders.values()):
        if o["project_id"] == project["id"] and o["payment_status"] == "AUTHORIZED":
            o["payment_status"] = "CHARGE_PENDING"
            o["charge_attempts"] = int(o.get("charge_attempts", 0)) + 1
            bump_version(o)
            append_audit(
                subject_type="ORDER",
                subject_id=o["id"],
                event_type="STATUS_CHANGE",
                payload={"from": "AUTHORIZED", "to": "CHARGE_PENDING"},
                actor_role="SYSTEM",
                actor_id="SYSTEM",
            )
    # final_raised_cents will be recomputed once charges resolve
    recompute_final(project)


def _do_fail(project):
    transition_project_status(project, "FAILED", actor_role="SYSTEM", actor_id="SYSTEM",
                              payload={"trigger": "deadline_reached"})
    # Cascade: void all AUTHORIZED orders and synthesize EXECUTED refund records (amount=0)
    for o in list(DB.orders.values()):
        if o["project_id"] == project["id"] and o["payment_status"] == "AUTHORIZED":
            _void_order_for_project_termination(project, o, reason="PROJECT_FAILED")


def _do_cancel(project, reason_msg):
    transition_project_status(project, "CANCELLED", actor_role="Initiator", actor_id=project["initiator_id"],
                              payload={"reason": reason_msg} if reason_msg else {})
    for o in list(DB.orders.values()):
        if o["project_id"] != project["id"]:
            continue
        if o["payment_status"] == "AUTHORIZED":
            _void_order_for_project_termination(project, o, reason="PROJECT_CANCELLED")
        elif o["payment_status"] == "CHARGED":
            _synthesize_refund_for_charged(project, o)


def _void_order_for_project_termination(project, order, reason):
    """Auto-void AUTHORIZED order due to project FAILED/CANCELLED, then synthesize an
    EXECUTED RefundRequest with amount 0 for audit."""
    from_state = order["payment_status"]
    order["payment_status"] = "VOIDED"
    bump_version(order)
    # Reverse inventory
    _reverse_order_inventory(order)
    append_escrow(project["id"], order["id"], "CHARGE_VOID", amount_cents=0)
    append_audit(
        subject_type="ORDER",
        subject_id=order["id"],
        event_type="STATUS_CHANGE",
        payload={"from": from_state, "to": "VOIDED"},
        actor_role="SYSTEM",
        actor_id="SYSTEM",
    )
    # Synthesize executed refund record (amount 0)
    rr = _synthesize_refund_record(
        order=order,
        reason=reason,
        triggered_by="PLATFORM_AUTO",
        approved_amount_cents=0,
        status_value="EXECUTED",
    )
    append_audit(
        subject_type="REFUND_REQUEST",
        subject_id=rr["id"],
        event_type="REFUND_EXECUTED",
        payload={"amount_cents": 0, "reason": reason},
        actor_role="SYSTEM",
        actor_id="SYSTEM",
    )
    # provisional_raised drops since order left AUTHORIZED
    recompute_provisional(project)


def _synthesize_refund_for_charged(project, order):
    """For project cancellation, synthesize APPROVED refund for full remainder; auto-execute it."""
    rr = _synthesize_refund_record(
        order=order,
        reason="PROJECT_CANCELLED",
        triggered_by="PLATFORM_AUTO",
        approved_amount_cents=int(order.get("refundable_remainder_cents", 0)),
        status_value="APPROVED",
    )
    # Auto-execute the refund
    from services.refunds import execute_refund_internal
    execute_refund_internal(rr, actor_role="SYSTEM", actor_id="SYSTEM")


def _synthesize_refund_record(order, reason, triggered_by, approved_amount_cents, status_value):
    now = CLOCK.now()
    rr = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "order_id": order["id"],
        "reason": reason,
        "requested_amount_cents": approved_amount_cents,
        "status": status_value,
        "approved_amount_cents": approved_amount_cents if status_value in ("APPROVED", "EXECUTED") else None,
        "rejection_reason": None,
        "triggered_by": triggered_by,
    }
    DB.refund_requests[rr["id"]] = rr
    return rr


def _reverse_order_inventory(order):
    reward = DB.rewards.get(order.get("reward_id"))
    if reward is not None:
        reward["inventory_claimed"] = max(0, int(reward.get("inventory_claimed", 0)) - 1)
        bump_version(reward)
    for ao in order.get("add_ons", []) or []:
        addon = DB.add_on_items.get(ao.get("add_on_item_id"))
        if addon is not None:
            addon["inventory_claimed"] = max(0, int(addon.get("inventory_claimed", 0)) - int(ao.get("quantity", 0)))
            bump_version(addon)


def resolve_all_due_deadlines():
    """Iterate every LIVE project; resolve any whose deadlines have passed."""
    # Snapshot to avoid mutation issues
    for p in list(DB.projects.values()):
        if p["status"] == "LIVE":
            auto_resolve_deadline(p)
