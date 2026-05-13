"""Network CRUD + test-clock advance."""
from flask import Blueprint, g

from clock import server_now
from db import lock, networks, next_seq, public, stamp_create, stamp_update
from errors import err
from middleware import get_json_body, require_auth
from response import success
from services.clock_sweep import run_clock_advance_sweeps
from services.common import get_network


bp = Blueprint("networks", __name__)


@bp.post("/networks")
@require_auth(roles={"TopologyApprover"})
def create_network():
    body = get_json_body()
    name = body.get("name")
    utility_code = body.get("utility_code")
    if not name or not isinstance(name, str):
        raise err("ERR_BAD_REQUEST", "name is required")
    if not utility_code or not isinstance(utility_code, str):
        raise err("ERR_BAD_REQUEST", "utility_code is required")
    # uniqueness on utility_code
    for n in networks.values():
        if n.get("utility_code") == utility_code:
            raise err("ERR_BAD_REQUEST", "utility_code already exists")
    nrw_target = body.get("nrw_target_pct")
    if nrw_target is not None:
        try:
            nrw_target = float(nrw_target)
        except (TypeError, ValueError):
            raise err("ERR_BAD_REQUEST", "nrw_target_pct must be a number")
    with lock():
        now_dt = server_now()
        n = {
            "name": name,
            "utility_code": utility_code,
            "active_topology_version_id": None,
            "nrw_target_pct": nrw_target,
            "clock_epoch_ms": int(now_dt.timestamp() * 1000),
        }
        stamp_create(n)
        networks[n["id"]] = n
        return success(public(n), 201)


@bp.get("/networks/<network_id>")
@require_auth(roles={
    "TopologyEngineer", "TopologyApprover", "ControlOperator",
    "MaintenanceSupervisor", "Technician", "Auditor",
})
def get_network_endpoint(network_id):
    n = get_network(network_id)
    return success(public(n))


@bp.post("/networks/<network_id>/_clock/advance")
@require_auth(roles={"ControlOperator"})
def advance_clock(network_id):
    n = get_network(network_id)
    body = get_json_body()
    advance_ms = body.get("advance_ms")
    if advance_ms is None:
        raise err("ERR_BAD_REQUEST", "advance_ms is required")
    try:
        advance_ms = int(advance_ms)
    except (TypeError, ValueError):
        raise err("ERR_BAD_REQUEST", "advance_ms must be an integer")
    if advance_ms <= 0:
        raise err("ERR_BAD_REQUEST", "advance_ms must be > 0")
    with lock():
        n["clock_epoch_ms"] = int(n.get("clock_epoch_ms", 0)) + advance_ms
        stamp_update(n)
        # Run sweeps. Clock advance is permitted even in FROZEN DMAs.
        run_clock_advance_sweeps(n, actor_role=g.user_role, actor_id=g.user_id)
    return success(public(n))
