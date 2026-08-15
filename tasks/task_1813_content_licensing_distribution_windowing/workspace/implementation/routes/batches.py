"""Delivery batches: queue, submit (spec check), resubmit (PRD §3.7)."""
from flask import Blueprint, request

from auth import (
    check_buyer_owns,
    require_roles,
    ROLE_RIGHTS_MANAGER,
    ROLE_PLATFORM_BUYER,
)
from domain import list_page, ser_batch
from errors import err, ERR_BATCH_NOT_FOUND, ERR_LICENSE_NOT_FOUND, ERR_BATCH_INVALID_STATE
from response import ok_list, ok_object
from store import DB, mutate
from util import CLOCK
from validate import field_arr, field_str, json_body

bp = Blueprint("batches", __name__)


def _get_batch_or_404(bid):
    rec = DB.get("batches", bid)
    if rec is None:
        err(ERR_BATCH_NOT_FOUND, "referenced delivery batch does not exist")
    return rec


def _batch_platform_id(batch):
    lic = DB.get("licenses", batch["license_id"])
    return lic["platform_id"] if lic else None


@bp.route("/licensing/delivery-batches", methods=["POST"])
def create_batch():
    require_roles(ROLE_RIGHTS_MANAGER)
    body = json_body()
    license_id = field_str(body, "license_id")
    asset_manifest = field_arr(body, "asset_manifest", min_len=1, elem_str=True)
    metadata_spec_version = field_str(body, "metadata_spec_version")
    if DB.get("licenses", license_id) is None:
        err(ERR_LICENSE_NOT_FOUND, "referenced license does not exist")
    rec = DB.insert(
        "batches",
        {
            "license_id": license_id,
            "asset_manifest": list(asset_manifest),
            "metadata_spec_version": metadata_spec_version,
            "delivery_status": "QUEUED",
            "missing_profiles": [],
            "attempt_count": 0,
            "submitted_at": None,
            "delivered_at": None,
        },
    )
    return ok_object(ser_batch(rec), status=201)


@bp.route("/licensing/delivery-batches", methods=["GET"])
def list_batches():
    user_id, role = require_roles(ROLE_RIGHTS_MANAGER, ROLE_PLATFORM_BUYER)
    records = DB.all("batches")
    if role == ROLE_PLATFORM_BUYER:
        records = [b for b in records if _batch_platform_id(b) == user_id]
    license_id = request.args.get("license_id")
    if license_id is not None:
        records = [b for b in records if b["license_id"] == license_id]
    status = request.args.get("delivery_status")
    if status is not None:
        records = [b for b in records if b["delivery_status"] == status]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_batch(b) for b in page], limit, offset, total)


@bp.route("/licensing/delivery-batches/<bid>", methods=["GET"])
def get_batch(bid):
    user_id, role = require_roles(ROLE_RIGHTS_MANAGER, ROLE_PLATFORM_BUYER)
    rec = _get_batch_or_404(bid)
    check_buyer_owns(user_id, role, _batch_platform_id(rec))
    return ok_object(ser_batch(rec))


@bp.route("/licensing/delivery-batches/<bid>/submit", methods=["POST"])
def submit_batch(bid):
    require_roles(ROLE_RIGHTS_MANAGER)
    rec = _get_batch_or_404(bid)
    if rec["delivery_status"] != "QUEUED":
        err(ERR_BATCH_INVALID_STATE, "only a QUEUED batch can be submitted")
    lic = DB.get("licenses", rec["license_id"])
    platform = DB.get("platforms", lic["platform_id"]) if lic else None
    required = platform["required_asset_profiles"] if platform else []
    missing = [p for p in required if p not in rec["asset_manifest"]]
    spec_ok = platform is not None and rec["metadata_spec_version"] == platform["metadata_spec_version"]
    rec["attempt_count"] += 1
    rec["submitted_at"] = CLOCK.now()
    if not missing and spec_ok:
        rec["delivery_status"] = "DELIVERED"
        rec["missing_profiles"] = []
        rec["delivered_at"] = CLOCK.now()
    else:
        rec["delivery_status"] = "REJECTED"
        rec["missing_profiles"] = missing
    mutate(rec)
    return ok_object(ser_batch(rec))


@bp.route("/licensing/delivery-batches/<bid>/resubmit", methods=["POST"])
def resubmit_batch(bid):
    require_roles(ROLE_RIGHTS_MANAGER)
    rec = _get_batch_or_404(bid)
    body = json_body()
    asset_manifest = field_arr(body, "asset_manifest", min_len=1, elem_str=True)
    metadata_spec_version = field_str(body, "metadata_spec_version")
    if rec["delivery_status"] != "REJECTED":
        err(ERR_BATCH_INVALID_STATE, "only a REJECTED batch can be resubmitted")
    rec["asset_manifest"] = list(asset_manifest)
    rec["metadata_spec_version"] = metadata_spec_version
    rec["missing_profiles"] = []
    rec["delivery_status"] = "QUEUED"
    mutate(rec)
    return ok_object(ser_batch(rec))
