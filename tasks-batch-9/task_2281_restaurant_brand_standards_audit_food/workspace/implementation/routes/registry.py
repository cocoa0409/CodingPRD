"""Registry surface: brands, franchisees, auditors and locations."""

from decimal import Decimal

from flask import Blueprint

import db
import serializers
from common import touch
from errors import fail
from middleware import (
    begin,
    body,
    filter_enum,
    filter_value,
    listing,
    opt_int,
    opt_str,
    req_dt,
    req_enum,
    req_id,
    req_str,
    require,
    resolve_identity,
)
from response import object_response
from services import calc, cascade

bp = Blueprint("registry", __name__)

REGION_CODES = ("NORTHEAST", "SOUTHEAST", "MIDWEST", "WEST")
AGREEMENT_STATUSES = (
    "GOOD_STANDING",
    "NOTICE_OF_DEFAULT",
    "CURE_PERIOD",
    "TERMINATION_RECOMMENDED",
)
INSPECTION_STATUSES = ("RECORDED", "DISREGARDED")


def _is_upper_alnum(value):
    return all(("A" <= ch <= "Z") or ("0" <= ch <= "9") for ch in value)


# --------------------------------------------------------------------------
# Brands
# --------------------------------------------------------------------------

@bp.route("/brands", methods=["POST"])
def create_brand():
    begin("BrandAdmin")
    resolve_identity()
    payload = body()
    name = req_str(payload, "name", 1, 120)
    brand_code = req_str(payload, "brand_code", 2, 8)
    if not _is_upper_alnum(brand_code):
        fail("ERR_INVALID_REQUEST", "Field 'brand_code' must be uppercase alphanumeric.")
    ratio = opt_int(payload, "unannounced_min_ratio_pct", 0, 100, 40)

    for existing in db.store.brands.values():
        if existing["brand_code"] == brand_code:
            fail("ERR_DUPLICATE_RESOURCE_CODE", "brand_code is already registered.")

    record = db.new_record()
    record.update({
        "name": name,
        "brand_code": brand_code,
        "unannounced_min_ratio_pct": ratio,
        "brand_risk_index": Decimal("0.00"),
        "brand_risk_tier": "BASELINE",
        "location_count": 0,
        "default_location_count": 0,
    })
    db.store.brands[record["id"]] = record
    return object_response(serializers.brand(record), 201)


@bp.route("/brands/<brand_id>", methods=["GET"])
def read_brand(brand_id):
    begin("BrandAdmin", "ComplianceIntegrator")
    brand = require("brand", brand_id)
    resolve_identity()
    return object_response(serializers.brand(brand))


@bp.route("/brands/<brand_id>/risk-index", methods=["GET"])
def read_brand_risk_index(brand_id):
    begin("BrandAdmin")
    brand = require("brand", brand_id)
    resolve_identity()
    components = cascade.recompute_brand_risk(brand)
    return object_response({
        "brand_id": brand["id"],
        "brand_risk_index": float(components["brand_risk_index"]),
        "brand_risk_tier": components["brand_risk_tier"],
        "average_standing_score": float(components["average_standing_score"]),
        "rated_location_count": components["rated_location_count"],
        "open_critical_action_count": components["open_critical_action_count"],
        "default_location_count": components["default_location_count"],
        "fail_grade_surcharge_applied": components["fail_grade_surcharge_applied"],
    })


# --------------------------------------------------------------------------
# Franchisees
# --------------------------------------------------------------------------

@bp.route("/franchisees", methods=["POST"])
def create_franchisee():
    begin("BrandAdmin")
    resolve_identity()
    payload = body()
    brand_id = req_id(payload, "brand_id")
    legal_name = req_str(payload, "legal_name", 1, 160)
    contact_email = req_str(payload, "contact_email", 1)
    if "@" not in contact_email:
        fail("ERR_INVALID_REQUEST", "Field 'contact_email' must contain '@'.")
    signed_at = req_dt(payload, "agreement_signed_at")

    require("brand", brand_id)

    record = db.new_record()
    record.update({
        "brand_id": brand_id,
        "legal_name": legal_name,
        "contact_email": contact_email,
        "agreement_signed_at": signed_at,
        "open_default_location_count": 0,
        "termination_recommended": False,
    })
    db.store.franchisees[record["id"]] = record
    return object_response(serializers.franchisee(record), 201)


@bp.route("/franchisees/<franchisee_id>", methods=["GET"])
def read_franchisee(franchisee_id):
    begin("BrandAdmin", "Franchisee")
    franchisee = require("franchisee", franchisee_id)
    resolve_identity()
    return object_response(serializers.franchisee(franchisee))


@bp.route("/franchisees", methods=["GET"])
def list_franchisees():
    begin("BrandAdmin")
    resolve_identity()
    brand_id = filter_value("brand_id")
    records = [
        f for f in db.store.franchisees.values()
        if brand_id is None or f["brand_id"] == brand_id
    ]
    return listing(records, serializers.franchisee)


# --------------------------------------------------------------------------
# Auditors
# --------------------------------------------------------------------------

@bp.route("/auditors", methods=["POST"])
def create_auditor():
    begin("BrandAdmin")
    resolve_identity()
    payload = body()
    full_name = req_str(payload, "full_name", 1, 120)
    employee_code = req_str(payload, "employee_code", 3, 12)

    for existing in db.store.auditors.values():
        if existing["employee_code"] == employee_code:
            fail("ERR_DUPLICATE_RESOURCE_CODE", "employee_code is already registered.")

    record = db.new_record()
    record.update({
        "full_name": full_name,
        "employee_code": employee_code,
        "status": "PROVISIONAL",
        "certification_period_start": None,
        "reliability_score": Decimal("70.00"),
        "suspension_reason": None,
        "finalized_visit_count": 0,
    })
    db.store.auditors[record["id"]] = record
    return object_response(serializers.auditor(record), 201)


@bp.route("/auditors/<auditor_id>", methods=["GET"])
def read_auditor(auditor_id):
    begin("BrandAdmin", "Auditor", "CalibrationReviewer")
    auditor = require("auditor", auditor_id)
    resolve_identity()
    return object_response(serializers.auditor(auditor))


@bp.route("/auditors/<auditor_id>/certify", methods=["POST"])
def certify_auditor(auditor_id):
    begin("BrandAdmin")
    auditor = require("auditor", auditor_id)
    resolve_identity()
    body()
    if auditor["status"] == "CERTIFIED":
        fail("ERR_INVALID_AUDITOR_STATE", "The auditor is already CERTIFIED.")
    score = calc.certification_review_reliability(auditor)
    if score < calc.CERTIFICATION_FLOOR:
        fail(
            "ERR_RELIABILITY_BELOW_FLOOR",
            "Certification-review reliability %s is below the 70.00 floor." % score,
        )
    auditor["status"] = "CERTIFIED"
    auditor["certification_period_start"] = db.store.clock
    auditor["suspension_reason"] = None
    touch(auditor)
    return object_response(serializers.auditor(auditor))


@bp.route("/auditors/<auditor_id>/suspend", methods=["POST"])
def suspend_auditor(auditor_id):
    begin("BrandAdmin")
    auditor = require("auditor", auditor_id)
    resolve_identity()
    payload = body()
    opt_str(payload, "note", 0, 1000)
    if auditor["status"] == "SUSPENDED":
        fail("ERR_INVALID_AUDITOR_STATE", "The auditor is already SUSPENDED.")
    cascade.suspend_auditor(auditor, "MANUAL_REVIEW")
    return object_response(serializers.auditor(auditor))


@bp.route("/auditors/<auditor_id>/calibration-records", methods=["GET"])
def list_auditor_calibration_records(auditor_id):
    begin("BrandAdmin", "Auditor", "CalibrationReviewer")
    require("auditor", auditor_id)
    resolve_identity()
    records = [
        r for r in db.store.calibration_records.values()
        if r["auditor_id"] == auditor_id or r["reviewer_auditor_id"] == auditor_id
    ]
    return listing(records, serializers.calibration_record)


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------

@bp.route("/locations", methods=["POST"])
def create_location():
    begin("BrandAdmin")
    resolve_identity()
    payload = body()
    brand_id = req_id(payload, "brand_id")
    franchisee_id = req_id(payload, "franchisee_id")
    store_number = req_str(payload, "store_number", 3, 16)
    region_code = req_enum(payload, "region_code", REGION_CODES)

    brand = require("brand", brand_id)
    franchisee = require("franchisee", franchisee_id)

    if franchisee["brand_id"] != brand_id:
        fail(
            "ERR_FRANCHISEE_BRAND_MISMATCH",
            "The franchisee does not belong to the location's brand.",
        )

    for existing in db.store.locations.values():
        if existing["brand_id"] == brand_id and existing["store_number"] == store_number:
            fail("ERR_DUPLICATE_RESOURCE_CODE", "store_number is already used in this brand.")

    record = db.new_record()
    record.update({
        "brand_id": brand_id,
        "franchisee_id": franchisee_id,
        "store_number": store_number,
        "region_code": region_code,
        "standing_score": Decimal("0.00"),
        "latest_grade": None,
        "open_corrective_action_count": 0,
        "repeat_violation_count": 0,
        "escalation_level": 0,
        "franchise_agreement_status": "GOOD_STANDING",
        "cure_period_started_at": None,
    })
    db.store.locations[record["id"]] = record

    cascade.recompute_brand_counts(brand)
    return object_response(serializers.location(record), 201)


@bp.route("/locations/<location_id>", methods=["GET"])
def read_location(location_id):
    begin("BrandAdmin", "Franchisee", "Auditor")
    location = require("location", location_id)
    resolve_identity()
    return object_response(serializers.location(location))


@bp.route("/locations", methods=["GET"])
def list_locations():
    begin("BrandAdmin", "Franchisee")
    resolve_identity()
    brand_id = filter_value("brand_id")
    franchisee_id = filter_value("franchisee_id")
    region_code = filter_enum("region_code", REGION_CODES)
    status = filter_enum("franchise_agreement_status", AGREEMENT_STATUSES)

    records = []
    for loc in db.store.locations.values():
        if brand_id is not None and loc["brand_id"] != brand_id:
            continue
        if franchisee_id is not None and loc["franchisee_id"] != franchisee_id:
            continue
        if region_code is not None and loc["region_code"] != region_code:
            continue
        if status is not None and loc["franchise_agreement_status"] != status:
            continue
        records.append(loc)
    return listing(records, serializers.location)


@bp.route("/locations/<location_id>/health-inspections", methods=["GET"])
def list_location_health_inspections(location_id):
    begin("BrandAdmin", "ComplianceIntegrator", "Auditor")
    require("location", location_id)
    resolve_identity()
    status = filter_enum("status", INSPECTION_STATUSES)
    records = [
        h for h in db.store.health_inspections.values()
        if h["location_id"] == location_id
        and (status is None or h["status"] == status)
    ]
    return listing(records, serializers.health_inspection)


@bp.route("/locations/<location_id>/escalation-events", methods=["GET"])
def list_location_escalation_events(location_id):
    begin("BrandAdmin", "Franchisee")
    require("location", location_id)
    resolve_identity()
    records = [
        e for e in db.store.escalation_events.values()
        if e["location_id"] == location_id
    ]
    return listing(records, serializers.escalation_event)


@bp.route("/locations/<location_id>/cure-acceptance", methods=["POST"])
def accept_cure(location_id):
    begin("BrandAdmin")
    location = require("location", location_id)
    resolve_identity()
    payload = body()
    opt_str(payload, "note", 0, 1000)

    if location["franchise_agreement_status"] == "GOOD_STANDING" \
            or location["escalation_level"] <= 0:
        fail("ERR_NO_ESCALATION_TO_CURE", "The location is already in GOOD_STANDING.")
    if location["open_corrective_action_count"] != 0:
        fail(
            "ERR_OPEN_CORRECTIVE_ACTIONS",
            "Every corrective action must leave the open pool before a cure is accepted.",
        )

    cascade.append_escalation_event(location, "CURE_ACCEPTED")
    cascade.cascade_location(location)
    return object_response(serializers.location(location))
