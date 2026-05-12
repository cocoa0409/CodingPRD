"""Settlement ledger and payout endpoints."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now, iso, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.validation import get_body, require_str, optional_str


bp = Blueprint("settlement", __name__)


def _public(d: dict) -> dict:
    return db.public(d)


@bp.route("/counseling/settlement-ledger", methods=["GET"])
@require_auth(roles={"Counselor", "PlatformAdmin"})
def list_ledger():
    limit, offset = get_pagination()
    counselor_id = request.args.get("counselor_id")
    appointment_id = request.args.get("appointment_id")
    direction = request.args.get("direction")

    items = list(db.settlement_ledger.values())
    # Counselor may only see rows linked to own appointments
    if g.user_role == "Counselor":
        items = [
            r for r in items
            if (db.appointments.get(r["appointment_id"]) is not None
                and db.appointments[r["appointment_id"]]["counselor_id"] == g.user_id)
        ]
    if counselor_id:
        items = [
            r for r in items
            if (db.appointments.get(r["appointment_id"]) is not None
                and db.appointments[r["appointment_id"]]["counselor_id"] == counselor_id)
        ]
    if appointment_id:
        items = [r for r in items if r["appointment_id"] == appointment_id]
    if direction:
        items = [r for r in items if r["direction"] == direction]

    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_public(r) for r in page], limit, offset, total)


@bp.route("/counseling/payouts", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_payout():
    body = get_body()
    counselor_id = require_str(body, "counselor_id")
    period_start_at = require_str(body, "period_start_at")
    period_end_at = require_str(body, "period_end_at")

    counselor = db.counselors.get(counselor_id)
    if counselor is None:
        raise err("ERR_REF_NOT_FOUND", f"counselor_id {counselor_id} not found")
    if counselor["status"] == "DISQUALIFIED":
        raise err("ERR_COUNSELOR_DISQUALIFIED",
                  "Cannot create payout for DISQUALIFIED counselor")

    try:
        ps = parse_iso(period_start_at)
        pe = parse_iso(period_end_at)
    except ValueError:
        raise err("ERR_VALIDATION", "period bounds must be ISO 8601")
    if pe <= ps:
        raise err("ERR_VALIDATION", "period_end_at must be > period_start_at")

    # Window-overlap check vs PENDING/PAID payouts for same counselor
    for p in db.payouts.values():
        if p["counselor_id"] != counselor_id:
            continue
        if p["status"] not in ("PENDING", "PAID"):
            continue
        ops = parse_iso(p["period_start_at"])
        ope = parse_iso(p["period_end_at"])
        if ps < ope and ops < pe:
            raise err("ERR_PAYOUT_WINDOW_OVERLAP",
                      "Window overlaps existing payout")

    # Aggregate eligible ledger rows
    total_share = 0
    total_tax = 0
    rolled_ids = []
    for r in db.settlement_ledger.values():
        if r.get("payout_id") is not None:
            continue
        appt = db.appointments.get(r["appointment_id"])
        if appt is None:
            continue
        if appt["counselor_id"] != counselor_id:
            continue
        if appt["status"] not in ("COMPLETED", "NO_SHOW", "CANCELLED"):
            continue
        ended = appt.get("ended_at") or appt.get("cancellation_reason") and appt.get("updated_at")
        # use ended_at when available, else updated_at as a proxy for non-completed
        ts = parse_iso(appt.get("ended_at") or appt.get("updated_at") or appt["created_at"])
        if ts < ps or ts >= pe:
            continue
        total_share += int(r["counselor_share_cents"])
        total_tax += int(r["tax_cents"])
        rolled_ids.append(r["id"])

    payout = {
        "counselor_id": counselor_id,
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "total_counselor_share_cents": total_share,
        "total_tax_cents": total_tax,
        "status": "PENDING",
        "paid_at": None,
    }
    db.stamp_create(payout, common_fields=True)
    db.payouts[payout["id"]] = payout

    # Atomically attach payout_id to ledger rows
    for rid in rolled_ids:
        db.settlement_ledger[rid]["payout_id"] = payout["id"]

    return success(_public(payout), 201)


@bp.route("/counseling/payouts/<id>/mark-paid", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def mark_paid(id):
    p = db.payouts.get(id)
    if p is None:
        raise err("ERR_NOT_FOUND", f"Payout {id} not found")
    if p["status"] != "PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Payout status {p['status']} cannot be marked paid")
    counselor = db.counselors[p["counselor_id"]]
    if counselor["status"] == "DISQUALIFIED":
        raise err("ERR_COUNSELOR_DISQUALIFIED",
                  "Cannot mark payout paid for DISQUALIFIED counselor")
    p["status"] = "PAID"
    p["paid_at"] = iso(now())
    db.stamp_update(p)
    return success(_public(p))


@bp.route("/counseling/payouts/<id>/reverse", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def reverse_payout(id):
    p = db.payouts.get(id)
    if p is None:
        raise err("ERR_NOT_FOUND", f"Payout {id} not found")
    if p["status"] != "PAID":
        raise err("ERR_INVALID_STATE",
                  f"Payout status {p['status']} cannot be reversed")
    paid_at = parse_iso(p["paid_at"])
    if now() >= paid_at + timedelta(days=7):
        raise err("ERR_INVALID_STATE",
                  "Reverse window of 7 days has closed")
    body = get_body()
    optional_str(body, "reason")
    p["status"] = "REVERSED"
    db.stamp_update(p)
    # Detach ledger rows so they can be re-rolled
    for r in db.settlement_ledger.values():
        if r.get("payout_id") == p["id"]:
            r["payout_id"] = None
    return success(_public(p))


@bp.route("/counseling/payouts", methods=["GET"])
@require_auth(roles={"Counselor", "PlatformAdmin"})
def list_payouts():
    limit, offset = get_pagination()
    counselor_id = request.args.get("counselor_id")
    status = request.args.get("status")

    items = list(db.payouts.values())
    if g.user_role == "Counselor":
        items = [p for p in items if p["counselor_id"] == g.user_id]
    if counselor_id:
        items = [p for p in items if p["counselor_id"] == counselor_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_public(p) for p in page], limit, offset, total)
