"""Conservation easement, inspection and cure endpoints (PRD 3.9)."""

from flask import Blueprint

import serializers
from core import add_days, db, dec, new_record, now, q2, respond_object, touch
from errors import fail
from listing import match, paged
from middleware import ADMIN, ALL_ROLES, MONITOR, require_roles
from services import calc
from services.derive import cure_cascade, freeze_cascade
from validators import body, field_datetime, field_decimal, field_enum, field_str, filter_enum, filter_str

bp = Blueprint("easements", __name__)

RECORDING_STATUSES = ("PENDING_RECORDING", "RECORDED", "AMENDED")
COMPLIANCE_STATUSES = ("COMPLIANT", "VIOLATION_NOTICED", "UNDER_CURE", "CURED", "ESCALATED")
FINDINGS = ("COMPLIANT", "MINOR_VIOLATION", "MAJOR_VIOLATION")
INSPECTION_STATUSES = ("OPEN", "CURE_PENDING", "CURED", "ESCALATED", "CLOSED")
OUTCOMES = ("CURED", "CURE_IN_PROGRESS")
VIOLATION_FINDINGS = ("MINOR_VIOLATION", "MAJOR_VIOLATION")


def get_easement_or_404(easement_id):
    row = db.conservation_easements.get(easement_id)
    if row is None:
        fail("ERR_CONSERVATION_EASEMENT_NOT_FOUND", "conservation easement %s does not exist" % easement_id)
    return row


def get_inspection_or_404(inspection_id):
    row = db.monitoring_inspections.get(inspection_id)
    if row is None:
        fail("ERR_MONITORING_INSPECTION_NOT_FOUND", "monitoring inspection %s does not exist" % inspection_id)
    return row


@bp.get("/tdr/conservation-easements/<easement_id>")
def get_easement(easement_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.conservation_easement(get_easement_or_404(easement_id)))


@bp.get("/tdr/conservation-easements")
def list_easements():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.conservation_easements.values()),
        sending_parcel_id=filter_str("sending_parcel_id"),
        severance_application_id=filter_str("severance_application_id"),
        recording_status=filter_enum("recording_status", RECORDING_STATUSES),
        compliance_status=filter_enum("compliance_status", COMPLIANCE_STATUSES),
    )
    return paged(rows, serializers.conservation_easement)


@bp.post("/tdr/conservation-easements/<easement_id>/inspections")
def create_inspection(easement_id):
    user_id, role = require_roles(MONITOR)
    easement = get_easement_or_404(easement_id)
    data = body()
    inspection_date = field_datetime(data, "inspection_date")
    finding = field_enum(data, "finding", FINDINGS)
    affected_acres = field_decimal(data, "affected_acres", required=False, default="0", minimum=0, places=2)
    note = field_str(data, "note", required=False)

    if inspection_date > now():
        fail("ERR_INVALID_REQUEST", "inspection_date may not be after the current logical clock")

    last = easement["last_inspection_at"]
    if last is not None and inspection_date < add_days(last, calc.INSPECTION_WINDOW_DAYS):
        fail("ERR_INSPECTION_WINDOW_CONFLICT", "inspections must be at least 90 days apart")

    severity = calc.violation_severity(
        finding, affected_acres, easement["restricted_acres"], easement["prior_violation_count"]
    )

    rec = new_record(
        {
            "conservation_easement_id": easement["id"],
            "inspector_user_id": user_id,
            "inspection_date": inspection_date,
            "finding": finding,
            "affected_acres": affected_acres,
            "severity_score": severity,
            "cure_deadline": None,
            "status": "OPEN",
            "cure_verified_at": None,
            "cure_verified_by_user_id": None,
            "escalated_at": None,
            "note": note,
        }
    )

    if finding in VIOLATION_FINDINGS:
        cure_days = calc.cure_days_for(severity)
        rec["cure_deadline"] = add_days(inspection_date, cure_days)
        rec["status"] = "CURE_PENDING"
    else:
        rec["severity_score"] = q2(0)
        rec["cure_deadline"] = None
        rec["status"] = "CLOSED"

    db.monitoring_inspections[rec["id"]] = rec

    easement["last_inspection_at"] = inspection_date
    if finding in VIOLATION_FINDINGS:
        freeze_cascade(easement, rec["cure_deadline"])
    else:
        if easement["compliance_status"] == "CURED":
            easement["compliance_status"] = "COMPLIANT"
        touch(easement)

    return respond_object(serializers.monitoring_inspection(rec), 201)


@bp.get("/tdr/conservation-easements/<easement_id>/inspections")
def list_easement_inspections(easement_id):
    require_roles(*ALL_ROLES)
    get_easement_or_404(easement_id)
    rows = [r for r in db.monitoring_inspections.values() if r["conservation_easement_id"] == easement_id]
    rows = match(
        rows,
        status=filter_enum("status", INSPECTION_STATUSES),
        finding=filter_enum("finding", FINDINGS),
    )
    return paged(rows, serializers.monitoring_inspection)


@bp.get("/tdr/monitoring-inspections/<inspection_id>")
def get_inspection(inspection_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.monitoring_inspection(get_inspection_or_404(inspection_id)))


@bp.post("/tdr/monitoring-inspections/<inspection_id>/cure-verification")
def cure_verification(inspection_id):
    user_id, role = require_roles(MONITOR, ADMIN)
    inspection = get_inspection_or_404(inspection_id)
    data = body()
    outcome = field_enum(data, "outcome", OUTCOMES)
    field_str(data, "verification_note", required=False)

    if user_id == inspection["inspector_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the recording inspector may not verify the cure")

    curable = ("CURE_PENDING", "ESCALATED") if outcome == "CURED" else ("CURE_PENDING",)
    if inspection["status"] not in curable:
        fail("ERR_INSPECTION_NOT_CURABLE", "inspection is %s" % inspection["status"])

    easement = db.conservation_easements.get(inspection["conservation_easement_id"])

    if outcome == "CURE_IN_PROGRESS":
        if easement is not None and easement["compliance_status"] == "VIOLATION_NOTICED":
            easement["compliance_status"] = "UNDER_CURE"
            touch(easement)
        touch(inspection)
    else:
        inspection["status"] = "CURED"
        inspection["cure_verified_at"] = now()
        inspection["cure_verified_by_user_id"] = user_id
        touch(inspection)
        if easement is not None and easement["compliance_status"] in (
            "VIOLATION_NOTICED",
            "UNDER_CURE",
            "ESCALATED",
        ):
            cure_cascade(easement)

    return respond_object(serializers.monitoring_inspection(inspection))
