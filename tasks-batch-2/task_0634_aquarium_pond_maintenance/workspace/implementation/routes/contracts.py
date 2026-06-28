"""ServiceContract endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response, array_response
from serializers import contract_view, system_view
import common as C

bp = Blueprint("contracts", __name__)


@bp.post("/aquatics/contracts")
def create_contract():
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    data = C.require_body(request.get_json(silent=True))
    customer_name = C.req_str(data, "customer_name")
    customer_user_id = C.req_str(data, "customer_user_id")
    service_tier = C.req_enum(data, "service_tier", {"BASIC", "PLUS", "PREMIUM"})
    route_day = C.req_enum(data, "route_day", {"MON", "TUE", "WED", "THU", "FRI", "SAT"})

    rec = C.make_record({
        "customer_name": customer_name,
        "customer_user_id": customer_user_id,
        "service_tier": service_tier,
        "status": "DRAFT",
        "route_day": route_day,
        "account_balance_cents": 0,
        "alive_livestock_count": 0,
    })
    store.contracts[rec["id"]] = rec
    return object_response(contract_view(rec), 201)


@bp.get("/aquatics/contracts")
def list_contracts():
    _, role = get_auth()
    require_roles(role, {"AccountManager", "Dispatcher"})
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    route_day = request.args.get("route_day")
    recs = list(store.contracts.values())
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if route_day is not None:
        recs = [r for r in recs if r["route_day"] == route_day]
    page, total = C.paginate(recs, limit, offset)
    return array_response([contract_view(r) for r in page], limit, offset, total)


@bp.get("/aquatics/contracts/<cid>")
def get_contract(cid):
    _, role = get_auth()
    require_roles(role, {"AccountManager", "Dispatcher", "CustomerOwner"})
    rec = store.contracts.get(cid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")
    return object_response(contract_view(rec))


@bp.post("/aquatics/contracts/<cid>/activate")
def activate_contract(cid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.contracts.get(cid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")

    if rec["status"] == "DRAFT":
        # require at least one SystemProfile
        sys_list = C.systems_of_contract(cid)
        if len(sys_list) == 0:
            raise ApiError("ERR_NO_SYSTEM_ON_CONTRACT",
                           "Activating a DRAFT contract requires at least one system.")
        rec["status"] = "ACTIVE"
        C.touch(rec)
        return object_response(contract_view(rec))

    if rec["status"] == "SUSPENDED":
        # reactivation requires balance == 0
        if rec["account_balance_cents"] != 0:
            raise ApiError("ERR_BALANCE_OUTSTANDING",
                           "Reactivation requires account_balance_cents == 0.")
        rec["status"] = "ACTIVE"
        C.touch(rec)
        # cascade SUSPENDED systems back to ACTIVE
        for s in C.systems_of_contract(cid):
            if s["status"] == "SUSPENDED":
                s["status"] = "ACTIVE"
                C.touch(s)
        return object_response(contract_view(rec))

    raise ApiError("ERR_INVALID_STATE", "Contract cannot be activated from its current state.")


@bp.post("/aquatics/contracts/<cid>/suspend")
def suspend_contract(cid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.contracts.get(cid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE contract may be suspended.")
    if rec["account_balance_cents"] <= 0:
        raise ApiError("ERR_INVALID_STATE",
                       "Suspension requires account_balance_cents > 0.")
    rec["status"] = "SUSPENDED"
    C.touch(rec)
    # cascade ACTIVE systems -> SUSPENDED
    for s in C.systems_of_contract(cid):
        if s["status"] == "ACTIVE":
            s["status"] = "SUSPENDED"
            C.touch(s)
    return object_response(contract_view(rec))


@bp.post("/aquatics/contracts/<cid>/terminate")
def terminate_contract(cid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.contracts.get(cid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "Contract cannot be terminated from its current state.")
    # blocked if any visit on this contract's systems is SCHEDULED/IN_PROGRESS
    sys_ids = {s["id"] for s in C.systems_of_contract(cid)}
    for v in store.visits.values():
        if v["system_id"] in sys_ids and v["status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError("ERR_VISIT_IN_FLIGHT",
                           "Termination blocked by an in-flight visit.")
    rec["status"] = "TERMINATED"
    C.touch(rec)
    # cascade non-decommissioned systems -> DECOMMISSIONED, sweep ALIVE livestock
    for s in C.systems_of_contract(cid):
        if s["status"] != "DECOMMISSIONED":
            s["status"] = "DECOMMISSIONED"
            C.touch(s)
            for l in store.livestock.values():
                if l["system_id"] == s["id"] and l["status"] == "ALIVE":
                    l["status"] = "DECEASED"
                    C.touch(l)
            C.recompute_system_bioload(s)
    C.recompute_alive_livestock_count(rec)
    return object_response(contract_view(rec))


# ---- nested list endpoints rooted at a contract ----
@bp.get("/aquatics/contracts/<cid>/systems")
def list_contract_systems(cid):
    _, role = get_auth()
    require_roles(role, {"AccountManager", "Dispatcher", "CustomerOwner"})
    if cid not in store.contracts:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")
    limit, offset = C.parse_pagination(request.args)
    recs = C.systems_of_contract(cid)
    page, total = C.paginate(recs, limit, offset)
    return array_response([system_view(r) for r in page], limit, offset, total)
