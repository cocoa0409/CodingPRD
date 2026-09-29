"""Billing disputes, escalation and the deadline sweep (PRD 3.9)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import validation as v
from auth import (ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE,
                  DISPUTE_RESOLUTION_OFFICER, PLATFORM_ADMIN,
                  REVENUE_ASSURANCE_CONTROLLER, authenticate, carrier_of_dispute,
                  scope_check, scope_filter, segregation_check)
from constants import (DISPUTE_DECISIONS, DISPUTE_OPEN_STATUSES,
                       DISPUTE_REASON_CODES, ESCALATION_EXTENSION_DAYS,
                       ESCALATION_LIMIT, SLA_DAYS_BY_REASON)
from dec import q2
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_dispute, get_invoice
from services import reserve
from services.invoicing import (apply_credit, derive_lifecycle,
                                refresh_dispute_dimension)
from store import base_record, db, now, ordered, sort_key, touch

bp = Blueprint("disputes", __name__)

ZERO2 = Decimal("0.00")


@bp.post("/billing-disputes")
def file_dispute():
    actor = authenticate((CARRIER_REPRESENTATIVE,))
    payload = v.body()
    invoice_id = v.string(payload, "invoice_id")
    amount = v.number(payload, "disputed_amount_usd", 2, gt=0)
    reason_code = v.enum(payload, "reason_code", DISPUTE_REASON_CODES)
    supporting_detail = v.string(payload, "supporting_detail", max_len=500)

    invoice = get_invoice(invoice_id)
    scope_check(actor, invoice["carrier_id"])

    if invoice["payment_status"] == "WRITTEN_OFF":
        raise ApiError("ERR_INVOICE_ALREADY_WRITTEN_OFF",
                       "a written-off invoice may not be disputed")
    if invoice["lifecycle_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "only an ISSUED invoice may be disputed")
    if invoice["dispute_deadline_at"] is None or now() > invoice["dispute_deadline_at"]:
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED",
                       "the dispute filing window has closed")
    undisputed = q2(invoice["open_balance_usd"] - invoice["disputed_amount_usd"])
    if amount > undisputed:
        raise ApiError("ERR_DISPUTE_AMOUNT_EXCEEDS_BALANCE",
                       "disputed_amount_usd exceeds the undisputed open balance")

    sla_days = SLA_DAYS_BY_REASON[reason_code]
    filed_at = now()
    dispute = base_record()
    dispute.update({
        "invoice_id": invoice["id"],
        "disputed_amount_usd": amount,
        "reason_code": reason_code,
        "supporting_detail": supporting_detail,
        "status": "SUBMITTED",
        "sla_days": sla_days,
        "filed_at": filed_at,
        "resolution_due_at": filed_at + timedelta(days=sla_days),
        "escalation_round": 0,
        "credited_amount_usd": ZERO2,
        "resolution_note": None,
        "resolved_at": None,
        "resolved_by_user_id": None,
    })
    db.disputes[dispute["id"]] = dispute

    refresh_dispute_dimension(invoice)
    touch(invoice)

    carrier = db.carriers.get(invoice["carrier_id"])
    reserve.recompute(carrier, "BILLING_DISPUTE_SUBMITTED", invoice["id"])
    return object_response(dispute, 201)


@bp.get("/billing-disputes/<dispute_id>")
def read_dispute(dispute_id):
    actor = authenticate((PLATFORM_ADMIN, DISPUTE_RESOLUTION_OFFICER,
                          ACCESS_BILLING_ANALYST, REVENUE_ASSURANCE_CONTROLLER,
                          CARRIER_REPRESENTATIVE))
    dispute = get_dispute(dispute_id)
    scope_check(actor, carrier_of_dispute(dispute))
    return object_response(dispute)


@bp.get("/access-invoices/<invoice_id>/disputes")
def list_invoice_disputes(invoice_id):
    actor = authenticate((PLATFORM_ADMIN, DISPUTE_RESOLUTION_OFFICER,
                          ACCESS_BILLING_ANALYST, REVENUE_ASSURANCE_CONTROLLER,
                          CARRIER_REPRESENTATIVE))
    invoice = get_invoice(invoice_id)
    scope_check(actor, invoice["carrier_id"])
    rows = [d for d in ordered(db.disputes) if d["invoice_id"] == invoice["id"]]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, request.args, lambda r: r)


@bp.get("/billing-disputes")
def list_disputes():
    actor = authenticate((PLATFORM_ADMIN, DISPUTE_RESOLUTION_OFFICER,
                          ACCESS_BILLING_ANALYST, REVENUE_ASSURANCE_CONTROLLER,
                          CARRIER_REPRESENTATIVE))
    rows = ordered(db.disputes)
    invoice_id = request.args.get("invoice_id")
    if invoice_id:
        rows = [r for r in rows if r["invoice_id"] == invoice_id]
    reason_code = request.args.get("reason_code")
    if reason_code:
        rows = [r for r in rows if r["reason_code"] == reason_code]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = scope_filter(actor, rows, carrier_of_dispute)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/billing-disputes/<dispute_id>/acknowledge")
def acknowledge_dispute(dispute_id):
    authenticate((DISPUTE_RESOLUTION_OFFICER,))
    dispute = get_dispute(dispute_id)

    if dispute["status"] not in ("SUBMITTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_DISPUTE_STATE",
                       "only a SUBMITTED or ESCALATED dispute may be acknowledged")
    if now() >= dispute["resolution_due_at"]:
        raise ApiError("ERR_DISPUTE_SLA_EXPIRED", "the resolution SLA has expired")

    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return object_response(dispute)


@bp.post("/billing-disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    actor = authenticate((DISPUTE_RESOLUTION_OFFICER,))
    dispute = get_dispute(dispute_id)
    payload = v.body()
    decision = v.enum(payload, "decision", DISPUTE_DECISIONS)
    credited = v.number(payload, "credited_amount_usd", 2, ge=0)
    resolution_note = v.string(payload, "resolution_note")

    invoice = db.invoices.get(dispute["invoice_id"])
    segregation_check(actor, invoice["issued_by_user_id"])

    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_DISPUTE_STATE",
                       "only an UNDER_REVIEW dispute may be resolved")
    if now() >= dispute["resolution_due_at"]:
        raise ApiError("ERR_DISPUTE_SLA_EXPIRED", "the resolution SLA has expired")

    if decision == "SUSTAINED":
        if not (ZERO2 < credited <= dispute["disputed_amount_usd"]):
            raise ApiError("ERR_INVALID_CREDIT_AMOUNT",
                           "a sustained dispute must credit a positive amount no greater "
                           "than the disputed amount")
    else:
        if credited != ZERO2:
            raise ApiError("ERR_INVALID_CREDIT_AMOUNT",
                           "a denied dispute must credit exactly 0.00")

    dispute["status"] = "RESOLVED_SUSTAINED" if decision == "SUSTAINED" else "RESOLVED_DENIED"
    dispute["credited_amount_usd"] = credited
    dispute["resolution_note"] = resolution_note
    dispute["resolved_at"] = now()
    dispute["resolved_by_user_id"] = actor.user_id
    touch(dispute)

    if decision == "SUSTAINED":
        apply_credit(invoice, credited)
    refresh_dispute_dimension(invoice)
    derive_lifecycle(invoice)
    touch(invoice)

    carrier = db.carriers.get(invoice["carrier_id"])
    reserve.recompute(carrier, "BILLING_DISPUTE_RESOLVED", invoice["id"])
    return object_response(dispute)


@bp.post("/billing-disputes/<dispute_id>/escalate")
def escalate_dispute(dispute_id):
    actor = authenticate((CARRIER_REPRESENTATIVE,))
    dispute = get_dispute(dispute_id)
    payload = v.body()
    note = v.string(payload, "escalation_note")

    invoice = db.invoices.get(dispute["invoice_id"])
    scope_check(actor, invoice["carrier_id"])

    if dispute["status"] != "RESOLVED_DENIED":
        raise ApiError("ERR_INVALID_DISPUTE_STATE",
                       "only a denied dispute may be escalated")
    if dispute["escalation_round"] + 1 > ESCALATION_LIMIT:
        raise ApiError("ERR_ESCALATION_LIMIT_REACHED",
                       "the escalation limit has been reached")

    dispute["status"] = "ESCALATED"
    dispute["escalation_round"] += 1
    dispute["resolution_due_at"] = dispute["resolution_due_at"] + timedelta(
        days=ESCALATION_EXTENSION_DAYS)
    dispute["_escalation_note"] = note
    touch(dispute)

    refresh_dispute_dimension(invoice)
    touch(invoice)

    carrier = db.carriers.get(invoice["carrier_id"])
    reserve.recompute(carrier, "BILLING_DISPUTE_ESCALATED", invoice["id"])
    return object_response(dispute)


@bp.post("/billing-disputes/<dispute_id>/withdraw")
def withdraw_dispute(dispute_id):
    actor = authenticate((CARRIER_REPRESENTATIVE,))
    dispute = get_dispute(dispute_id)
    payload = v.body()
    reason = v.string(payload, "withdrawal_reason")

    invoice = db.invoices.get(dispute["invoice_id"])
    scope_check(actor, invoice["carrier_id"])

    if dispute["status"] not in DISPUTE_OPEN_STATUSES:
        raise ApiError("ERR_INVALID_DISPUTE_STATE",
                       "only an open dispute may be withdrawn")

    dispute["status"] = "WITHDRAWN"
    dispute["resolved_at"] = now()
    dispute["resolved_by_user_id"] = actor.user_id
    dispute["_withdrawal_reason"] = reason
    touch(dispute)

    refresh_dispute_dimension(invoice)
    derive_lifecycle(invoice)
    touch(invoice)

    carrier = db.carriers.get(invoice["carrier_id"])
    reserve.recompute(carrier, "BILLING_DISPUTE_WITHDRAWN", invoice["id"])
    return object_response(dispute)


@bp.post("/dispute-deadline-sweeps")
def sweep_dispute_deadlines():
    authenticate((PLATFORM_ADMIN,))

    candidates = [d for d in db.disputes.values()
                  if d["status"] in DISPUTE_OPEN_STATUSES
                  and now() >= d["resolution_due_at"]]
    candidates.sort(key=lambda d: (d["filed_at"],) + sort_key(d))

    swept_count = 0
    total_credited = ZERO2
    for dispute in candidates:
        invoice = db.invoices.get(dispute["invoice_id"])
        credit = dispute["disputed_amount_usd"]

        dispute["status"] = "RESOLVED_DEEMED_ALLOWED"
        dispute["credited_amount_usd"] = credit
        dispute["resolved_at"] = now()
        dispute["resolved_by_user_id"] = "SYSTEM_SWEEP"
        touch(dispute)

        if invoice is not None:
            apply_credit(invoice, credit)
            refresh_dispute_dimension(invoice)
            derive_lifecycle(invoice)
            touch(invoice)
            carrier = db.carriers.get(invoice["carrier_id"])
            if carrier is not None:
                reserve.recompute(carrier, "DISPUTE_DEADLINE_SWEEP", invoice["id"])

        swept_count += 1
        total_credited = q2(total_credited + credit)

    return object_response({
        "swept_count": swept_count,
        "total_credited_usd": total_credited,
    }, 201)
