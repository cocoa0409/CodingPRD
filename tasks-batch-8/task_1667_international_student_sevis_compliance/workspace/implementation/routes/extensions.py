"""Program extensions (PRD §3.8): OCC-guarded request; approval moves the
record's program_end_date and auto-issues a prorated replacement I-20 that
supersedes the current one (voiding its travel endorsements)."""

from flask import Blueprint

import db
import services
from db import clock_date, new_id, parse_date, stamp_new, touch
from errors import (
    ERR_EXTENSION_NOT_FORWARD,
    ERR_EXTENSION_NOT_REQUESTED,
    ERR_EXTENSION_WINDOW_CLOSED,
    ERR_INSUFFICIENT_VERIFIED_FUNDING,
    ERR_NOT_FOUND,
    ERR_RECORD_NOT_ACTIVE,
    ERR_RESOURCE_NOT_OWNED,
    ERR_STALE_VERSION,
    raise_error,
)
from helpers import (
    body, get_or_404, get_student_or_404, list_response, occ_token, opt_str,
    req_date, req_enum, req_str,
)
from middleware import ALL_ROLES, STAFF_ROLES, require_roles
from response import success_object
from serializers import program_extension_out

bp = Blueprint("extensions", __name__)

EXTENSION_DECISIONS = ("APPROVED", "DENIED")


@bp.route("/sevis/students/<sid>/program-extensions", methods=["POST"])
def create_program_extension(sid):
    require_roles(STAFF_ROLES)
    student = get_student_or_404(sid)
    data = body()
    new_program_end_date = req_date(data, "new_program_end_date")
    reason = req_str(data, "reason")
    expected_version = occ_token(data, "expected_sevis_record_version")
    record = services.record_of_student(student["id"])
    if record is None:
        raise_error(ERR_NOT_FOUND, "Student has no SevisRecord")
    # OCC runs before any business validation (PRD §2.8).
    if expected_version != record["version"]:
        raise_error(ERR_STALE_VERSION, "expected_sevis_record_version does not match the record's current version")
    if record["status"] != "ACTIVE":
        raise_error(ERR_RECORD_NOT_ACTIVE, "Record must be ACTIVE to request a program extension")
    if parse_date(new_program_end_date) <= parse_date(record["program_end_date"]):
        raise_error(ERR_EXTENSION_NOT_FORWARD, "new_program_end_date must be strictly later than the current program_end_date")
    extension = {
        "id": new_id(),
        "student_id": student["id"],
        "new_program_end_date": new_program_end_date,
        "reason": reason,
        "status": "REQUESTED",
        "decision_note": None,
    }
    stamp_new(extension)
    db.program_extensions[extension["id"]] = extension
    # Filing the request advances the record version (SCAFFOLD §1.5).
    touch(record)
    return success_object(program_extension_out(extension), 201)


@bp.route("/sevis/students/<sid>/program-extensions", methods=["GET"])
def list_program_extensions(sid):
    user_id, role = require_roles(ALL_ROLES)
    if role == "Student" and user_id != sid:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only read their own resources")
    student = get_student_or_404(sid)
    items = [p for p in db.program_extensions.values() if p["student_id"] == student["id"]]
    return list_response(items, program_extension_out)


@bp.route("/sevis/program-extensions/<eid>/decision", methods=["POST"])
def decide_program_extension(eid):
    require_roles(STAFF_ROLES)
    extension = get_or_404(db.program_extensions, eid, "ProgramExtension")
    data = body()
    decision = req_enum(data, "decision", EXTENSION_DECISIONS)
    note = opt_str(data, "note")
    if extension["status"] != "REQUESTED":
        raise_error(ERR_EXTENSION_NOT_REQUESTED, "Extension not in REQUESTED for decision")

    if decision == "APPROVED":
        record = services.record_of_student(extension["student_id"])
        if record is None or record["status"] != "ACTIVE":
            raise_error(ERR_RECORD_NOT_ACTIVE, "Record must be ACTIVE to approve an extension")
        # Temporal (priority 7) beats fiscal (priority 8).
        if clock_date() > parse_date(record["program_end_date"]):
            raise_error(ERR_EXTENSION_WINDOW_CLOSED, "Extension approval attempted after the current program_end_date")
        # Prorated extension cost from the currently ISSUED I-20's cost lines,
        # per-line round_half_up first, then integer sum (PRD §3.8).
        issued = sorted(
            services.issued_forms_of_record(record["id"]), key=lambda f: f["_seq"]
        )
        prior = issued[-1] if issued else None
        months = services.extension_months(record["program_end_date"], extension["new_program_end_date"])
        if prior is not None:
            lines = services.prorated_lines(prior, months)
            program_name = prior["program_name"]
        else:
            lines = {"tuition_cents": 0, "living_cents": 0, "insurance_cents": 0, "other_cents": 0}
            program_name = ""
        prorated_total = sum(lines.values())
        verified, provisional = services.funding_cents(extension["student_id"])
        if verified < prorated_total:
            raise_error(ERR_INSUFFICIENT_VERIFIED_FUNDING, "Verified fresh funding does not cover the prorated extension cost")

        # Coordinated multi-entity update (PRD §3.8).
        record["program_end_date"] = extension["new_program_end_date"]
        touch(record)
        replacement = {
            "id": new_id(),
            "student_id": extension["student_id"],
            "sevis_record_id": record["id"],
            "program_name": program_name,
            "program_start_date": record["program_start_date"],
            "program_end_date": extension["new_program_end_date"],
            "tuition_cents": lines["tuition_cents"],
            "living_cents": lines["living_cents"],
            "insurance_cents": lines["insurance_cents"],
            "other_cents": lines["other_cents"],
            "verified_funding_cents": verified,
            "provisional_funding_cents": provisional,
            "supersedes_i20_form_id": prior["id"] if prior is not None else None,
            "status": "ISSUED",
        }
        stamp_new(replacement)
        db.i20_forms[replacement["id"]] = replacement
        for form in issued:
            services.supersede_form(form)
        extension["status"] = "APPROVED"
    else:
        extension["status"] = "DENIED"

    if note is not None:
        extension["decision_note"] = note
    touch(extension)
    return success_object(program_extension_out(extension), 200)
