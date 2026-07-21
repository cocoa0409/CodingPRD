"""Claimant endpoints (4)."""
from flask import Blueprint, request

import db
import middleware as mw
import response as resp
import serializers as ser
from errors import err

bp = Blueprint("claimants", __name__)

READ_ROLES = (
    "ProgramAdmin", "ClaimsProcessor", "FinanceOfficer", "FraudAnalyst", "Dealer", "Consumer",
)


@bp.post("/api/claimants")
@mw.require("ProgramAdmin")
def create_claimant():
    data = mw.body()
    ctype = mw.as_enum(data, "type", {"DEALER", "CONSUMER"})
    legal_name = mw.as_string(data, "legal_name")
    email = mw.as_string(data, "email")
    mailing_state = mw.as_string(data, "mailing_state", allow_empty=True)

    rec = db.base_record()
    rec.update({
        "type": ctype,
        "legal_name": legal_name,
        "email": email,
        "mailing_state": mailing_state,
        "status": "ACTIVE",
        "fraud_score": 0,
        "duplicate_attempt_count": 0,
        "denied_claim_count": 0,
        "open_claim_count": 0,
    })
    db.claimants[rec["id"]] = rec
    return resp.created(ser.claimant(rec))


@bp.get("/api/claimants/<cid>")
@mw.require(*READ_ROLES)
def read_claimant(cid):
    return resp.ok(ser.claimant(db.get_claimant(cid)))


@bp.get("/api/claimants")
@mw.require("ProgramAdmin", "ClaimsProcessor", "FraudAnalyst")
def list_claimants():
    items = db.by_created(list(db.claimants.values()))
    for field in ("type", "status"):
        value = request.args.get(field)
        if value:
            items = [c for c in items if c[field] == value]
    return resp.paginated(items, ser.claimant)


@bp.post("/api/claimants/<cid>/reinstate")
@mw.require("FraudAnalyst")
def reinstate_claimant(cid):
    claimant = db.get_claimant(cid)
    mw.body()
    if claimant["status"] != "BLOCKED":
        raise err("ERR_INVALID_TRANSITION", "Only a BLOCKED claimant may be reinstated.")
    for case in db.cases_of_claimant(cid):
        if case["status"] in ("OPEN", "UNDER_INVESTIGATION", "PENDING_INFO"):
            raise err("ERR_INVALID_TRANSITION", "A fraud case is still open for this claimant.")
    claimant["status"] = "ACTIVE"
    claimant["fraud_score"] = db.FRAUD_SCORE_MIN
    db.touch(claimant)
    return resp.ok(ser.claimant(claimant))
