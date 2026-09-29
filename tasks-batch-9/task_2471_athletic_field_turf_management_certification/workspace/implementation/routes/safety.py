"""Safety testing and the head of the remediation cascade (PRD 3.3, 3.4)."""

from decimal import Decimal as D

import calc
import derive
import errors
import middleware
import response
import validate
from db import bump, common_fields, db, new_id, now
from errors import ApiError
from routes.blueprint import bp
from routes.common import listing

FILTERS = {
    "field_id": "field_id",
    "inspector_staff_member_id": "inspector_staff_member_id",
    "assessment_type": "assessment_type",
    "status": "status",
    "result": "result",
}

_METRIC_MISMATCH = (
    "gmax_readings must hold exactly three readings with declared_result null for "
    "IMPACT_ATTENUATION, and gmax_readings must be null with declared_result "
    "present for GOAL_ANCHORING and STRIPING_LAYOUT.")


def _metric_mismatch():
    return ApiError("ERR_ASSESSMENT_METRIC_MISMATCH", 422, _METRIC_MISMATCH)


@bp.post("/safety-assessments")
def record_assessment():
    middleware.authenticate(["SafetyInspector"])
    body = validate.Body(
        required=["field_id", "inspector_staff_member_id", "assessment_type",
                  "assessed_at_utc"],
        optional=["gmax_readings", "declared_result"])

    field_id = body.string("field_id")
    inspector_id = body.string("inspector_staff_member_id")
    assessment_type = body.enum("assessment_type", calc.ASSESSMENT_TYPES)
    assessed_at = body.instant("assessed_at_utc")
    raw_readings = body.array("gmax_readings")
    declared_result = body.enum("declared_result", calc.DECLARED_RESULTS)

    field = middleware.body_field(field_id)          # priority 18
    middleware.body_staff(inspector_id)              # priority 19

    # priority 26 - the assessment-metric pairing rule
    readings = None
    if assessment_type == "IMPACT_ATTENUATION":
        if raw_readings is None or len(raw_readings) != 3 or declared_result is not None:
            raise _metric_mismatch()
        readings = []
        for value in raw_readings:
            if isinstance(value, bool) or not isinstance(value, (int, D)):
                raise _metric_mismatch()
            readings.append(calc.r1(value))
        for value in readings:
            if value < D("50.0") or value > D("400.0"):
                raise errors.invalid_request(
                    "Each g-max reading must lie between 50.0 and 400.0.")
    else:
        if raw_readings is not None or declared_result is None:
            raise _metric_mismatch()

    # priority 30 - an assessment may never be future-dated
    current = now()
    if assessed_at.dt > current.dt:
        raise ApiError("ERR_ASSESSMENT_IN_FUTURE", 422,
                       "assessed_at_utc may not be later than the current instant.")

    # priority 34 - the retirement guard
    if field["retired_at"] is not None:
        raise ApiError("ERR_FIELD_RETIRED", 409,
                       "No assessment may be recorded against a retired field.")

    if readings is not None:
        mean, result = calc.impact_attenuation_result(readings)
    else:
        mean, result = None, declared_result

    assessment = {
        "id": new_id(),
        "field_id": field_id,
        "inspector_staff_member_id": inspector_id,
        "assessment_type": assessment_type,
        "assessed_at_utc": assessed_at,
        "gmax_readings": readings,
        "declared_result": declared_result,
        "gmax_mean_value": mean,
        "result": result,
        "status": "RECORDED",
        "superseded_at_utc": None,
        "void_reason": None,
    }
    assessment.update(common_fields())
    db.safety_assessments[assessment["id"]] = assessment

    # PRD 3.3: a newer assessment of the same type on the same field supersedes
    # the earlier one, so each field has at most one live assessment per type.
    for other in list(db.safety_assessments.values()):
        if (other["id"] != assessment["id"] and other["field_id"] == field_id
                and other["assessment_type"] == assessment_type
                and other["status"] == "RECORDED"
                and assessed_at.dt >= other["assessed_at_utc"].dt):
            other["status"] = "SUPERSEDED"
            other["superseded_at_utc"] = current
            bump(other)

    derive.recompute_field(field)
    derive.open_remediation_order(field, assessment)
    derive.touch_field(field)
    return response.created(assessment)


@bp.get("/safety-assessments")
def list_assessments():
    middleware.authenticate(middleware.ALL_ROLES)
    return listing(db.safety_assessments, FILTERS)


@bp.get("/safety-assessments/<assessment_id>")
def read_assessment(assessment_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.assessment_or_404(assessment_id))


@bp.post("/safety-assessments/<assessment_id>/void")
def void_assessment(assessment_id):
    middleware.authenticate(["SafetyInspector"])
    assessment = middleware.assessment_or_404(assessment_id)
    body = validate.Body(required=["void_reason"])
    void_reason = body.string("void_reason", 1, 500)

    # priority 36 - only a RECORDED assessment may be voided
    if assessment["status"] != "RECORDED":
        raise ApiError("ERR_ASSESSMENT_NOT_RECORDED", 409,
                       "Only a RECORDED assessment may be voided.")

    # priority 55 - an assessment under live certification paperwork is pinned
    for packet in db.certification_packets.values():
        if (packet["governing_assessment_id"] == assessment_id
                and packet["status"] in ("SUBMITTED", "APPROVED")):
            raise ApiError("ERR_ASSESSMENT_IN_USE", 409,
                           "A SUBMITTED or APPROVED certification packet governs "
                           "this assessment.")

    current = now()
    assessment["status"] = "VOIDED"
    assessment["void_reason"] = void_reason
    bump(assessment)

    # PRD 3.4: every order this assessment opened is cancelled.
    for order in db.remediation_orders.values():
        if (order["source_assessment_id"] == assessment_id
                and order["status"] in ("OPEN", "VERIFICATION_SUBMITTED")):
            order["status"] = "CANCELLED"
            order["closed_at_utc"] = current
            bump(order)

    field = db.fields[assessment["field_id"]]
    derive.touch_field(field)
    return response.ok(assessment)
