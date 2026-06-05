"""ApprovalStep endpoints: approve / reject (PRD §3.5).

A step may be acted on only if it is the lowest-level PENDING step for its invoice
and the parent invoice is PENDING_APPROVAL. Approving the highest level bubbles the
invoice to APPROVED. Rejecting cascades higher PENDING steps to REJECTED, moves the
invoice to REJECTED, and compensates the PO matched ledger.
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_APPROVAL_OUT_OF_ORDER,
)
from middleware import auth_required, ALL_ROLES, current_user_id
from response import ok_object
from routes._helpers import serialize
from services.common import touch
from services.ledger import recompute_po_matched
from services.audit import append_audit

bp = Blueprint("approval_steps", __name__)


def _require_step(sid):
    step = db.approval_steps.get(sid)
    if step is None:
        raise APIError(ERR_NOT_FOUND, 404, "Approval step not found")
    return step


def _invoice_steps(iid):
    return [s for s in db.approval_steps.values() if s["invoice_id"] == iid]


def _lowest_pending_level(iid):
    pending = [s["level"] for s in _invoice_steps(iid) if s["status"] == "PENDING"]
    return min(pending) if pending else None


@bp.get("/ap/approval-steps/<sid>")
def get_step(sid):
    auth_required(ALL_ROLES)()
    step = _require_step(sid)
    return ok_object(serialize(step))


@bp.post("/ap/approval-steps/<sid>/approve")
def approve_step(sid):
    auth_required({"Approver"})()
    step = _require_step(sid)
    inv = db.invoices.get(step["invoice_id"])

    # State: step PENDING and parent invoice PENDING_APPROVAL.
    if step["status"] != "PENDING" or inv is None or inv["status"] != "PENDING_APPROVAL":
        raise APIError(ERR_INVALID_STATE, 409, "Step not actionable in current state")

    # business: must be the lowest-level PENDING step (409).
    if step["level"] != _lowest_pending_level(step["invoice_id"]):
        raise APIError(ERR_APPROVAL_OUT_OF_ORDER, 409, "Not the lowest-level pending step")

    step["status"] = "APPROVED"
    step["acted_by"] = current_user_id()
    touch(step)

    # Bubble-up only when this is the highest level on the invoice.
    max_level = max(s["level"] for s in _invoice_steps(step["invoice_id"]))
    if step["level"] == max_level:
        inv["status"] = "APPROVED"
        inv["approved_by"] = current_user_id()
        touch(inv)
        append_audit(inv["id"], "APPROVED", current_user_id())

    return ok_object(serialize(step))


@bp.post("/ap/approval-steps/<sid>/reject")
def reject_step(sid):
    auth_required({"Approver"})()
    step = _require_step(sid)
    inv = db.invoices.get(step["invoice_id"])

    if step["status"] != "PENDING" or inv is None or inv["status"] != "PENDING_APPROVAL":
        raise APIError(ERR_INVALID_STATE, 409, "Step not actionable in current state")

    if step["level"] != _lowest_pending_level(step["invoice_id"]):
        raise APIError(ERR_APPROVAL_OUT_OF_ORDER, 409, "Not the lowest-level pending step")

    step["status"] = "REJECTED"
    step["acted_by"] = current_user_id()
    touch(step)

    # Cascade: all higher-level PENDING steps -> REJECTED.
    for s in _invoice_steps(step["invoice_id"]):
        if s["level"] > step["level"] and s["status"] == "PENDING":
            s["status"] = "REJECTED"
            touch(s)

    # Invoice -> REJECTED; compensate PO matched ledger (reopen if closed).
    inv["status"] = "REJECTED"
    touch(inv)
    if inv["po_id"]:
        po = db.purchase_orders.get(inv["po_id"])
        if po is not None:
            recompute_po_matched(po)
    append_audit(inv["id"], "REJECTED", current_user_id())

    return ok_object(serialize(step))
