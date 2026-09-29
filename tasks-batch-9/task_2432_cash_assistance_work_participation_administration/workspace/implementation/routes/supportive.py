"""Supportive service authorizations and the fiscal-year cap waterfall (PRD 3.8)."""

from flask import Blueprint

import guards
from calc import fiscal_year_of_date
from domain import (auths_of_case, lookup, recompute_supportive_fy, rows_where,
                    supportive_waterfall)
from errors import fail
from guards import Fields, body_str, raw_body, require
from respond import created, filter_value, listing, ok, pagination
from store import clock_fiscal_year, db, new_record, touch

bp = Blueprint("supportive", __name__)

SERVICE_TYPES = ("TRANSPORTATION", "CHILD_CARE", "WORK_EXPENSE")
BLOCKING_STATUSES = ("REQUESTED", "HELD", "AUTHORIZED")
RELEASE_COMPLIANCE = ("ASSIGNED", "EXEMPT", "NOT_REQUIRED")


def _auth(auth_id):
    return lookup("supportive_auths", auth_id, "ERR_AUTHORIZATION_NOT_FOUND")


@bp.post("/supportive-service-authorizations")
def request_service():
    require(guards.SPECIALIST)
    body = raw_body()
    candidate_case = body_str(body, "case_id")
    if candidate_case is not None:
        lookup("cases", candidate_case, "ERR_CASE_NOT_FOUND")
    candidate_assignment = body_str(body, "work_assignment_id")
    if candidate_assignment is not None:
        lookup("work_assignments", candidate_assignment,
               "ERR_WORK_ASSIGNMENT_NOT_FOUND")
    fields = Fields(body)
    fields.identifier("case_id")
    fields.identifier("work_assignment_id")
    fields.enum("service_type", SERVICE_TYPES)
    fields.integer("requested_amount_cents", minimum=1)
    fields.date("period_start")
    fields.date("period_end")
    fields.integer("expected_case_version")

    case = db.cases[fields["case_id"]]
    assignment = db.work_assignments[fields["work_assignment_id"]]
    if fields["expected_case_version"] != case["version"]:
        fail("ERR_STALE_CASE_VERSION", "The case has changed since it was read.")
    start = fields["period_start"]
    end = fields["period_end"]
    if end < start:
        fail("ERR_SERVICE_PERIOD_OVERLAP",
             "period_end must fall on or after period_start.")
    for other in auths_of_case(case["id"]):
        if other["service_type"] != fields["service_type"]:
            continue
        if other["status"] not in BLOCKING_STATUSES:
            continue
        if start <= other["period_end"] and other["period_start"] <= end:
            fail("ERR_SERVICE_PERIOD_OVERLAP",
                 "The service period overlaps an existing authorization.")
    if assignment["case_id"] != case["id"]:
        fail("ERR_WORK_ASSIGNMENT_CASE_MISMATCH",
             "The work assignment does not belong to the given case.")

    auth = new_record({
        "case_id": case["id"],
        "work_assignment_id": assignment["id"],
        "service_type": fields["service_type"],
        "requested_amount_cents": fields["requested_amount_cents"],
        "period_start": start,
        "period_end": end,
        "fiscal_year": fiscal_year_of_date(start),
        "authorized_amount_cents": 0,
        "status": "REQUESTED",
        "void_reason": None,
    })
    db.supportive_auths[auth["id"]] = auth
    touch(case)
    return created(auth)


@bp.get("/supportive-service-authorizations/<auth_id>")
def read_auth(auth_id):
    require()
    return ok(_auth(auth_id))


@bp.get("/supportive-service-authorizations")
def search_auths():
    require(*guards.STAFF_ROLES)
    limit, offset = pagination()
    rows = rows_where("supportive_auths")
    for name in ("case_id", "work_assignment_id", "service_type", "status"):
        value = filter_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return listing(rows, limit, offset)


@bp.post("/supportive-service-authorizations/<auth_id>/authorize")
def authorize(auth_id):
    require(guards.SPECIALIST)
    auth = _auth(auth_id)
    if auth["status"] != "REQUESTED":
        fail("ERR_INVALID_AUTHORIZATION_STATE",
             "Only a REQUESTED authorization may be authorized.")
    assignment = db.work_assignments[auth["work_assignment_id"]]
    if assignment["status"] != "ACTIVE":
        fail("ERR_ASSIGNMENT_NOT_ACTIVE",
             "The supported work assignment must be ACTIVE.")
    case = db.cases[auth["case_id"]]
    awarded = supportive_waterfall(case, auth["service_type"], auth["fiscal_year"],
                                   auth["requested_amount_cents"])
    if awarded <= 0:
        fail("ERR_SUPPORTIVE_CAP_EXHAUSTED",
             "No supportive service funding remains for this type or case.")
    auth["status"] = "AUTHORIZED"
    auth["authorized_amount_cents"] = awarded
    touch(auth)
    recompute_supportive_fy(case, clock_fiscal_year())
    return ok(auth)


@bp.post("/supportive-service-authorizations/<auth_id>/void")
def void_auth(auth_id):
    require(guards.SPECIALIST, guards.FISCAL)
    auth = _auth(auth_id)
    fields = Fields(raw_body())
    fields.text("void_reason")
    if auth["status"] not in BLOCKING_STATUSES:
        fail("ERR_INVALID_AUTHORIZATION_STATE",
             "This authorization has already been voided.")
    auth["status"] = "VOIDED"
    auth["void_reason"] = fields["void_reason"]
    auth["authorized_amount_cents"] = 0
    touch(auth)
    case = db.cases[auth["case_id"]]
    recompute_supportive_fy(case, clock_fiscal_year())
    return ok(auth)


@bp.post("/supportive-service-authorizations/<auth_id>/release-hold")
def release_hold(auth_id):
    require(guards.SPECIALIST)
    auth = _auth(auth_id)
    if auth["status"] != "HELD":
        fail("ERR_INVALID_AUTHORIZATION_STATE",
             "Only a HELD authorization may be released.")
    case = db.cases[auth["case_id"]]
    if case["compliance_status"] not in RELEASE_COMPLIANCE:
        fail("ERR_ASSIGNMENT_NOT_ACTIVE",
             "The case compliance posture does not permit releasing the hold.")
    auth["status"] = "REQUESTED"
    touch(auth)
    return ok(auth)
