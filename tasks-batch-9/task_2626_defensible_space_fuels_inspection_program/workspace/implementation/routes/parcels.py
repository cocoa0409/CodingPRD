"""Parcel inventory, risk scoring, discretionary notices and certificate intake."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
from auth import auth, owner_must_match
from db import db, insert, sort_created
from errors import fail
from response import created, jsonable, ok, ok_list, touch
from validate import (
    body, get_bool, get_decimal, get_dt, get_enum, get_int, get_str, lookup, page,
    pagination, resolve_fks,
)

bp = Blueprint("parcels", __name__, url_prefix="/fire-district")

ROOF_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C", "NONE")
VEGETATION_TYPES = ("IRRIGATED_LANDSCAPE", "GRASS", "BRUSH", "MIXED_CONIFER")
HAZARD_ZONES = ("MODERATE", "HIGH", "VERY_HIGH")
ACCESS_CONSTRAINTS = ("NONE", "GATED", "LOCKED_GATE", "DOG_ON_SITE")
COMPLIANCE_STATUSES = (
    "PENDING_INSPECTION", "COMPLIANT", "NON_COMPLIANT", "ABATEMENT_PENDING", "EXEMPT",
)
RISK_CLASSES = ("LOW", "MODERATE", "HIGH", "EXTREME")
NOTICE_METHODS = ("IN_PERSON", "CERTIFIED_MAIL", "EMAIL")
REQUESTER_KINDS = ("INSURANCE", "REAL_ESTATE", "LENDER")
SCORING_FIELDS = ("roof_class", "vegetation_type", "slope_pct", "hazard_zone",
                  "access_constraint")


def _parcel(parcel_id):
    return lookup("parcels", parcel_id, "ERR_PARCEL_NOT_FOUND")


@bp.post("/parcels")
def create_parcel():
    auth("ProgramAdmin")
    b = body()
    resolve_fks(b, ["community_id"])
    apn = get_str(b, "apn", allow_empty=False)
    owner_name = get_str(b, "owner_name")
    owner_email = get_str(b, "owner_email")
    situs_address = get_str(b, "situs_address")
    roof_class = get_enum(b, "roof_class", ROOF_CLASSES)
    vegetation_type = get_enum(b, "vegetation_type", VEGETATION_TYPES)
    slope_pct = get_decimal(b, "slope_pct", minimum=0, maximum=100)
    lot_area_sqft = get_int(b, "lot_area_sqft", minimum=1)
    hazard_zone = get_enum(b, "hazard_zone", HAZARD_ZONES)
    access_constraint = get_enum(b, "access_constraint", ACCESS_CONSTRAINTS)
    community_id = get_str(b, "community_id", required=False)
    structure_present = get_bool(b, "structure_present", required=False, default=True)
    owner_hardship_flag = get_bool(b, "owner_hardship_flag", required=False, default=False)
    exemption_flag = get_bool(b, "exemption_flag", required=False, default=False)
    for existing in db.parcels.values():
        if existing["apn"] == apn:
            fail("ERR_APN_ALREADY_REGISTERED", "APN %r is already registered." % apn)

    parcel = insert(db.parcels, {
        "apn": apn,
        "owner_name": owner_name,
        "owner_email": owner_email,
        "situs_address": situs_address,
        "community_id": community_id,
        "structure_present": structure_present,
        "roof_class": roof_class,
        "vegetation_type": vegetation_type,
        "slope_pct": slope_pct,
        "lot_area_sqft": lot_area_sqft,
        "hazard_zone": hazard_zone,
        "access_constraint": access_constraint,
        "owner_hardship_flag": owner_hardship_flag,
        "exemption_flag": exemption_flag,
        "risk_score": None,
        "risk_score_basis": None,
        "risk_class": None,
        "compliance_status": "EXEMPT" if exemption_flag else "PENDING_INSPECTION",
        "open_violation_count": 0,
        "inspection_priority_rank": None,
        "last_passed_inspection_at_utc": None,
        "structure_survival_outcome": None,
        "survival_incident_name": None,
        "survival_incident_date_utc": None,
    })
    domain.rescore_parcel(parcel, basis="INTAKE_PROVISIONAL")
    return created(jsonable(parcel))


@bp.get("/parcels/<parcel_id>")
def read_parcel(parcel_id):
    auth("ProgramAdmin", "FireMarshal", "Inspector", "PropertyOwner", "TitleAgent")
    return ok(jsonable(_parcel(parcel_id)))


@bp.get("/parcels")
def list_parcels():
    auth("ProgramAdmin", "FireMarshal")
    limit, offset = pagination()
    community_id = request.args.get("community_id")
    compliance_status = request.args.get("compliance_status")
    risk_class = request.args.get("risk_class")
    records = sort_created(list(db.parcels.values()))
    if community_id is not None:
        records = [p for p in records if p["community_id"] == community_id]
    if compliance_status is not None:
        records = [p for p in records if p["compliance_status"] == compliance_status]
    if risk_class is not None:
        records = [p for p in records if p["risk_class"] == risk_class]
    return ok_list(
        [jsonable(p) for p in page(records, limit, offset)], limit, offset, len(records)
    )


@bp.patch("/parcels/<parcel_id>")
def update_parcel(parcel_id):
    auth("ProgramAdmin")
    parcel = _parcel(parcel_id)
    b = body()
    resolve_fks(b, ["community_id"])
    expected = get_int(b, "expected_parcel_version")
    updates = {}
    if "access_constraint" in b:
        updates["access_constraint"] = get_enum(b, "access_constraint", ACCESS_CONSTRAINTS)
    if "roof_class" in b:
        updates["roof_class"] = get_enum(b, "roof_class", ROOF_CLASSES)
    if "vegetation_type" in b:
        updates["vegetation_type"] = get_enum(b, "vegetation_type", VEGETATION_TYPES)
    if "slope_pct" in b:
        updates["slope_pct"] = get_decimal(b, "slope_pct", minimum=0, maximum=100)
    if "hazard_zone" in b:
        updates["hazard_zone"] = get_enum(b, "hazard_zone", HAZARD_ZONES)
    if "owner_email" in b:
        updates["owner_email"] = get_str(b, "owner_email")
    if "community_id" in b:
        updates["community_id"] = get_str(b, "community_id", required=False)
    if "owner_hardship_flag" in b:
        updates["owner_hardship_flag"] = get_bool(b, "owner_hardship_flag")
    if "exemption_flag" in b:
        updates["exemption_flag"] = get_bool(b, "exemption_flag")

    if expected != parcel["version"]:
        fail("ERR_STALE_PARCEL_VERSION", "The parcel has moved on since version %s." % expected)

    scoring_changed = any(
        key in updates and updates[key] != parcel[key] for key in SCORING_FIELDS
    )
    parcel.update(updates)
    if scoring_changed:
        domain.rescore_parcel(parcel)
    if updates.get("exemption_flag") is True:
        parcel["compliance_status"] = "EXEMPT"
        parcel["inspection_priority_rank"] = None
        domain.cascade_parcel_posture(parcel)
    touch(parcel)
    return ok(jsonable(parcel))


@bp.post("/parcels/<parcel_id>/survival-outcome")
def survival_outcome(parcel_id):
    auth("ProgramAdmin")
    parcel = _parcel(parcel_id)
    b = body()
    incident_name = get_str(b, "incident_name")
    outcome = get_enum(b, "outcome", ("SURVIVED", "DESTROYED"))
    incident_date = get_dt(b, "incident_date_utc")
    parcel["survival_incident_name"] = incident_name
    parcel["structure_survival_outcome"] = outcome
    parcel["survival_incident_date_utc"] = incident_date
    touch(parcel)
    return ok(jsonable(parcel))


@bp.post("/parcels/<parcel_id>/violation-notices")
def discretionary_notice(parcel_id):
    auth("ProgramAdmin")
    parcel = _parcel(parcel_id)
    b = body()
    resolved = resolve_fks(b, ["inspection_id"])
    inspection = resolved.get("inspection_id")
    if inspection is None:
        fail("ERR_INVALID_REQUEST", "Field 'inspection_id' is required.")
    notice_method = get_enum(b, "notice_method", NOTICE_METHODS)
    expected = get_int(b, "expected_parcel_version")
    if expected != parcel["version"]:
        fail("ERR_STALE_PARCEL_VERSION", "The parcel has moved on since version %s." % expected)

    severity = inspection.get("max_deficiency_severity")
    if severity is None or severity == "NONE":
        severity = "CRITICAL"
    notice = domain.issue_notice(parcel, inspection, severity, notice_method, supersede=True)
    parcel["compliance_status"] = "NON_COMPLIANT"
    touch(parcel)
    domain.cascade_parcel_posture(parcel)
    return created(jsonable(notice))


@bp.post("/parcels/<parcel_id>/compliance-certificates")
def request_certificate(parcel_id):
    auth("TitleAgent", "PropertyOwner")
    parcel = _parcel(parcel_id)
    owner_must_match(parcel["id"])
    b = body()
    requester_kind = get_enum(b, "requester_kind", REQUESTER_KINDS)
    transaction_reference = get_str(b, "transaction_reference")
    certificate = insert(db.certificates, {
        "parcel_id": parcel["id"],
        "requester_kind": requester_kind,
        "transaction_reference": transaction_reference,
        "status": "REQUESTED",
        "decision_note": None,
        "issued_at_utc": None,
        "expires_at_utc": None,
        "snapshot_risk_class": None,
        "snapshot_compliance_status": None,
        "revoked_at_utc": None,
    })
    return created(jsonable(certificate))
