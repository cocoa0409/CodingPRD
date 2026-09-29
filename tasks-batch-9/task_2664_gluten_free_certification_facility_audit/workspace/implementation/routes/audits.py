"""Audit scheduling, start, close and reads."""

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import AUDIT_TYPES, READ_AUDITS, ROLE_FIELD_AUDITOR
from errors import ApiError
from services import calc, derive, sweep

bp = Blueprint("audits", __name__)


@bp.post("/gfco/audits")
def create_audit():
    mw.authenticate([ROLE_FIELD_AUDITOR])
    data = mw.body()
    facility_id = mw.req_str(data, "facility_id")
    audit_type = mw.req_enum(data, "audit_type", AUDIT_TYPES)
    onsite_start_at = mw.req_dt(data, "onsite_start_at")
    onsite_end_at = mw.req_dt(data, "onsite_end_at")
    if onsite_end_at <= onsite_start_at:
        mw.bad("onsite_end_at", "must be strictly after onsite_start_at")

    query.fetch("facility", facility_id)

    for other in db.ordered(db.audits):
        if other["facility_id"] != facility_id:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if onsite_start_at < other["onsite_end_at"] \
                and other["onsite_start_at"] < onsite_end_at:
            raise ApiError("ERR_AUDIT_WINDOW_CONFLICT")

    row = db.insert(
        db.audits,
        {
            "facility_id": facility_id,
            "audit_type": audit_type,
            "onsite_start_at": onsite_start_at,
            "onsite_end_at": onsite_end_at,
            "status": "SCHEDULED",
            "lead_auditor_user_id": None,
            "closed_by_user_id": None,
            "shared_equipment_verified": False,
            "air_handling_verified": False,
            "sanitation_validation_reviewed": False,
            "provisional_score": None,
            "final_score": None,
            "finding_count": 0,
            "critical_finding_count": 0,
            "closed_on": None,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/audits/<audit_id>")
def get_audit(audit_id):
    mw.authenticate(READ_AUDITS)
    return response.ok(response.serialize(query.fetch("audit", audit_id)))


@bp.get("/gfco/audits")
def list_audits():
    mw.authenticate(READ_AUDITS)
    return query.listing(
        db.audits,
        {
            "facility_id": query.arg("facility_id"),
            "status": query.arg("status"),
            "audit_type": query.arg("audit_type"),
        },
    )


@bp.post("/gfco/audits/<audit_id>/start")
def start_audit(audit_id):
    user_id, _ = mw.authenticate([ROLE_FIELD_AUDITOR])
    mw.body()
    audit = query.fetch("audit", audit_id)
    if audit["status"] != "SCHEDULED" or clock.now() < audit["onsite_start_at"]:
        raise ApiError("ERR_INVALID_AUDIT_STATE")
    audit["status"] = "IN_PROGRESS"
    audit["lead_auditor_user_id"] = user_id
    db.touch(audit)
    return response.ok(response.serialize(audit))


@bp.post("/gfco/audits/<audit_id>/close")
def close_audit(audit_id):
    user_id, _ = mw.authenticate([ROLE_FIELD_AUDITOR])
    data = mw.body()
    shared_equipment_verified = mw.req_bool(data, "shared_equipment_verified")
    air_handling_verified = mw.req_bool(data, "air_handling_verified")
    sanitation_reviewed = mw.req_bool(data, "sanitation_validation_reviewed")
    audit = query.fetch("audit", audit_id)

    now = clock.now()
    if audit["status"] != "IN_PROGRESS" or now < audit["onsite_end_at"]:
        raise ApiError("ERR_INVALID_AUDIT_STATE")

    facility = db.facilities.get(audit["facility_id"])
    if facility is None \
            or facility["sanitation_validation_status"] != "VALIDATED":
        raise ApiError("ERR_FACILITY_SANITATION_NOT_VALIDATED")

    findings = derive.nonconformances_for_audit(audit["id"])
    onsite = [
        nc for nc in findings if nc["created_at"] <= audit["onsite_end_at"]
    ]
    provisional = calc.provisional_onsite_score(onsite)
    critical_count = sum(1 for nc in findings if nc["severity"] == "CRITICAL")
    outcome = calc.audit_outcome(provisional, critical_count)

    if outcome == "CLOSED_PASS" and facility["shared_equipment_present"] \
            and not shared_equipment_verified:
        outcome = "CLOSED_CONDITIONAL"

    audit["shared_equipment_verified"] = shared_equipment_verified
    audit["air_handling_verified"] = air_handling_verified
    audit["sanitation_validation_reviewed"] = sanitation_reviewed
    audit["status"] = outcome
    audit["provisional_score"] = provisional
    audit["final_score"] = provisional
    audit["finding_count"] = len(findings)
    audit["critical_finding_count"] = critical_count
    audit["closed_by_user_id"] = user_id
    audit["closed_on"] = now
    db.touch(audit)

    derive.recompute_facility_audit_outcome(facility)

    if outcome == "CLOSED_FAIL":
        _suspend_facility_certificates(facility["id"])
    elif audit["audit_type"] == "SURVEILLANCE":
        sweep.rebase_surveillance_for_facility(facility["id"])

    return response.ok(response.serialize(audit))


def _suspend_facility_certificates(facility_id):
    product_ids = [
        product["id"]
        for product in db.ordered(db.products)
        if product["facility_id"] == facility_id
    ]
    for product_id in product_ids:
        derive.suspend_certificates_for_product(
            product_id, "CRITICAL_NONCONFORMANCE"
        )
