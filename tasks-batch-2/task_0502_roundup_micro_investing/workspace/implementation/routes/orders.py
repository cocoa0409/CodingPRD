"""Order routes (PRD §3.7): create/read/list/submit/settle/reject/cancel,
plus TaxLot reads. OCC on bucket version for submit.
"""

from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_json, require_auth, require_owner
from models import new_entity, serialize, touch
from response import success
from routes.buckets import _enforce_bucket_scope
from routes.helpers import (
    fetch_or_404,
    list_response,
    require_enum,
    require_int,
    require_str,
)
from services.settlement import settle_invest, settle_withdraw

bp = Blueprint("orders", __name__)


# ---------------------------------------------------------------------------
# Order create (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.route("/orders", methods=["POST"])
def create_order():
    role, user_id = require_auth({"Investor", "CustodialGuardian"})
    body = get_json()
    account_id = require_str(body, "account_id")
    bucket_id = require_str(body, "bucket_id")
    order_kind = require_enum(body, "order_kind", {"INVEST", "WITHDRAW"})
    requested_amount_cents = require_int(body, "requested_amount_cents", minimum=1)

    account = fetch_or_404(store.accounts, account_id)
    bucket = fetch_or_404(store.buckets, bucket_id)
    require_owner(role, user_id, account["id"])
    _enforce_bucket_scope(role, bucket["bucket_type"])

    source = require_enum(
        body,
        "source",
        {"SWEEP", "RECURRING", "FOUND_MONEY", "REFERRAL", "MANUAL"},
        required=False,
        default="MANUAL",
    )

    lot_selection_method = body.get("lot_selection_method")
    if order_kind == "WITHDRAW":
        if lot_selection_method is None:
            lot_selection_method = "FIFO"
        elif lot_selection_method not in ("FIFO", "HIFO", "SPEC_ID"):
            raise err("ERR_INVALID_REQUEST", "lot_selection_method must be FIFO, HIFO, or SPEC_ID.")
    else:
        # INVEST: source defaults MANUAL; lot_selection_method not applicable.
        lot_selection_method = lot_selection_method if lot_selection_method else None

    order = new_entity(
        {
            "account_id": account_id,
            "bucket_id": bucket_id,
            "order_kind": order_kind,
            "source": source,
            "requested_amount_cents": requested_amount_cents,
            "lot_selection_method": lot_selection_method,
            "settled_amount_cents": 0,
            "realized_gain_cents": 0,
            "management_fee_cents": 0,
            "status": "DRAFT",
        }
    )
    store.orders[order["id"]] = order
    return success(serialize(order), status=201)


@bp.route("/orders/<entity_id>", methods=["GET"])
def get_order(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    order = fetch_or_404(store.orders, entity_id)
    require_owner(role, user_id, order["account_id"])
    return success(serialize(order))


@bp.route("/orders", methods=["GET"])
def list_orders():
    role, user_id = require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    items = list(store.orders.values())
    account_id = request.args.get("account_id")
    bucket_id = request.args.get("bucket_id")
    status = request.args.get("status")
    order_kind = request.args.get("order_kind")
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    if bucket_id is not None:
        items = [o for o in items if o["bucket_id"] == bucket_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if order_kind is not None:
        items = [o for o in items if o["order_kind"] == order_kind]
    if role in ("Investor", "CustodialGuardian"):
        items = [o for o in items if o["account_id"] == user_id]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)


# ---------------------------------------------------------------------------
# Submit (PRD §3.7) — OCC on bucket version.
# ---------------------------------------------------------------------------
@bp.route("/orders/<entity_id>/submit", methods=["POST"])
def submit_order(entity_id):
    role, user_id = require_auth({"Investor", "CustodialGuardian"})
    order = fetch_or_404(store.orders, entity_id)
    require_owner(role, user_id, order["account_id"])
    bucket = store.buckets[order["bucket_id"]]
    _enforce_bucket_scope(role, bucket["bucket_type"])
    account = store.accounts[order["account_id"]]
    body = get_json()

    # Structural (priority 5): expected_bucket_version present.
    if "expected_bucket_version" not in body or body["expected_bucket_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_bucket_version is required.")
    expected = body["expected_bucket_version"]

    # State (priority 7): order DRAFT and bucket OPEN.
    if order["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT order can be submitted.")
    if bucket["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Target bucket is not OPEN.")

    # KYC gate (priority 9): owning account VERIFIED.
    if account["kyc_status"] != "VERIFIED":
        raise err("ERR_KYC_NOT_VERIFIED", "Owning account must be VERIFIED to submit.")

    # OCC (priority 21): expected_bucket_version must equal live bucket version.
    if expected != bucket["version"]:
        raise err("ERR_STALE_VERSION", "Bucket version is stale.")

    order["status"] = "SUBMITTED"
    touch(order)
    # Submit on the bucket legitimately bumps the bucket version (PRD §2.8).
    touch(bucket)
    return success(serialize(order))


# ---------------------------------------------------------------------------
# Settle (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.route("/orders/<entity_id>/settle", methods=["POST"])
def settle_order(entity_id):
    require_auth({"PlatformAdmin"})
    order = fetch_or_404(store.orders, entity_id)
    bucket = store.buckets[order["bucket_id"]]
    account = store.accounts[order["account_id"]]
    body = get_json()

    # State (priority 7): order SUBMITTED and bucket OPEN.
    if order["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED order can be settled.")
    if bucket["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Target bucket is not OPEN.")

    if order["order_kind"] == "INVEST":
        settle_invest(order, bucket, account)
    else:
        spec_lot_ids = body.get("spec_lot_ids")
        settle_withdraw(order, bucket, account, spec_lot_ids)

    order["status"] = "SETTLED"
    touch(order)
    # Settle on the bucket legitimately bumps the bucket version (PRD §2.8).
    # recompute_bucket inside the settlement already touched the bucket because
    # a settle always changes the bucket's open-lot inventory (a new lot on
    # INVEST, depleted basis/MV on WITHDRAW), so no extra touch is needed here.
    return success(serialize(order))


@bp.route("/orders/<entity_id>/reject", methods=["POST"])
def reject_order(entity_id):
    require_auth({"PlatformAdmin"})
    order = fetch_or_404(store.orders, entity_id)
    if order["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED order can be rejected.")
    order["status"] = "REJECTED"
    touch(order)
    return success(serialize(order))


@bp.route("/orders/<entity_id>/cancel", methods=["POST"])
def cancel_order(entity_id):
    role, user_id = require_auth({"Investor", "CustodialGuardian"})
    order = fetch_or_404(store.orders, entity_id)
    require_owner(role, user_id, order["account_id"])
    if order["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT order can be cancelled.")
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize(order))


# ---------------------------------------------------------------------------
# TaxLot reads (PRD §3.7, §3.12)
# ---------------------------------------------------------------------------
@bp.route("/tax-lots/<entity_id>", methods=["GET"])
def get_tax_lot(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    lot = fetch_or_404(store.tax_lots, entity_id)
    bucket = store.buckets.get(lot["bucket_id"])
    if bucket is not None:
        require_owner(role, user_id, bucket["account_id"])
    return success(serialize(lot))


@bp.route("/tax-lots", methods=["GET"])
def list_tax_lots():
    role, user_id = require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    items = list(store.tax_lots.values())
    bucket_id = request.args.get("bucket_id")
    open_order_id = request.args.get("open_order_id")
    status = request.args.get("status")
    if bucket_id is not None:
        items = [t for t in items if t["bucket_id"] == bucket_id]
    if open_order_id is not None:
        items = [t for t in items if t["open_order_id"] == open_order_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if role in ("Investor", "CustodialGuardian"):
        owned_buckets = {b["id"] for b in store.buckets.values() if b["account_id"] == user_id}
        items = [t for t in items if t["bucket_id"] in owned_buckets]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)
