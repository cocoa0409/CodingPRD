"""Consumer complaints: filing, triage with recall scoping, investigation."""

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import (
    COMPLAINT_EVIDENCE,
    READ_CONSUMER_COMPLAINTS,
    ROLE_CERTIFICATION_REVIEWER,
    ROLE_PROGRAM_ADMIN,
    SYMPTOM_SEVERITIES,
)
from errors import ApiError
from services import calc, nc as nc_service

bp = Blueprint("consumer_complaints", __name__)

_TRIAGE_PRIORITY = {
    "SEVERE": "P1",
    "ANAPHYLAXIS": "P1",
    "MODERATE": "P2",
    "MILD": "P3",
}


@bp.post("/gfco/consumer-complaints")
def file_complaint():
    mw.authenticate([ROLE_PROGRAM_ADMIN])
    data = mw.body()
    certificate_id = mw.req_str(data, "certificate_id")
    exposure_date = mw.req_dt(data, "exposure_date")
    symptom_severity = mw.req_enum(data, "symptom_severity", SYMPTOM_SEVERITIES)
    lot_code = mw.opt_str(data, "lot_code")

    cert = query.fetch("certificate", certificate_id)
    if cert["status"] in ("REVOKED", "EXPIRED"):
        raise ApiError("ERR_CERTIFICATE_TERMINAL")

    row = db.insert(
        db.consumer_complaints,
        {
            "certificate_id": certificate_id,
            "lot_code": lot_code,
            "exposure_date": exposure_date,
            "symptom_severity": symptom_severity,
            "reported_on": clock.now(),
            "status": "RECEIVED",
            "triage_priority": None,
            "investigated_by_user_id": None,
            "outcome_evidence": None,
            "recall_action": "NONE",
            "recall_scope_lot_codes": [],
            "closed_on": None,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/consumer-complaints/<complaint_id>")
def get_complaint(complaint_id):
    mw.authenticate(READ_CONSUMER_COMPLAINTS)
    return response.ok(response.serialize(query.fetch("complaint", complaint_id)))


@bp.get("/gfco/consumer-complaints")
def list_complaints():
    mw.authenticate(READ_CONSUMER_COMPLAINTS)
    return query.listing(
        db.consumer_complaints,
        {
            "certificate_id": query.arg("certificate_id"),
            "status": query.arg("status"),
            "triage_priority": query.arg("triage_priority"),
        },
    )


@bp.post("/gfco/consumer-complaints/<complaint_id>/triage")
def triage(complaint_id):
    mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    mw.body()
    complaint = query.fetch("complaint", complaint_id)
    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE")

    complaint["status"] = "INVESTIGATING"
    complaint["triage_priority"] = _TRIAGE_PRIORITY[complaint["symptom_severity"]]

    cert = db.certificates.get(complaint["certificate_id"])
    candidates = []
    if cert is not None:
        candidates = [
            lot
            for lot in db.ordered(db.lot_tests)
            if lot["product_id"] == cert["product_id"]
        ]
    selected, action = calc.recall_scope(candidates, complaint["exposure_date"])
    complaint["recall_scope_lot_codes"] = [lot["lot_code"] for lot in selected]
    complaint["recall_action"] = action
    db.touch(complaint)
    for lot in selected:
        if not lot["in_recall_scope"]:
            lot["in_recall_scope"] = True
            db.touch(lot)
    return response.ok(response.serialize(complaint))


@bp.post("/gfco/consumer-complaints/<complaint_id>/investigation-outcome")
def investigation_outcome(complaint_id):
    user_id, _ = mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    outcome = mw.req_enum(data, "outcome", ("SUBSTANTIATED", "UNSUBSTANTIATED"))
    outcome_evidence = mw.req_enum(data, "outcome_evidence", COMPLAINT_EVIDENCE)
    complaint = query.fetch("complaint", complaint_id)
    if complaint["status"] != "INVESTIGATING":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE")

    complaint["investigated_by_user_id"] = user_id
    complaint["outcome_evidence"] = outcome_evidence

    if outcome == "UNSUBSTANTIATED":
        complaint["status"] = "UNSUBSTANTIATED"
        db.touch(complaint)
        return response.ok(response.serialize(complaint))

    if complaint["recall_action"] == "ADVISORY_ONLY":
        complaint["status"] = "SUBSTANTIATED"
    else:
        complaint["status"] = "RECALL_COORDINATION"
    db.touch(complaint)

    cert = db.certificates.get(complaint["certificate_id"])
    if cert is not None:
        severity = (
            "CRITICAL"
            if complaint["symptom_severity"] in ("SEVERE", "ANAPHYLAXIS")
            else "MAJOR"
        )
        nc_service.create(
            applicant_id=cert["applicant_id"],
            source_type="COMPLAINT",
            category="THRESHOLD_EXCEEDANCE",
            severity=severity,
            description="Substantiated consumer complaint %s" % complaint["id"],
            raised_by_user_id=user_id,
            complaint_id=complaint["id"],
            suspension_reason="SUBSTANTIATED_COMPLAINT",
        )
    return response.ok(response.serialize(complaint))
