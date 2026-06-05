"""Appeal endpoints: submit, read, decide (cascades into citation + balance)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_STATE
from middleware import get_json_body, require_auth
from response import ok_object
from services import recompute
from services.common import (
    lookup,
    require_enum,
    require_owner_motorist,
    require_string,
)
from services.serialize import public

bp = Blueprint("appeals", __name__)

DECISIONS = {"UPHELD", "DISMISSED"}


@bp.post("/parking/appeals")
def submit_appeal():
    require_auth(["Motorist"])()
    body = get_json_body()
    citation_id = require_string(body, "citation_id")
    motorist_id = require_string(body, "motorist_id")
    reason = require_string(body, "reason")

    citation = lookup(db.citations, citation_id)
    lookup(db.motorists, motorist_id)

    require_owner_motorist(motorist_id)

    a = db.stamp_common(
        {
            "citation_id": citation_id,
            "motorist_id": motorist_id,
            "reason": reason,
            "status": "SUBMITTED",
        }
    )
    db.appeals[a["id"]] = a
    return ok_object(public(a), 201)


@bp.get("/parking/appeals/<aid>")
def read_appeal(aid):
    require_auth(["FacilityAdmin", "EnforcementOfficer", "Motorist"])()
    a = lookup(db.appeals, aid)
    return ok_object(public(a), 200)


@bp.post("/parking/appeals/<aid>/decide")
def decide_appeal(aid):
    require_auth(["EnforcementOfficer"])()
    a = lookup(db.appeals, aid)
    body = get_json_body()
    decision = require_enum(body, "decision", DECISIONS, required=True)

    # state (priority 4): appeal SUBMITTED and citation ISSUED.
    if a["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Appeal is not SUBMITTED")
    citation = db.citations.get(a["citation_id"])
    if citation is None or citation["status"] != "ISSUED":
        raise APIError(ERR_INVALID_STATE, 409, "Linked citation is not ISSUED")

    if decision == "UPHELD":
        # appeal UPHELD -> citation DISMISSED -> balance down (cascade T3).
        a["status"] = "UPHELD"
        db.bump(a)
        citation["status"] = "DISMISSED"
        db.bump(citation)
        if citation.get("motorist_id") is not None:
            motorist = db.motorists.get(citation["motorist_id"])
            if motorist is not None:
                recompute.recompute_motorist_balance(motorist, bump=True)
    else:
        # appeal DISMISSED -> citation UPHELD, balance unchanged.
        a["status"] = "DISMISSED"
        db.bump(a)
        citation["status"] = "UPHELD"
        db.bump(citation)
        # Citation still counts (ISSUED -> UPHELD), balance unchanged; but the
        # balance recompute is idempotent and harmless. Per PRD §3.9 it is
        # unchanged, so we still recompute to keep the field authoritative.
        if citation.get("motorist_id") is not None:
            motorist = db.motorists.get(citation["motorist_id"])
            if motorist is not None:
                recompute.recompute_motorist_balance(motorist, bump=True)

    return ok_object(public(a), 200)
