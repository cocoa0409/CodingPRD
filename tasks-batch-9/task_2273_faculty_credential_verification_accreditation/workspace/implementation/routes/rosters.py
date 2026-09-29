"""Faculty roster endpoints: generation and certification (PRD 3.6)."""

from decimal import Decimal

from flask import Blueprint

import clock
import db
import guards
import middleware
import response
import serialize
import validate
from constants import (
    ACCREDITATION_LIAISON, CERTIFICATION_READINESS, PROGRAM_DEAN, READ_ROLES,
    ROSTER_STATUSES,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import domain, lookup

bp = Blueprint("rosters", __name__)

REDECIDED_STATUSES = ("PENDING_VERIFICATION", "EXCEPTION_FLAGGED", "VERIFIED_QUALIFIED")


@bp.route("/faculty-rosters", methods=["POST"])
def create_roster():
    middleware.require_role(ACCREDITATION_LIAISON, PROGRAM_DEAN)
    payload = validate.body()

    raw_program_id = payload.get("program_id")
    if isinstance(raw_program_id, str):
        middleware.require_dean_owns(raw_program_id)

    program_id = validate.req_str(payload, "program_id")
    term_id = validate.req_str(payload, "term_id")

    lookup.program(program_id)
    lookup.term(term_id)

    existing = lookup.rosters_for(program_id, term_id)
    for roster in existing:
        if roster["status"] in ("DRAFT", "GENERATED"):
            raise ApiError("ERR_DUPLICATE_ROSTER")

    row = db.new_row(
        program_id=program_id,
        term_id=term_id,
        status="DRAFT",
        generation_epoch=0,
        total_assignment_count=0,
        distinct_faculty_count=0,
        flagged_exception_count=0,
        terminal_qualified_headcount=0,
        credit_hours_total=0,
        credit_hours_terminal_qualified=0,
        adequacy_ratio_snapshot=Decimal("0.0000"),
        certification_readiness="BLOCKED",
        blocking_reason_codes=[],
        certified_at=None,
        certified_by_user_id=None,
    )
    store.rosters[row["id"]] = row

    for roster in existing:
        if roster["status"] == "CERTIFIED":
            roster["status"] = "SUPERSEDED"
            touch(roster)

    return response.created(serialize.roster(row))


@bp.route("/faculty-rosters/<roster_id>", methods=["GET"])
def read_roster(roster_id):
    middleware.require_role(*READ_ROLES)
    return response.ok(serialize.roster(lookup.roster(roster_id)))


@bp.route("/faculty-rosters", methods=["GET"])
def list_rosters():
    middleware.require_role(*READ_ROLES)
    program_id = validate.q_str("program_id")
    term_id = validate.q_str("term_id")
    status = validate.q_enum("status", ROSTER_STATUSES)
    readiness = validate.q_enum("certification_readiness", CERTIFICATION_READINESS)
    rows = [r for r in db.ordered(store.rosters)
            if match(r, "program_id", program_id)
            and match(r, "term_id", term_id)
            and match(r, "status", status)
            and match(r, "certification_readiness", readiness)]
    return list_response(rows, serialize.roster)


@bp.route("/faculty-rosters/<roster_id>/entries", methods=["GET"])
def roster_entries(roster_id):
    middleware.require_role(*READ_ROLES)
    only_flagged = validate.q_bool("only_flagged")
    roster = lookup.roster(roster_id)
    rows = lookup.included_assignments(roster["program_id"], roster["term_id"])
    if only_flagged:
        rows = [r for r in rows
                if r["status"] in ("EXCEPTION_FLAGGED", "REMEDIATION_IN_PROGRESS")]
    return list_response(rows, serialize.assignment)


@bp.route("/faculty-rosters/<roster_id>/generate", methods=["POST"])
def generate_roster(roster_id):
    middleware.require_role(ACCREDITATION_LIAISON)
    validate.body()

    roster = lookup.roster(roster_id)

    if roster["status"] not in ("DRAFT", "GENERATED"):
        guards.invalid_state("A roster in %s may not be generated." % roster["status"])

    term = store.terms.get(roster["term_id"])
    guards.require_term_status(term, ("OPEN", "ROSTER_LOCKED"))

    program = store.programs.get(roster["program_id"])
    delta = 0
    for assignment in lookup.included_assignments(roster["program_id"], roster["term_id"]):
        if assignment["status"] not in REDECIDED_STATUSES:
            continue
        old_status, new_status, changed = domain.apply_decision(assignment)
        if changed:
            touch(assignment)
        delta += domain.unqualified_delta(old_status, new_status)

    roster["status"] = "GENERATED"
    domain.recompute_roster(roster, advance_epoch=True)

    if program is not None:
        if delta:
            domain.bump_unqualified(program, delta)
        domain.write_program_adequacy(program, roster["term_id"])

    return response.ok(serialize.roster(roster))


@bp.route("/faculty-rosters/<roster_id>/certification", methods=["POST"])
def certify_roster(roster_id):
    middleware.require_role(ACCREDITATION_LIAISON)
    payload = validate.body()
    validate.opt_str(payload, "attestation_note")

    roster = lookup.roster(roster_id)

    if roster["status"] != "GENERATED":
        guards.invalid_state("A roster in %s may not be certified." % roster["status"])

    for review in lookup.reviews_of_program(roster["program_id"]):
        if review["status"] == "REMEDIATION_REQUIRED":
            guards.invalid_state("The program has an accreditor review demanding "
                                 "remediation.")

    term = store.terms.get(roster["term_id"])
    guards.require_term_status(term, ("OPEN", "ROSTER_LOCKED"))

    included = lookup.included_assignments(roster["program_id"], roster["term_id"])
    included_ids = {a["id"] for a in included}
    actor = middleware.user_id()
    for justification in db.ordered(store.justifications):
        if justification["course_assignment_id"] not in included_ids:
            continue
        if justification.get("decided_by_user_id") == actor:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if roster.get("certification_readiness") != "READY":
        raise ApiError("ERR_ROSTER_NOT_READY")

    roster["status"] = "CERTIFIED"
    roster["certified_at"] = clock.stamp()
    roster["certified_by_user_id"] = actor
    touch(roster)
    return response.ok(serialize.roster(roster))
