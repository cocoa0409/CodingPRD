"""Credential records, transcripts, verification and foreign evaluations."""

from flask import Blueprint

import db
import guards
import middleware
import response
import serialize
import validate
from constants import (
    ALL_ROLES, CREDENTIAL_ANALYST, DEGREE_LEVELS, EQUIVALENCY_VERDICTS,
    EVALUATION_STATUSES, READ_ROLES, REGISTRAR_OFFICER, SERVICE_LEVELS,
    TRANSCRIPT_STATUSES, VERIFICATION_STATUSES,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import calc, domain, lookup

bp = Blueprint("credentials", __name__)

TRANSCRIPT_TRANSITIONS = {
    "NOT_REQUESTED": ("REQUESTED", "UNOFFICIAL_ONLY", "OFFICIAL_RECEIVED"),
    "REQUESTED": ("UNOFFICIAL_ONLY", "OFFICIAL_RECEIVED"),
    "UNOFFICIAL_ONLY": ("OFFICIAL_RECEIVED",),
    "OFFICIAL_RECEIVED": (),
}

EVALUATION_TRANSITIONS = {
    "ORDERED": ("IN_REVIEW", "VOIDED"),
    "IN_REVIEW": ("COMPLETED", "VOIDED"),
    "COMPLETED": (),
    "VOIDED": (),
}


# ----------------------------------------------------------- credential records
@bp.route("/credential-records", methods=["POST"])
def create_credential_record():
    middleware.require_role(REGISTRAR_OFFICER)
    payload = validate.body()

    faculty_id = validate.req_str(payload, "faculty_member_id")
    degree_level = validate.req_enum(payload, "degree_level", DEGREE_LEVELS)
    discipline_id = validate.req_str(payload, "discipline_id")
    institution = validate.req_str(payload, "conferring_institution")
    is_foreign = validate.opt_bool(payload, "is_foreign_institution", default=False)
    hours = validate.opt_num(payload, "graduate_credit_hours_in_discipline",
                             default=0, minimum=0)

    faculty = lookup.faculty(faculty_id)
    lookup.discipline(discipline_id)

    guards.require_not_separated(faculty)

    row = db.new_row(
        faculty_member_id=faculty_id,
        degree_level=degree_level,
        discipline_id=discipline_id,
        conferring_institution=institution,
        is_foreign_institution=is_foreign,
        graduate_credit_hours_in_discipline=hours,
        transcript_status="NOT_REQUESTED",
        verification_status="PENDING",
        verified_by_user_id=None,
        effective_degree_level=None,
        effective_discipline_id=None,
    )
    store.credential_records[row["id"]] = row

    domain.recompute_dossier(faculty)
    return response.created(serialize.credential(row))


@bp.route("/credential-records/<credential_record_id>", methods=["GET"])
def read_credential_record(credential_record_id):
    middleware.require_role(*READ_ROLES)
    return response.ok(serialize.credential(lookup.credential(credential_record_id)))


@bp.route("/credential-records", methods=["GET"])
def list_credential_records():
    middleware.require_role(*READ_ROLES)
    faculty_id = validate.q_str("faculty_member_id")
    discipline_id = validate.q_str("discipline_id")
    effective_discipline_id = validate.q_str("effective_discipline_id")
    verification_status = validate.q_enum("verification_status", VERIFICATION_STATUSES)
    transcript_status = validate.q_enum("transcript_status", TRANSCRIPT_STATUSES)
    is_foreign = validate.q_bool("is_foreign_institution")

    rows = []
    for row in db.ordered(store.credential_records):
        if not (match(row, "faculty_member_id", faculty_id)
                and match(row, "discipline_id", discipline_id)
                and match(row, "effective_discipline_id", effective_discipline_id)
                and match(row, "verification_status", verification_status)
                and match(row, "transcript_status", transcript_status)):
            continue
        if is_foreign is not None and bool(row.get("is_foreign_institution")) is not is_foreign:
            continue
        rows.append(row)
    return list_response(rows, serialize.credential)


@bp.route("/faculty-members/<faculty_member_id>/credential-records", methods=["GET"])
def list_faculty_credential_records(faculty_member_id):
    middleware.require_role(*ALL_ROLES)
    middleware.require_instructor_owns(faculty_member_id)
    faculty = lookup.faculty(faculty_member_id)
    middleware.require_dean_owns(faculty.get("home_program_id"))

    verification_status = validate.q_enum("verification_status", VERIFICATION_STATUSES)
    rows = [r for r in lookup.credentials_of(faculty_member_id)
            if match(r, "verification_status", verification_status)]
    return list_response(rows, serialize.credential)


@bp.route("/credential-records/<credential_record_id>/transcript", methods=["POST"])
def advance_transcript(credential_record_id):
    middleware.require_role(REGISTRAR_OFFICER)
    payload = validate.body()
    to_status = validate.req_enum(payload, "transcript_status", TRANSCRIPT_STATUSES)

    record = lookup.credential(credential_record_id)
    current = record["transcript_status"]

    if to_status not in TRANSCRIPT_TRANSITIONS[current]:
        guards.invalid_state("A transcript in %s may not move to %s."
                             % (current, to_status))

    record["transcript_status"] = to_status
    touch(record)

    if not (current == "NOT_REQUESTED" and to_status == "REQUESTED"):
        faculty = store.faculty_members.get(record["faculty_member_id"])
        if faculty is not None:
            domain.recompute_dossier(faculty)

    return response.ok(serialize.credential(record))


@bp.route("/credential-records/<credential_record_id>/verification", methods=["POST"])
def decide_credential(credential_record_id):
    middleware.require_role(CREDENTIAL_ANALYST)
    payload = validate.body()
    decision = validate.req_enum(payload, "decision", ("VERIFY", "REJECT", "REPUDIATE"))
    validate.opt_str(payload, "note")

    record = lookup.credential(credential_record_id)
    current = record["verification_status"]

    if decision == "VERIFY":
        if current != "PENDING":
            guards.invalid_state("A credential in %s may not be verified." % current)
        if record["transcript_status"] == "NOT_REQUESTED":
            guards.invalid_state("A credential whose transcript has not been requested "
                                 "may not be verified.")
        record["verification_status"] = "VERIFIED"
    elif decision == "REJECT":
        if current != "PENDING":
            guards.invalid_state("A credential in %s may not be rejected." % current)
        record["verification_status"] = "REJECTED"
    else:
        if current != "VERIFIED":
            guards.invalid_state("A credential in %s may not be repudiated." % current)
        record["verification_status"] = "REPUDIATED"

    record["verified_by_user_id"] = middleware.user_id()
    touch(record)

    if decision == "REPUDIATE":
        domain.cascade_a(record)
    else:
        faculty = store.faculty_members.get(record["faculty_member_id"])
        if faculty is not None:
            domain.recompute_dossier(faculty)

    return response.ok(serialize.credential(record))


# ------------------------------------------------------- credential evaluations
def _budget_totals(program_id):
    reserved = 0
    spent = 0
    for ev in db.ordered(store.credential_evaluations):
        if ev["billed_program_id"] == program_id and ev["status"] in ("ORDERED", "IN_REVIEW"):
            reserved += int(ev["fee_cents"])
        if ev["status"] == "COMPLETED":
            for share in ev.get("allocation_shares") or []:
                if share["program_id"] == program_id:
                    spent += int(share["share_cents"])
    return reserved, spent


@bp.route("/credential-evaluations", methods=["POST"])
def order_evaluation():
    middleware.require_role(CREDENTIAL_ANALYST)
    payload = validate.body()

    record_id = validate.req_str(payload, "credential_record_id")
    billed_program_id = validate.req_str(payload, "billed_program_id")
    agency = validate.req_str(payload, "evaluator_agency")
    page_count = validate.req_int(payload, "page_count", minimum=0)
    service_level = validate.req_enum(payload, "service_level", SERVICE_LEVELS)

    record = lookup.credential(record_id)
    program = lookup.program(billed_program_id)

    guards.require_no_review_lockout(billed_program_id)

    if not record.get("is_foreign_institution"):
        raise ApiError("ERR_NOT_FOREIGN_CREDENTIAL")

    fee = calc.evaluation_fee_cents(page_count, True, service_level)
    reserved, spent = _budget_totals(billed_program_id)
    if reserved + spent + fee > int(program["credential_budget_cents"]):
        raise ApiError("ERR_CREDENTIAL_BUDGET_EXCEEDED")

    row = db.new_row(
        credential_record_id=record_id,
        billed_program_id=billed_program_id,
        evaluator_agency=agency,
        page_count=page_count,
        service_level=service_level,
        fee_cents=fee,
        status="ORDERED",
        equivalency_degree_level=None,
        equivalency_discipline_id=None,
        equivalency_verdict=None,
        allocation_shares=[],
    )
    store.credential_evaluations[row["id"]] = row
    touch(program)
    return response.created(serialize.evaluation(row))


@bp.route("/credential-evaluations/<evaluation_id>", methods=["GET"])
def read_evaluation(evaluation_id):
    middleware.require_role(*READ_ROLES)
    return response.ok(serialize.evaluation(lookup.evaluation(evaluation_id)))


@bp.route("/credential-evaluations", methods=["GET"])
def list_evaluations():
    middleware.require_role(*READ_ROLES)
    record_id = validate.q_str("credential_record_id")
    billed_program_id = validate.q_str("billed_program_id")
    equivalency_discipline_id = validate.q_str("equivalency_discipline_id")
    status = validate.q_enum("status", EVALUATION_STATUSES)
    service_level = validate.q_enum("service_level", SERVICE_LEVELS)
    rows = [r for r in db.ordered(store.credential_evaluations)
            if match(r, "credential_record_id", record_id)
            and match(r, "billed_program_id", billed_program_id)
            and match(r, "equivalency_discipline_id", equivalency_discipline_id)
            and match(r, "status", status)
            and match(r, "service_level", service_level)]
    return list_response(rows, serialize.evaluation)


@bp.route("/credential-evaluations/<evaluation_id>/status", methods=["POST"])
def evaluation_status(evaluation_id):
    middleware.require_role(CREDENTIAL_ANALYST)
    payload = validate.body()
    to_status = validate.req_enum(payload, "to_status", EVALUATION_STATUSES)

    equivalency_level = None
    equivalency_discipline_id = None
    equivalency_verdict = None
    if to_status == "COMPLETED":
        equivalency_level = validate.req_enum(payload, "equivalency_degree_level",
                                              DEGREE_LEVELS)
        equivalency_discipline_id = validate.req_str(payload, "equivalency_discipline_id")
        equivalency_verdict = validate.req_enum(payload, "equivalency_verdict",
                                                EQUIVALENCY_VERDICTS)
    else:
        validate.opt_enum(payload, "equivalency_degree_level", DEGREE_LEVELS)
        validate.opt_str(payload, "equivalency_discipline_id")
        validate.opt_enum(payload, "equivalency_verdict", EQUIVALENCY_VERDICTS)

    evaluation = lookup.evaluation(evaluation_id)

    if equivalency_discipline_id is not None:
        lookup.discipline(equivalency_discipline_id)

    current = evaluation["status"]
    if to_status not in EVALUATION_TRANSITIONS[current]:
        guards.invalid_state("An evaluation in %s may not move to %s."
                             % (current, to_status))

    record = store.credential_records.get(evaluation["credential_record_id"])
    billed_program = store.programs.get(evaluation["billed_program_id"])

    if to_status == "IN_REVIEW":
        evaluation["status"] = "IN_REVIEW"
        touch(evaluation)
        return response.ok(serialize.evaluation(evaluation))

    if to_status == "VOIDED":
        evaluation["status"] = "VOIDED"
        touch(evaluation)
        if billed_program is not None:
            touch(billed_program)
        return response.ok(serialize.evaluation(evaluation))

    # COMPLETED
    evaluation["status"] = "COMPLETED"
    evaluation["equivalency_degree_level"] = equivalency_level
    evaluation["equivalency_discipline_id"] = equivalency_discipline_id
    evaluation["equivalency_verdict"] = equivalency_verdict
    evaluation["allocation_shares"] = calc.evaluation_allocation(evaluation)
    touch(evaluation)

    if billed_program is not None:
        touch(billed_program)
    for share in evaluation["allocation_shares"]:
        program = store.programs.get(share["program_id"])
        if program is not None:
            touch(program)

    if record is not None:
        if equivalency_verdict == "EQUIVALENT":
            record["effective_degree_level"] = equivalency_level
            record["effective_discipline_id"] = equivalency_discipline_id
        touch(record)
        faculty = store.faculty_members.get(record["faculty_member_id"])
        if faculty is not None:
            domain.recompute_dossier(faculty)

    return response.ok(serialize.evaluation(evaluation))
