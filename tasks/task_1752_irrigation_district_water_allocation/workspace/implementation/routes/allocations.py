"""SeasonAllocation endpoints: create (base entitlement + carryover-in), list, get."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_id, new_common, D, round2
from errors import ApiError
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity, resolve_fk
from services import ledger

bp = Blueprint("allocations", __name__)

READ_ROLES = ["DistrictAdmin", "WaterUser", "DitchRider"]

_CREATE_SCHEMA = {
    "water_account_id": ("string", True, None, None),
    "season_id": ("string", True, None, None),
}


def _prior_closed_carryover(account_id, new_season):
    """carryover_out_af of the account's allocation in the most recent CLOSED
    season with year strictly less than the new season's year; 0 when none."""
    best = None
    for a in store.allocations.values():
        if a["water_account_id"] != account_id:
            continue
        s = store.seasons.get(a["season_id"])
        if s is None or s["status"] != "CLOSED" or s["year"] >= new_season["year"]:
            continue
        if best is None or s["year"] > best[0]:
            best = (s["year"], a)
    if best is None:
        return Decimal("0")
    return D(best[1]["carryover_out_af"])


@bp.post("/district/season-allocations")
def create_allocation():
    uid, role = get_context()
    body = parse_body(_CREATE_SCHEMA, allow_empty=False)
    require_roles(["DistrictAdmin"])
    account = resolve_fk(store.water_accounts, body["water_account_id"], "water_account_id")
    season = resolve_fk(store.seasons, body["season_id"], "season_id")
    if season["status"] not in ("ANNOUNCED", "OPEN"):
        raise ApiError("ERR_SEASON_NOT_OPEN", 409,
                       "Allocations may be created only while the season is ANNOUNCED or OPEN")
    if ledger.find_allocation(account["id"], season["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_ALLOCATION", 409,
                       "An allocation already exists for this account and season")
    base = round2(D(account["irrigated_acres"]) * D(season["announced_af_per_acre"]))
    alloc = new_common({
        "id": new_id(),
        "water_account_id": account["id"],
        "season_id": season["id"],
        "base_entitlement_af": base,
        "curtailed_entitlement_af": None,
        "carryover_in_af": _prior_closed_carryover(account["id"], season),
        "carryover_out_af": None,
        "status": "ACTIVE",
    })
    store.allocations[alloc["id"]] = alloc
    ledger.recompute_allocation(alloc)
    return created(alloc)


@bp.get("/district/season-allocations")
def list_allocations():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = list(store.allocations.values())
    for f in ("water_account_id", "season_id", "status"):
        rows = filter_eq(rows, f)
    return list_ok(rows)


@bp.get("/district/season-allocations/<aid>")
def get_allocation(aid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.allocations, aid))
