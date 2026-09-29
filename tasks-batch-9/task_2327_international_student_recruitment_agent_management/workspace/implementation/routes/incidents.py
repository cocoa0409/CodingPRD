"""Integrity incidents and their adjudication (PRD 3.8)."""

from flask import Blueprint

import errors
import serializers
from db import db, base_record, touch, today, creation_order
from errors import fail
from response import obj
from routes.common import auth, listing, need
from services import calc, domain
from validation import (body, fmt_date, opt_id, opt_str, query_enum, query_str, req_date,
                        req_enum, req_id)

bp = Blueprint("incidents", __name__)

OUTCOMES = ("CONFIRM", "DISMISS")


@bp.route("/recruitment/integrity-incidents", methods=["POST"])
def create_incident():
    auth("RecruitmentOfficer", "ComplianceOfficer")
    data = body()
    agency_id = req_id(data, "agency_id")
    category = req_enum(data, "category", calc.INCIDENT_CATEGORIES)
    severity = req_enum(data, "severity", calc.SEVERITIES)
    occurred_on = req_date(data, "occurred_on")
    source = req_enum(data, "source", calc.INCIDENT_SOURCES)
    application_id = opt_id(data, "application_id")
    document_id = opt_id(data, "document_id")

    agency = need(db.agencies, agency_id, errors.ERR_AGENCY_NOT_FOUND)
    if application_id is not None:
        need(db.applications, application_id, errors.ERR_APPLICATION_NOT_FOUND)
    if document_id is not None:
        need(db.documents, document_id, errors.ERR_DOCUMENT_NOT_FOUND)

    if occurred_on > today():
        fail(errors.ERR_FUTURE_DATE_NOT_ALLOWED, "occurred_on may not be in the future")

    record = base_record()
    record.update({
        "agency_id": agency["id"],
        "application_id": application_id,
        "document_id": document_id,
        "category": category,
        "severity": severity,
        "occurred_on": fmt_date(occurred_on),
        "source": source,
        "status": "REPORTED",
        "resolved_by_user_id": None,
    })
    db.incidents[record["id"]] = record
    return obj(serializers.incident(record), 201)


@bp.route("/recruitment/integrity-incidents/<incident_id>", methods=["GET"])
def read_incident(incident_id):
    auth("RecruitmentOfficer", "ComplianceOfficer")
    record = need(db.incidents, incident_id, errors.ERR_INCIDENT_NOT_FOUND)
    return obj(serializers.incident(record))


@bp.route("/recruitment/integrity-incidents", methods=["GET"])
def list_incidents():
    auth("RecruitmentOfficer", "ComplianceOfficer")
    agency_id = query_str("agency_id")
    application_id = query_str("application_id")
    document_id = query_str("document_id")
    category = query_enum("category", calc.INCIDENT_CATEGORIES)
    status = query_enum("status", calc.INCIDENT_STATUSES)

    records = list(db.incidents.values())
    if agency_id is not None:
        records = [r for r in records if r["agency_id"] == agency_id]
    if application_id is not None:
        records = [r for r in records if r["application_id"] == application_id]
    if document_id is not None:
        records = [r for r in records if r["document_id"] == document_id]
    if category is not None:
        records = [r for r in records if r["category"] == category]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return listing(records, serializers.incident)


@bp.route("/recruitment/integrity-incidents/<incident_id>/resolution", methods=["POST"])
def resolve_incident(incident_id):
    user_id, _role = auth("ComplianceOfficer")
    data = body()
    outcome = req_enum(data, "outcome", OUTCOMES)
    opt_str(data, "note")
    incident = need(db.incidents, incident_id, errors.ERR_INCIDENT_NOT_FOUND)

    if incident["status"] != "REPORTED":
        fail(errors.ERR_INVALID_INCIDENT_STATE,
             "Only a REPORTED incident can be adjudicated")

    incident["status"] = "CONFIRMED" if outcome == "CONFIRM" else "DISMISSED"
    incident["resolved_by_user_id"] = user_id
    touch(incident)

    agency = db.agencies.get(incident["agency_id"])
    if agency is not None:
        domain.recompute_risk(agency)
        if outcome == "CONFIRM" and incident["category"] == "PROHIBITED_CLAIM":
            for cert in creation_order(calc.agency_certifications(agency["id"])):
                if cert["module_code"] == "PROHIBITED_CLAIMS" and cert["status"] == "VALID":
                    domain.commit(cert, {
                        "status": "REVOKED",
                        "revoked_reason": "CONFIRMED_PROHIBITED_CLAIM",
                    })
    return obj(serializers.incident(incident))
