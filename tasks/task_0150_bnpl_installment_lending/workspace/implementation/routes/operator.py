"""Operator endpoints: clock advance and autopay sweep (PRD §3.6, §3.7).

These endpoints are restricted to the Servicer role. They drive time-dependent
behavior (due dates, late fees, delinquency, settlement hold) and the autopay
batch charge.
"""
from datetime import datetime, timezone, timedelta

from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services import engine
from services import calculations as calc
from services.engine import touch, _parse_iso
from routes.common import get_json_body
from routes.payments import make_payment

bp = Blueprint("operator", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_role(role, {"Servicer"})
    body = get_json_body()

    to_iso = body.get("to_iso8601")
    if not to_iso or not isinstance(to_iso, str):
        raise err("ERR_INVALID_REQUEST", "Missing required field 'to_iso8601'.")
    try:
        new_now = _parse_iso(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")

    db.set_now(new_now)

    transitioned = []
    # SCHEDULED installments past due+GRACE_DAYS -> LATE with a late fee assessed once.
    for inst in db.installments.values():
        if inst["status"] != "SCHEDULED":
            continue
        loan = db.loans.get(inst["loan_id"])
        if loan is None or loan["status"] != "ACTIVE":
            continue
        due = _parse_iso(inst["due_date"])
        if new_now > (due + timedelta(days=calc.GRACE_DAYS)):
            outstanding = inst["amount_due_cents"] - inst["amount_paid_cents"]
            inst["status"] = "LATE"
            inst["late_fee_cents"] = calc.late_fee_for(outstanding)
            touch(inst)
            transitioned.append(inst["id"])

    # Recompute delinquency for all ACTIVE loans.
    for loan in db.loans.values():
        if loan["status"] == "ACTIVE":
            engine.recompute_posture(loan)

    data = {
        "now": db.iso_millis(new_now),
        "transitioned_installment_ids": transitioned,
    }
    return success(data, status=200)


@bp.route("/_servicer/run_autopay_sweep", methods=["POST"])
def run_autopay_sweep():
    _uid, role = authenticate()
    require_role(role, {"Servicer"})

    now = db.now()
    charged_count = 0
    payment_ids = []

    # Deterministic order: by mandate creation order.
    mandates = sorted(db.autopay_mandates.values(), key=lambda m: m["_seq"])
    for mandate in mandates:
        if mandate["status"] != "ENABLED":
            continue
        loan = db.loans.get(mandate["loan_id"])
        if loan is None or loan["status"] != "ACTIVE":
            continue
        # Oldest-due-first open installment whose due_date <= now.
        open_insts = [i for i in engine.loan_installments(loan["id"])
                      if i["status"] in ("SCHEDULED", "LATE")]
        open_insts.sort(key=lambda i: (i["sequence_no"], i["_seq"]))
        next_due = None
        for inst in open_insts:
            due = _parse_iso(inst["due_date"])
            if due <= now:
                next_due = inst
                break
        if next_due is None:
            continue
        # Charge the next due installment's outstanding amount.
        amount = next_due["amount_due_cents"] - next_due["amount_paid_cents"]
        if amount <= 0:
            continue
        payment = make_payment(loan, amount, "AUTOPAY")
        charged_count += 1
        payment_ids.append(payment["id"])

    return success({"charged_count": charged_count, "payment_ids": payment_ids},
                   status=200)
