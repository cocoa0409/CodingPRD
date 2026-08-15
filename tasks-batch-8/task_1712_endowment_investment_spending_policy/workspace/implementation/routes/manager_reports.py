from flask import Blueprint

from constants import ALL_ROLES, QUARTER_DAYS
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services.calc import compute_manager_returns, apply_excess_streak
from services.domain import get_or_404, list_response, pool_gate
from util import new_id, parse_body, req_str, req_int, is_int

bp = Blueprint("manager_reports", __name__)


@bp.route("/endowment/manager-quarter-reports", methods=["POST"])
def create_report():
    authenticate(["InvestmentOfficer"])
    body = parse_body(required=True)
    manager_id = req_str(body, "manager_id")
    quarter_index = req_int(body, "quarter_index")
    beginning = req_int(body, "beginning_mv_cents", minv=0)
    ending = req_int(body, "ending_mv_cents", minv=0)
    flows = body.get("flows")
    if flows is None:
        flows = []
    if not isinstance(flows, list):
        raise_err("ERR_INVALID_REQUEST", "flows must be an array")
    for i, f in enumerate(flows):
        if not isinstance(f, dict):
            raise_err("ERR_INVALID_REQUEST", f"flows[{i}] must be an object")
        day = f.get("day_offset")
        amt = f.get("amount_cents")
        if not is_int(day) or not (0 <= day < QUARTER_DAYS):
            raise_err(
                "ERR_INVALID_REQUEST",
                f"flows[{i}].day_offset must be an integer in 0..89",
            )
        if not is_int(amt) or amt == 0:
            raise_err(
                "ERR_INVALID_REQUEST",
                f"flows[{i}].amount_cents must be a non-zero integer",
            )
    benchmark = req_int(body, "benchmark_return_bps")

    manager = get_or_404(store.managers, manager_id, "InvestmentManager")
    if manager["engagement_status"] not in ("ENGAGED", "WATCHLIST", "PROBATION"):
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Reports may be filed only for ENGAGED, WATCHLIST, or PROBATION "
            f"managers (current: {manager['engagement_status']})",
        )
    pool = store.pools.get(manager["pool_id"])
    pool_gate(pool, "manager_report_create")

    duplicate = any(
        r["manager_id"] == manager_id and r["quarter_index"] == quarter_index
        for r in store.manager_reports.values()
    )
    if duplicate:
        raise_err(
            "ERR_DUPLICATE_RECORD",
            f"A report already exists for this manager and quarter "
            f"{quarter_index}",
        )

    open_quarter = pool["current_quarter_index"] + 1
    if quarter_index != open_quarter or quarter_index < manager["coverage_start_quarter"]:
        raise_err(
            "ERR_WINDOW_CONFLICT",
            "quarter_index must equal the pool's open quarter and be no "
            "earlier than coverage_start_quarter",
        )

    priors = [
        r
        for r in store.manager_reports.values()
        if r["manager_id"] == manager_id and r["quarter_index"] < quarter_index
    ]
    if priors:
        priors.sort(key=lambda r: r["quarter_index"])
        if beginning != priors[-1]["ending_mv_cents"]:
            raise_err(
                "ERR_MV_CONTINUITY_BREAK",
                "beginning_mv_cents must equal the manager's prior-quarter "
                "ending_mv_cents",
            )

    return_bps, simple_return_bps, excess_bps = compute_manager_returns(
        beginning, ending, flows, benchmark
    )

    rec = {
        "id": new_id(),
        "manager_id": manager_id,
        "quarter_index": quarter_index,
        "beginning_mv_cents": beginning,
        "ending_mv_cents": ending,
        "flows": flows,
        "benchmark_return_bps": benchmark,
        "return_bps": return_bps,
        "simple_return_bps": simple_return_bps,
        "excess_bps": excess_bps,
        "version": 1,
    }
    stamp_new(rec)
    store.manager_reports[rec["id"]] = rec

    apply_excess_streak(manager, excess_bps)
    bump(manager)
    return success(pub(rec), status=201)


@bp.route("/endowment/manager-quarter-reports", methods=["GET"])
def list_reports():
    authenticate(ALL_ROLES)
    return list_response(
        store.manager_reports,
        [
            ("manager_id", "manager_id", "str"),
            ("quarter_index", "quarter_index", "int"),
        ],
    )


@bp.route("/endowment/manager-quarter-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    authenticate(ALL_ROLES)
    return success(
        pub(get_or_404(store.manager_reports, report_id, "ManagerQuarterReport"))
    )
