"""WarehouseReceipt and LoanPledge routes."""

from flask import Blueprint, request

from db import db, parse_dt
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_BALE_NOT_FOUND,
    ERR_WAREHOUSE_NOT_FOUND,
    ERR_WAREHOUSE_RECEIPT_NOT_FOUND,
    ERR_LOAN_PLEDGE_NOT_FOUND,
    ERR_RECEIPT_NOT_ISSUABLE,
    ERR_RECEIPT_NOT_CANCELLABLE,
    ERR_RECEIPT_NOT_ACTIVE,
    ERR_BALE_NOT_CLASSED,
    ERR_NO_ACTIVE_GRADE_SCHEDULE,
    ERR_WAREHOUSE_AT_CAPACITY,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_LOAN_CAP_EXCEEDED,
    ERR_PLEDGE_NOT_ACTIVE,
)
from middleware import (
    get_context,
    require_role,
    grower_owns,
    parse_pagination,
    get_json_body,
    require_fields,
)
from response import success_object
from services.core import (
    stamp_new,
    touch,
    post_ledger,
    sorted_entities,
    paginate,
    recompute_warehouse_count,
)
from services.calc import (
    find_covering_schedule,
    compute_adjustment_cents,
    compute_storage_charge_cents,
    recompute_draft_settlements,
)

bp = Blueprint("warehouse_receipts", __name__)

SEASON_LOAN_CAP_CENTS = 50000000


def receipt_out(r):
    return {
        "id": r["id"],
        "bale_id": r["bale_id"],
        "warehouse_id": r["warehouse_id"],
        "receipt_number": r["receipt_number"],
        "storage_start_date": r["storage_start_date"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def pledge_out(p):
    return {
        "id": p["id"],
        "warehouse_receipt_id": p["warehouse_receipt_id"],
        "loan_rate_points": p["loan_rate_points"],
        "principal_cents": p["principal_cents"],
        "interest_cents": p["interest_cents"],
        "pledged_date": p["pledged_date"],
        "redeemed_date": p["redeemed_date"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _bale_grower_season(bale):
    module = db.modules.get(bale["module_id"])
    if module is None:
        return None, None
    return module["grower_id"], module["season"]


@bp.route("/gin-ops/warehouse-receipts", methods=["POST"])
def create_receipt():
    user_id, role = get_context()
    require_role(role, {"WarehouseManager"})
    body = get_json_body()
    require_fields(body, ["bale_id", "warehouse_id"])
    bale_id = body["bale_id"]
    warehouse_id = body["warehouse_id"]
    bale = db.bales.get(bale_id) if isinstance(bale_id, str) else None
    if bale is None:
        err_id, status = ERR_BALE_NOT_FOUND
        raise ApiError(err_id, "Bale not found", status)
    wh = db.warehouses.get(warehouse_id) if isinstance(warehouse_id, str) else None
    if wh is None:
        err_id, status = ERR_WAREHOUSE_NOT_FOUND
        raise ApiError(err_id, "Warehouse not found", status)
    # State gate: custody + no non-terminal receipt
    if bale["custody_status"] != "ON_GIN_FLOOR":
        err_id, status = ERR_RECEIPT_NOT_ISSUABLE
        raise ApiError(err_id, "Bale custody is not ON_GIN_FLOOR", status)
    for r in db.warehouse_receipts.values():
        if r["bale_id"] == bale_id and r["status"] in ("ACTIVE", "PLEDGED", "RELEASED"):
            err_id, status = ERR_RECEIPT_NOT_ISSUABLE
            raise ApiError(err_id, "A non-terminal receipt already exists for this bale", status)
    # Segregation of duties
    module = db.modules.get(bale["module_id"])
    if module is not None and module.get("ginned_by_user_id") == user_id:
        err_id, status = ERR_SEGREGATION_OF_DUTIES
        raise ApiError(err_id, "Receipt issuer may not be the operator who ginned the module", status)
    # Capacity
    if wh["stored_bale_count"] >= wh["capacity_bales"]:
        err_id, status = ERR_WAREHOUSE_AT_CAPACITY
        raise ApiError(err_id, "Warehouse is at capacity", status)

    db.receipt_seq += 1
    receipt = stamp_new({
        "bale_id": bale_id,
        "warehouse_id": warehouse_id,
        "receipt_number": f"WR-{db.receipt_seq:08d}",
        "storage_start_date": db.clock_date_str(),
        "status": "ACTIVE",
    })
    db.warehouse_receipts[receipt["id"]] = receipt
    bale["custody_status"] = "WAREHOUSED"
    touch(bale)
    recompute_warehouse_count(warehouse_id)
    touch(wh)
    return success_object(receipt_out(receipt), 201)


@bp.route("/gin-ops/warehouse-receipts/<rid>", methods=["GET"])
def get_receipt(rid):
    user_id, role = get_context()
    r = db.warehouse_receipts.get(rid)
    if r is None:
        err_id, status = ERR_WAREHOUSE_RECEIPT_NOT_FOUND
        raise ApiError(err_id, "Warehouse receipt not found", status)
    if role == "Grower":
        bale = db.bales.get(r["bale_id"])
        gid, _ = _bale_grower_season(bale) if bale else (None, None)
        grower_owns(user_id, role, gid)
    return success_object(receipt_out(r))


@bp.route("/gin-ops/warehouse-receipts", methods=["GET"])
def list_receipts():
    user_id, role = get_context()
    limit, offset = parse_pagination()
    args = request.args
    items = list(db.warehouse_receipts.values())
    if role == "Grower":
        own_bales = {
            b["id"] for b in db.bales.values()
            if db.modules.get(b["module_id"]) and db.modules[b["module_id"]]["grower_id"] == user_id
        }
        items = [r for r in items if r["bale_id"] in own_bales]
    if args.get("bale_id"):
        items = [r for r in items if r["bale_id"] == args["bale_id"]]
    if args.get("warehouse_id"):
        items = [r for r in items if r["warehouse_id"] == args["warehouse_id"]]
    if args.get("status"):
        items = [r for r in items if r["status"] == args["status"]]
    items = sorted_entities(items)
    return paginate([receipt_out(r) for r in items], limit, offset)


@bp.route("/gin-ops/warehouse-receipts/<rid>/cancel", methods=["POST"])
def cancel_receipt(rid):
    user_id, role = get_context()
    require_role(role, {"WarehouseManager"})
    r = db.warehouse_receipts.get(rid)
    if r is None:
        err_id, status = ERR_WAREHOUSE_RECEIPT_NOT_FOUND
        raise ApiError(err_id, "Warehouse receipt not found", status)
    if r["status"] != "ACTIVE":
        err_id, status = ERR_RECEIPT_NOT_CANCELLABLE
        raise ApiError(err_id, "Receipt must be ACTIVE to cancel", status)
    r["status"] = "CANCELLED"
    touch(r)
    bale = db.bales.get(r["bale_id"])
    if bale is not None:
        bale["custody_status"] = "ON_GIN_FLOOR"
        touch(bale)
    wh = db.warehouses.get(r["warehouse_id"])
    if wh is not None:
        recompute_warehouse_count(wh["id"])
        touch(wh)
    return success_object(receipt_out(r))


@bp.route("/gin-ops/warehouse-receipts/<rid>/loan-pledges", methods=["GET"])
def list_receipt_pledges(rid):
    user_id, role = get_context()
    r = db.warehouse_receipts.get(rid)
    if r is None:
        err_id, status = ERR_WAREHOUSE_RECEIPT_NOT_FOUND
        raise ApiError(err_id, "Warehouse receipt not found", status)
    if role == "Grower":
        bale = db.bales.get(r["bale_id"])
        gid, _ = _bale_grower_season(bale) if bale else (None, None)
        grower_owns(user_id, role, gid)
    limit, offset = parse_pagination()
    items = [p for p in db.loan_pledges.values() if p["warehouse_receipt_id"] == rid]
    items = sorted_entities(items)
    return paginate([pledge_out(p) for p in items], limit, offset)


# ---------------------------------------------------------------------------
# Loan pledges
# ---------------------------------------------------------------------------

@bp.route("/gin-ops/loan-pledges", methods=["POST"])
def create_pledge():
    user_id, role = get_context()
    require_role(role, {"CoopAccountant"})
    body = get_json_body()
    require_fields(body, ["warehouse_receipt_id"])
    rid = body["warehouse_receipt_id"]
    r = db.warehouse_receipts.get(rid) if isinstance(rid, str) else None
    if r is None:
        err_id, status = ERR_WAREHOUSE_RECEIPT_NOT_FOUND
        raise ApiError(err_id, "Warehouse receipt not found", status)
    if r["status"] not in ("ACTIVE", "RELEASED"):
        err_id, status = ERR_RECEIPT_NOT_ACTIVE
        raise ApiError(err_id, "Receipt is not in ACTIVE or RELEASED", status)
    bale = db.bales.get(r["bale_id"])
    if bale["classing_status"] != "CLASSED":
        err_id, status = ERR_BALE_NOT_CLASSED
        raise ApiError(err_id, "Bale is not CLASSED", status)
    pledge_date = db.clock_datetime()
    schedule = find_covering_schedule(bale["active_grade_code"], pledge_date)
    if schedule is None:
        err_id, status = ERR_NO_ACTIVE_GRADE_SCHEDULE
        raise ApiError(err_id, "No active grade schedule covers the pledge date", status)
    loan_rate_points = schedule["loan_rate_points"]
    principal = compute_adjustment_cents(bale["net_weight_lbs"], loan_rate_points)
    gid, season = _bale_grower_season(bale)
    # Season cap over ACTIVE pledges
    active_total = 0
    for p in db.loan_pledges.values():
        if p["status"] != "ACTIVE":
            continue
        pr = db.warehouse_receipts.get(p["warehouse_receipt_id"])
        if pr is None:
            continue
        pb = db.bales.get(pr["bale_id"])
        if pb is None:
            continue
        pgid, pseason = _bale_grower_season(pb)
        if pgid == gid and pseason == season:
            active_total += p["principal_cents"]
    if active_total + principal > SEASON_LOAN_CAP_CENTS:
        err_id, status = ERR_LOAN_CAP_EXCEEDED
        raise ApiError(err_id, "Season loan cap exceeded", status)

    pledge = stamp_new({
        "warehouse_receipt_id": rid,
        "loan_rate_points": loan_rate_points,
        "principal_cents": principal,
        "interest_cents": 0,
        "pledged_date": db.clock_date_str(),
        "redeemed_date": None,
        "status": "ACTIVE",
    })
    db.loan_pledges[pledge["id"]] = pledge
    r["status"] = "PLEDGED"
    touch(r)
    post_ledger(gid, season, "LOAN_ADVANCE", principal, r["receipt_number"])
    recompute_draft_settlements(gid, season)
    return success_object(pledge_out(pledge), 201)


@bp.route("/gin-ops/loan-pledges/<pid>", methods=["GET"])
def get_pledge(pid):
    user_id, role = get_context()
    p = db.loan_pledges.get(pid)
    if p is None:
        err_id, status = ERR_LOAN_PLEDGE_NOT_FOUND
        raise ApiError(err_id, "Loan pledge not found", status)
    if role == "Grower":
        r = db.warehouse_receipts.get(p["warehouse_receipt_id"])
        bale = db.bales.get(r["bale_id"]) if r else None
        gid, _ = _bale_grower_season(bale) if bale else (None, None)
        grower_owns(user_id, role, gid)
    return success_object(pledge_out(p))


@bp.route("/gin-ops/loan-pledges/<pid>/redeem", methods=["POST"])
def redeem_pledge(pid):
    user_id, role = get_context()
    require_role(role, {"CoopAccountant"})
    p = db.loan_pledges.get(pid)
    if p is None:
        err_id, status = ERR_LOAN_PLEDGE_NOT_FOUND
        raise ApiError(err_id, "Loan pledge not found", status)
    if p["status"] != "ACTIVE":
        err_id, status = ERR_PLEDGE_NOT_ACTIVE
        raise ApiError(err_id, "Pledge is not ACTIVE", status)
    r = db.warehouse_receipts[p["warehouse_receipt_id"]]
    bale = db.bales[r["bale_id"]]
    gid, season = _bale_grower_season(bale)
    pledged_dt = parse_dt(p["pledged_date"])
    now = db.clock_datetime()
    days = (now.date() - pledged_dt.date()).days
    from decimal import Decimal, ROUND_HALF_UP
    interest = int(
        (Decimal(p["principal_cents"]) * Decimal("0.0001") * Decimal(days)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    p["interest_cents"] = interest
    p["redeemed_date"] = db.clock_date_str()
    p["status"] = "REPAID"
    touch(p)
    r["status"] = "RELEASED"
    touch(r)
    post_ledger(gid, season, "LOAN_REPAYMENT", -(p["principal_cents"] + interest), r["receipt_number"])
    recompute_draft_settlements(gid, season)
    return success_object(pledge_out(p))


@bp.route("/gin-ops/loan-pledges/<pid>/forfeit", methods=["POST"])
def forfeit_pledge(pid):
    user_id, role = get_context()
    require_role(role, {"CoopAccountant"})
    p = db.loan_pledges.get(pid)
    if p is None:
        err_id, status = ERR_LOAN_PLEDGE_NOT_FOUND
        raise ApiError(err_id, "Loan pledge not found", status)
    if p["status"] != "ACTIVE":
        err_id, status = ERR_PLEDGE_NOT_ACTIVE
        raise ApiError(err_id, "Pledge is not ACTIVE", status)
    r = db.warehouse_receipts[p["warehouse_receipt_id"]]
    bale = db.bales[r["bale_id"]]
    gid, season = _bale_grower_season(bale)
    p["status"] = "FORFEITED"
    touch(p)
    r["status"] = "FORFEITED"
    touch(r)
    bale["custody_status"] = "SHIPPED"
    touch(bale)
    wh = db.warehouses.get(r["warehouse_id"])
    if wh is not None:
        recompute_warehouse_count(wh["id"])
        touch(wh)
    # Storage charge
    charge = compute_storage_charge_cents(r, db.clock_datetime())
    if charge > 0:
        post_ledger(gid, season, "STORAGE_CHARGE", -charge, r["receipt_number"])
    else:
        # still recompute balance (no-op but keeps semantics)
        from services.core import recompute_grower_balance
        recompute_grower_balance(gid)
    recompute_draft_settlements(gid, season)
    return success_object(pledge_out(p))
