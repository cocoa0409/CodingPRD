"""Investment pools, pool holdings, unitization events."""
from decimal import Decimal

from flask import Blueprint, request

from common import (
    STORE, body, err, get_path, get_ref, list_response, new_resource, now,
    pool_unit_price, q2, q4, req_decimal, req_enum, req_present, require_roles,
    serialize, success, touch,
)

bp = Blueprint("invest", __name__)

POOL_KINDS = ("CONSERVATIVE", "BALANCED", "GROWTH")
EVENT_KINDS = ("BUY_IN", "REDEMPTION", "MARK_TO_MARKET")


def pool_view(p):
    out = serialize(p)
    out["nav"] = float(q2(p["nav"]))
    out["units_outstanding"] = float(q4(p["units_outstanding"]))
    price = pool_unit_price(p)
    out["unit_price"] = float(price) if price is not None else None
    return out


def holding_view(h):
    return serialize(h)


def event_view(e):
    return serialize(e)


def find_holding(fund_id, pool_id):
    for h in STORE["holdings"].values():
        if h["fund_id"] == fund_id and h["pool_id"] == pool_id:
            return h
    return None


# ---------------------------------------------------------------------------
# Pools
# ---------------------------------------------------------------------------
@bp.post("/pools")
@require_roles("InvestmentManager")
def create_pool():
    data = body()
    name = data.get("pool_name")
    if name is not None:
        for p in STORE["pools"].values():
            if p["pool_name"] == name:
                err("ERR_UNIQUENESS_VIOLATION", 409, "pool_name must be unique")
    name = req_present(data, "pool_name")
    kind = req_enum(data, "pool_kind", POOL_KINDS)
    nav = req_decimal(data, "initial_nav")
    if nav < 0:
        err("ERR_FIELD_CONSTRAINT", 422, "initial_nav must be >= 0")
    units = req_decimal(data, "initial_units")
    if units <= 0:
        err("ERR_FIELD_CONSTRAINT", 422, "initial_units must be greater than zero")
    p = new_resource()
    p.update({
        "pool_name": name,
        "pool_kind": kind,
        "status": "OPEN",
        "nav": q2(nav),
        "units_outstanding": q4(units),
    })
    STORE["pools"][p["id"]] = p
    return success(pool_view(p), code=201)


@bp.get("/pools")
@require_roles("FoundationAdmin", "InvestmentManager", "FinanceOfficer")
def list_pools():
    return list_response(list(STORE["pools"].values()), pool_view)


@bp.get("/pools/<poolId>")
@require_roles("FoundationAdmin", "InvestmentManager", "FinanceOfficer")
def get_pool(poolId):
    return success(pool_view(get_path("pools", poolId)))


@bp.post("/pools/<poolId>/suspend")
@require_roles("InvestmentManager")
def suspend_pool(poolId):
    p = get_path("pools", poolId)
    if p["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Only an OPEN pool can be suspended")
    p["status"] = "SUSPENDED"
    touch(p)
    return success(pool_view(p))


@bp.post("/pools/<poolId>/reopen")
@require_roles("InvestmentManager")
def reopen_pool(poolId):
    p = get_path("pools", poolId)
    if p["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Only a SUSPENDED pool can be reopened")
    p["status"] = "OPEN"
    touch(p)
    return success(pool_view(p))


@bp.post("/pools/<poolId>/terminate")
@require_roles("InvestmentManager")
def terminate_pool(poolId):
    p = get_path("pools", poolId)
    if p["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Only an OPEN pool can be terminated")
    if q4(p["units_outstanding"]) != Decimal("0.0000"):
        err("ERR_POOL_NOT_EMPTY", 409, "Pool must have zero units outstanding to terminate")
    p["status"] = "TERMINATED"
    touch(p)
    return success(pool_view(p))


# ---------------------------------------------------------------------------
# Unitization events
# ---------------------------------------------------------------------------
@bp.post("/pools/<poolId>/unitization-events")
@require_roles("InvestmentManager", "FinanceOfficer")
def create_unitization_event(poolId):
    p = get_path("pools", poolId)
    data = body()
    kind = req_enum(data, "event_kind", EVENT_KINDS)

    fund = None
    if kind in ("BUY_IN", "REDEMPTION"):
        fund_id = data.get("fund_id")
        if fund_id is not None:
            fund = get_ref("funds", fund_id, "fund")
    # State (priority 5): transactional events only while pool is OPEN.
    if kind in ("BUY_IN", "REDEMPTION") and p["status"] != "OPEN":
        err("ERR_POOL_NOT_OPEN", 409, "Transactional events require an OPEN pool")
    # OCC (priority 6): BUY_IN / REDEMPTION carry expected_pool_version.
    if kind in ("BUY_IN", "REDEMPTION"):
        if data.get("expected_pool_version") != p["version"]:
            err("ERR_STALE_POOL_VERSION", 412,
                "expected_pool_version does not match the pool's current version")

    e = new_resource(common_fields=False)
    e.update({
        "pool_id": p["id"],
        "event_kind": kind,
        "fund_id": None,
        "cash_amount": None,
        "units_amount": None,
        "new_nav": None,
        "unit_price_applied": None,
        "units_delta": Decimal("0.0000"),
    })

    if kind == "BUY_IN":
        if fund is None:
            err("ERR_FIELD_CONSTRAINT", 422, "fund_id is required for BUY_IN")
        cash = req_decimal(data, "cash_amount")
        if cash <= 0:
            err("ERR_FIELD_CONSTRAINT", 422, "cash_amount must be greater than zero")
        cash = q2(cash)
        price = pool_unit_price(p)
        if price is None:
            err("ERR_INVALID_STATE", 409, "Pool unit price is undefined (no units outstanding)")
        # Fiscal capacity (priority 13).
        if fund["cash_balance"] < cash:
            err("ERR_INSUFFICIENT_CASH", 422, "Fund cash balance is below the buy-in amount")
        minted = q4(cash / price)
        e["fund_id"] = fund["id"]
        e["cash_amount"] = cash
        e["unit_price_applied"] = price
        e["units_delta"] = minted
        p["units_outstanding"] = q4(p["units_outstanding"] + minted)
        p["nav"] = q2(p["nav"] + cash)
        fund["cash_balance"] = q2(fund["cash_balance"] - cash)
        h = find_holding(fund["id"], p["id"])
        if h is None:
            h = new_resource()
            h.update({"fund_id": fund["id"], "pool_id": p["id"], "units_held": Decimal("0.0000")})
            STORE["holdings"][h["id"]] = h
        h["units_held"] = q4(h["units_held"] + minted)
        touch(h)
        touch(fund)
        touch(p)
    elif kind == "REDEMPTION":
        if fund is None:
            err("ERR_FIELD_CONSTRAINT", 422, "fund_id is required for REDEMPTION")
        units = req_decimal(data, "units_amount")
        if units <= 0:
            err("ERR_FIELD_CONSTRAINT", 422, "units_amount must be greater than zero")
        units = q4(units)
        h = find_holding(fund["id"], p["id"])
        held = h["units_held"] if h is not None else Decimal("0.0000")
        if units > held:
            err("ERR_INSUFFICIENT_CASH", 422,
                "Redemption exceeds the fund's units held in this pool")
        price = pool_unit_price(p)
        if price is None:
            err("ERR_INVALID_STATE", 409, "Pool unit price is undefined (no units outstanding)")
        payout = q2(units * price)
        e["fund_id"] = fund["id"]
        e["units_amount"] = units
        e["unit_price_applied"] = price
        e["units_delta"] = q4(-units)
        p["units_outstanding"] = q4(p["units_outstanding"] - units)
        p["nav"] = q2(p["nav"] - payout)
        fund["cash_balance"] = q2(fund["cash_balance"] + payout)
        h["units_held"] = q4(h["units_held"] - units)
        if h["units_held"] <= 0:
            # Holding rows exist only while units_held > 0.
            del STORE["holdings"][h["id"]]
        else:
            touch(h)
        touch(fund)
        touch(p)
    else:  # MARK_TO_MARKET
        new_nav = req_decimal(data, "new_nav")
        if new_nav < 0:
            err("ERR_FIELD_CONSTRAINT", 422, "new_nav must be >= 0")
        new_nav = q2(new_nav)
        old_price = pool_unit_price(p)
        p["nav"] = new_nav
        new_price = pool_unit_price(p)
        e["new_nav"] = new_nav
        e["unit_price_applied"] = new_price
        e["units_delta"] = Decimal("0.0000")
        # Per-fund mark-to-market deltas for statement investment_gain_loss.
        deltas = {}
        if old_price is not None and new_price is not None:
            for h in STORE["holdings"].values():
                if h["pool_id"] == p["id"] and h["units_held"] > 0:
                    deltas[h["fund_id"]] = h["units_held"] * (new_price - old_price)
        e["_mtm_fund_deltas"] = deltas
        touch(p)
    STORE["events"][e["id"]] = e
    return success(event_view(e), code=201)


@bp.get("/pools/<poolId>/unitization-events")
@require_roles("FoundationAdmin", "InvestmentManager", "FinanceOfficer")
def list_pool_events(poolId):
    p = get_path("pools", poolId)
    items = [e for e in STORE["events"].values() if e["pool_id"] == p["id"]]
    return list_response(items, event_view)


@bp.get("/unitization-events/<eventId>")
@require_roles("FoundationAdmin", "InvestmentManager", "FinanceOfficer")
def get_event(eventId):
    return success(event_view(get_path("events", eventId)))


@bp.get("/unitization-events")
@require_roles("FoundationAdmin", "InvestmentManager", "FinanceOfficer")
def list_events():
    items = list(STORE["events"].values())
    pid = request.args.get("pool_id")
    fid = request.args.get("fund_id")
    if pid is not None:
        items = [e for e in items if e["pool_id"] == pid]
    if fid is not None:
        items = [e for e in items if e["fund_id"] == fid]
    return list_response(items, event_view)


# ---------------------------------------------------------------------------
# Pool holdings
# ---------------------------------------------------------------------------
@bp.get("/funds/<fundId>/pool-holdings")
@require_roles("FoundationAdmin", "InvestmentManager", "FinanceOfficer")
def list_fund_holdings(fundId):
    f = get_path("funds", fundId)
    items = [h for h in STORE["holdings"].values() if h["fund_id"] == f["id"]]
    return list_response(items, holding_view)


@bp.get("/pool-holdings/<holdingId>")
@require_roles("FoundationAdmin", "InvestmentManager", "FinanceOfficer")
def get_holding(holdingId):
    return success(holding_view(get_path("holdings", holdingId)))


@bp.get("/pool-holdings")
@require_roles("FoundationAdmin", "InvestmentManager", "FinanceOfficer")
def list_holdings():
    items = list(STORE["holdings"].values())
    fid = request.args.get("fund_id")
    pid = request.args.get("pool_id")
    if fid is not None:
        items = [h for h in items if h["fund_id"] == fid]
    if pid is not None:
        items = [h for h in items if h["pool_id"] == pid]
    return list_response(items, holding_view)
