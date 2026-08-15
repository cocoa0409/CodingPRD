"""Bypass dispute routes (PRD 3.6). Open -> adjudicate (OPENED) -> appeal ->
adjudicate (APPEALED, different officer). OVERTURNED grants credit and runs the
auto-apply sweep."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import (
    body_json,
    ctx,
    list_response,
    need_str,
    ownership_guard,
    require_role,
)
from response import ok
from services.credit import REASON_DISPUTE_OVERTURN, append_ledger, auto_apply_credit
from util import fmt_ts

bp = Blueprint("disputes", __name__)

OPEN_STATUSES = ("OPENED", "UPHELD", "APPEALED")
DISPUTE_WINDOW_DAYS = 30
OUTCOMES = ("UPHELD", "OVERTURNED")


@bp.post("/api/bypass-disputes")
def create_dispute():
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    body = body_json()
    eid = body.get("bypass_event_id")
    event = store.events.get(eid) if isinstance(eid, str) else None
    # Rung 3: ownership resolves through the event
    if event is not None:
        ownership_guard(event["carrier_id"], uid)
    # Rung 4
    if isinstance(eid, str) and event is None:
        raise ApiError("ERR_BYPASS_EVENT_NOT_FOUND", 404, "bypass event id does not exist")
    # Rung 7: carrier must be ACTIVE
    if event is not None:
        carrier = store.carriers.get(event["carrier_id"])
        if carrier is not None and carrier["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CARRIER_NOT_ACTIVE", 409, "carrier must be ACTIVE to open disputes"
            )
    # Rung 11: dispute target checks, in order — disputable decision, then window
    if event is not None:
        if event["decision"] != "PULL_IN":
            raise ApiError(
                "ERR_EVENT_NOT_DISPUTABLE", 422, "only PULL_IN decisions are disputable"
            )
        age_days = (db.today() - event["_approach_dt"].date()).days
        if age_days > DISPUTE_WINDOW_DAYS:
            raise ApiError(
                "ERR_DISPUTE_WINDOW_EXPIRED",
                422,
                "disputes must be opened within 30 days of the approach",
            )
    # Rung 12: fields
    eid = need_str(body, "bypass_event_id")
    reason = need_str(body, "reason")
    claimed = body.get("claimed_credit_cents")
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "claimed_credit_cents must be an integer")
    if not (1 <= claimed <= 100000):
        raise ApiError(
            "ERR_CREDIT_AMOUNT_OUT_OF_RANGE",
            400,
            "claimed_credit_cents must be in 1..100000",
        )
    # Rung 13: at most one open dispute per event
    for d in store.disputes.values():
        if d["bypass_event_id"] == eid and d["status"] in OPEN_STATUSES:
            raise ApiError(
                "ERR_DISPUTE_ALREADY_OPEN",
                409,
                "an open dispute already exists for this bypass event",
            )
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "bypass_event_id": eid,
        "carrier_id": event["carrier_id"],
        "reason": reason,
        "claimed_credit_cents": claimed,
        "status": "OPENED",
        "first_reviewer_id": None,
        "appeal_reviewer_id": None,
        "granted_credit_cents": None,
        "adjudicated_at": None,
        "version": 1,
    }
    db.stamp(rec)
    store.disputes[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/bypass-disputes")
def list_disputes():
    return list_response(
        store.disputes.values(),
        [
            ("carrier_id", "carrier_id"),
            ("bypass_event_id", "bypass_event_id"),
            ("status", "status"),
        ],
    )


@bp.get("/api/bypass-disputes/<disputeId>")
def get_dispute(disputeId):
    ctx()
    d = store.disputes.get(disputeId)
    if d is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "dispute id does not exist")
    return ok(db.public(d), 200)


@bp.post("/api/bypass-disputes/<disputeId>/adjudicate")
def adjudicate_dispute(disputeId):
    uid, role = ctx()
    require_role(role, ("ComplianceOfficer",))
    d = store.disputes.get(disputeId)
    if d is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "dispute id does not exist")
    body = body_json()
    outcome = body.get("outcome")
    # Rung 5: state-machine legality for valid outcomes; rung 12 otherwise
    if isinstance(outcome, str) and outcome in OUTCOMES:
        if d["status"] not in ("OPENED", "APPEALED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"dispute in status {d['status']} cannot be adjudicated",
            )
    else:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "outcome must be one of UPHELD, OVERTURNED"
        )
    # Rung 12: credit bounds for OVERTURNED
    credit_amount = None
    if outcome == "OVERTURNED":
        ca = body.get("credit_amount_cents")
        if ca is not None:
            if isinstance(ca, bool) or not isinstance(ca, int):
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "credit_amount_cents must be an integer"
                )
            if not (1 <= ca <= 100000) or ca > d["claimed_credit_cents"]:
                raise ApiError(
                    "ERR_CREDIT_AMOUNT_OUT_OF_RANGE",
                    400,
                    "credit_amount_cents must be in 1..100000 and no more than claimed_credit_cents",
                )
            credit_amount = ca
    # Rung 14: segregation of duties on appeal review
    if d["status"] == "APPEALED" and uid == d["first_reviewer_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "appeal review must be performed by a different officer than the first review",
        )
    from_state = d["status"]
    now_s = fmt_ts(db.now())
    if outcome == "UPHELD":
        if from_state == "OPENED":
            d["status"] = "UPHELD"
            d["first_reviewer_id"] = uid
        else:
            d["status"] = "UPHELD_FINAL"
            d["appeal_reviewer_id"] = uid
        d["adjudicated_at"] = now_s
        db.bump(d)
    else:  # OVERTURNED: credit grant + auto-apply cascade
        granted = credit_amount if credit_amount is not None else d["claimed_credit_cents"]
        d["granted_credit_cents"] = granted
        d["status"] = "OVERTURNED"
        if from_state == "OPENED":
            d["first_reviewer_id"] = uid
        else:
            d["appeal_reviewer_id"] = uid
        d["adjudicated_at"] = now_s
        db.bump(d)
        carrier = store.carriers.get(d["carrier_id"])
        if carrier is not None:
            append_ledger(carrier, granted, REASON_DISPUTE_OVERTURN, d["id"])
            # Exactly one carrier version increment per adjudication, regardless
            # of how many ledger entries the sweep appends.
            carrier["version"] += 1
            carrier["updated_at"] = now_s
            auto_apply_credit(carrier)
    return ok(db.public(d), 200)


@bp.post("/api/bypass-disputes/<disputeId>/appeal")
def appeal_dispute(disputeId):
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    d = store.disputes.get(disputeId)
    # Rung 3 / 4
    if d is not None:
        ownership_guard(d["carrier_id"], uid)
    if d is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "dispute id does not exist")
    # Rung 5
    if d["status"] != "UPHELD":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            409,
            f"dispute in status {d['status']} cannot be appealed",
        )
    d["status"] = "APPEALED"
    db.bump(d)
    return ok(db.public(d), 200)
