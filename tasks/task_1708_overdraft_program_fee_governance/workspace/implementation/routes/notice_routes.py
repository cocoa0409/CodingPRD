from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_PROGRAM_SUSPENDED,
                    ERR_NOTICE_NOT_ELAPSED, ERR_NOTICE_OVERLAP,
                    ERR_STALE_PROGRAM)
from helpers import (auth, require_role, require_body, ok, ok_list, v_str,
                     v_int, v_enum, ALL_ROLES, sort_created)
from serializers import notice_to_dict

bp = Blueprint("notices", __name__)

PARAMETERS = ["FEE_AMOUNT", "DAILY_CAP_CENTS", "MAX_DAILY_FEES",
              "DE_MINIMIS", "POSTING_ORDER", "SUSTAINED_FEE"]

PARAM_FIELDS = {
    "FEE_AMOUNT": "fee_amount_cents",
    "DAILY_CAP_CENTS": "daily_fee_cap_cents",
    "MAX_DAILY_FEES": "max_daily_fees_count",
    "DE_MINIMIS": "de_minimis_threshold_cents",
    "POSTING_ORDER": "posting_order_policy",
    "SUSTAINED_FEE": "sustained_overdraft_fee_cents",
}


def get_notice_or_404(nid):
    n = db.store["notices"].get(nid)
    if n is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Notice %s not found" % nid)
    return n


@bp.post("/v1/notices")
def create_notice():
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    body = require_body()
    program_id = v_str(body, "program_id")
    parameter = v_enum(body, "parameter", PARAMETERS)
    new_value = v_str(body, "new_value")
    if parameter == "POSTING_ORDER":
        if new_value not in ("HIGH_TO_LOW", "CHRONOLOGICAL"):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "new_value for POSTING_ORDER must be a posting-order enum member")
    else:
        try:
            int(new_value)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "new_value must be an integer rendered as a string")
    expected_program_version = v_int(body, "expected_program_version")
    program = db.store["programs"].get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Program %s not found" % program_id)
    # Tier 13 (last): OCC against the parent program's version.
    if expected_program_version != program["version"]:
        raise ApiError(ERR_STALE_PROGRAM, 412,
                       "expected_program_version does not match the program's version")
    field = PARAM_FIELDS[parameter]
    old_value = str(program[field])
    # Supersede any existing DRAFT notice for the same program + parameter.
    for n in db.store["notices"].values():
        if (n["program_id"] == program_id and n["parameter"] == parameter
                and n["status"] == "DRAFT"):
            n["status"] = "SUPERSEDED"
            db.touch(n)
    n = db.new_entity({
        "program_id": program_id,
        "parameter": parameter,
        "new_value": new_value,
        "old_value": old_value,
        "status": "DRAFT",
        "sent_at": None,
        "effective_at": None,
    })
    db.store["notices"][n["id"]] = n
    db.touch(program)
    return ok(notice_to_dict(n), status=201)


@bp.get("/v1/notices")
def list_notices():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["notices"].values())
    program_id = request.args.get("program_id")
    parameter = request.args.get("parameter")
    status = request.args.get("status")
    if program_id is not None:
        items = [n for n in items if n["program_id"] == program_id]
    if parameter is not None:
        items = [n for n in items if n["parameter"] == parameter]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    return ok_list([notice_to_dict(n) for n in sort_created(items)])


@bp.get("/v1/notices/<nid>")
def get_notice(nid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    return ok(notice_to_dict(get_notice_or_404(nid)))


@bp.post("/v1/notices/<nid>/issue")
def issue_notice(nid):
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    n = get_notice_or_404(nid)
    if n["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT notice can be issued")
    program = db.store["programs"][n["program_id"]]
    now = db.clock_dt()
    new_eff = now + timedelta(days=program["notice_window_days"])
    # Half-open [sent_at, effective_at) windows may not overlap on the same
    # program+parameter; sent_at == prior effective_at is permitted.
    for other in db.store["notices"].values():
        if (other["id"] != n["id"] and other["program_id"] == n["program_id"]
                and other["parameter"] == n["parameter"]
                and other["status"] == "ISSUED"):
            o_sent = db.parse_ts(other["sent_at"])
            o_eff = db.parse_ts(other["effective_at"])
            if o_sent < new_eff and now < o_eff:
                raise ApiError(ERR_NOTICE_OVERLAP, 409,
                               "An ISSUED notice window already covers this parameter")
    n["sent_at"] = db.fmt_ts(now)
    n["effective_at"] = db.fmt_ts(new_eff)
    n["status"] = "ISSUED"
    db.touch(n)
    return ok(notice_to_dict(n))


@bp.post("/v1/notices/<nid>/activate")
def activate_notice(nid):
    _, role = auth()
    require_role(role, ["ComplianceOfficer"])
    n = get_notice_or_404(nid)
    if n["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ISSUED notice can be activated")
    program = db.store["programs"][n["program_id"]]
    if program["status"] != "ACTIVE":
        raise ApiError(ERR_PROGRAM_SUSPENDED, 409,
                       "A SUSPENDED program refuses notice activation")
    if db.clock_dt() < db.parse_ts(n["effective_at"]):
        raise ApiError(ERR_NOTICE_NOT_ELAPSED, 409,
                       "The disclosure window has not yet elapsed")
    field = PARAM_FIELDS[n["parameter"]]
    if n["parameter"] == "POSTING_ORDER":
        program[field] = n["new_value"]
    else:
        program[field] = int(n["new_value"])
    db.touch(program)
    n["status"] = "EFFECTIVE"
    db.touch(n)
    return ok(notice_to_dict(n))


@bp.post("/v1/notices/<nid>/withdraw")
def withdraw_notice(nid):
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    n = get_notice_or_404(nid)
    if n["status"] == "DRAFT":
        pass
    elif n["status"] == "ISSUED":
        if db.clock_dt() >= db.parse_ts(n["effective_at"]):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "An already-effective notice cannot be withdrawn")
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT or ISSUED notice can be withdrawn")
    n["status"] = "WITHDRAWN"
    db.touch(n)
    return ok(notice_to_dict(n))
