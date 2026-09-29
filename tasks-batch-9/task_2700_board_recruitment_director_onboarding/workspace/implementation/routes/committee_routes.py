"""Committees, their assignments and the seat ledger."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    SEATED_DIRECTOR,
    require,
)
from calc import parse_iso_date
from derive import committee_assignments, recompute_committee
from errors import fail
from payload import (
    body,
    check_enum,
    check_interval_on_or_after,
    check_min,
    optional,
    parse_date,
    required,
)
from store import clock_instant, db, new_row, touch
from vocab import ASSIGNMENT_SEAT_ROLE, COMMITTEE_CODE

from routes.common import apply_filters, by_created_at, by_field, emit, emit_list, need

bp = Blueprint("committee", __name__)

READ_ROLES = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER,
              SEATED_DIRECTOR)
OCCUPYING_TERM = ("PROPOSED", "ACTIVE")


@bp.post("/committees")
def charter_committee():
    require(CORPORATE_SECRETARY)
    b = body()
    code = required(b, "code", "string")
    name = required(b, "name", "string")
    authorized_seats = required(b, "authorized_seats", "integer")
    min_seats = optional(b, "min_seats", "integer", 3)
    requires_all_independent = optional(b, "requires_all_independent", "boolean", False)
    requires_financial_expert = optional(b, "requires_financial_expert", "boolean", False)
    check_enum("code", code, COMMITTEE_CODE)
    check_min("authorized_seats", authorized_seats, 1)
    check_min("min_seats", min_seats, 1)
    for row in db.committees.values():
        if row["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE", "Committee %s is already chartered." % code)
        if row["name"] == name:
            fail("ERR_DUPLICATE_RESOURCE", "A committee named %s already exists." % name)
    row = new_row({
        "code": code,
        "name": name,
        "authorized_seats": authorized_seats,
        "min_seats": min_seats,
        "requires_all_independent": requires_all_independent,
        "requires_financial_expert": requires_financial_expert,
        "filled_seats": 0,
        "status": "UNDER_STRENGTH",
    })
    db.committees[row["id"]] = row
    return emit(row, 201)


@bp.get("/committees/<committee_id>")
def read_committee(committee_id):
    require(*READ_ROLES)
    return emit(need("committee", committee_id))


@bp.get("/committees")
def list_committees():
    require(*READ_ROLES)
    rows = apply_filters(list(db.committees.values()), {"status": ("status", "str")})
    return emit_list(by_field(rows, "code"))


@bp.post("/committees/<committee_id>/assignments")
def propose_assignment(committee_id):
    require(CORPORATE_SECRETARY)
    b = body()
    director_id = required(b, "director_id", "string")
    term_start_on = required(b, "term_start_on", "string")
    term_end_on = required(b, "term_end_on", "string")
    expected_version = required(b, "expected_committee_version", "integer")
    seat_role = check_enum("seat_role", optional(b, "seat_role", "string", "MEMBER"),
                           ASSIGNMENT_SEAT_ROLE)
    start_date = parse_date(term_start_on, "term_start_on")
    end_date = parse_date(term_end_on, "term_end_on")
    check_interval_on_or_after(end_date, start_date,
                               "term_end_on must fall on or after term_start_on.")
    committee = need("committee", committee_id)
    director = need("director", director_id)
    if expected_version != committee["version"]:
        fail("ERR_STALE_COMMITTEE_VERSION",
             "expected_committee_version %s does not match the committee version %s."
             % (expected_version, committee["version"]))
    if committee["requires_all_independent"] and not director["is_independent"]:
        fail("ERR_COMMITTEE_INDEPENDENCE_REQUIRED",
             "This committee seats only independent directors.")
    for row in committee_assignments(committee_id):
        if row["director_id"] != director_id or row["status"] not in OCCUPYING_TERM:
            continue
        other_start = parse_iso_date(row["term_start_on"])
        other_end = parse_iso_date(row["term_end_on"])
        if other_start is None or other_end is None:
            continue
        if start_date <= other_end and other_start <= end_date:
            fail("ERR_ASSIGNMENT_TERM_OVERLAP",
                 "That term overlaps an existing assignment of this director.")
    row = new_row({
        "committee_id": committee_id,
        "director_id": director_id,
        "seat_role": seat_role,
        "term_start_on": term_start_on,
        "term_end_on": term_end_on,
        "status": "PROPOSED",
        "ended_reason_code": None,
        "activated_at": None,
        "ended_at": None,
    })
    db.assignments[row["id"]] = row
    touch(committee)
    return emit(row, 201)


@bp.get("/assignments/<assignment_id>")
def read_assignment(assignment_id):
    require(*READ_ROLES)
    return emit(need("assignment", assignment_id))


@bp.get("/assignments")
def list_assignments():
    require(*READ_ROLES)
    rows = apply_filters(list(db.assignments.values()), {
        "committee_id": ("committee_id", "str"),
        "director_id": ("director_id", "str"),
        "status": ("status", "str"),
    })
    return emit_list(by_created_at(rows))


@bp.post("/assignments/<assignment_id>/activate")
def activate_assignment(assignment_id):
    require(CORPORATE_SECRETARY)
    row = need("assignment", assignment_id)
    if row["status"] != "PROPOSED":
        fail("ERR_ASSIGNMENT_STATE_INVALID",
             "Only a PROPOSED assignment may be activated; this one is %s." % row["status"])
    committee = db.committees.get(row["committee_id"])
    director = db.directors.get(row["director_id"])
    if director is None or director["service_status"] != "SEATED":
        fail("ERR_DIRECTOR_NOT_SEATABLE",
             "Only a SEATED director may take a committee seat.")
    if committee is None or committee["status"] == "SUSPENDED":
        fail("ERR_DIRECTOR_NOT_SEATABLE",
             "A SUSPENDED committee may not seat a new assignment.")
    if committee["requires_all_independent"] and not director["is_independent"]:
        fail("ERR_COMMITTEE_INDEPENDENCE_REQUIRED",
             "This committee seats only independent directors.")
    active = [a for a in committee_assignments(committee["id"]) if a["status"] == "ACTIVE"]
    if row["seat_role"] == "CHAIR":
        for other in active:
            if other["seat_role"] == "CHAIR":
                fail("ERR_DUPLICATE_RESOURCE",
                     "This committee already holds an ACTIVE chair.")
    if len(active) + 1 > committee["authorized_seats"]:
        fail("ERR_COMMITTEE_SEATS_EXHAUSTED",
             "The committee already fills %s of %s authorized seats."
             % (len(active), committee["authorized_seats"]))
    row["status"] = "ACTIVE"
    row["activated_at"] = clock_instant()
    touch(row)
    touch(committee)
    recompute_committee(committee)
    return emit(row)


@bp.post("/assignments/<assignment_id>/revoke")
def revoke_assignment(assignment_id):
    require(CORPORATE_SECRETARY)
    row = need("assignment", assignment_id)
    if row["status"] not in OCCUPYING_TERM:
        fail("ERR_ASSIGNMENT_STATE_INVALID",
             "An assignment that is %s may not be revoked." % row["status"])
    row["status"] = "REVOKED"
    row["ended_reason_code"] = "REVOCATION"
    row["ended_at"] = clock_instant()
    touch(row)
    committee = db.committees.get(row["committee_id"])
    if committee is not None:
        touch(committee)
        recompute_committee(committee)
    return emit(row)
