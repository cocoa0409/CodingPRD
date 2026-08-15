"""Ops-run sweep and the test-driving logical clock (PRD 2.4, 3.9)."""
from datetime import timedelta

from flask import Blueprint

import db
import serialize as ser
from middleware import auth_context, require_role, body, req_dt, touch
from response import success
from services.cascade import (
    agreement_of_certificate, agreement_maybe_delinquent,
    recompute_commitment_aggregates,
)

bp = Blueprint("ops", __name__)


@bp.post("/network/_clock/set_current_utc")
def set_clock_endpoint():
    uid, role = auth_context()
    require_role(role, {"NetworkAdmin"})
    b = body()
    to = req_dt(b, "to_iso8601")
    db.set_clock(to)
    return success({"current_utc": db.now_iso()})


@bp.post("/network/sweeps/run")
def run_sweep():
    uid, role = auth_context()
    require_role(role, {"NetworkAdmin"})
    body()  # tolerate an absent/empty JSON body
    now = db.clock_now()
    marked_late = 0
    escalated = 0
    expired = 0

    # Family 1: SCHEDULED remittances past due_at + grace flip to LATE_UNPAID
    for r in sorted(db.remittances.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if r["status"] != "SCHEDULED":
            continue
        cert = db.certificates[r["certificate_id"]]
        agreement = agreement_of_certificate(cert)
        threshold_at = r["due_at"] + timedelta(days=agreement["grace_period_days"])
        if now > threshold_at:
            r["status"] = "LATE_UNPAID"
            touch("remittance", r)
            agreement["late_remittance_count"] += 1
            touch("agreement", agreement)
            agreement_maybe_delinquent(agreement)
            marked_late += 1

    # Family 2: exceptions OPEN/REJECTED past cure_deadline -> ESCALATED,
    # auto-creating a TRIGGERED repurchase case
    for e in sorted(db.exceptions.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if e["status"] not in ("OPEN", "REJECTED"):
            continue
        if now > e["cure_deadline"]:
            e["status"] = "ESCALATED"
            touch("exception", e)
            db.insert("repurchase_case", {
                "certificate_id": e["certificate_id"],
                "trigger_reason": "DOCUMENTATION_DEFAULT",
                "documentation_exception_id": e["id"],
                "repurchase_price_cents": None,
                "status": "TRIGGERED",
            })
            escalated += 1

    # Family 3: OPEN offerings past close_at with remaining principal -> EXPIRED,
    # rescinding PENDING_DILIGENCE / COMMITTED certificates
    for o in sorted(db.offerings.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if o["status"] != "OPEN":
            continue
        remaining = o["pool_principal_cents"] - ser.offering_committed(o["id"])
        if now > o["close_at"] and remaining > 0:
            o["status"] = "EXPIRED"
            touch("offering", o)
            affected_buyers = set()
            for c in db.certificates.values():
                if c["offering_id"] == o["id"] and c["status"] in ("PENDING_DILIGENCE", "COMMITTED"):
                    c["status"] = "RESCINDED"
                    touch("certificate", c)
                    affected_buyers.add(c["buyer_id"])
            recompute_commitment_aggregates(o, affected_buyers)
            expired += 1

    return success({
        "remittances_marked_late": marked_late,
        "exceptions_escalated": escalated,
        "offerings_expired": expired,
    })
