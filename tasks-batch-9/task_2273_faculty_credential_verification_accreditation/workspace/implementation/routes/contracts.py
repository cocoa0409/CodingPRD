"""Faculty contract endpoints (PRD 3.7)."""

from flask import Blueprint

import clock
import db
import guards
import middleware
import response
import serialize
import util
import validate
from constants import (
    ALL_ROLES, CONTRACT_STATUSES, EMPLOYMENT_CLASSES, INSTRUCTOR, PROGRAM_DEAN,
    READ_ROLES,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import lookup

bp = Blueprint("contracts", __name__)


@bp.route("/faculty-contracts", methods=["POST"])
def issue_contract():
    middleware.require_role(PROGRAM_DEAN)
    payload = validate.body()

    provisional = lookup.maybe("faculty_members", payload.get("faculty_member_id"))
    if provisional is not None:
        middleware.require_dean_owns(provisional.get("home_program_id"))

    faculty_id = validate.req_str(payload, "faculty_member_id")
    term_id = validate.req_str(payload, "term_id")
    employment_class = validate.req_enum(payload, "employment_class", EMPLOYMENT_CLASSES)
    credit_hours = validate.req_num(payload, "contract_credit_hours", exclusive_min=0)
    expected_version = validate.req_int(payload, "expected_faculty_version")

    if provisional is not None and provisional["employment_class"] != employment_class:
        validate.bad("Field 'employment_class' must equal the faculty member's current "
                     "employment class.")

    faculty = lookup.faculty(faculty_id)
    term = lookup.term(term_id)

    if expected_version != faculty["version"]:
        raise ApiError("ERR_STALE_FACULTY_VERSION")

    guards.require_not_separated(faculty)
    guards.require_dossier_verified(faculty)

    start_date = util.parse_date(term["start_date"])
    if start_date is None or clock.current_date() >= start_date:
        raise ApiError("ERR_CONTRACT_WINDOW_CLOSED")

    row = db.new_row(
        faculty_member_id=faculty_id,
        term_id=term_id,
        employment_class=employment_class,
        contract_credit_hours=credit_hours,
        status="ISSUED",
        issued_at=clock.stamp(),
        countersigned_at=None,
        dossier_snapshot_status=faculty["dossier_status"],
        credential_snapshot_version=faculty["version"],
    )
    store.contracts[row["id"]] = row

    for contract in lookup.contracts_of_faculty(faculty_id):
        if contract["id"] == row["id"]:
            continue
        if contract["term_id"] != term_id:
            continue
        if contract["status"] in ("ISSUED", "COUNTERSIGNED"):
            contract["status"] = "SUPERSEDED"
            touch(contract)

    touch(faculty)
    return response.created(serialize.contract(row))


@bp.route("/faculty-contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    middleware.require_role(*ALL_ROLES)
    row = lookup.contract(contract_id)
    middleware.require_instructor_owns(row.get("faculty_member_id"))
    return response.ok(serialize.contract(row))


@bp.route("/faculty-contracts", methods=["GET"])
def list_contracts():
    middleware.require_role(*READ_ROLES)
    faculty_id = validate.q_str("faculty_member_id")
    term_id = validate.q_str("term_id")
    status = validate.q_enum("status", CONTRACT_STATUSES)
    employment_class = validate.q_enum("employment_class", EMPLOYMENT_CLASSES)
    rows = [r for r in db.ordered(store.contracts)
            if match(r, "faculty_member_id", faculty_id)
            and match(r, "term_id", term_id)
            and match(r, "status", status)
            and match(r, "employment_class", employment_class)]
    return list_response(rows, serialize.contract)


@bp.route("/faculty-contracts/<contract_id>/countersignature", methods=["POST"])
def countersign_contract(contract_id):
    middleware.require_role(INSTRUCTOR)
    provisional = lookup.maybe("contracts", contract_id)
    if provisional is not None:
        middleware.require_instructor_owns(provisional.get("faculty_member_id"))
    validate.body()

    contract = lookup.contract(contract_id)

    if contract["status"] != "ISSUED":
        guards.invalid_state("A contract in %s may not be countersigned."
                             % contract["status"])

    faculty = store.faculty_members.get(contract["faculty_member_id"])
    if faculty is not None:
        guards.require_not_separated(faculty)

    contract["status"] = "COUNTERSIGNED"
    contract["countersigned_at"] = clock.stamp()
    touch(contract)

    if faculty is not None:
        faculty["appointment_status"] = "CONTRACTED"
        touch(faculty)

    return response.ok(serialize.contract(contract))


@bp.route("/faculty-contracts/<contract_id>/void", methods=["POST"])
def void_contract(contract_id):
    middleware.require_role(PROGRAM_DEAN)
    provisional = lookup.maybe("contracts", contract_id)
    if provisional is not None:
        owner = store.faculty_members.get(provisional["faculty_member_id"])
        if owner is not None:
            middleware.require_dean_owns(owner.get("home_program_id"))
    payload = validate.body()
    validate.opt_str(payload, "reason")

    contract = lookup.contract(contract_id)

    if contract["status"] not in ("ISSUED", "COUNTERSIGNED"):
        guards.invalid_state("A contract in %s may not be voided." % contract["status"])

    contract["status"] = "VOIDED"
    touch(contract)

    faculty = store.faculty_members.get(contract["faculty_member_id"])
    if faculty is not None:
        live = [c for c in lookup.contracts_of_faculty(faculty["id"])
                if c["status"] in ("ISSUED", "COUNTERSIGNED")]
        if not live and faculty["appointment_status"] == "CONTRACTED":
            faculty["appointment_status"] = "CREDENTIALED_ELIGIBLE"
            touch(faculty)

    return response.ok(serialize.contract(contract))
