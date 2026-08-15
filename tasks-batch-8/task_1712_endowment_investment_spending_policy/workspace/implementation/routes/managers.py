from flask import Blueprint

from constants import ALL_ROLES, ASSET_CLASSES
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services.domain import get_or_404, list_response, pool_gate
from util import new_id, parse_body, req_str, req_int, req_enum

bp = Blueprint("managers", __name__)


def _terminated_gate(pool):
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )


@bp.route("/endowment/managers", methods=["POST"])
def create_manager():
    authenticate(["InvestmentOfficer"])
    body = parse_body(required=True)
    pool_id = req_str(body, "pool_id")
    manager_name = req_str(body, "manager_name")
    asset_class = req_enum(body, "asset_class", ASSET_CLASSES)
    benchmark_code = req_str(body, "benchmark_code")
    coverage_start = req_int(body, "coverage_start_quarter", minv=1)

    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    _terminated_gate(pool)

    rec = {
        "id": new_id(),
        "pool_id": pool_id,
        "manager_name": manager_name,
        "asset_class": asset_class,
        "benchmark_code": benchmark_code,
        "coverage_start_quarter": coverage_start,
        "coverage_end_quarter": None,
        "engagement_status": "PROSPECT",
        "neg_excess_streak": 0,
        "nonneg_excess_streak": 0,
        "version": 1,
    }
    stamp_new(rec)
    store.managers[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/managers", methods=["GET"])
def list_managers():
    authenticate(ALL_ROLES)
    return list_response(
        store.managers,
        [
            ("pool_id", "pool_id", "str"),
            ("asset_class", "asset_class", "str"),
            ("engagement_status", "engagement_status", "str"),
        ],
    )


@bp.route("/endowment/managers/<manager_id>", methods=["GET"])
def get_manager(manager_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.managers, manager_id, "InvestmentManager")))


@bp.route("/endowment/managers/<manager_id>/engage", methods=["POST"])
def engage_manager(manager_id):
    authenticate(["InvestmentOfficer"])
    manager = get_or_404(store.managers, manager_id, "InvestmentManager")
    if manager["engagement_status"] != "PROSPECT":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot engage a manager in state {manager['engagement_status']}",
        )
    pool = store.pools.get(manager["pool_id"])
    pool_gate(pool, "manager_engage")

    # Coverage exclusivity per (pool, asset_class); intervals inclusive.
    start = manager["coverage_start_quarter"]
    for other in store.managers.values():
        if other["id"] == manager["id"]:
            continue
        if other["pool_id"] != manager["pool_id"]:
            continue
        if other["asset_class"] != manager["asset_class"]:
            continue
        if other["engagement_status"] in ("PROSPECT", "DECLINED"):
            continue
        if other["engagement_status"] == "TERMINATED":
            # Closed historical interval [start, coverage_end]; adjacency ok.
            if start <= other["coverage_end_quarter"]:
                raise_err(
                    "ERR_WINDOW_CONFLICT",
                    "Coverage interval intersects a terminated same-class "
                    "manager's historical interval",
                )
        else:
            # Engaged-family managers occupy [start, +inf): any same-class
            # engaged-family manager intersects the open-ended candidate.
            raise_err(
                "ERR_WINDOW_CONFLICT",
                "Coverage interval intersects an engaged same-class manager",
            )

    manager["engagement_status"] = "ENGAGED"
    bump(manager)
    return success(pub(manager))


@bp.route("/endowment/managers/<manager_id>/decline", methods=["POST"])
def decline_manager(manager_id):
    authenticate(["InvestmentOfficer"])
    manager = get_or_404(store.managers, manager_id, "InvestmentManager")
    if manager["engagement_status"] != "PROSPECT":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot decline a manager in state {manager['engagement_status']}",
        )
    _terminated_gate(store.pools.get(manager["pool_id"]))
    manager["engagement_status"] = "DECLINED"
    bump(manager)
    return success(pub(manager))


@bp.route("/endowment/managers/<manager_id>/terminate", methods=["POST"])
def terminate_manager(manager_id):
    authenticate(["BoardMember"])
    manager = get_or_404(store.managers, manager_id, "InvestmentManager")
    if manager["engagement_status"] not in ("WATCHLIST", "PROBATION"):
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot terminate a manager in state {manager['engagement_status']}",
        )
    pool = store.pools.get(manager["pool_id"])
    _terminated_gate(pool)
    manager["engagement_status"] = "TERMINATED"
    manager["coverage_end_quarter"] = pool["current_quarter_index"]
    bump(manager)
    return success(pub(manager))
