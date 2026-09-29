"""The logical clock, clients and consultants (PRD 2.6, 3.1)."""

import re

from flask import Blueprint

from calc import DECISION_PROCESSES, GRADES, INDUSTRY_CODES, PRACTICE_CODES
from db import db, fmt_ts, new_row, touch
from errors import fail
from middleware import READ_ROLES, ROLE_ADMIN, require_roles
from response import ok
from routes.common import fetch, filtered, paged
from serializers import client_out, consultant_out
from validators import (
    bool_arg,
    filter_arg,
    get_bool,
    get_datetime,
    get_enum,
    get_int,
    get_str,
    get_str_list,
    json_body,
)

bp = Blueprint("masterdata", __name__)

CLIENT_STATUSES = ("ACTIVE", "CREDIT_HOLD", "INACTIVE")
CODE_RE = re.compile(r"^[A-Z0-9]+$")


# ------------------------------------------------------------------ logical clock


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(ROLE_ADMIN)
    body = json_body()
    moment = get_datetime(body, "current_utc")
    if moment < db.clock:
        fail(
            "ERR_CLOCK_REWIND_FORBIDDEN",
            "The logical clock is forward-only and may not be rewound.",
        )
    db.clock = moment
    return ok({"current_utc": fmt_ts(db.clock)})


# ------------------------------------------------------------------ clients


@bp.post("/clients")
def create_client():
    require_roles(ROLE_ADMIN)
    body = json_body()
    name = get_str(body, "name", min_len=1, max_len=200)
    client_code = get_str(body, "client_code", min_len=2, max_len=10)
    if not CODE_RE.match(client_code):
        fail("ERR_INVALID_REQUEST", "client_code must use uppercase letters and digits only.")
    industry_code = get_enum(body, "industry_code", INDUSTRY_CODES)
    decision_process = get_enum(body, "decision_process", DECISION_PROCESSES)
    budget = get_int(body, "stated_budget_authority_cents", minimum=0)
    codes = get_str_list(body, "adverse_party_codes", required=False, max_items=10, default=[])
    for code in codes:
        if not CODE_RE.match(code):
            fail("ERR_INVALID_REQUEST", "adverse_party_codes must be uppercase codes.")

    for existing in db.clients.values():
        if existing["client_code"] == client_code:
            fail("ERR_CLIENT_CODE_TAKEN", "client_code %s is already registered." % client_code)

    row = new_row(
        {
            "name": name,
            "client_code": client_code,
            "industry_code": industry_code,
            "decision_process": decision_process,
            "adverse_party_codes": list(codes),
            "stated_budget_authority_cents": budget,
            "status": "ACTIVE",
            "completed_engagement_count": 0,
            "at_risk_engagement_count": 0,
        }
    )
    db.clients[row["id"]] = row
    return ok(client_out(row), 201)


@bp.get("/clients/<client_id>")
def read_client(client_id):
    require_roles(*READ_ROLES)
    return ok(client_out(fetch("clients", client_id)))


@bp.get("/clients")
def list_clients():
    require_roles(*READ_ROLES)
    code = filter_arg("client_code")
    status = filter_arg("status")

    def keep(row):
        if code is not None and row["client_code"] != code:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paged(filtered("clients", keep), client_out)


@bp.post("/clients/<client_id>/status")
def set_client_status(client_id):
    require_roles(ROLE_ADMIN)
    body = json_body()
    status = get_enum(body, "status", CLIENT_STATUSES)
    row = fetch("clients", client_id)
    row["status"] = status
    touch(row)
    return ok(client_out(row))


# ------------------------------------------------------------------ consultants


@bp.post("/consultants")
def create_consultant():
    require_roles(ROLE_ADMIN)
    body = json_body()
    name = get_str(body, "name", min_len=1, max_len=120)
    grade = get_enum(body, "grade", GRADES)
    practice_code = get_enum(body, "practice_code", PRACTICE_CODES)
    cost_rate = get_int(body, "cost_rate_cents_per_hour", minimum=1)
    certified = get_bool(body, "quality_reviewer_certified", required=False, default=False)

    row = new_row(
        {
            "name": name,
            "grade": grade,
            "practice_code": practice_code,
            "cost_rate_cents_per_hour": cost_rate,
            "quality_reviewer_certified": certified,
        }
    )
    db.consultants[row["id"]] = row
    return ok(consultant_out(row), 201)


@bp.get("/consultants/<consultant_id>")
def read_consultant(consultant_id):
    require_roles(*READ_ROLES)
    return ok(consultant_out(fetch("consultants", consultant_id)))


@bp.get("/consultants")
def list_consultants():
    require_roles(*READ_ROLES)
    practice_code = filter_arg("practice_code")
    grade = filter_arg("grade")
    certified = bool_arg("quality_reviewer_certified")

    def keep(row):
        if practice_code is not None and row["practice_code"] != practice_code:
            return False
        if grade is not None and row["grade"] != grade:
            return False
        if certified is not None and row["quality_reviewer_certified"] is not certified:
            return False
        return True

    return paged(filtered("consultants", keep), consultant_out)
