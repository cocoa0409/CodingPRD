"""Contributions, asset lots, liquidation waterfall."""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request

from common import (
    STORE, D, body, err, get_path, get_ref, list_response, new_resource, now,
    opt_decimal, q2, reactivate_if_inactive, req_decimal, req_enum,
    req_present, require_roles, serialize, success, touch,
)

bp = Blueprint("gifts", __name__)

ASSET_KINDS = ("CASH", "PUBLICLY_TRADED", "RESTRICTED_STOCK", "REAL_PROPERTY")
BROKERAGE_FLAT_PER_LOT = Decimal("75.00")


def contribution_view(c):
    return serialize(c)


def lot_view(l):
    return serialize(l)


# ---------------------------------------------------------------------------
# Contributions
# ---------------------------------------------------------------------------
@bp.post("/contributions")
@require_roles("GiftOfficer")
def create_contribution():
    data = body()
    fund_id = data.get("fund_id")
    if fund_id is not None:
        get_ref("funds", fund_id, "fund")
    fund_id = req_present(data, "fund_id")
    get_ref("funds", fund_id, "fund")
    donor = req_present(data, "donor_name")
    kind = req_enum(data, "asset_kind", ASSET_KINDS)
    declared = req_decimal(data, "declared_value")
    if declared <= 0:
        err("ERR_FIELD_CONSTRAINT", 422, "declared_value must be greater than zero")
    c = new_resource()
    c.update({
        "fund_id": fund_id,
        "donor_name": donor,
        "asset_kind": kind,
        "declared_value": q2(declared),
        "acceptance_status": "PLEDGED",
        "liquidation_status": "NOT_REQUIRED" if kind == "CASH" else "PENDING_LIQUIDATION",
        "net_proceeds": None,
        "gift_date": None,
        "decline_reason": None,
    })
    STORE["contributions"][c["id"]] = c
    return success(contribution_view(c), code=201)


@bp.get("/contributions")
@require_roles("FoundationAdmin", "GiftOfficer", "FinanceOfficer")
def list_contributions():
    items = list(STORE["contributions"].values())
    fid = request.args.get("fund_id")
    st = request.args.get("acceptance_status")
    if fid is not None:
        items = [c for c in items if c["fund_id"] == fid]
    if st is not None:
        items = [c for c in items if c["acceptance_status"] == st]
    return list_response(items, contribution_view)


@bp.get("/contributions/<contributionId>")
@require_roles("FoundationAdmin", "GiftOfficer", "FinanceOfficer")
def get_contribution(contributionId):
    return success(contribution_view(get_path("contributions", contributionId)))


# ---------------------------------------------------------------------------
# Asset lots
# ---------------------------------------------------------------------------
@bp.post("/contributions/<contributionId>/lots")
@require_roles("GiftOfficer")
def add_lot(contributionId):
    c = get_path("contributions", contributionId)
    data = body()
    if c["acceptance_status"] != "PLEDGED":
        err("ERR_INVALID_STATE", 409, "Lots may be added only to a PLEDGED contribution")
    if c["asset_kind"] == "CASH":
        err("ERR_INVALID_STATE", 409, "Asset lots apply only to non-cash contributions")
    description = req_present(data, "description")
    quantity = req_decimal(data, "quantity")
    if quantity <= 0:
        err("ERR_FIELD_CONSTRAINT", 422, "quantity must be greater than zero")
    appraised = req_decimal(data, "appraised_value")
    if appraised <= 0:
        err("ERR_FIELD_CONSTRAINT", 422, "appraised_value must be greater than zero")
    fee_pct = opt_decimal(data, "liquidation_fee_pct", Decimal("1.50"))
    if fee_pct < 0:
        err("ERR_FIELD_CONSTRAINT", 422, "liquidation_fee_pct must be >= 0")
    lot = new_resource(common_fields=False)
    lot.update({
        "contribution_id": c["id"],
        "description": description,
        "quantity": q2(quantity),
        "appraised_value": q2(appraised),
        "liquidation_fee_pct": q2(fee_pct),
        "gross_proceeds": None,
    })
    STORE["lots"][lot["id"]] = lot
    return success(lot_view(lot), code=201)


@bp.get("/contributions/<contributionId>/lots")
@require_roles("FoundationAdmin", "GiftOfficer", "FinanceOfficer")
def list_contribution_lots(contributionId):
    c = get_path("contributions", contributionId)
    items = [l for l in STORE["lots"].values() if l["contribution_id"] == c["id"]]
    return list_response(items, lot_view)


@bp.get("/lots/<lotId>")
@require_roles("FoundationAdmin", "GiftOfficer", "FinanceOfficer")
def get_lot(lotId):
    return success(lot_view(get_path("lots", lotId)))


@bp.get("/lots")
@require_roles("FoundationAdmin", "GiftOfficer", "FinanceOfficer")
def list_lots():
    items = list(STORE["lots"].values())
    cid = request.args.get("contribution_id")
    if cid is not None:
        items = [l for l in items if l["contribution_id"] == cid]
    return list_response(items, lot_view)


# ---------------------------------------------------------------------------
# Acceptance / decline / liquidation
# ---------------------------------------------------------------------------
@bp.post("/contributions/<contributionId>/accept")
@require_roles("GiftOfficer")
def accept_contribution(contributionId):
    c = get_path("contributions", contributionId)
    if c["acceptance_status"] != "PLEDGED":
        err("ERR_INVALID_STATE", 409, "Only a PLEDGED contribution can be accepted")
    f = STORE["funds"][c["fund_id"]]
    if f["status"] not in ("PENDING_AGREEMENT", "ACTIVE"):
        err("ERR_FUND_NOT_ACCEPTING", 409,
            "Fund is not accepting contributions in its current state")
    c["acceptance_status"] = "ACCEPTED"
    c["gift_date"] = now()
    if c["asset_kind"] == "CASH":
        c["net_proceeds"] = q2(c["declared_value"])
        f["cash_balance"] = q2(f["cash_balance"] + c["net_proceeds"])
        c["liquidation_status"] = "LIQUIDATED"
    # Acceptance is qualifying activity regardless of asset kind.
    f["last_activity_at"] = now()
    reactivate_if_inactive(f)
    touch(f)
    touch(c)
    return success(contribution_view(c))


@bp.post("/contributions/<contributionId>/decline")
@require_roles("GiftOfficer")
def decline_contribution(contributionId):
    c = get_path("contributions", contributionId)
    if c["acceptance_status"] != "PLEDGED":
        err("ERR_INVALID_STATE", 409, "Only a PLEDGED contribution can be declined")
    data = body()
    reason = req_present(data, "decline_reason")
    c["acceptance_status"] = "DECLINED"
    c["decline_reason"] = reason
    touch(c)
    return success(contribution_view(c))


@bp.post("/contributions/<contributionId>/liquidate")
@require_roles("GiftOfficer")
def liquidate_contribution(contributionId):
    c = get_path("contributions", contributionId)
    if c["acceptance_status"] != "ACCEPTED" or c["liquidation_status"] != "PENDING_LIQUIDATION":
        err("ERR_INVALID_STATE", 409,
            "Only an ACCEPTED contribution pending liquidation can be liquidated")
    data = body()
    raw = data.get("lot_proceeds")
    proceeds_map = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            proceeds_map[k] = v
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and "lot_id" in entry:
                proceeds_map[entry["lot_id"]] = entry.get("gross_proceeds")
    lots = [l for l in STORE["lots"].values() if l["contribution_id"] == c["id"]]
    lots.sort(key=lambda l: (l["created_at"], -l["appraised_value"], l["_seq"]))
    # Every lot must have gross_proceeds recorded in the payload.
    missing = [l for l in lots if l["id"] not in proceeds_map or proceeds_map[l["id"]] is None]
    if missing:
        err("ERR_LOT_PROCEEDS_MISSING", 422,
            "gross_proceeds must be recorded for every asset lot of the contribution")
    net_total = Decimal("0.00")
    parsed = {}
    for l in lots:
        try:
            gp = D(proceeds_map[l["id"]])
        except (InvalidOperation, ValueError, AttributeError):
            err("ERR_FIELD_CONSTRAINT", 422, "gross_proceeds must be a number")
        if gp < 0:
            err("ERR_FIELD_CONSTRAINT", 422, "gross_proceeds must be >= 0")
        parsed[l["id"]] = q2(gp)
    # Liquidation waterfall: per-lot fee rounded to 2dp first, then netted, then summed.
    for l in lots:
        gp = parsed[l["id"]]
        l["gross_proceeds"] = gp
        lot_fee = q2(gp * l["liquidation_fee_pct"] / Decimal("100"))
        lot_net = gp - lot_fee - BROKERAGE_FLAT_PER_LOT
        if lot_net < 0:
            lot_net = Decimal("0.00")
        net_total += lot_net
    c["net_proceeds"] = q2(net_total)
    c["liquidation_status"] = "LIQUIDATED"
    f = STORE["funds"][c["fund_id"]]
    f["cash_balance"] = q2(f["cash_balance"] + c["net_proceeds"])
    f["last_activity_at"] = now()
    reactivate_if_inactive(f)
    touch(f)
    touch(c)
    return success(contribution_view(c))
