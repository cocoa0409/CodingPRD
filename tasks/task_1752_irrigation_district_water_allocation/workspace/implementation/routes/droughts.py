"""DroughtDeclaration endpoints: create, list, get, effectuate, lift."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_id, new_common, touch, D, round2
from errors import ApiError
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity, resolve_fk
from services import ledger, ordering

bp = Blueprint("droughts", __name__)

READ_ROLES = ["DistrictAdmin", "WaterUser"]

# Pinned stage constants: stage -> (senior_curtailment_pct, junior_curtailment_pct).
STAGES = {
    "STAGE_1": (0, 15),
    "STAGE_2": (10, 40),
    "STAGE_3": (25, 75),
}

_CREATE_SCHEMA = {
    "season_id": ("string", True, None, None),
    "stage": ("enum", True, ["STAGE_1", "STAGE_2", "STAGE_3"], None),
}


@bp.post("/district/drought-declarations")
def create_declaration():
    uid, role = get_context()
    body = parse_body(_CREATE_SCHEMA, allow_empty=False)
    require_roles(["DistrictAdmin"])
    season = resolve_fk(store.seasons, body["season_id"], "season_id")
    senior_pct, junior_pct = STAGES[body["stage"]]
    decl = new_common({
        "id": new_id(),
        "season_id": season["id"],
        "stage": body["stage"],
        "senior_curtailment_pct": senior_pct,
        "junior_curtailment_pct": junior_pct,
        "status": "PROPOSED",
    })
    store.drought_declarations[decl["id"]] = decl
    return created(decl)


@bp.get("/district/drought-declarations")
def list_declarations():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = list(store.drought_declarations.values())
    for f in ("season_id", "status"):
        rows = filter_eq(rows, f)
    return list_ok(rows)


@bp.get("/district/drought-declarations/<did>")
def get_declaration(did):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.drought_declarations, did))


@bp.post("/district/drought-declarations/<did>/effectuate")
def effectuate_declaration(did):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    decl = require_path_entity(store.drought_declarations, did)
    if decl["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_DROUGHT_STATE", 409,
                       "Only a PROPOSED declaration may be effectuated")
    season = store.seasons[decl["season_id"]]
    if season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", 409,
                       "Season must be OPEN to effectuate a declaration")
    if any(d["season_id"] == decl["season_id"] and d["status"] == "EFFECTIVE"
           and d["id"] != decl["id"]
           for d in store.drought_declarations.values()):
        raise ApiError("ERR_INVALID_DROUGHT_STATE", 409,
                       "Another declaration is already EFFECTIVE on this season")
    decl["status"] = "EFFECTIVE"
    touch(decl)
    # Curtail every allocation of the season per its account's priority class.
    allocs = sorted(ledger.allocations_of_season(decl["season_id"]),
                    key=lambda r: (r["created_at"], r["_seq"]))
    for alloc in allocs:
        account = store.water_accounts[alloc["water_account_id"]]
        pct = D(decl["junior_curtailment_pct"] if account["priority_class"] == "JUNIOR"
                else decl["senior_curtailment_pct"])
        alloc["curtailed_entitlement_af"] = round2(
            D(alloc["base_entitlement_af"]) * (Decimal("100") - pct) / Decimal("100"))
        alloc["status"] = "CURTAILED"
        ledger.refresh_allocation(alloc)
    # Cascade: restore ledger feasibility by cancelling over-committed orders,
    # latest requested_start_at first (ties: created_at descending).
    for alloc in allocs:
        while True:
            ledger.recompute_allocation(alloc)
            if alloc["committed_af"] <= alloc["available_af"]:
                break
            candidates = [o for o in ledger.orders_of_allocation(alloc)
                          if o["status"] in ("REQUESTED", "SCHEDULED")]
            if not candidates:
                break
            candidates.sort(key=lambda o: (o["_start_dt"], o["created_at"], o["_seq"]),
                            reverse=True)
            ordering.cascade_cancel_order(candidates[0])
        ledger.recompute_allocation(alloc)
    return ok(decl)


@bp.post("/district/drought-declarations/<did>/lift")
def lift_declaration(did):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    decl = require_path_entity(store.drought_declarations, did)
    if decl["status"] != "EFFECTIVE":
        raise ApiError("ERR_INVALID_DROUGHT_STATE", 409,
                       "Only an EFFECTIVE declaration may be lifted")
    decl["status"] = "LIFTED"
    touch(decl)
    # Restore full entitlements; cancelled orders are NOT resurrected.
    for alloc in sorted(ledger.allocations_of_season(decl["season_id"]),
                        key=lambda r: (r["created_at"], r["_seq"])):
        if alloc["status"] == "CURTAILED":
            alloc["status"] = "ACTIVE"
            ledger.refresh_allocation(alloc)
    return ok(decl)
