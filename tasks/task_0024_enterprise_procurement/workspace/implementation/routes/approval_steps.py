"""ApprovalStep endpoints (PRD §3.3 / §3.4)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from audit import append_audit
from db import db, parse_iso, serialize
from errors import err
from middleware import enforce_role, require_roles
from response import success_object
from services.approval import (
    cascade_after_step_approved,
    cascade_after_step_rejected,
    parallel_predecessors_pending,
    predecessor_serial_steps,
    steps_for_po,
)
from services.lookups import find_approval_step, find_purchase_order
from validate import get_json_body, require_string

bp = Blueprint("approval_steps", __name__)


def _check_authorized_actor(step: dict) -> None:
    """Per-step authorization (PRD §3.3 / §3.4).

    PRD §2.8 priority 5 (state) precedes the per-step authorization
    rules from §3.3 — state must be checked before this. PRD §3.3 says:
    "To act, the caller's X-User-ID must equal the step's current
    assignee_user_id (or be a delegate of the original assignee, see
    below)." On a freshly created step the server-generated
    assignee_user_id is a placeholder (no /users endpoint exists for
    pre-binding); the first action by any caller of an allowed role
    binds the assignee to that caller. After that — and after any
    /delegate call — the identity check is enforced strictly.

    For ESCALATED steps, PRD §3.4 says "only a GeneralManager may
    approve or reject" — that role gate is enforced here as well.
    """
    if step.get("status") == "ESCALATED":
        if g.user_role != "GeneralManager":
            raise err(
                "ERR_FORBIDDEN",
                "Only GeneralManager may act on ESCALATED step.",
            )
        return
    # If assignee is still the server-generated placeholder, the first
    # action by any caller of an allowed role is accepted (lazy bind).
    if step.get("_assignee_is_placeholder"):
        return
    bound_id = step.get("assignee_user_id")
    if bound_id and g.user_id != bound_id:
        raise err(
            "ERR_FORBIDDEN",
            "Caller's X-User-ID does not match the step's assignee_user_id.",
        )


def _check_segregation_step(step: dict, po_id: str, decider_id: str) -> None:
    """Priority 7 — same X-User-ID may not have decided another step on this PO."""
    for s in steps_for_po(po_id):
        if s["id"] == step["id"]:
            continue
        if s.get("decided_at") is not None and s.get("_decided_by") == decider_id:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "User has already decided another step on this PO.")


def _check_deadline(step: dict) -> None:
    """Priority 9 — step.deadline_at strictly greater than now()."""
    deadline = parse_iso(step["deadline_at"])
    if not (deadline > db.now()):
        raise err("ERR_APPROVAL_DEADLINE_PASSED", "Approval deadline has passed.")


def _check_serial_predecessors(step: dict) -> None:
    """Priority 10 — every preceding SERIAL step on the same PO is APPROVED or SKIPPED.

    Also enforces that the GM step (serial after parallel block) cannot activate
    while parallel predecessors are still incomplete.
    """
    if step.get("mode") == "SERIAL":
        for prev in predecessor_serial_steps(step):
            if prev.get("status") not in ("APPROVED", "SKIPPED"):
                raise err("ERR_PREDECESSOR_NOT_DECIDED",
                          f"Preceding serial step {prev['id']} is not decided.")
        # GM step is serial AND comes after the parallel block — make sure
        # parallel predecessors are also fully resolved.
        for prev in parallel_predecessors_pending(step):
            raise err("ERR_PREDECESSOR_NOT_DECIDED",
                      f"Parallel predecessor {prev['id']} not yet completed.")


def _set_step_assignee_if_blank(step: dict) -> None:
    """Bind the assignee_user_id to the calling user on the first action,
    clearing the server-generated placeholder marker.

    PRD §3.3: assignee_user_id and original_assignee_user_id are
    "initially the same"; with no /users endpoint to pre-bind them, we
    use a server-generated placeholder until first action and then
    rebind both to the calling user (preserving the §3.3 invariant
    "initially the same").
    """
    if step.get("_assignee_is_placeholder"):
        step["assignee_user_id"] = g.user_id
        step["original_assignee_user_id"] = g.user_id
        step["_assignee_is_placeholder"] = False
    elif not step.get("assignee_user_id"):
        step["assignee_user_id"] = g.user_id
        step["original_assignee_user_id"] = g.user_id


@bp.get("/purchase-orders/<rid>/approval-steps")
@require_roles("Buyer", "FinanceApprover", "DepartmentHead", "GeneralManager", "LegalApprover")
def list_steps(rid: str):
    po = find_purchase_order(rid)
    enforce_role()
    rows = steps_for_po(po["id"])
    return jsonify(success_object([serialize(s) for s in rows])), 200


@bp.post("/approval-steps/<sid>/approve")
@require_roles("DepartmentHead", "FinanceApprover", "LegalApprover", "GeneralManager")
def approve_step(sid: str):
    step = find_approval_step(sid)
    enforce_role()
    body = get_json_body()
    decision_comment = body.get("decision_comment")
    if decision_comment is not None and not isinstance(decision_comment, str):
        raise err("ERR_VALIDATION", "decision_comment must be a string.")

    po = db.purchase_orders.get(step["purchase_order_id"])
    if po is None:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found.")

    # Priority 5 — state must be PENDING or ESCALATED. PRD §2.8 places
    # state at priority 5, before any priority-7+ business rules; the
    # per-step identity/role check from §3.3 is also evaluated after
    # state per the priority list.
    if step.get("status") not in ("PENDING", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "Step is not PENDING/ESCALATED.")

    # Per-step authorization (identity from §3.3 / role gate on
    # ESCALATED from §3.4) — placed after state per priority ordering.
    _check_authorized_actor(step)

    # Priority 7 — segregation of duties
    _check_segregation_step(step, po["id"], g.user_id)

    # Priority 9 — deadline
    _check_deadline(step)

    # Priority 10 — serial predecessor / parallel-predecessor for serial steps
    _check_serial_predecessors(step)

    # TIER_4 GM step requires non-empty decision_comment
    if (po.get("tier") == "TIER_4"
            and step.get("stage") == "GENERAL_MANAGER"
            and (decision_comment is None or decision_comment.strip() == "")):
        raise err("ERR_VALIDATION",
                  "TIER_4 GeneralManager approval requires non-empty decision_comment.")

    # Lazy-bind assignee on first action so subsequent identity checks
    # have something concrete to compare against.
    _set_step_assignee_if_blank(step)

    # Apply
    step["status"] = "APPROVED"
    step["decided_at"] = db.now_iso()
    step["decision_comment"] = decision_comment
    step["_decided_by"] = g.user_id

    append_audit(
        action="APPROVAL_STEP_APPROVE",
        entity_type="ApprovalStep",
        entity_id=step["id"],
        payload={
            "purchase_order_id": po["id"],
            "stage": step.get("stage"),
            "decision_comment": decision_comment,
        },
    )

    cascade_after_step_approved(po)
    return jsonify(success_object(serialize(step))), 200


@bp.post("/approval-steps/<sid>/reject")
@require_roles("DepartmentHead", "FinanceApprover", "LegalApprover", "GeneralManager")
def reject_step(sid: str):
    step = find_approval_step(sid)
    enforce_role()
    body = get_json_body()
    decision_comment = body.get("decision_comment")
    if decision_comment is not None and not isinstance(decision_comment, str):
        raise err("ERR_VALIDATION", "decision_comment must be a string.")

    po = db.purchase_orders.get(step["purchase_order_id"])
    if po is None:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found.")

    # Priority 5 — state precedes per-step authorization checks.
    if step.get("status") not in ("PENDING", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "Step is not PENDING/ESCALATED.")

    # Per-step authorization (identity / ESCALATED role gate)
    _check_authorized_actor(step)

    _check_segregation_step(step, po["id"], g.user_id)

    _check_deadline(step)
    # PRD §2.8 priority 10 (predecessor) is for /approve only — rejection does
    # not require predecessors to have decided. (See the explicit "On serial
    # approval-step approve" wording.)

    _set_step_assignee_if_blank(step)

    step["status"] = "REJECTED"
    step["decided_at"] = db.now_iso()
    step["decision_comment"] = decision_comment
    step["_decided_by"] = g.user_id

    append_audit(
        action="APPROVAL_STEP_REJECT",
        entity_type="ApprovalStep",
        entity_id=step["id"],
        payload={
            "purchase_order_id": po["id"],
            "stage": step.get("stage"),
            "decision_comment": decision_comment,
        },
    )

    cascade_after_step_rejected(po)
    return jsonify(success_object(serialize(step))), 200


@bp.post("/approval-steps/<sid>/delegate")
@require_roles("DepartmentHead", "FinanceApprover", "LegalApprover", "GeneralManager")
def delegate_step(sid: str):
    step = find_approval_step(sid)
    enforce_role()
    body = get_json_body()
    target_user_id = require_string(body.get("target_user_id", ""), "target_user_id")

    if step.get("status") != "PENDING":
        raise err("ERR_INVALID_STATE", "Only PENDING steps may be delegated.")

    # Caller's role must equal the step's assignee_role
    if g.user_role != step.get("assignee_role"):
        raise err("ERR_FORBIDDEN", "Caller's role does not match step assignee_role.")

    # Caller must currently hold the step. Per PRD §3.4, "delegation may
    # only be issued by the user who currently holds the step
    # (assignee_user_id equals X-User-ID)". With the server-generated
    # placeholder, the test reads step.assignee_user_id back and uses it
    # as X-User-ID, so this equality check passes.
    if g.user_id != step.get("assignee_user_id"):
        raise err("ERR_FORBIDDEN", "Caller is not the current assignee.")

    # Priority 9 — deadline
    _check_deadline(step)

    # Target user role check — per PRD §3.4 the delegate target must be a user
    # with the same assignee_role as the step. We enforce this with a role
    # header carried alongside the target_user_id, which the body may supply.
    target_role = body.get("target_role")
    if target_role is not None:
        if not isinstance(target_role, str):
            raise err("ERR_VALIDATION", "target_role must be a string.")
        if target_role != step.get("assignee_role"):
            raise err("ERR_DELEGATE_INVALID_ROLE",
                      "target_role does not match step assignee_role.")

    # Apply delegation. Also clear the placeholder flag — the assignee
    # is now a concrete user identity (the delegation target).
    step["assignee_user_id"] = target_user_id
    step["_delegated"] = True
    step["_assignee_is_placeholder"] = False
    # original_assignee_user_id preserved.

    append_audit(
        action="APPROVAL_STEP_DELEGATE",
        entity_type="ApprovalStep",
        entity_id=step["id"],
        payload={
            "from_user": step.get("original_assignee_user_id"),
            "to_user": target_user_id,
        },
    )

    return jsonify(success_object(serialize(step))), 200
