"""Disposition cases (PRD §3.8): end-of-season inventory write-off/carryover."""
from flask import Blueprint

from db import db, stamp, touch, serialize, sorted_all
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_DISPOSITION_CASE_NOT_FOUND,
    ERR_DISPOSITION_NOT_PROPOSED,
    ERR_DISPOSITION_NOT_APPROVED,
    ERR_DISPOSITION_SCOPE_EMPTY,
    ERR_POOL_HAS_ACTIVE_COMMITMENTS,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES
from routes.pools import GARMENT_TYPES
from services.pools import reconcile_pool
from util import is_int

bp = Blueprint("dispositions", __name__)

DISPOSITION_METHODS = {"RETURN_TO_STOCK", "DONATE", "MEMORABILIA_SALE", "DISCARD"}


@bp.post("/disposition-cases")
@endpoint("EquipmentManager")
def create_case(ctx):
    b = ctx.body
    season_label = b.get("season_label")
    garment_type = b.get("garment_type")
    size_code = b.get("size_code")
    method = b.get("method")
    unit_price = b.get("unit_price_cents")
    if not isinstance(season_label, str) or not season_label:
        raise_err(ERR_INVALID_REQUEST, "season_label is required")
    if garment_type not in GARMENT_TYPES:
        raise_err(ERR_INVALID_REQUEST, "garment_type is not a declared value")
    if size_code is not None and (not isinstance(size_code, str) or not size_code):
        raise_err(ERR_INVALID_REQUEST, "size_code must be a string")
    if method not in DISPOSITION_METHODS:
        raise_err(ERR_INVALID_REQUEST, "method is not a declared value")
    if method == "MEMORABILIA_SALE" and unit_price is None:
        raise_err(ERR_INVALID_REQUEST, "MEMORABILIA_SALE requires unit_price_cents")
    if unit_price is not None and (not is_int(unit_price) or unit_price < 0):
        raise_err(ERR_INVALID_REQUEST, "unit_price_cents must be an integer >= 0")
    case = stamp(
        {
            "season_label": season_label,
            "garment_type": garment_type,
            "size_code": size_code,
            "method": method,
            "unit_price_cents": unit_price,
            "status": "PROPOSED",
            "affected_pool_ids": [],
            "units_disposed": None,
            "proceeds_cents": None,
        }
    )
    db.dispositions[case["id"]] = case
    return success(serialize(case), 201)


@bp.get("/disposition-cases/<case_id>")
@endpoint(*ALL_ROLES)
def get_case(ctx, case_id):
    case = db.dispositions.get(case_id)
    if case is None:
        raise_err(ERR_DISPOSITION_CASE_NOT_FOUND, "disposition case not found")
    return success(serialize(case))


@bp.post("/disposition-cases/<case_id>/approve")
@endpoint("TeamAdmin")
def approve_case(ctx, case_id):
    case = db.dispositions.get(case_id)
    if case is None:
        raise_err(ERR_DISPOSITION_CASE_NOT_FOUND, "disposition case not found")
    if case["status"] != "PROPOSED":
        raise_err(ERR_DISPOSITION_NOT_PROPOSED, "approve requires case in PROPOSED")
    # Snapshot scope: ACTIVE pools matching season + garment (+ size when given).
    case["affected_pool_ids"] = [
        p["id"]
        for p in sorted_all(db.pools)
        if p["status"] == "ACTIVE"
        and p["season_label"] == case["season_label"]
        and p["garment_type"] == case["garment_type"]
        and (case["size_code"] is None or p["size_code"] == case["size_code"])
    ]
    case["status"] = "APPROVED"
    touch(case)
    return success(serialize(case))


@bp.post("/disposition-cases/<case_id>/reject")
@endpoint("TeamAdmin")
def reject_case(ctx, case_id):
    case = db.dispositions.get(case_id)
    if case is None:
        raise_err(ERR_DISPOSITION_CASE_NOT_FOUND, "disposition case not found")
    if case["status"] != "PROPOSED":
        raise_err(ERR_DISPOSITION_NOT_PROPOSED, "reject requires case in PROPOSED")
    case["status"] = "REJECTED"
    touch(case)
    return success(serialize(case))


@bp.post("/disposition-cases/<case_id>/execute")
@endpoint("EquipmentManager")
def execute_case(ctx, case_id):
    case = db.dispositions.get(case_id)
    if case is None:
        raise_err(ERR_DISPOSITION_CASE_NOT_FOUND, "disposition case not found")
    if case["status"] != "APPROVED":
        raise_err(ERR_DISPOSITION_NOT_APPROVED, "execute requires case in APPROVED")
    pools = [db.pools[pid] for pid in case["affected_pool_ids"] if pid in db.pools]
    if not pools:
        raise_err(ERR_DISPOSITION_SCOPE_EMPTY, "no matching ACTIVE pools in scope")
    for pool in pools:
        if pool["reserved_quantity"] != 0 or pool["in_laundry_quantity"] != 0:
            raise_err(
                ERR_POOL_HAS_ACTIVE_COMMITMENTS,
                "affected pool has reserved or in-laundry units",
            )
    method = case["method"]
    if method == "RETURN_TO_STOCK":
        units_disposed = 0
        proceeds = 0
    else:
        units_disposed = sum(p["stock_on_hand"] for p in pools)
        proceeds = (
            units_disposed * case["unit_price_cents"] if method == "MEMORABILIA_SALE" else 0
        )
        # Write-off: stock to zero, pool closes (system act). Reconciliation +
        # threshold check run per PRD §2.6 (decrease direction).
        for pool in pools:
            prev = pool["available_quantity"]
            pool["stock_on_hand"] = 0
            pool["status"] = "CLOSED"
            reconcile_pool(pool, "decrease", prev)
    case["units_disposed"] = units_disposed
    case["proceeds_cents"] = proceeds
    case["status"] = "EXECUTED"
    touch(case)
    return success(serialize(case))
