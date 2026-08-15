"""TransferRequest endpoints: create (OCC on source allocation), list, get,
approve, post, reject, cancel."""
from flask import Blueprint

from db import store, new_id, new_common, touch, D
from errors import ApiError
from response import ok, created, list_ok, filter_eq
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services import ledger

bp = Blueprint("transfers", __name__)

READ_ROLES = ["DistrictAdmin", "WaterUser"]

_CREATE_SCHEMA = {
    "from_account_id": ("string", True, None, None),
    "to_account_id": ("string", True, None, None),
    "season_id": ("string", True, None, None),
    "quantity_af": ("number", True, None, "gt0"),
    "expected_source_allocation_version": ("integer", True, None, None),
}


def _drought_effective(season_id):
    return any(d["season_id"] == season_id and d["status"] == "EFFECTIVE"
               for d in store.drought_declarations.values())


def _accounts_active(tr):
    for aid in (tr["from_account_id"], tr["to_account_id"]):
        acct = store.water_accounts.get(aid)
        if acct is None or acct["status"] != "ACTIVE":
            raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Both accounts must be ACTIVE")


def _source_allocation(tr):
    alloc = ledger.find_allocation(tr["from_account_id"], tr["season_id"])
    if alloc is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Source season allocation does not exist")
    return alloc


def _check_source_balance(tr, alloc):
    ledger.recompute_allocation(alloc)
    if D(tr["quantity_af"]) > alloc["available_af"]:
        raise ApiError("ERR_INSUFFICIENT_ALLOCATION", 422,
                       "Source allocation's available balance does not cover quantity_af")


@bp.post("/district/transfer-requests")
def create_transfer():
    uid, role = get_context()
    body = parse_body(_CREATE_SCHEMA, allow_empty=False)
    # Shape rule (priority 2): destination must differ from source.
    if body["to_account_id"] == body["from_account_id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_account_id must differ from from_account_id")
    require_roles(["WaterUser"])
    # Ownership (priority 3): caller must be the source account.
    if uid != body["from_account_id"]:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "WaterUser may request transfers only from their own account")
    # Existence (priority 4): body FKs in declared input order.
    from_acct = store.water_accounts.get(body["from_account_id"])
    if from_acct is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced from_account_id does not exist")
    to_acct = store.water_accounts.get(body["to_account_id"])
    if to_acct is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced to_account_id does not exist")
    season = store.seasons.get(body["season_id"])
    if season is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced season_id does not exist")
    src = ledger.find_allocation(from_acct["id"], season["id"])
    if src is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Source season allocation does not exist")
    # OCC (priority 5) on the source SeasonAllocation.
    if body["expected_source_allocation_version"] != src["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_source_allocation_version does not match the allocation's current version")
    # Cross-entity state gates (priority 6).
    if from_acct["status"] != "ACTIVE" or to_acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Both accounts must be ACTIVE")
    if season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", 409, "Season is not OPEN")
    # Drought freeze (priority 7).
    if _drought_effective(season["id"]):
        raise ApiError("ERR_TRANSFER_BLOCKED_DROUGHT", 409,
                       "Transfers are frozen while a drought declaration is EFFECTIVE")
    # Sufficient water (priority 10), net-of-committed reading.
    _check_source_balance({"quantity_af": body["quantity_af"]}, src)
    tr = new_common({
        "id": new_id(),
        "from_account_id": from_acct["id"],
        "to_account_id": to_acct["id"],
        "season_id": season["id"],
        "quantity_af": body["quantity_af"],
        "status": "PENDING",
    })
    store.transfer_requests[tr["id"]] = tr
    touch(src)  # creation increments the source allocation's version
    return created(tr)


@bp.get("/district/transfer-requests")
def list_transfers():
    uid, role = get_context()
    require_roles(READ_ROLES)
    rows = list(store.transfer_requests.values())
    for f in ("from_account_id", "to_account_id", "season_id", "status"):
        rows = filter_eq(rows, f)
    return list_ok(rows)


@bp.get("/district/transfer-requests/<tid>")
def get_transfer(tid):
    uid, role = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.transfer_requests, tid))


@bp.post("/district/transfer-requests/<tid>/approve")
def approve_transfer(tid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    tr = require_path_entity(store.transfer_requests, tid)
    if tr["status"] != "PENDING":
        raise ApiError("ERR_INVALID_TRANSFER_STATE", 409,
                       "Only a PENDING transfer may be approved")
    _accounts_active(tr)
    season = store.seasons[tr["season_id"]]
    if season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", 409, "Season is not OPEN")
    if _drought_effective(tr["season_id"]):
        raise ApiError("ERR_TRANSFER_BLOCKED_DROUGHT", 409,
                       "Transfers are frozen while a drought declaration is EFFECTIVE")
    _check_source_balance(tr, _source_allocation(tr))
    tr["status"] = "APPROVED"
    touch(tr)
    return ok(tr)


@bp.post("/district/transfer-requests/<tid>/post")
def post_transfer(tid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    tr = require_path_entity(store.transfer_requests, tid)
    if tr["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_TRANSFER_STATE", 409,
                       "Only an APPROVED transfer may be posted")
    _accounts_active(tr)
    if _drought_effective(tr["season_id"]):
        raise ApiError("ERR_TRANSFER_BLOCKED_DROUGHT", 409,
                       "Transfers are frozen while a drought declaration is EFFECTIVE")
    src = _source_allocation(tr)
    _check_source_balance(tr, src)  # re-evaluated at post time
    dst = ledger.find_allocation(tr["to_account_id"], tr["season_id"])
    if dst is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Destination season allocation does not exist")
    tr["status"] = "POSTED"
    touch(tr)
    ledger.refresh_allocation(src)  # transfers_out += quantity; version += 1
    ledger.refresh_allocation(dst)  # transfers_in += quantity; version += 1
    return ok(tr)


@bp.post("/district/transfer-requests/<tid>/reject")
def reject_transfer(tid):
    uid, role = get_context()
    parse_body({})
    require_roles(["DistrictAdmin"])
    tr = require_path_entity(store.transfer_requests, tid)
    if tr["status"] not in ("PENDING", "APPROVED"):
        raise ApiError("ERR_INVALID_TRANSFER_STATE", 409,
                       "Only a PENDING or APPROVED transfer may be rejected")
    tr["status"] = "REJECTED"
    touch(tr)
    return ok(tr)


@bp.post("/district/transfer-requests/<tid>/cancel")
def cancel_transfer(tid):
    uid, role = get_context()
    parse_body({})
    require_roles(["WaterUser"])
    tr = require_path_entity(store.transfer_requests, tid)
    if uid != tr["from_account_id"]:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the source account owner may cancel this transfer")
    if tr["status"] not in ("PENDING", "APPROVED"):
        raise ApiError("ERR_INVALID_TRANSFER_STATE", 409,
                       "Only a PENDING or APPROVED transfer may be cancelled")
    tr["status"] = "CANCELLED"
    touch(tr)
    return ok(tr)
