"""Test-driving endpoints (PRD §3.11)."""

from __future__ import annotations

import datetime as _dt

from flask import Blueprint, jsonify

from audit import append_audit
from db import db, parse_iso, fmt_iso
from errors import err
from middleware import require_roles
from response import success_object
from validate import get_json_body, require_fields, require_int, require_string

bp = Blueprint("system", __name__)


@bp.post("/_clock/advance")
@require_roles("PlatformAdmin")
def clock_advance():
    body = get_json_body()
    require_fields(body, ["to"])
    to = require_string(body["to"], "to")
    try:
        new_time = parse_iso(to)
    except Exception:
        raise err("ERR_VALIDATION", "to must be ISO 8601.")
    db.set_clock(new_time)
    new_now = db.now()

    # Sweep 1: ApprovalStep escalation. Each PENDING step whose deadline_at <= now
    # transitions to ESCALATED.
    escalated_ids: list[str] = []
    for step in db.approval_steps.values():
        if step.get("status") != "PENDING":
            continue
        try:
            deadline = parse_iso(step["deadline_at"])
        except Exception:
            continue
        if deadline <= new_now:
            step["status"] = "ESCALATED"
            # Per PRD §3.4: assignee_user_id rewritten to a GeneralManager user
            # (we use a synthetic placeholder so the escalated assignee can be
            # discovered by the GM caller acting on the step).
            step["assignee_user_id"] = "GM_ESCALATION_TARGET"
            step["deadline_at"] = fmt_iso(new_now + _dt.timedelta(hours=24))
            escalated_ids.append(step["id"])
            append_audit(
                action="APPROVAL_STEP_ESCALATE",
                entity_type="ApprovalStep",
                entity_id=step["id"],
                payload={
                    "purchase_order_id": step.get("purchase_order_id"),
                    "stage": step.get("stage"),
                },
            )

    # Sweep 2: Quote expiry — quotes of suppliers whose qualification has lapsed
    # AND that are still SUBMITTED.
    expired_ids: list[str] = []
    for q in db.quotes.values():
        if q.get("status") != "SUBMITTED":
            continue
        sup = db.suppliers.get(q.get("supplier_id"))
        if sup is None:
            continue
        try:
            qexp = parse_iso(sup["qualification_expires_at"])
        except Exception:
            continue
        if qexp <= new_now:
            q["status"] = "EXPIRED"
            expired_ids.append(q["id"])

    return jsonify(success_object({
        "now": fmt_iso(new_now),
        "escalated_step_ids": escalated_ids,
        "expired_quote_ids": expired_ids,
    })), 200


@bp.post("/_events/supplier-delivery")
@require_roles("PlatformAdmin")
def supplier_delivery():
    body = get_json_body()
    require_fields(body, ["purchase_order_id", "delivery_note_no", "declared_quantity"])
    po_id = require_string(body["purchase_order_id"], "purchase_order_id")
    delivery_note_no = require_string(body["delivery_note_no"], "delivery_note_no")
    declared = require_int(body["declared_quantity"], "declared_quantity", min_value=1)
    if po_id not in db.purchase_orders:
        raise err("ERR_VALIDATION", "purchase_order_id does not exist.")
    rec = {
        "purchase_order_id": po_id,
        "delivery_note_no": delivery_note_no,
        "declared_quantity": declared,
        "received_at": db.now_iso(),
    }
    db.delivery_notes.append(rec)
    return jsonify(success_object(rec)), 201
