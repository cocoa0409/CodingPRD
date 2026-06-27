"""Bucket routes (PRD §3.6): open/read/list/freeze/unfreeze/close.

Custodial scoping (PRD §2.1, §3.6): a CustodialGuardian may act only on UTMA
buckets; an Investor may not act on UTMA buckets.
"""

from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_json, require_auth, require_owner
from models import new_entity, serialize, touch
from response import success
from routes.helpers import (
    fetch_or_404,
    list_response,
    require_enum,
    require_str,
)

bp = Blueprint("buckets", __name__)


def _enforce_bucket_scope(role, bucket_type):
    """Priority 8 (PRD §3.6): CustodialGuardian -> UTMA only; Investor -> non-UTMA."""
    if role == "CustodialGuardian" and bucket_type != "UTMA":
        raise err("ERR_BUCKET_TYPE_NOT_PERMITTED", "A guardian may act only on UTMA buckets.")
    if role == "Investor" and bucket_type == "UTMA":
        raise err("ERR_BUCKET_TYPE_NOT_PERMITTED", "An investor may not act on UTMA buckets.")


@bp.route("/buckets", methods=["POST"])
def open_bucket():
    role, user_id = require_auth({"Investor", "CustodialGuardian"})
    body = get_json()
    account_id = require_str(body, "account_id")
    bucket_type = require_enum(body, "bucket_type", {"TAXABLE", "UTMA", "IRA"})

    account = fetch_or_404(store.accounts, account_id)
    require_owner(role, user_id, account["id"])

    # Priority 8 — role/bucket-type scope.
    _enforce_bucket_scope(role, bucket_type)

    plan = store.subscription_plans[account["plan_id"]]

    # Priority 10 — plan entitlements (PRD §3.6).
    if bucket_type == "UTMA" and not plan["allows_custodial"]:
        raise err("ERR_BUCKET_NOT_ALLOWED_BY_PLAN", "Plan does not allow custodial (UTMA) buckets.")
    if bucket_type == "IRA" and not plan["allows_ira"]:
        raise err("ERR_BUCKET_NOT_ALLOWED_BY_PLAN", "Plan does not allow IRA buckets.")

    # Priority 11 — UTMA requires beneficiary_name (PRD §3.6).
    beneficiary_name = body.get("beneficiary_name")
    if bucket_type == "UTMA" and (beneficiary_name is None or beneficiary_name == ""):
        raise err("ERR_BENEFICIARY_REQUIRED", "UTMA bucket requires a beneficiary_name.")

    bucket = new_entity(
        {
            "account_id": account_id,
            "bucket_type": bucket_type,
            "beneficiary_name": beneficiary_name,
            "ytd_ira_contributed_cents": 0,
            "invested_principal_cents": 0,
            "market_value_cents": 0,
            "total_drift_bps": 0,
            "needs_rebalance": False,
            "status": "OPEN",
        }
    )
    store.buckets[bucket["id"]] = bucket
    return success(serialize(bucket), status=201)


@bp.route("/buckets/<entity_id>", methods=["GET"])
def get_bucket(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    bucket = fetch_or_404(store.buckets, entity_id)
    require_owner(role, user_id, bucket["account_id"])
    return success(serialize(bucket))


@bp.route("/buckets", methods=["GET"])
def list_buckets():
    role, user_id = require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    items = list(store.buckets.values())
    account_id = request.args.get("account_id")
    bucket_type = request.args.get("bucket_type")
    status = request.args.get("status")
    if account_id is not None:
        items = [b for b in items if b["account_id"] == account_id]
    if bucket_type is not None:
        items = [b for b in items if b["bucket_type"] == bucket_type]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if role in ("Investor", "CustodialGuardian"):
        items = [b for b in items if b["account_id"] == user_id]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)


@bp.route("/buckets/<entity_id>/freeze", methods=["POST"])
def freeze_bucket(entity_id):
    require_auth({"PlatformAdmin"})
    bucket = fetch_or_404(store.buckets, entity_id)
    if bucket["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only an OPEN bucket can be frozen.")
    bucket["status"] = "FROZEN"
    touch(bucket)
    return success(serialize(bucket))


@bp.route("/buckets/<entity_id>/unfreeze", methods=["POST"])
def unfreeze_bucket(entity_id):
    require_auth({"PlatformAdmin"})
    bucket = fetch_or_404(store.buckets, entity_id)
    if bucket["status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "Only a FROZEN bucket can be unfrozen.")
    account = store.accounts[bucket["account_id"]]
    if account["kyc_status"] != "VERIFIED":
        raise err("ERR_KYC_NOT_VERIFIED", "Owning account must be VERIFIED to unfreeze.")
    bucket["status"] = "OPEN"
    touch(bucket)
    return success(serialize(bucket))


@bp.route("/buckets/<entity_id>/close", methods=["POST"])
def close_bucket(entity_id):
    role, user_id = require_auth({"Investor", "CustodialGuardian"})
    bucket = fetch_or_404(store.buckets, entity_id)
    require_owner(role, user_id, bucket["account_id"])
    _enforce_bucket_scope(role, bucket["bucket_type"])

    if bucket["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only an OPEN bucket can be closed.")

    # No OPEN tax lots and no non-terminal orders (PRD §3.6).
    for lot in store.tax_lots.values():
        if lot["bucket_id"] == bucket["id"] and lot["status"] == "OPEN":
            raise err("ERR_BUCKET_NOT_EMPTY", "Bucket has OPEN tax lots.")
    for o in store.orders.values():
        if o["bucket_id"] == bucket["id"] and o["status"] in ("DRAFT", "SUBMITTED"):
            raise err("ERR_BUCKET_NOT_EMPTY", "Bucket has non-terminal orders.")

    bucket["status"] = "CLOSED"
    touch(bucket)
    return success(serialize(bucket))
