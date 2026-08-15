"""Program endpoints: create, read, funder-report, nested market/shopper lists."""

from flask import Blueprint

from db import STORE, stamp_new
from errors import ApiError, ERR_INVALID_REQUEST
from logical_clock import _parse_iso
from middleware import (
    ensure_valid_json,
    fail_shape,
    paginate,
    req_datetime,
    req_int,
    req_str,
)
from response import success_list, success_object
from routes.common import Pipeline, get_path_entity
from services.domain import (
    iso,
    program_liabilities,
    program_paid_out,
    program_pool_remaining,
    serialize_market,
    serialize_program,
    serialize_shopper,
)

bp = Blueprint("programs", __name__)


@bp.route("/programs", methods=["POST"])
def create_program():
    pipe = Pipeline(["ProgramAdmin"], is_write=True)
    body = pipe.body
    ensure_valid_json(body)
    name = req_str(body, "name")
    season_start = req_datetime(body, "season_start")
    season_end = req_datetime(body, "season_end")
    budget = req_int(body, "match_pool_budget_cents")
    if budget < 0:
        fail_shape("match_pool_budget_cents must be >= 0")
    program = stamp_new({
        "name": name,
        "season_start": iso(season_start),
        "season_end": iso(season_end),
        "match_pool_budget_cents": budget,
    })
    STORE["programs"][program["id"]] = program
    env, status = success_object(serialize_program(program), 201)
    pipe.commit(status, env.get_json())
    return env, status


@bp.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    Pipeline(
        ["ProgramAdmin", "MarketManager", "BoothOperator", "Auditor", "Vendor", "Shopper"],
        is_write=False,
    )
    program = get_path_entity("programs", pid)
    return success_object(serialize_program(program))


@bp.route("/programs/<pid>/funder-report", methods=["GET"])
def funder_report(pid):
    Pipeline(["ProgramAdmin", "Auditor"], is_write=False)
    program = get_path_entity("programs", pid)

    # Optional half-open window over issuance created_at (PRD §3.8).
    from flask import request
    period_start_raw = request.args.get("period_start")
    period_end_raw = request.args.get("period_end")
    period_start = period_end = None
    if period_start_raw is not None:
        try:
            period_start = _parse_iso(period_start_raw)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "period_start must be ISO 8601")
    if period_end_raw is not None:
        try:
            period_end = _parse_iso(period_end_raw)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "period_end must be ISO 8601")

    def in_window(dt_str):
        dt = _parse_iso(dt_str)
        if period_start is not None and dt < period_start:
            return False
        if period_end is not None and dt >= period_end:
            return False
        return True

    from services.domain import program_id_of_issuance, program_id_of_submission

    issued_base = 0
    issued_match = 0
    for issuance in STORE["issuances"].values():
        if issuance["status"] != "ACTIVE":
            continue
        if program_id_of_issuance(issuance) != program["id"]:
            continue
        if not in_window(issuance["created_at"]):
            continue
        issued_base += issuance["base_value_cents"]
        issued_match += issuance["match_cents"]

    redeemed = 0
    for token in STORE["tokens"].values():
        if token["status"] not in ("REDEEMED", "SETTLED"):
            continue
        issuance = STORE["issuances"].get(token["issuance_id"])
        if not issuance or program_id_of_issuance(issuance) != program["id"]:
            continue
        if not in_window(issuance["created_at"]):
            continue
        redeemed += token["denomination_cents"]

    reimbursed = 0
    for sub in STORE["submissions"].values():
        if sub["status"] == "PAID" and program_id_of_submission(sub) == program["id"]:
            reimbursed += sub.get("paid_amount_cents") or 0

    forward, realized = program_liabilities(program)
    remaining = program_pool_remaining(program)
    budget = program["match_pool_budget_cents"]
    utilization_bp = 0 if budget == 0 else (10000 * (budget - remaining)) // budget
    days_flagged = sum(
        1
        for d in STORE["market_days"].values()
        if d["status"] == "VARIANCE_FLAGGED"
        and STORE["markets"].get(d["market_id"])
        and STORE["markets"][d["market_id"]]["program_id"] == program["id"]
    )

    report = {
        "issued_base_cents": issued_base,
        "issued_match_cents": issued_match,
        "redeemed_cents": redeemed,
        "reimbursed_cents": reimbursed,
        "match_pool_remaining_cents": remaining,
        "liability_forward_cents": forward,
        "liability_realized_cents": realized,
        "utilization_bp": utilization_bp,
        "days_flagged_count": days_flagged,
    }
    return success_object(report)


@bp.route("/programs/<pid>/markets", methods=["GET"])
def list_program_markets(pid):
    Pipeline(["ProgramAdmin", "MarketManager", "Auditor"], is_write=False)
    program = get_path_entity("programs", pid)
    items = [m for m in STORE["markets"].values() if m["program_id"] == program["id"]]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_market(m) for m in page], limit, offset, total)


@bp.route("/programs/<pid>/shoppers", methods=["GET"])
def list_program_shoppers(pid):
    Pipeline(["ProgramAdmin", "MarketManager", "BoothOperator", "Auditor"], is_write=False)
    program = get_path_entity("programs", pid)
    from flask import request
    status_filter = request.args.get("status")
    items = [s for s in STORE["shoppers"].values() if s["program_id"] == program["id"]]
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_shopper(s) for s in page], limit, offset, total)
