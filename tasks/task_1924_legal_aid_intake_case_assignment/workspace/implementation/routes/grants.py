"""GrantProgram management and cascades (PRD section 3.9), plus report
generation nested under a program."""
from decimal import Decimal
from flask import Blueprint, g, request

from db import db, new_id
from errors import (ERR_GRANT_HAS_RESERVED_FUNDS, ERR_GRANT_PERIOD_OVERLAP,
                    ERR_INVALID_GRANT_STATE, ERR_INVALID_REPORT_STATE,
                    ERR_INVALID_REQUEST, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services import derived
from services.calc import round2
from services.common import get_or_404, list_response, stamp_new, touch
from services.enums import CASE_TYPES
from services.serialize import (grant_program_json, grant_report_json,
                                grant_utilization_json)
from validators import (as_date, body, check_allowed, req_date, req_int,
                        req_list, req_number, req_str)

bp = Blueprint("grants", __name__)

_REPORT_READ_ROLES = ["SupervisingAttorney", "GrantsManager", "ProgramDirector"]


def _get_program(gid):
    return get_or_404(db.grant_programs, gid)


@bp.route("/grant-programs", methods=["POST"])
@require_roles(["ProgramDirector"])
def create_grant_program():
    b = body()
    check_allowed(b, ["name", "funder", "period_start", "period_end",
                      "allowed_case_types", "allowed_counties",
                      "income_cap_percentage", "per_case_rate_cents",
                      "total_budget_cents"])
    name = req_str(b, "name")
    funder = req_str(b, "funder")
    period_start = req_date(b, "period_start")
    period_end = req_date(b, "period_end")
    if as_date(period_end) < as_date(period_start):
        fail(ERR_INVALID_REQUEST, "period_end must not precede period_start")
    allowed_case_types = req_list(b, "allowed_case_types",
                                  enum_values=CASE_TYPES)
    allowed_counties = req_list(b, "allowed_counties")
    income_cap = req_number(b, "income_cap_percentage")
    rate = req_int(b, "per_case_rate_cents", min_v=0)
    budget = req_int(b, "total_budget_cents", min_v=0)
    # Same-funder closed-interval overlap; boundary-touching IS overlap.
    new_s, new_e = as_date(period_start), as_date(period_end)
    for other in db.grant_programs.values():
        if other["funder"] != funder:
            continue
        o_s, o_e = as_date(other["period_start"]), as_date(other["period_end"])
        if new_s <= o_e and o_s <= new_e:
            fail(ERR_GRANT_PERIOD_OVERLAP,
                 "Another program from this funder has an overlapping period")
    rec = {
        "id": new_id(),
        "name": name,
        "funder": funder,
        "period_start": period_start,
        "period_end": period_end,
        "allowed_case_types": allowed_case_types,
        "allowed_counties": allowed_counties,
        "income_cap_percentage": income_cap,
        "per_case_rate_cents": rate,
        "total_budget_cents": budget,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.grant_programs[rec["id"]] = rec
    return ok_object(grant_program_json(rec), 201)


@bp.route("/grant-programs/<gid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_grant_program(gid):
    return ok_object(grant_program_json(_get_program(gid)))


@bp.route("/grant-programs", methods=["GET"])
@require_roles(ALL_ROLES)
def list_grant_programs():
    records = list(db.grant_programs.values())
    for param in ("funder", "status"):
        value = request.args.get(param)
        if value is not None:
            records = [g for g in records if g[param] == value]
    return list_response(records, grant_program_json)


@bp.route("/grant-programs/<gid>/suspend", methods=["POST"])
@require_roles(["ProgramDirector"])
def suspend_grant_program(gid):
    program = _get_program(gid)
    b = body()
    check_allowed(b, [])
    if program["status"] != "ACTIVE":
        fail(ERR_INVALID_GRANT_STATE,
             "Only an ACTIVE program can be suspended")
    program["status"] = "SUSPENDED"
    touch(program)
    # Cascade links 1-3: freeze funding, force OPEN -> ON_HOLD, which
    # releases attorney load (load is derived from OPEN cases).
    for case in db.cases.values():
        if (case["grant_program_id"] == program["id"]
                and case["funding_status"] == "GRANT_RESERVED"):
            case["funding_status"] = "GRANT_FROZEN"
            if case["status"] == "OPEN":
                case["status"] = "ON_HOLD"
            touch(case)
            if case["assigned_attorney_id"] is not None:
                attorney = db.staff.get(case["assigned_attorney_id"])
                if attorney is not None:
                    touch(attorney)
    return ok_object(grant_program_json(program))


@bp.route("/grant-programs/<gid>/resume", methods=["POST"])
@require_roles(["ProgramDirector"])
def resume_grant_program(gid):
    program = _get_program(gid)
    b = body()
    check_allowed(b, [])
    if program["status"] != "SUSPENDED":
        fail(ERR_INVALID_GRANT_STATE,
             "Only a SUSPENDED program can be resumed")
    program["status"] = "ACTIVE"
    touch(program)
    # Unfreeze funding; cases stay ON_HOLD for manual resume.
    for case in db.cases.values():
        if (case["grant_program_id"] == program["id"]
                and case["funding_status"] == "GRANT_FROZEN"):
            case["funding_status"] = "GRANT_RESERVED"
            touch(case)
    return ok_object(grant_program_json(program))


@bp.route("/grant-programs/<gid>/close", methods=["POST"])
@require_roles(["ProgramDirector"])
def close_grant_program(gid):
    program = _get_program(gid)
    b = body()
    check_allowed(b, [])
    if program["status"] not in ("ACTIVE", "SUSPENDED"):
        fail(ERR_INVALID_GRANT_STATE,
             "Only an ACTIVE or SUSPENDED program can be closed")
    if derived.grant_reserved_cents(program["id"]) != 0:
        fail(ERR_GRANT_HAS_RESERVED_FUNDS,
             "Program still has reserved funds (frozen cases still reserve)")
    program["status"] = "CLOSED"
    touch(program)
    return ok_object(grant_program_json(program))


@bp.route("/grant-programs/<gid>/utilization", methods=["GET"])
@require_roles(ALL_ROLES)
def get_grant_utilization(gid):
    return ok_object(grant_utilization_json(_get_program(gid)))


# ---- Grant report generation / listing (nested under programs) ----

def _compute_aggregates(program):
    cases = [c for c in db.cases.values()
             if c["grant_program_id"] == program["id"]]
    opened = sum(1 for c in cases if c["opened_at"] is not None)
    closed = sum(1 for c in cases if c["status"] == "CLOSED")
    case_ids = {c["id"] for c in cases}
    hours = Decimal(0)
    for t in db.time_entries.values():
        if t["case_id"] in case_ids:
            hours += t["hours"]
    return {
        "cases_opened_count": opened,
        "cases_closed_count": closed,
        "total_hours": round2(hours),
        "reserved_cents_snapshot": derived.grant_reserved_cents(
            program["id"]),
        "spent_cents_snapshot": derived.grant_spent_cents(program["id"]),
    }


@bp.route("/grant-programs/<gid>/reports", methods=["POST"])
@require_roles(["GrantsManager"])
def generate_report(gid):
    program = _get_program(gid)
    b = body()
    check_allowed(b, ["period_label"])
    period_label = req_str(b, "period_label")
    for r in db.grant_reports.values():
        if (r["grant_program_id"] == program["id"]
                and r["status"] in ("DRAFT", "SUBMITTED")):
            fail(ERR_INVALID_REPORT_STATE,
                 "A DRAFT or SUBMITTED report already exists for this program")
    rec = {
        "id": new_id(),
        "grant_program_id": program["id"],
        "period_label": period_label,
        "status": "DRAFT",
        "generated_by_user_id": g.user_id,
        "return_reason": None,
    }
    rec.update(_compute_aggregates(program))
    stamp_new(rec)
    db.grant_reports[rec["id"]] = rec
    return ok_object(grant_report_json(rec), 201)


@bp.route("/grant-programs/<gid>/reports", methods=["GET"])
@require_roles(_REPORT_READ_ROLES)
def list_reports(gid):
    program = _get_program(gid)
    records = [r for r in db.grant_reports.values()
               if r["grant_program_id"] == program["id"]]
    return list_response(records, grant_report_json)
