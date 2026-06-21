"""VoucherBatch + VoucherRedemption routes (§3.7)."""
from flask import Blueprint, request

from common import init_common, touch, require_fields, req_str, req_int, paginate
from db import db
from errors import err
from middleware import get_auth, require_role, get_json_body
from response import success
from routes.helpers import get_or_404, fk_or_404
from serializers import view, view_list
from services import derived

bp = Blueprint("vouchers", __name__)


# ---------------------------------------------------------------------------
# VoucherBatch
# ---------------------------------------------------------------------------
@bp.route("/voucher-batches", methods=["POST"])
def create_voucher_batch():
    _, role = get_auth()
    require_role(role, {"MarketManager"})
    body = get_json_body()
    require_fields(body, ["market_id", "market_day_id", "tokens_issued"])
    market_id = req_str(body, "market_id")
    market_day_id = req_str(body, "market_day_id")
    tokens_issued = req_int(body, "tokens_issued")

    fk_or_404("market", market_id)
    md = fk_or_404("market_day", market_day_id)
    if md["market_id"] != market_id:
        raise err("ERR_NOT_FOUND", "market_day not in market scope")

    if tokens_issued <= 0:
        raise err("ERR_INVALID_REQUEST", "tokens_issued must be > 0")

    batch = {
        "market_id": market_id,
        "market_day_id": market_day_id,
        "tokens_issued": tokens_issued,
        "tokens_redeemed": 0,
        "status": "ISSUED",
    }
    init_common(batch)
    db.voucher_batches[batch["id"]] = batch
    return success(view(batch), 201)


@bp.route("/voucher-batches/<voucher_batch_id>", methods=["GET"])
def get_voucher_batch(voucher_batch_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    b = get_or_404("voucher_batch", voucher_batch_id)
    return success(view(b), 200)


@bp.route("/voucher-batches", methods=["GET"])
def list_voucher_batches():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.voucher_batches.values())
    for key in ("market_id", "market_day_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


# ---------------------------------------------------------------------------
# VoucherRedemption
# ---------------------------------------------------------------------------
@bp.route("/voucher-redemptions", methods=["POST"])
def create_voucher_redemption():
    user_id, role = get_auth()
    require_role(role, {"MarketManager", "Vendor"})
    body = get_json_body()
    require_fields(body, ["market_id", "voucher_batch_id", "vendor_id",
                          "market_day_id", "token_count"])
    market_id = req_str(body, "market_id")
    voucher_batch_id = req_str(body, "voucher_batch_id")
    vendor_id = req_str(body, "vendor_id")
    market_day_id = req_str(body, "market_day_id")
    token_count = req_int(body, "token_count")

    # ownership (priority 2)
    if role == "Vendor" and vendor_id != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Vendor may only redeem its own tokens")

    fk_or_404("market", market_id)
    batch = fk_or_404("voucher_batch", voucher_batch_id)
    fk_or_404("vendor", vendor_id)
    md = fk_or_404("market_day", market_day_id)
    if (batch["market_id"] != market_id or md["market_id"] != market_id):
        raise err("ERR_NOT_FOUND", "batch/market_day not in market scope")

    # bounds (priority 4)
    if token_count <= 0:
        raise err("ERR_INVALID_REQUEST", "token_count must be > 0")

    # referential: redemption market_day_id must equal batch market_day_id
    if md["id"] != batch["market_day_id"]:
        raise err("ERR_REFERENTIAL_MISMATCH", "redemption market_day_id != batch market_day_id")

    redemption = {
        "market_id": market_id,
        "voucher_batch_id": voucher_batch_id,
        "vendor_id": vendor_id,
        "market_day_id": market_day_id,
        "token_count": token_count,
        "status": "SUBMITTED",
        "reimbursed_cents": 0,
    }
    init_common(redemption)
    db.voucher_redemptions[redemption["id"]] = redemption
    return success(view(redemption), 201)


@bp.route("/voucher-redemptions/<redemption_id>", methods=["GET"])
def get_voucher_redemption(redemption_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    r = get_or_404("voucher_redemption", redemption_id)
    return success(view(r), 200)


@bp.route("/voucher-redemptions", methods=["GET"])
def list_voucher_redemptions():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.voucher_redemptions.values())
    for key in ("market_id", "voucher_batch_id", "vendor_id", "market_day_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


@bp.route("/voucher-redemptions/<redemption_id>/reconcile", methods=["POST"])
def reconcile_voucher_redemption(redemption_id):
    _, role = get_auth()
    require_role(role, {"MarketManager"})
    redemption = get_or_404("voucher_redemption", redemption_id)
    # state (priority 6)
    if redemption["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Redemption is not SUBMITTED")
    # day must be OPEN or CLOSED, not CANCELLED (ERR_DAY_NOT_OPEN)
    md = db.market_days.get(redemption["market_day_id"])
    if md is None or md["status"] not in ("OPEN", "CLOSED"):
        raise err("ERR_DAY_NOT_OPEN", "Market day is not OPEN/CLOSED")

    batch = db.voucher_batches[redemption["voucher_batch_id"]]
    market = db.markets[redemption["market_id"]]

    # fiscal cap (ERR_TOKEN_OVERDRAW): running RECONCILED total + this <= issued
    running = sum(r["token_count"] for r in db.voucher_redemptions.values()
                  if r["voucher_batch_id"] == batch["id"] and r["status"] == "RECONCILED")
    if running + redemption["token_count"] > batch["tokens_issued"]:
        raise err("ERR_TOKEN_OVERDRAW", "Reconcile would exceed batch tokens_issued")

    redemption["status"] = "RECONCILED"
    redemption["reimbursed_cents"] = redemption["token_count"] * market["voucher_face_value_cents"]
    touch(redemption)
    # ledger sync (§2.9 / §3.7)
    derived.recompute_batch_tokens_redeemed(batch)
    derived.recompute_market_voucher_liability(market, force_bump=True)
    return success(view(redemption), 200)
