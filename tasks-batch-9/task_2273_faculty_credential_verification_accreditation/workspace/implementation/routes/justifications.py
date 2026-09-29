"""Tested-experience justifications and cascade B (PRD 3.5)."""

from flask import Blueprint

import db
import guards
import middleware
import response
import serialize
import util
import validate
from constants import (
    CREDENTIAL_ANALYST, INDUSTRY_CERTIFICATION_LEVELS, JUSTIFICATION_STATUSES,
    PROGRAM_DEAN, READ_ROLES, TESTED_EXPERIENCE_MIN_YEARS,
    TESTED_EXPERIENCE_SCORE_THRESHOLD,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import calc, domain, lookup

bp = Blueprint("justifications", __name__)

BACKABLE_STATUSES = ("EXCEPTION_FLAGGED", "REMEDIATION_IN_PROGRESS")


def _score(row):
    return calc.tested_experience_score(
        row["documented_years_experience"],
        row["industry_certification_level"],
        row["alternative_credential_codes"],
    )


def _backing(justification):
    assignment = store.course_assignments.get(justification["course_assignment_id"])
    if assignment is None:
        return None, None, None
    section = store.course_sections.get(assignment["course_section_id"])
    if section is None:
        return assignment, None, None
    return assignment, section, store.programs.get(section["program_id"])


def _require_dean_of_backing(justification_id):
    provisional = lookup.maybe("justifications", justification_id)
    if provisional is None:
        return
    assignment, section, _program = _backing(provisional)
    if section is not None:
        middleware.require_dean_owns(section.get("program_id"))


@bp.route("/tested-experience-justifications", methods=["POST"])
def create_justification():
    middleware.require_role(PROGRAM_DEAN)
    payload = validate.body()

    provisional = lookup.maybe("course_assignments", payload.get("course_assignment_id"))
    if provisional is not None:
        section = store.course_sections.get(provisional["course_section_id"])
        if section is not None:
            middleware.require_dean_owns(section.get("program_id"))

    assignment_id = validate.req_str(payload, "course_assignment_id")
    narrative = validate.req_str(payload, "narrative")
    codes = validate.req_str_array(payload, "alternative_credential_codes")
    years = validate.req_num(payload, "documented_years_experience", minimum=0)
    cert_level = validate.req_enum(payload, "industry_certification_level",
                                   INDUSTRY_CERTIFICATION_LEVELS)
    attestation = validate.opt_bool(payload, "supervisor_attestation_on_file",
                                    default=False)

    lookup.assignment(assignment_id)

    row = db.new_row(
        course_assignment_id=assignment_id,
        narrative=narrative,
        alternative_credential_codes=codes,
        documented_years_experience=years,
        industry_certification_level=cert_level,
        supervisor_attestation_on_file=attestation,
        tested_experience_score=None,
        status="DRAFT",
        decided_by_user_id=None,
        decision_rationale=None,
    )
    row["tested_experience_score"] = _score(row)
    store.justifications[row["id"]] = row
    return response.created(serialize.justification(row))


@bp.route("/tested-experience-justifications/<justification_id>", methods=["POST"])
def update_justification(justification_id):
    middleware.require_role(PROGRAM_DEAN)
    _require_dean_of_backing(justification_id)
    payload = validate.body()

    narrative = validate.opt_str(payload, "narrative", allow_empty=False)
    codes_given = "alternative_credential_codes" in payload
    codes = validate.req_str_array(payload, "alternative_credential_codes",
                                   allow_absent=True, default=None) if codes_given else None
    years = validate.opt_num(payload, "documented_years_experience", minimum=0)
    cert_level = validate.opt_enum(payload, "industry_certification_level",
                                   INDUSTRY_CERTIFICATION_LEVELS)
    attestation = validate.opt_bool(payload, "supervisor_attestation_on_file")

    row = lookup.justification(justification_id)

    if row["status"] != "DRAFT":
        guards.invalid_state("A justification in %s may not be edited." % row["status"])

    if narrative is not None:
        row["narrative"] = narrative
    if codes is not None:
        row["alternative_credential_codes"] = codes
    if years is not None:
        row["documented_years_experience"] = years
    if cert_level is not None:
        row["industry_certification_level"] = cert_level
    if attestation is not None:
        row["supervisor_attestation_on_file"] = attestation

    row["tested_experience_score"] = _score(row)
    touch(row)
    return response.ok(serialize.justification(row))


@bp.route("/tested-experience-justifications/<justification_id>", methods=["GET"])
def read_justification(justification_id):
    middleware.require_role(*READ_ROLES)
    return response.ok(serialize.justification(lookup.justification(justification_id)))


@bp.route("/tested-experience-justifications", methods=["GET"])
def list_justifications():
    middleware.require_role(*READ_ROLES)
    assignment_id = validate.q_str("course_assignment_id")
    status = validate.q_enum("status", JUSTIFICATION_STATUSES)
    cert_level = validate.q_enum("industry_certification_level",
                                 INDUSTRY_CERTIFICATION_LEVELS)
    rows = [r for r in db.ordered(store.justifications)
            if match(r, "course_assignment_id", assignment_id)
            and match(r, "status", status)
            and match(r, "industry_certification_level", cert_level)]
    return list_response(rows, serialize.justification)


@bp.route("/tested-experience-justifications/<justification_id>/status", methods=["POST"])
def justification_status(justification_id):
    middleware.require_role(PROGRAM_DEAN)
    _require_dean_of_backing(justification_id)
    payload = validate.body()
    to_status = validate.req_enum(payload, "to_status", JUSTIFICATION_STATUSES)

    row = lookup.justification(justification_id)
    current = row["status"]

    if to_status == "SUBMITTED":
        if current != "DRAFT":
            guards.invalid_state("A justification in %s may not be submitted." % current)
        assignment, _section, _program = _backing(row)
        if assignment is None or assignment["status"] not in BACKABLE_STATUSES:
            guards.invalid_state("The backed assignment is not in an exception state.")
        row["tested_experience_score"] = _score(row)
        row["status"] = "SUBMITTED"
    elif to_status == "WITHDRAWN":
        if current not in ("DRAFT", "SUBMITTED"):
            guards.invalid_state("A justification in %s may not be withdrawn." % current)
        row["status"] = "WITHDRAWN"
    else:
        guards.invalid_state("A justification may not be driven to %s." % to_status)

    touch(row)
    return response.ok(serialize.justification(row))


@bp.route("/tested-experience-justifications/<justification_id>/review", methods=["POST"])
def review_justification(justification_id):
    middleware.require_role(CREDENTIAL_ANALYST)
    validate.body()

    row = lookup.justification(justification_id)
    if row["status"] != "SUBMITTED":
        guards.invalid_state("A justification in %s may not be taken under review."
                             % row["status"])
    row["status"] = "UNDER_REVIEW"
    touch(row)
    return response.ok(serialize.justification(row))


@bp.route("/tested-experience-justifications/<justification_id>/decision", methods=["POST"])
def decide_justification(justification_id):
    middleware.require_role(CREDENTIAL_ANALYST)
    payload = validate.body()
    decision = validate.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    rationale = validate.req_str(payload, "decision_rationale")

    row = lookup.justification(justification_id)

    if row["status"] != "UNDER_REVIEW":
        guards.invalid_state("A justification in %s may not be decided." % row["status"])

    assignment, section, program = _backing(row)

    # Rung 13 — segregation of duties against the faculty member's verifiers.
    actor = middleware.user_id()
    if assignment is not None:
        for record in lookup.credentials_of(assignment["faculty_member_id"]):
            if record.get("verified_by_user_id") == actor:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVE":
        if not row.get("supervisor_attestation_on_file"):
            raise ApiError("ERR_ATTESTATION_MISSING")
        score = util.dec(row["tested_experience_score"])
        years = util.dec(row["documented_years_experience"])
        if years < TESTED_EXPERIENCE_MIN_YEARS or score < TESTED_EXPERIENCE_SCORE_THRESHOLD:
            raise ApiError("ERR_TESTED_EXPERIENCE_INSUFFICIENT")

    row["decided_by_user_id"] = actor
    row["decision_rationale"] = rationale

    if decision == "REJECT":
        row["status"] = "REJECTED"
        touch(row)
        return response.ok(serialize.justification(row))

    row["status"] = "APPROVED"
    touch(row)

    # Cascade B — assignment, roster, program.
    if assignment is not None and section is not None:
        old_status = assignment["status"]
        assignment["status"] = "VERIFIED_QUALIFIED"
        assignment["qualification_basis"] = "TESTED_EXPERIENCE"
        assignment["exception_code"] = None
        assignment["remediation_action"] = None
        touch(assignment)

        delta = domain.unqualified_delta(old_status, "VERIFIED_QUALIFIED")
        if delta:
            domain.bump_unqualified(program, delta)
        roster = lookup.generated_roster(section["program_id"], section["term_id"])
        if roster is not None:
            domain.recompute_roster(roster)
            if program is not None:
                domain.write_program_adequacy(program, section["term_id"])

    return response.ok(serialize.justification(row))


@bp.route("/tested-experience-justifications/<justification_id>/revision", methods=["POST"])
def revise_justification(justification_id):
    middleware.require_role(PROGRAM_DEAN)
    _require_dean_of_backing(justification_id)
    validate.body()

    row = lookup.justification(justification_id)
    if row["status"] != "REJECTED":
        guards.invalid_state("A justification in %s may not be re-opened." % row["status"])

    row["status"] = "DRAFT"
    row["decided_by_user_id"] = None
    row["decision_rationale"] = None
    touch(row)
    return response.ok(serialize.justification(row))
