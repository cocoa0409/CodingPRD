"""Dispute endpoints and the dispute -> subrogation escalation."""

from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db
from errors import (err_dispute_open, err_dispute_target, err_invalid_state,
                    err_not_found, err_ownership)
from middleware import require_roles
from serializers import dispute_out
from services.core import (has_open_dispute, has_open_dispute_on_allocation,
                           invoice_status_from_paid, maybe_advance_case_recovery,
                           recompute_debtor_outstanding,
                           recompute_invoice_amount_due, touch)
from util import (get_pagination, new_id, paginate, parse_body, require_enum,
                  require_string, success_envelope)

bp = Blueprint("disputes", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


@bp.route("/damage-recovery/disputes", methods=["POST"])
def create_dispute():
    user_id, role = require_roles("Excavator", "Locator")
    body = parse_body(required_fields=["target_type", "target_id", "reason"])
    target_type = require_enum(body["target_type"], ("FAULT_ALLOCATION", "CLAIM_INVOICE"), "target_type")
    target_id = require_string(body["target_id"], "target_id")
    reason = require_enum(body["reason"], ("FAULT_SHARE", "AMOUNT", "EVIDENCE", "OTHER"), "reason")
    detail = body.get("detail", "")
    if not isinstance(detail, str):
        from errors import err_invalid_request
        raise err_invalid_request("detail must be a string")

    # polymorphic target resolution: type must match the entity it resolves to
    invoice = None
    allocation = None
    if target_type == "CLAIM_INVOICE":
        invoice = db.claim_invoices.get(target_id)
        if invoice is None:
            raise err_dispute_target()
    else:
        allocation = db.fault_allocations.get(target_id)
        if allocation is None:
            raise err_dispute_target()

    # PRD §3.8: ALREADY_OPEN check precedes the state check — a target that
    # already has an open dispute rejects with ERR_DISPUTE_ALREADY_OPEN.
    if invoice is not None:
        if has_open_dispute(invoice["id"]):
            raise err_dispute_open()
        if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            raise err_invalid_state("invoice target must be ISSUED or PARTIALLY_PAID")
    else:
        if has_open_dispute_on_allocation(allocation["id"]):
            raise err_dispute_open()
        if allocation["status"] not in ("PROPOSED", "CONTESTED"):
            raise err_invalid_state("allocation target must be PROPOSED or CONTESTED")

    now = clock.get_current_utc()
    did = new_id()
    dispute = {
        "id": did,
        "target_type": target_type,
        "target_id": target_id,
        "reason": reason,
        "detail": detail,
        "filed_by_type": role.upper(),
        "filed_by_id": user_id,
        "status": "OPEN",
        "rounds": 0,
        "response_deadline_at": now + timedelta(days=14),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.disputes[did] = dispute
    if invoice is not None:
        invoice["status"] = "DISPUTED"
        touch(invoice)
        recompute_debtor_outstanding(invoice["debtor_type"], invoice["debtor_id"])
    return success_envelope(dispute_out(dispute), "object", 201)


@bp.route("/damage-recovery/disputes/<did>", methods=["GET"])
def get_dispute(did):
    require_roles(*ALL_ROLES)
    d = db.disputes.get(did)
    if d is None:
        raise err_not_found("dispute not found")
    return success_envelope(dispute_out(d), "object", 200)


@bp.route("/damage-recovery/disputes", methods=["GET"])
def list_disputes():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.disputes.values())
    target_id = request.args.get("target_id")
    target_type = request.args.get("target_type")
    status = request.args.get("status")
    if target_id is not None:
        items = [d for d in items if d["target_id"] == target_id]
    if target_type is not None:
        items = [d for d in items if d["target_type"] == target_type]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([dispute_out(d) for d in page], "array", 200, meta)


@bp.route("/damage-recovery/disputes/<did>/respond", methods=["POST"])
def respond_dispute(did):
    require_roles("ClaimsAdjuster")
    d = db.disputes.get(did)
    if d is None:
        raise err_not_found("dispute not found")
    if d["status"] not in ("OPEN", "COUNTERED"):
        raise err_invalid_state("dispute is not OPEN or COUNTERED")
    d["status"] = "UNDER_REVIEW"
    d["rounds"] += 1
    d["updated_at"] = clock.get_current_utc()
    d["version"] += 1
    return success_envelope(dispute_out(d), "object", 200)


@bp.route("/damage-recovery/disputes/<did>/counter", methods=["POST"])
def counter_dispute(did):
    user_id, role = require_roles("Excavator", "Locator")
    d = db.disputes.get(did)
    if d is None:
        raise err_not_found("dispute not found")
    if d["status"] != "UNDER_REVIEW":
        raise err_invalid_state("dispute is not UNDER_REVIEW")
    if d["filed_by_id"] != user_id:
        raise err_ownership("caller is not the filer")
    d["status"] = "COUNTERED"
    d["updated_at"] = clock.get_current_utc()
    d["version"] += 1
    return success_envelope(dispute_out(d), "object", 200)


def _invoice_leave_disputed(invoice):
    if has_open_dispute(invoice["id"]):
        return
    if invoice["status"] == "DISPUTED":
        invoice["status"] = invoice_status_from_paid(invoice)
        recompute_invoice_amount_due(invoice)
        touch(invoice)
        recompute_debtor_outstanding(invoice["debtor_type"], invoice["debtor_id"])
        case = db.damage_cases.get(invoice["damage_case_id"])
        if case is not None:
            maybe_advance_case_recovery(case)


@bp.route("/damage-recovery/disputes/<did>/accept-resolution", methods=["POST"])
def accept_resolution(did):
    user_id, role = require_roles("Excavator", "Locator")
    d = db.disputes.get(did)
    if d is None:
        raise err_not_found("dispute not found")
    if d["status"] not in ("UNDER_REVIEW", "COUNTERED"):
        raise err_invalid_state("dispute is not UNDER_REVIEW or COUNTERED")
    if d["filed_by_id"] != user_id:
        raise err_ownership("caller is not the filer")
    d["status"] = "RESOLVED"
    d["updated_at"] = clock.get_current_utc()
    d["version"] += 1
    if d["target_type"] == "CLAIM_INVOICE":
        invoice = db.claim_invoices.get(d["target_id"])
        if invoice is not None:
            _invoice_leave_disputed(invoice)
    return success_envelope(dispute_out(d), "object", 200)


@bp.route("/damage-recovery/disputes/<did>/escalate", methods=["POST"])
def escalate_dispute(did):
    require_roles("ClaimsAdjuster", "RecoveryManager")
    d = db.disputes.get(did)
    if d is None:
        raise err_not_found("dispute not found")
    if d["status"] not in ("OPEN", "UNDER_REVIEW", "COUNTERED"):
        raise err_invalid_state("dispute is not OPEN, UNDER_REVIEW, or COUNTERED")
    now = clock.get_current_utc()
    d["status"] = "ESCALATED"
    d["updated_at"] = now
    d["version"] += 1

    claim_invoice_id = None
    target_party_type = None
    target_party_id = None
    demand_amount = 0
    invoice = None
    if d["target_type"] == "CLAIM_INVOICE":
        invoice = db.claim_invoices.get(d["target_id"])
        if invoice is not None:
            claim_invoice_id = invoice["id"]
            target_party_type = invoice["debtor_type"]
            target_party_id = invoice["debtor_id"]
            recompute_invoice_amount_due(invoice)
            demand_amount = invoice["amount_due_cents"]
    else:
        alloc = db.fault_allocations.get(d["target_id"])
        if alloc is not None:
            # target party: excavator share if present, else first share
            exc = next((s for s in alloc["shares"] if s["party_type"] == "EXCAVATOR"), None)
            share = exc or (alloc["shares"][0] if alloc["shares"] else None)
            if share is not None:
                target_party_type = share["party_type"] if share["party_type"] in ("EXCAVATOR", "LOCATOR") else "EXCAVATOR"
                target_party_id = share["party_id"]

    sid = new_id()
    sub = {
        "id": sid,
        "dispute_id": d["id"],
        "claim_invoice_id": claim_invoice_id,
        "target_party_type": target_party_type,
        "target_party_id": target_party_id,
        "status": "DEMANDED",
        "demand_amount_cents": demand_amount,
        "recovered_cents": 0,
        "legal_cost_cents": 0,
        "owner_share_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.subrogation_cases[sid] = sub
    return success_envelope(dispute_out(d), "object", 200)
