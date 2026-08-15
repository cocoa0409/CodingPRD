"""Violation intake, adjudication, voluntary self-disclosure, closure."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import auth, get_body, no_unknown, need, v_str, v_enum, find
from response import ok
from services.audit import write_audit

bp = Blueprint("violations", __name__)

SOURCE_TYPES = ("ORDER", "SHIPMENT", "ACCESS_GRANT", "SCREENING", "OTHER")
SEVERITIES = ("MINOR", "MATERIAL", "CRITICAL")

# Polymorphic source_id resolution per source_type
_SOURCE_STORES = {
    "ORDER": (db.ORDERS, "ExportOrder"),
    "SHIPMENT": (db.SHIPMENTS, "Shipment"),
    "ACCESS_GRANT": (db.GRANTS, "AccessGrant"),
    "SCREENING": (db.SCREENING_RESULTS, "ScreeningResult"),
}


@bp.post("/compliance/violations")
def create_violation():
    uid, _ = auth("ComplianceAnalyst", "ComplianceManager", "TradeOpsSpecialist")
    body = get_body()
    # Priority 3: polymorphic source existence (same discipline as FK refs)
    source_type = body.get("source_type")
    source_id = body.get("source_id")
    if source_type in _SOURCE_STORES and isinstance(source_id, str):
        store, label = _SOURCE_STORES[source_type]
        if source_id not in store:
            raise ApiError(ERR_NOT_FOUND, "%s not found: %s" % (label, source_id), 404)
    # Priority 4: request shape
    no_unknown(body, {"source_type", "source_id", "severity", "description"})
    source_type = v_enum(need(body, "source_type"), "source_type", SOURCE_TYPES)
    source_id = v_str(need(body, "source_id"), "source_id")
    severity = v_enum(need(body, "severity"), "severity", SEVERITIES)
    description = v_str(need(body, "description"), "description")
    violation = {
        "source_type": source_type,
        "source_id": source_id,
        "severity": severity,
        "description": description,
        "identified_by_user_id": uid,
        "adjudicated_by_user_id": None,
        "disclosure_reference": None,
        "status": "IDENTIFIED",
    }
    db.stamp_new(violation)
    db.VIOLATIONS[violation["id"]] = violation
    return ok(db.pub(violation), "object", 201)


@bp.get("/compliance/violations/<vid>")
def get_violation(vid):
    auth()
    violation = find(db.VIOLATIONS, vid, "Violation")
    return ok(db.pub(violation), "object", 200)


@bp.post("/compliance/violations/<vid>/advance")
def advance_violation(vid):
    uid, role = auth("ComplianceManager")
    violation = find(db.VIOLATIONS, vid, "Violation")
    body = get_body()
    no_unknown(body, {"event"})
    event = v_enum(
        need(body, "event"), "event", ("START_REVIEW", "SUBSTANTIATE", "DISMISS", "CLOSE")
    )
    if event == "START_REVIEW":
        if violation["status"] != "IDENTIFIED":
            raise ApiError(ERR_INVALID_STATE, "START_REVIEW requires IDENTIFIED", 409)
        violation["status"] = "UNDER_REVIEW"
    elif event in ("SUBSTANTIATE", "DISMISS"):
        if violation["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "%s requires UNDER_REVIEW" % event, 409)
        if uid == violation["identified_by_user_id"]:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                "Adjudicator must differ from the identifying user",
                409,
            )
        violation["status"] = "SUBSTANTIATED" if event == "SUBSTANTIATE" else "UNFOUNDED"
        violation["adjudicated_by_user_id"] = uid
    else:  # CLOSE
        if violation["status"] not in ("DISCLOSED", "UNFOUNDED"):
            raise ApiError(ERR_INVALID_STATE, "CLOSE requires DISCLOSED or UNFOUNDED", 409)
        if uid == violation["identified_by_user_id"]:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                "Closer must differ from the identifying user",
                409,
            )
        violation["status"] = "CLOSED"
        db.touch(violation)
        write_audit(
            "VIOLATION_CLOSED", "Violation", violation["id"], role, uid,
            "Violation %s closed" % violation["id"],
        )
        return ok(db.pub(violation), "object", 200)
    db.touch(violation)
    return ok(db.pub(violation), "object", 200)


@bp.post("/compliance/violations/<vid>/submit-disclosure")
def submit_disclosure(vid):
    uid, role = auth("ComplianceDirector")
    violation = find(db.VIOLATIONS, vid, "Violation")
    if violation["status"] != "SUBSTANTIATED":
        raise ApiError(ERR_INVALID_STATE, "Violation is not SUBSTANTIATED", 409)
    violation["status"] = "DISCLOSED"
    violation["disclosure_reference"] = db.next_vsd_reference()
    db.touch(violation)
    write_audit(
        "VSD_SUBMITTED", "Violation", violation["id"], role, uid,
        "Voluntary self-disclosure %s submitted for violation %s"
        % (violation["disclosure_reference"], violation["id"]),
    )
    return ok(db.pub(violation), "object", 200)
