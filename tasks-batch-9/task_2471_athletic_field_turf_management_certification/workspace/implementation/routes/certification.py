"""Certifying a field for sanctioned competition (PRD 3.8)."""

import calc
import derive
import middleware
import response
import validate
from db import bump, common_fields, db, new_id, now
from errors import ApiError
from routes.blueprint import bp
from routes.common import listing

FILTERS = {
    "field_id": "field_id",
    "governing_assessment_id": "governing_assessment_id",
    "submitted_by_staff_member_id": "submitted_by_staff_member_id",
    "decided_by_staff_member_id": "decided_by_staff_member_id",
    "status": "status",
}


def _require_current_governing(field, assessment):
    """Priority 57: an ADVISORY reading is acceptable evidence, a FAIL is not."""
    if (assessment["field_id"] != field["id"]
            or assessment["assessment_type"] != "IMPACT_ATTENUATION"
            or assessment["status"] != "RECORDED"
            or assessment["result"] == "FAIL"):
        raise ApiError("ERR_GOVERNING_ASSESSMENT_NOT_CURRENT", 422,
                       "The governing assessment is not a current, non-failing "
                       "impact-attenuation test on this field.")


@bp.post("/certification-packets")
def create_packet():
    middleware.authenticate(["CertificationOfficer"])
    body = validate.Body(required=["field_id", "governing_assessment_id",
                                   "competition_season_label",
                                   "expected_field_version"])
    field_id = body.string("field_id")
    assessment_id = body.string("governing_assessment_id")
    season_label = body.string("competition_season_label", 1, 40)
    expected_version = body.integer("expected_field_version")

    field = middleware.body_field(field_id)                     # priority 18
    assessment = middleware.body_assessment(assessment_id)      # priority 20

    # priority 33 - optimistic concurrency on Field.version
    if expected_version != field["version"]:
        raise ApiError("ERR_STALE_FIELD_VERSION", 412,
                       "expected_field_version does not match the current "
                       "Field.version.")

    # priority 34 - the retirement guard
    if field["retired_at"] is not None:
        raise ApiError("ERR_FIELD_RETIRED", 409,
                       "A retired field cannot be certified.")

    # priority 57 - the governing assessment must still be current
    _require_current_governing(field, assessment)

    packet = {
        "id": new_id(),
        "field_id": field_id,
        "governing_assessment_id": assessment_id,
        "submitted_by_staff_member_id": None,
        "decided_by_staff_member_id": None,
        "competition_season_label": season_label,
        "status": "DRAFT",
        "documentation_completeness_score": None,
        "condition_index_certification": None,
        "submitted_at_utc": None,
        "decided_at_utc": None,
        "certified_until_utc": None,
        "decision_notes": None,
        "return_count": 0,
    }
    packet.update(common_fields())
    db.certification_packets[packet["id"]] = packet
    derive.touch_field(field)
    return response.created(packet)


@bp.get("/certification-packets")
def list_packets():
    middleware.authenticate(middleware.ALL_ROLES)
    return listing(db.certification_packets, FILTERS)


@bp.get("/certification-packets/<packet_id>")
def read_packet(packet_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.packet_or_404(packet_id))


@bp.post("/certification-packets/<packet_id>/submit")
def submit_packet(packet_id):
    middleware.authenticate(["CertificationOfficer"])
    packet = middleware.packet_or_404(packet_id)
    body = validate.Body(required=["submitted_by_staff_member_id"])
    submitted_by = body.string("submitted_by_staff_member_id")
    middleware.body_staff(submitted_by)                          # priority 19

    field = db.fields[packet["field_id"]]

    # priority 34 - the retirement guard
    if field["retired_at"] is not None:
        raise ApiError("ERR_FIELD_RETIRED", 409,
                       "A retired field cannot be certified.")

    # priority 41 - DRAFT and RETURNED alike may be submitted
    if packet["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_PACKET_NOT_SUBMITTABLE", 409,
                       "Only a DRAFT or RETURNED packet may be submitted.")

    # priority 57 - re-checked, because the assessment may since have moved
    assessment = db.safety_assessments[packet["governing_assessment_id"]]
    _require_current_governing(field, assessment)

    derive.recompute_field(field)
    submitted_at = now()

    # PRD 3.8: both scores are recomputed from scratch at every submission.
    packet["status"] = "SUBMITTED"
    packet["submitted_by_staff_member_id"] = submitted_by
    packet["submitted_at_utc"] = submitted_at
    packet["documentation_completeness_score"] = derive.completeness_score(
        field, assessment, submitted_at)
    packet["condition_index_certification"] = calc.condition_index(
        field["cumulative_wear_units"], field["age_years"],
        field["expected_life_years"], field["latest_gmax_mean_value"],
        "CERTIFICATION")
    bump(packet)

    derive.touch_field(field)
    return response.ok(packet)


@bp.post("/certification-packets/<packet_id>/decide")
def decide_packet(packet_id):
    user_id, _role = middleware.authenticate(["CertificationOfficer"])
    packet = middleware.packet_or_404(packet_id)

    # priority 15 - segregation of duties bites hardest here, before body parsing
    governing = db.safety_assessments[packet["governing_assessment_id"]]
    middleware.deny_self(user_id, packet["submitted_by_staff_member_id"])
    middleware.deny_self(user_id, governing["inspector_staff_member_id"])

    body = validate.Body(required=["decision", "decided_by_staff_member_id"],
                         optional=["decision_notes"])
    decision = body.enum("decision", ["APPROVE", "RETURN"])
    decided_by = body.string("decided_by_staff_member_id")
    notes = body.string("decision_notes", 1, 2000)
    middleware.body_staff(decided_by)                            # priority 19

    # priority 42 - the packet must be awaiting a decision
    if packet["status"] != "SUBMITTED":
        raise ApiError("ERR_PACKET_NOT_SUBMITTED", 409,
                       "Only a SUBMITTED packet may be decided.")

    field = db.fields[packet["field_id"]]
    current = now()

    if decision == "APPROVE":
        derive.recompute_field(field)
        # priority 54 - a mid-flight safety failure surfaces as itself
        if field["open_mandatory_remediation_count"] > 0:
            raise ApiError("ERR_OPEN_MANDATORY_REMEDIATION", 422,
                           "The field carries open mandatory remediation.")
        # priority 66 then priority 67 - the two scoring floors, in this order
        if (packet["documentation_completeness_score"]
                < calc.MIN_CERTIFICATION_COMPLETENESS_SCORE):
            raise ApiError("ERR_CERTIFICATION_DOCUMENTATION_INCOMPLETE", 422,
                           "documentation_completeness_score is below 90.00.")
        if (packet["condition_index_certification"]
                < calc.MIN_CERTIFICATION_CONDITION_INDEX):
            raise ApiError("ERR_CONDITION_INDEX_BELOW_CERTIFICATION_FLOOR", 422,
                           "condition_index_certification is below 55.00.")

        packet["status"] = "APPROVED"
        packet["decided_by_staff_member_id"] = decided_by
        packet["decided_at_utc"] = current
        packet["decision_notes"] = notes
        packet["certified_until_utc"] = current.plus_days(
            calc.CERTIFICATION_VALID_DAYS)
        bump(packet)

        # PRD 3.8: any other APPROVED packet on the field is superseded, keeping
        # its own certified_until_utc for audit.
        for other in db.certification_packets.values():
            if (other["id"] != packet["id"]
                    and other["field_id"] == field["id"]
                    and other["status"] == "APPROVED"):
                other["status"] = "SUPERSEDED"
                bump(other)

        derive.touch_field(field)
        return response.ok(packet)

    # RETURN clears the submitter so that a different officer must resubmit.
    packet["status"] = "RETURNED"
    packet["return_count"] = packet["return_count"] + 1
    packet["decided_by_staff_member_id"] = decided_by
    packet["decided_at_utc"] = current
    packet["decision_notes"] = notes
    packet["submitted_by_staff_member_id"] = None
    bump(packet)

    derive.touch_field(field)
    return response.ok(packet)
