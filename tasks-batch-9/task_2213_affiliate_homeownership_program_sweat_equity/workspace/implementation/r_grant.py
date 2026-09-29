"""Grant awards and the households-served impact report."""
from flask import Blueprint

import calc
import derive
from common import API, created, get_grant, get_program, listing, match, okay
from errors import fail
from payload import body, qenum, qid, qstring, vbool, vdatetime, vint, vstring
from rbac import auth
from store import bump, db, stamp
from util import date_start

bp = Blueprint("grants", __name__)


@bp.post(API + "/grant-awards")
def create_grant():
    auth("ProgramAdmin")
    data = body()
    raw = data.get("program_id")
    program = get_program(raw) if isinstance(raw, str) and raw else None

    program_id = vstring(data, "program_id", 1, None, required=True)
    award_code = vstring(data, "award_code", 1, 40, required=True)
    funder = vstring(data, "funder_name", 1, 120, required=True, aliases=("donor_name",))
    amount = vint(data, "award_amount_cents", minimum=0, required=True,
                  aliases=("amount_cents",))
    period_start = vdatetime(data, "period_start", required=True)
    period_end = vdatetime(data, "period_end", required=True)
    target = vint(data, "households_served_target", minimum=1, maximum=500, required=True)
    restricted = vbool(data, "restricted_to_in_kind_reporting", default=False)
    if program is None:
        program = get_program(program_id)

    if period_end <= period_start:
        fail("ERR_VALIDATION", "period_end must be strictly after period_start.")

    for existing in db.grants.values():
        if existing.get("program_id") == program["id"] and \
                existing.get("award_code") == award_code:
            fail("ERR_VALIDATION", "award_code must be unique within the program.")

    row = {
        "program_id": program["id"],
        "award_code": award_code,
        "funder_name": funder,
        "award_amount_cents": amount,
        "households_served_target": target,
        "period_start": period_start,
        "period_end": period_end,
        "restricted_to_in_kind_reporting": bool(restricted),
        "status": "OPEN",
    }
    stamp(row)
    db.grants[row["id"]] = row
    return created(derive.public_grant(row))


@bp.get(API + "/grant-awards")
def list_grants():
    auth("ProgramAdmin", "MortgageOfficer")
    program_id = qid("program_id")
    status = qenum("status", ("OPEN", "REPORTED"))
    award_code = qstring("award_code")
    rows = [r for r in db.grants.values()
            if match(r, "program_id", program_id)
            and match(r, "status", status)
            and match(r, "award_code", award_code)]
    return listing(rows, derive.public_grant)


@bp.get(API + "/grant-awards/<gid>")
def read_grant(gid):
    auth("ProgramAdmin", "MortgageOfficer")
    grant = get_grant(gid)
    return okay(derive.public_grant(grant))


@bp.post(API + "/grant-awards/<gid>/impact-reports")
def impact_report(gid):
    auth("ProgramAdmin")
    grant = get_grant(gid)
    body()

    if grant.get("status") == "REPORTED":
        fail("ERR_REPORTING_PERIOD_OPEN")
    period_end = date_start(grant.get("period_end"))
    if period_end is None or db.now() < period_end:
        fail("ERR_REPORTING_PERIOD_OPEN")

    program = db.programs.get(grant.get("program_id"))
    if program is None:
        fail("ERR_PROGRAM_NOT_FOUND")

    report = calc.impact_report(grant, program)
    grant["status"] = "REPORTED"
    bump(grant)
    report["grant_award_id"] = grant["id"]
    report["award_code"] = grant.get("award_code")
    report["households_served_target"] = grant.get("households_served_target")
    return okay(derive.jsonable(report))
