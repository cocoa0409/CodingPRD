"""Certification audits, findings and the corrective-action cycle (PRD 3.7)."""

from flask import Blueprint

import db
import middleware
import response
import serializers
import services
import validate
from db import store
from errors import ApiError
from routes.helpers import paginated

bp = Blueprint("certification", __name__)

FINDING_ACTION_ROLES = {
    "SUBMIT_CAR": ("ForestManager",),
    "REJECT_CAR": ("CertificationAuditor",),
    "VERIFY_CLOSE": ("CertificationAuditor",),
}
OPEN_FINDING_STATES = ("OPEN", "CAR_SUBMITTED")


@bp.post("/certification-audits")
def create_audit():
    middleware.require("CertificationAuditor")
    body = validate.json_body()

    raw_property_id = validate.opt_str_id(body, "property_id")
    prop = None
    if raw_property_id is not None:
        prop = services.find(store.properties, raw_property_id, "ERR_PROPERTY_NOT_FOUND")

    property_id = validate.string(body, "property_id")
    audit_type = validate.enum(body, "audit_type",
                               ("SURVEILLANCE", "RECERTIFICATION"))
    scheduled_raw, _scheduled = validate.date_field(body, "scheduled_date")
    if prop is None:
        prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")

    if prop["status"] not in ("OWNED", "HBU_MARKETED"):
        raise ApiError("ERR_PROPERTY_NOT_OWNED")

    rec = db.base_fields()
    rec.update({
        "property_id": prop["id"],
        "audit_type": audit_type,
        "scheduled_date": scheduled_raw,
        "status": "SCHEDULED",
    })
    store.certification_audits[rec["id"]] = rec
    services.recompute_posture(prop)
    return response.created(serializers.certification_audit(rec))


@bp.get("/certification-audits/<audit_id>")
def get_audit(audit_id):
    middleware.require(*middleware.ANY_ROLE)
    audit = services.find(store.certification_audits, audit_id,
                          "ERR_CERTIFICATION_AUDIT_NOT_FOUND")
    return response.ok(serializers.certification_audit(audit))


@bp.post("/certification-audits/<audit_id>/advance")
def advance_audit(audit_id):
    middleware.require("CertificationAuditor")
    audit = services.find(store.certification_audits, audit_id,
                          "ERR_CERTIFICATION_AUDIT_NOT_FOUND")
    body = validate.json_body()
    action = validate.enum(body, "action", ("START_FIELD_WORK", "ISSUE_FINDINGS",
                                            "SUSPEND", "REINSTATE", "CLOSE"))

    prop = store.properties.get(audit["property_id"])
    counts = services.audit_counts(audit)
    status = audit["status"]

    if action == "START_FIELD_WORK":
        if status != "SCHEDULED" or prop["certification_scheme"] == "NONE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        audit["status"] = "FIELD_WORK"
    elif action == "ISSUE_FINDINGS":
        if status != "FIELD_WORK":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        audit["status"] = "FINDINGS_ISSUED"
    elif action == "SUSPEND":
        if status != "FINDINGS_ISSUED" or counts["open_major_count"] < 2:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        audit["status"] = "SUSPENDED"
    elif action == "REINSTATE":
        if status != "SUSPENDED" or counts["open_major_count"] > 1:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        audit["status"] = "FINDINGS_ISSUED"
    else:  # CLOSE
        if status not in ("FINDINGS_ISSUED", "CAR_REVIEW"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if counts["open_major_count"] != 0 or counts["open_minor_count"] != 0:
            raise ApiError("ERR_OPEN_FINDINGS_BLOCK_CLOSURE")
        audit["status"] = "CLOSED_CONFORMING"

    services.mark(audit)
    # Every advance increments the property's version, whether or not the
    # derived posture actually moves.
    services.mark(prop)
    services.recompute_posture(prop)
    return response.ok(serializers.certification_audit(audit))


@bp.post("/certification-audits/<audit_id>/findings")
def create_finding(audit_id):
    middleware.require("CertificationAuditor")
    audit = services.find(store.certification_audits, audit_id,
                          "ERR_CERTIFICATION_AUDIT_NOT_FOUND")
    body = validate.json_body()
    finding_code = validate.string(body, "finding_code", 1, 40)
    severity = validate.enum(body, "severity", ("MAJOR", "MINOR", "OBSERVATION"))
    indicator_ref = validate.string(body, "indicator_ref", 1, 40)
    due_raw, _due = validate.date_field(body, "due_date")

    if audit["status"] not in ("FIELD_WORK", "FINDINGS_ISSUED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    rec = db.base_fields()
    rec.update({
        "certification_audit_id": audit["id"],
        "finding_code": finding_code,
        "severity": severity,
        "indicator_ref": indicator_ref,
        "due_date": due_raw,
        "status": "OPEN",
        "car_text": None,
        "car_submitted_by_user_id": None,
        "closed_by_user_id": None,
        "rejection_count": 0,
    })
    store.audit_findings[rec["id"]] = rec
    prop = store.properties.get(audit["property_id"])
    if prop is not None:
        services.recompute_posture(prop)
    return response.created(serializers.audit_finding(rec))


@bp.get("/certification-audits/<audit_id>/findings")
def list_findings(audit_id):
    middleware.require(*middleware.ANY_ROLE)
    audit = services.find(store.certification_audits, audit_id,
                          "ERR_CERTIFICATION_AUDIT_NOT_FOUND")
    return paginated(services.rows(store.audit_findings,
                                   certification_audit_id=audit["id"]),
                     serializers.audit_finding)


@bp.get("/audit-findings/<finding_id>")
def get_finding(finding_id):
    middleware.require(*middleware.ANY_ROLE)
    finding = services.find(store.audit_findings, finding_id,
                            "ERR_AUDIT_FINDING_NOT_FOUND")
    return response.ok(serializers.audit_finding(finding))


@bp.post("/audit-findings/<finding_id>/transition")
def transition_finding(finding_id):
    user_id = middleware.require("ForestManager", "CertificationAuditor")
    # Authorization is evaluated at action granularity (PRD 2.1), and it sits
    # above path existence in the precedence order, so the raw action is read
    # from the body before the finding is resolved. An action outside the
    # declared set falls through to the shape check below.
    body = validate.json_body()
    middleware.authorize_action(validate.raw(body, "action"), FINDING_ACTION_ROLES)

    finding = services.find(store.audit_findings, finding_id,
                            "ERR_AUDIT_FINDING_NOT_FOUND")
    action = validate.enum(body, "action",
                           ("SUBMIT_CAR", "REJECT_CAR", "VERIFY_CLOSE"))
    car_text = None
    if action == "SUBMIT_CAR":
        car_text = validate.string(body, "car_text", 1)

    audit = store.certification_audits.get(finding["certification_audit_id"])
    prop = store.properties.get(audit["property_id"]) if audit else None

    if action == "VERIFY_CLOSE" and finding["car_submitted_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if action == "SUBMIT_CAR":
        if finding["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if audit["status"] not in ("FINDINGS_ISSUED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        finding["car_text"] = car_text
        finding["car_submitted_by_user_id"] = user_id
        finding["status"] = "CAR_SUBMITTED"
        services.mark(finding)
        counts = services.audit_counts(audit)
        still_open = any(
            f["status"] == "OPEN"
            for f in store.audit_findings.values()
            if f["certification_audit_id"] == audit["id"])
        if (audit["status"] == "FINDINGS_ISSUED" and not still_open
                and counts["open_major_count"] + counts["open_minor_count"] >= 1):
            audit["status"] = "CAR_REVIEW"
            services.mark(audit)
    elif action == "REJECT_CAR":
        if finding["status"] != "CAR_SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        finding["status"] = "OPEN"
        finding["rejection_count"] += 1
        services.mark(finding)
        if audit["status"] == "CAR_REVIEW":
            audit["status"] = "FINDINGS_ISSUED"
            services.mark(audit)
    else:  # VERIFY_CLOSE
        if finding["status"] != "CAR_SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        finding["status"] = "CLOSED"
        finding["closed_by_user_id"] = user_id
        services.mark(finding)

    if prop is not None:
        services.recompute_posture(prop)
    return response.ok(serializers.audit_finding(finding))
