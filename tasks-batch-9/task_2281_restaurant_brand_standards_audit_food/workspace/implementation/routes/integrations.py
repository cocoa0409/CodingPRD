"""Health-department imports, auditor calibration and the logical clock."""

from decimal import Decimal

from flask import Blueprint, g

import db
import serializers
from common import dec, fmt_dt, q2, touch
from errors import fail
from middleware import (
    begin,
    body,
    req_dt,
    req_enum,
    req_id,
    req_int,
    req_str,
    require,
    resolve_identity,
)
from response import object_response
from services import calc, cascade

bp = Blueprint("integrations", __name__)

LETTER_GRADES = ("A", "B", "C", "FAIL")
DISREGARD_REASONS = ("SUPERSEDED_BY_REINSPECTION", "WRONG_LOCATION", "DATA_ERROR")


# --------------------------------------------------------------------------
# Health inspections
# --------------------------------------------------------------------------

@bp.route("/health-inspections", methods=["POST"])
def import_health_inspection():
    begin("ComplianceIntegrator")
    resolve_identity()
    payload = body()
    location_id = req_id(payload, "location_id")
    authority_name = req_str(payload, "authority_name", 1, 120)
    inspection_date = req_dt(payload, "inspection_date")
    points_scored = req_int(payload, "points_scored", 0)
    points_possible = req_int(payload, "points_possible", 1, 1000)
    letter_grade = req_enum(payload, "letter_grade", LETTER_GRADES)
    if points_scored > points_possible:
        fail("ERR_INVALID_REQUEST", "points_scored may not exceed points_possible.")

    require("location", location_id)

    if inspection_date > db.store.clock:
        fail("ERR_TIMESTAMP_IN_FUTURE", "inspection_date may not be after the logical clock.")

    record = db.new_record()
    record.update({
        "location_id": location_id,
        "authority_name": authority_name,
        "inspection_date": inspection_date,
        "points_scored": points_scored,
        "points_possible": points_possible,
        "letter_grade": letter_grade,
        "status": "RECORDED",
        "disregard_reason": None,
    })
    db.store.health_inspections[record["id"]] = record
    return object_response(serializers.health_inspection(record), 201)


@bp.route("/health-inspections/<inspection_id>", methods=["GET"])
def read_health_inspection(inspection_id):
    begin("BrandAdmin", "ComplianceIntegrator")
    inspection = require("health_inspection", inspection_id)
    resolve_identity()
    return object_response(serializers.health_inspection(inspection))


@bp.route("/health-inspections/<inspection_id>/disregard", methods=["POST"])
def disregard_health_inspection(inspection_id):
    begin("ComplianceIntegrator")
    inspection = require("health_inspection", inspection_id)
    resolve_identity()
    payload = body()
    reason = req_enum(payload, "disregard_reason", DISREGARD_REASONS)

    inspection["status"] = "DISREGARDED"
    inspection["disregard_reason"] = reason
    touch(inspection)
    return object_response(serializers.health_inspection(inspection))


# --------------------------------------------------------------------------
# Calibration records
# --------------------------------------------------------------------------

@bp.route("/calibration-records", methods=["POST"])
def record_calibration():
    begin("CalibrationReviewer")
    resolve_identity()
    payload = body()
    shadow_visit_id = req_id(payload, "shadow_visit_id")

    shadow_visit = require("visit", shadow_visit_id)

    reviewer = g.actor
    if reviewer["status"] == "SUSPENDED":
        fail("ERR_AUDITOR_SUSPENDED", "A SUSPENDED auditor may not record calibration.")

    primary_visit = None
    if shadow_visit["shadow_of_visit_id"] is not None:
        primary_visit = db.store.audit_visits.get(shadow_visit["shadow_of_visit_id"])

    if primary_visit is not None and primary_visit["auditor_id"] == g.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "A reviewer may not record calibration against their own scoring.",
        )

    if shadow_visit["visit_type"] != "SHADOW" \
            or shadow_visit["shadow_of_visit_id"] is None \
            or primary_visit is None \
            or shadow_visit["composite_score"] is None \
            or primary_visit["composite_score"] is None:
        fail(
            "ERR_CALIBRATION_INPUTS_INCOMPLETE",
            "Calibration requires a SHADOW visit linked to a scored primary visit.",
        )

    for existing in db.store.calibration_records.values():
        if existing["shadow_visit_id"] == shadow_visit_id:
            fail(
                "ERR_CALIBRATION_ALREADY_RECORDED",
                "Calibration has already been recorded for this shadow visit.",
            )

    variance = q2(abs(dec(shadow_visit["composite_score"]) - dec(primary_visit["composite_score"])))
    band, delta = calc.calibration_band(variance)

    record = db.new_record(light=True)
    record.update({
        "shadow_visit_id": shadow_visit_id,
        "primary_visit_id": primary_visit["id"],
        "auditor_id": primary_visit["auditor_id"],
        "reviewer_auditor_id": shadow_visit["auditor_id"],
        "variance_points": variance,
        "reliability_delta": delta,
        "band": band,
        "recorded_at": db.store.clock,
    })
    db.store.calibration_records[record["id"]] = record

    audited = db.store.auditors.get(primary_visit["auditor_id"])
    if audited is not None:
        cascade.apply_rolling_reliability(audited)

    return object_response(serializers.calibration_record(record), 201)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    begin("BrandAdmin")
    resolve_identity()
    payload = body()
    instant = req_dt(payload, "to_iso8601")
    db.store.clock = instant
    return object_response({"current_utc": fmt_dt(db.store.clock)})
