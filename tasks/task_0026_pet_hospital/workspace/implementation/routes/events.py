"""External event endpoints + admin utilities (PRD §3.3, §3.6, §3.9, §3.10)."""
from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, g, request

import db
from clock import advance, now_iso
from errors import err
from middleware import authenticate, require_roles
from response import success_array, success_object
from services.bill_calc import recompute_final, recompute_provisional
from services.common import bump, init_bare
from validators import (
    require_int,
    require_str,
    validate_pagination,
)

bp = Blueprint("events", __name__)


@bp.before_request
def _auth():
    authenticate()


# Vaccine batch recall ------------------------------------------------------
@bp.post("/_events/vaccine-batch-recall")
def vaccine_batch_recall():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    batch_id = payload.get("batch_id")
    vaccine_code = payload.get("vaccine_code")
    event_id = payload.get("event_id")
    if not isinstance(batch_id, str) or not batch_id:
        raise err("ERR_VALIDATION_FAILED", "batch_id required")
    if not isinstance(vaccine_code, str) or not vaccine_code:
        raise err("ERR_VALIDATION_FAILED", "vaccine_code required")
    if not isinstance(event_id, str) or not event_id:
        raise err("ERR_VALIDATION_FAILED", "event_id required")
    with db.GLOBAL_LOCK:
        if event_id in db.processed_recall_event_ids:
            # Idempotent: 200 with no further write.
            return success_object({"event_id": event_id, "status": "duplicate"})
        db.processed_recall_event_ids.add(event_id)
        db.recalled_batches.add(batch_id)
        # Flip every matching ACTIVE vaccination record to RECALLED.
        affected_owner_ids = set()
        for vr in db.vaccination_records.values():
            if (vr.get("batch_id") == batch_id
                    and vr.get("vaccine_code") == vaccine_code
                    and vr.get("status") == "ACTIVE"):
                vr["status"] = "RECALLED"
                # next_due_at = administered_at (due now)
                vr["next_due_at"] = vr.get("administered_at")
                pet = db.pets.get(vr.get("pet_id"))
                if pet:
                    affected_owner_ids.add(pet.get("owner_id"))
        # Emit IM-bridge notifications (test stub).
        for owner_id in affected_owner_ids:
            db.im_emissions.append({
                "id": db.new_uuid(),
                "recipient_owner_id": owner_id,
                "kind": "VACCINE_RECALL",
                "payload": {
                    "batch_id": batch_id,
                    "vaccine_code": vaccine_code,
                },
                "created_at": now_iso(),
            })
        return success_object({"event_id": event_id, "status": "ok"})


# External lab result -------------------------------------------------------
@bp.post("/_events/external-lab-result")
def external_lab_result():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    ref = payload.get("external_lab_ref")
    results = payload.get("results")
    event_id = payload.get("event_id")
    if not isinstance(ref, str) or not ref:
        raise err("ERR_VALIDATION_FAILED", "external_lab_ref required")
    if not isinstance(results, list):
        raise err("ERR_VALIDATION_FAILED", "results must be a list")
    if not isinstance(event_id, str) or not event_id:
        raise err("ERR_VALIDATION_FAILED", "event_id required")
    with db.GLOBAL_LOCK:
        # Idempotent on external_lab_ref.
        existing_lr_id = db.processed_lab_refs.get(ref)
        lr = db.lab_report_by_external_ref(ref)
        if not lr:
            raise err("ERR_NOT_FOUND", "no lab report with that external_lab_ref")
        if existing_lr_id and existing_lr_id == lr["id"] and lr.get("status") != "SENT_TO_LAB":
            # Duplicate delivery — return current state.
            from routes.lab_reports import lr_view
            return success_object(lr_view(lr))
        # First-arrival path.
        if lr.get("status") != "SENT_TO_LAB":
            raise err("ERR_INVALID_STATE", "LabReport must be SENT_TO_LAB")
        # Validate results match test_items.
        test_items = lr.get("test_items", [])
        if len(results) != len(test_items):
            raise err("ERR_VALIDATION_FAILED", "results length must match test_items length")
        item_map = {it["code"]: it for it in test_items}
        result_codes = []
        for r in results:
            if not isinstance(r, dict):
                raise err("ERR_VALIDATION_FAILED", "results entries must be objects")
            c = r.get("code")
            v = r.get("value")
            if c not in item_map:
                raise err("ERR_VALIDATION_FAILED", "result code not in test_items")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise err("ERR_VALIDATION_FAILED", "result value must be a number")
            result_codes.append(c)
        if set(result_codes) != set(item_map.keys()):
            raise err("ERR_VALIDATION_FAILED", "results codes must permute test_items codes")
        lr["results"] = [{"code": r["code"], "value": float(r["value"])} for r in results]
        # Compute abnormal_codes (exclusive boundary).
        abnormals = []
        for r in lr["results"]:
            it = item_map[r["code"]]
            if r["value"] < float(it["ref_low"]) or r["value"] > float(it["ref_high"]):
                abnormals.append(r["code"])
        lr["abnormal_codes"] = sorted(abnormals)
        lr["status"] = "RESULT_RECEIVED"
        bump(lr)
        db.processed_lab_refs[ref] = lr["id"]
        from routes.lab_reports import lr_view
        return success_object(lr_view(lr))


# Payment event -------------------------------------------------------------
@bp.post("/_events/payment")
def payment_event():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    bill_id = payload.get("bill_id")
    amount = payload.get("amount_cents")
    event_id = payload.get("event_id")
    if not isinstance(bill_id, str) or not bill_id:
        raise err("ERR_VALIDATION_FAILED", "bill_id required")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise err("ERR_VALIDATION_FAILED", "amount_cents must be positive int")
    if not isinstance(event_id, str) or not event_id:
        raise err("ERR_VALIDATION_FAILED", "event_id required")
    with db.GLOBAL_LOCK:
        if event_id in db.processed_payment_event_ids:
            raise err("ERR_DUPLICATE_EVENT", "Duplicate payment event_id")
        b = db.bills.get(bill_id)
        if not b:
            raise err("ERR_REFERENCE_NOT_FOUND", "bill_id not found")
        if b["status"] not in {"ISSUED", "PARTIALLY_PAID"}:
            raise err("ERR_INVALID_STATE", "Bill not in ISSUED/PARTIALLY_PAID")
        db.processed_payment_event_ids.add(event_id)
        new_paid = int(b["paid_amount_cents"]) + amount
        b["paid_amount_cents"] = new_paid
        # threshold = provisional_total at issue time (PRD §3.9 "amount_due").
        # We use provisional_total_cents directly.
        threshold = int(b["provisional_total_cents"])
        if new_paid >= threshold:
            b["status"] = "PAID"
            recompute_final(b)
            # Auto-refund flow if final_total < paid (overpay).
            if int(b["final_total_cents"]) < new_paid:
                # Set provisional refund_amount_cents to overpay; transition to REFUND_PENDING.
                # (Confirm event will still update refund_amount_cents.)
                b["refund_amount_cents"] = new_paid - int(b["final_total_cents"])
                b["status"] = "REFUND_PENDING"
        else:
            b["status"] = "PARTIALLY_PAID"
        bump(b)
        from routes.bills import bill_view
        return success_object(bill_view(b))


# Refund confirm ------------------------------------------------------------
@bp.post("/_events/refund-confirm")
def refund_confirm():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    bill_id = payload.get("bill_id")
    amount = payload.get("amount_cents")
    event_id = payload.get("event_id")
    if not isinstance(bill_id, str):
        raise err("ERR_VALIDATION_FAILED", "bill_id required")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise err("ERR_VALIDATION_FAILED", "amount_cents must be positive int")
    if not isinstance(event_id, str) or not event_id:
        raise err("ERR_VALIDATION_FAILED", "event_id required")
    with db.GLOBAL_LOCK:
        if event_id in db.processed_refund_event_ids:
            raise err("ERR_DUPLICATE_EVENT", "Duplicate refund event_id")
        b = db.bills.get(bill_id)
        if not b:
            raise err("ERR_REFERENCE_NOT_FOUND", "bill_id not found")
        if b["status"] != "REFUND_PENDING":
            raise err("ERR_INVALID_STATE", "Bill must be REFUND_PENDING")
        db.processed_refund_event_ids.add(event_id)
        b["refund_amount_cents"] = int(b.get("refund_amount_cents", 0)) + amount
        b["status"] = "REFUNDED"
        bump(b)
        from routes.bills import bill_view
        return success_object(bill_view(b))


# Outbound IM emit ---------------------------------------------------------
@bp.post("/_events/im-emit")
def im_emit():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    recipient = payload.get("recipient_owner_id")
    kind = payload.get("kind")
    body = payload.get("payload")
    if not isinstance(recipient, str) or not recipient:
        raise err("ERR_VALIDATION_FAILED", "recipient_owner_id required")
    if not isinstance(kind, str) or not kind:
        raise err("ERR_VALIDATION_FAILED", "kind required")
    if not isinstance(body, dict):
        body = {}
    with db.GLOBAL_LOCK:
        em = {
            "id": db.new_uuid(),
            "recipient_owner_id": recipient,
            "kind": kind,
            "payload": body,
            "created_at": now_iso(),
        }
        db.im_emissions.append(em)
        return success_object(em)


# Audit log query ----------------------------------------------------------
@bp.get("/audit-logs")
def list_audit_logs():
    require_roles("PlatformAdmin")
    args = request.args
    limit, offset = validate_pagination(args)
    subject_type = args.get("subject_type")
    subject_id = args.get("subject_id")
    action = args.get("action")
    with db.GLOBAL_LOCK:
        logs = list(db.audit_logs)
        if subject_type:
            logs = [l for l in logs if l.get("subject_type") == subject_type]
        if subject_id:
            logs = [l for l in logs if l.get("subject_id") == subject_id]
        if action:
            logs = [l for l in logs if l.get("action") == action]
        # Sort ascending by created_at by default.
        logs.sort(key=lambda l: l.get("created_at", ""))
        total = len(logs)
        page = logs[offset:offset + limit]
        return success_array(
            [_audit_view(l) for l in page],
            limit=limit, offset=offset, total_count=total,
        )


def _audit_view(l):
    return {
        "id": l["id"],
        "subject_type": l["subject_type"],
        "subject_id": l["subject_id"],
        "actor_role": l["actor_role"],
        "actor_id": l["actor_id"],
        "action": l["action"],
        "from_state": l.get("from_state"),
        "to_state": l["to_state"],
        "payload_hash": l["payload_hash"],
        "occurred_at": l["occurred_at"],
        "created_at": l["created_at"],
    }


# Clock -------------------------------------------------------------------
@bp.post("/_clock/advance")
def advance_clock():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    seconds = payload.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise err("ERR_VALIDATION_FAILED", "seconds must be an integer")
    advance(seconds)
    return success_object({"seconds": seconds})
