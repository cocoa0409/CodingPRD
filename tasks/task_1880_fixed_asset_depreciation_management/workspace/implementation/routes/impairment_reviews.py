"""ImpairmentReview endpoints."""
from flask import Blueprint, request
import db
import errors
from db import new_id, now_iso
from middleware import (require_roles, get_body, get_pagination,
                        require_string, require_enum, require_int)
from response import success_object, success_list
from services.serializers import impairment_review_view, recompute_asset_derived
from services import depreciation as dep

bp = Blueprint("impairment_reviews", __name__)
ALL_ROLES = ("AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst")
INDICATORS = {"DAMAGE", "OBSOLESCENCE", "MARKET_DECLINE"}


@bp.route("/impairment-reviews", methods=["POST"])
def create_review():
    user_id, _ = require_roles("AssetAccountant")
    data = get_body()
    asset_id = require_string(data, "asset_id")
    indicator = require_enum(data, "indicator", INDICATORS)
    asset = db.fixed_assets.get(asset_id)
    if asset is None:
        raise errors.not_found("asset_id not found")
    # state
    if asset["status"] == "DISPOSED":
        raise errors.already_disposed()
    if asset["status"] == "DRAFT":
        raise errors.asset_not_in_service()
    # one OPEN per asset (priority 6)
    for r in db.impairment_reviews.values():
        if r["asset_id"] == asset_id and r["status"] == "OPEN":
            raise errors.impairment_review_open()
    ts = now_iso()
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "indicator": indicator,
        "source": "MANUAL",
        "created_by_user_id": user_id,
        "recoverable_value_cents": None,
        "write_down_cents": None,
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.impairment_reviews[rec["id"]] = rec
    return success_object(impairment_review_view(rec), 201)


@bp.route("/impairment-reviews", methods=["GET"])
def list_reviews():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    f_asset = request.args.get("asset_id")
    f_status = request.args.get("status")
    items = sorted(db.impairment_reviews.values(), key=lambda r: (r["created_at"], r["id"]))
    out = []
    for rec in items:
        if f_asset is not None and rec["asset_id"] != f_asset:
            continue
        if f_status is not None and rec["status"] != f_status:
            continue
        out.append(rec)
    total = len(out)
    page = out[offset:offset + limit]
    return success_list([impairment_review_view(r) for r in page], limit, offset, total)


@bp.route("/impairment-reviews/<rid>", methods=["GET"])
def get_review(rid):
    require_roles(*ALL_ROLES)
    rec = db.impairment_reviews.get(rid)
    if rec is None:
        raise errors.not_found("Impairment review not found")
    return success_object(impairment_review_view(rec))


@bp.route("/impairment-reviews/<rid>/confirm", methods=["POST"])
def confirm_review(rid):
    user_id, _ = require_roles("Controller")
    data = get_body()
    rec = db.impairment_reviews.get(rid)
    if rec is None:
        raise errors.not_found("Impairment review not found")
    asset = db.fixed_assets.get(rec["asset_id"])
    if asset is None:
        raise errors.not_found("Asset not found")
    # SoD (priority 2) before state (priority 4) — only for MANUAL reviews
    if rec["source"] == "MANUAL" and user_id == rec["created_by_user_id"]:
        raise errors.segregation_of_duties("Confirmer must differ from review creator")
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Review is not OPEN")
    recoverable = require_int(data, "recoverable_value_cents")
    if recoverable < 0:
        raise errors.invalid_request("recoverable_value_cents must be >= 0")
    # OCC — required field
    if "expected_asset_version" not in data or data["expected_asset_version"] is None:
        raise errors.invalid_request("Missing required field: expected_asset_version")
    expected = data["expected_asset_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_asset_version must be an integer")
    if expected != asset["version"]:
        raise errors.stale_version()

    recompute_asset_derived(asset)
    nbv = asset["net_book_value_cents"]
    write_down = nbv - recoverable
    if write_down <= 0:
        raise errors.no_impairment_indicated()

    rec["recoverable_value_cents"] = recoverable
    rec["write_down_cents"] = write_down
    rec["status"] = "WRITTEN_DOWN"
    rec["version"] += 1
    rec["updated_at"] = now_iso()

    # cascade onto asset
    asset["impairment_total_cents"] += write_down
    asset["net_book_value_cents"] = (asset["acquisition_cost_cents"]
                                     - asset["accumulated_book_cents"]
                                     - asset["impairment_total_cents"])
    asset["version"] += 1
    asset["updated_at"] = now_iso()
    # auto transition if remaining basis <= 0; PRD §3.4 defines the remaining
    # basis here as cost - salvage - accumulated_book - impairment_total
    remaining_basis = (asset["acquisition_cost_cents"]
                       - asset["salvage_value_cents"]
                       - asset["accumulated_book_cents"]
                       - asset["impairment_total_cents"])
    if remaining_basis <= 0 and asset["status"] == "IN_SERVICE":
        asset["status"] = "FULLY_DEPRECIATED"
    recompute_asset_derived(asset)
    return success_object(impairment_review_view(rec))


@bp.route("/impairment-reviews/<rid>/dismiss", methods=["POST"])
def dismiss_review(rid):
    require_roles("Controller")
    rec = db.impairment_reviews.get(rid)
    if rec is None:
        raise errors.not_found("Impairment review not found")
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Review is not OPEN")
    rec["status"] = "DISMISSED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(impairment_review_view(rec))
