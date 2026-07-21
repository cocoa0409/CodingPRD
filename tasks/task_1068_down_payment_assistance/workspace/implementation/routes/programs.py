from flask import Blueprint

import store
from errors import ApiError
import context as ctx
from serializers import public, public_list
import envelope as env

bp = Blueprint("programs", __name__)

RECAPTURE_MODELS = {"SHARED_APPRECIATION", "DECLINING_BALANCE"}
PROGRAM_READ_ROLES = ["ProgramAdmin", "CaseManager", "Applicant", "ClosingCoordinator", "Servicer"]


@bp.post("/programs")
def create_program():
    ctx.authenticate(["ProgramAdmin"])
    data = ctx.body()
    name = ctx.req_str(data, "name")
    ami_limit_pct = ctx.req_int(data, "ami_limit_pct", 1, 120)
    max_assistance_cents = ctx.req_int(data, "max_assistance_cents", 0)
    recapture_model = ctx.req_enum(data, "recapture_model", RECAPTURE_MODELS)
    recapture_term_months = ctx.opt_int(data, "recapture_term_months", 120, 1)
    appreciation_share_pct = ctx.opt_int(data, "appreciation_share_pct", 30, 0, 100)

    rec = store.new_record("program")
    rec.update({
        "name": name,
        "ami_limit_pct": ami_limit_pct,
        "max_assistance_cents": max_assistance_cents,
        "recapture_model": recapture_model,
        "recapture_term_months": recapture_term_months,
        "appreciation_share_pct": appreciation_share_pct,
        "status": "OPEN",
    })
    store.programs[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.post("/programs/<pid>/close")
def close_program(pid):
    ctx.authenticate(["ProgramAdmin"])
    prog = ctx.lookup("program", pid)
    if prog["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Program is not OPEN.")
    prog["status"] = "CLOSED"
    store.touch(prog)
    return env.success(public(prog), 200)


@bp.get("/programs/<pid>")
def get_program(pid):
    ctx.authenticate(PROGRAM_READ_ROLES)
    prog = ctx.lookup("program", pid)
    return env.success(public(prog), 200)


@bp.get("/programs")
def list_programs():
    ctx.authenticate(PROGRAM_READ_ROLES)
    limit, offset = ctx.pagination_params()
    page, total = ctx.paginate(
        store.programs.values(), limit, offset,
        {"status": ctx.query_filter("status")})
    return env.list_response(public_list(page), limit, offset, total)


@bp.post("/programs/<pid>/income-limits")
def create_income_limit(pid):
    ctx.authenticate(["ProgramAdmin"])
    prog = ctx.lookup("program", pid)
    data = ctx.body()
    household_size = ctx.req_int(data, "household_size", 1, 12)
    ami_100_income_cents = ctx.req_int(data, "ami_100_income_cents", 1)
    for il in store.income_limits.values():
        if il["program_id"] == pid and il["household_size"] == household_size:
            raise ApiError("ERR_DUPLICATE_INCOME_LIMIT",
                           "An income-limit row already exists for this household size.")
    rec = store.new_record("income_limit", versioned=False)
    rec.update({
        "program_id": pid,
        "household_size": household_size,
        "ami_100_income_cents": ami_100_income_cents,
    })
    store.income_limits[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.get("/programs/<pid>/income-limits")
def list_income_limits(pid):
    ctx.authenticate(["ProgramAdmin", "CaseManager"])
    ctx.lookup("program", pid)
    limit, offset = ctx.pagination_params()
    rows = [il for il in store.income_limits.values() if il["program_id"] == pid]
    page, total = ctx.paginate(rows, limit, offset)
    return env.list_response(public_list(page), limit, offset, total)


@bp.get("/programs/<pid>/education-sessions")
def list_program_sessions(pid):
    ctx.authenticate(["ProgramAdmin", "CaseManager", "Applicant"])
    ctx.lookup("program", pid)
    limit, offset = ctx.pagination_params()
    rows = [s for s in store.sessions.values() if s["program_id"] == pid]
    page, total = ctx.paginate(rows, limit, offset)
    return env.list_response(public_list(page), limit, offset, total)
