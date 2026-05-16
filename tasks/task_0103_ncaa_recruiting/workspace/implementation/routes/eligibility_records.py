"""/eligibility-records endpoints."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.models import make_entity, mark_mutated, serialize
from core.store import STORE, lock
from core.validation import (
    require_body,
    require_field,
    require_enum,
    require_iso_datetime,
)


bp = Blueprint("eligibility_records", __name__)


VALID_DECISIONS = {"QUALIFIER", "PARTIAL_QUALIFIER", "NON_QUALIFIER", "INCOMPLETE"}


@bp.route("/eligibility-records", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_record():
    body = require_body(request)
    athlete_id = require_field(body, "athlete_id", kind="string")
    gpa = require_field(body, "core_gpa", kind="number")
    if isinstance(gpa, bool):
        raise_error("ERR_VALIDATION_FAILED", "core_gpa must be number")
    test_score = require_field(body, "standardized_test_score", kind="int")
    courses = require_field(body, "core_courses_completed", kind="int")
    decision = require_enum(body, "decision", VALID_DECISIONS)
    decided_at = require_iso_datetime(body, "decided_at")

    with lock():
        athlete = STORE.athletes.get(athlete_id)
        if athlete is None:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Athlete not found")

        # uniqueness check
        if athlete.get("eligibility_record_id"):
            raise_error("ERR_ELIGIBILITY_ALREADY_DECIDED", "Athlete already has an EligibilityRecord")

        # body shape: gpa 0..4, test_score either -1 or 400..1600, courses >=16? (just validate ranges per priority 18)
        if not (0.00 <= float(gpa) <= 4.00):
            raise_error("ERR_VALIDATION_FAILED", "core_gpa must be in [0.00, 4.00]")
        # Test score range
        if not (test_score == -1 or 400 <= test_score <= 1600):
            raise_error("ERR_VALIDATION_FAILED", "standardized_test_score must be -1 or 400..1600")
        if courses < 0:
            raise_error("ERR_VALIDATION_FAILED", "core_courses_completed must be >= 0")

        from core.clock import iso_format
        rec = make_entity("EligibilityRecord", {
            "athlete_id": athlete_id,
            "core_gpa": float(gpa),
            "standardized_test_score": int(test_score),
            "core_courses_completed": int(courses),
            "decision": decision,
            "decided_at": iso_format(decided_at),
        })
        STORE.eligibility_records[rec["id"]] = rec

        # Bind to athlete
        athlete["eligibility_record_id"] = rec["id"]
        mark_mutated(athlete)
        return success_object(serialize(rec), status=201)


@bp.route("/eligibility-records/<record_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Auditor")
def get_record(record_id):
    with lock():
        r = STORE.eligibility_records.get(record_id)
        if not r:
            raise_error("ERR_NOT_FOUND", "EligibilityRecord not found")
        return success_object(serialize(r))
