"""Disposal endpoints with full lifecycle and cascade."""
from flask import Blueprint, request
import db
import errors
from db import new_id, now_iso
from middleware import (require_roles, get_body, get_pagination,
                        require_string, optional_string, optional_int,
                        require_enum, require_date)
from response import success_object, success_list
from services.serializers import disposal_view, recompute_asset_derived
from services import depreciation as dep

bp = Blueprint("disposals", __name__)
ALL_ROLES = ("AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst")
DISPOSAL_TYPES = {"SALE", "SCRAP", "TRANSFER"}


def _validate_disposal_fields(asset, disposal_type, proceeds, transfer_to, effective_date):
    """Field-value validation (priority 8) shared by create and resubmit."""
    if disposal_type == "SALE":
        if proceeds is None:
            raise errors.invalid_disposal_fields("SALE requires proceeds_cents")
        if transfer_to is not None:
            raise errors.invalid_disposal_fields("transfer_to_cost_center forbidden for SALE")
    elif disposal_type == "SCRAP":
        if proceeds is None:
            proceeds = 0
        if transfer_to is not None:
            raise errors.invalid_disposal_fields("transfer_to_cost_center forbidden for SCRAP")
    elif disposal_type == "TRANSFER":
        if not transfer_to:
            raise errors.invalid_disposal_fields("TRANSFER requires transfer_to_cost_center")
        if proceeds is None:
            proceeds = 0
        if proceeds != 0:
            raise errors.invalid_disposal_fields("TRANSFER requires proceeds_cents == 0")
    if proceeds is not None and proceeds < 0:
        raise errors.invalid_amount("proceeds_cents must be >= 0")
    # effective_date must be >= in_service_date
    if asset is not None and asset.get("in_service_date"):
        if effective_date < asset["in_service_date"]:
            raise errors.invalid_disposal_fields("effective_date before in_service_date")
    return proceeds


def _check_period_open(effective_date):
    """Effective period must be later than latest POSTED run period."""
    latest = dep.latest_posted_period()
    if latest is not None:
        if dep.period_of_date(effective_date) <= latest:
            raise errors.period_closed()


@bp.route("/disposals", methods=["POST"])
def create_disposal():
    user_id, _ = require_roles("AssetAccountant")
    data = get_body()
    asset_id = require_string(data, "asset_id")
    disposal_type = require_enum(data, "disposal_type", DISPOSAL_TYPES)
    effective_date = require_date(data, "effective_date")
    proceeds = optional_int(data, "proceeds_cents")
    transfer_to = optional_string(data, "transfer_to_cost_center")

    asset = db.fixed_assets.get(asset_id)
    if asset is None:
        raise errors.not_found("asset_id not found")
    # state (priority 4)
    if asset["status"] == "DISPOSED":
        raise errors.already_disposed()
    if asset["status"] == "DRAFT":
        raise errors.asset_not_in_service()
    # temporal (priority 7)
    _check_period_open(effective_date)
    # field-value (priority 8)
    proceeds = _validate_disposal_fields(asset, disposal_type, proceeds, transfer_to, effective_date)

    ts = now_iso()
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "disposal_type": disposal_type,
        "proceeds_cents": proceeds,
        "transfer_to_cost_center": transfer_to,
        "effective_date": effective_date,
        "requested_by_user_id": user_id,
        "approved_by_user_id": None,
        "book_gain_loss_cents": None,
        "tax_gain_loss_cents": None,
        "auto_created": False,
        "status": "REQUESTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.disposals[rec["id"]] = rec
    return success_object(disposal_view(rec), 201)


@bp.route("/disposals", methods=["GET"])
def list_disposals():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    f_asset = request.args.get("asset_id")
    f_status = request.args.get("status")
    items = sorted(db.disposals.values(), key=lambda r: (r["created_at"], r["id"]))
    out = []
    for rec in items:
        if f_asset is not None and rec["asset_id"] != f_asset:
            continue
        if f_status is not None and rec["status"] != f_status:
            continue
        out.append(rec)
    total = len(out)
    page = out[offset:offset + limit]
    return success_list([disposal_view(r) for r in page], limit, offset, total)


@bp.route("/disposals/<did>", methods=["GET"])
def get_disposal(did):
    require_roles(*ALL_ROLES)
    rec = db.disposals.get(did)
    if rec is None:
        raise errors.not_found("Disposal not found")
    return success_object(disposal_view(rec))


@bp.route("/disposals/<did>/approve", methods=["POST"])
def approve_disposal(did):
    user_id, _ = require_roles("Controller")
    rec = db.disposals.get(did)
    if rec is None:
        raise errors.not_found("Disposal not found")
    # SoD (priority 2) before state (priority 4)
    if user_id == rec["requested_by_user_id"]:
        raise errors.segregation_of_duties("Approver must differ from requester")
    if rec["status"] != "REQUESTED":
        raise errors.invalid_state("Disposal is not REQUESTED")
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = user_id
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(disposal_view(rec))


@bp.route("/disposals/<did>/reject", methods=["POST"])
def reject_disposal(did):
    require_roles("Controller")
    rec = db.disposals.get(did)
    if rec is None:
        raise errors.not_found("Disposal not found")
    if rec["status"] != "REQUESTED":
        raise errors.invalid_state("Disposal is not REQUESTED")
    rec["status"] = "REJECTED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(disposal_view(rec))


@bp.route("/disposals/<did>/resubmit", methods=["POST"])
def resubmit_disposal(did):
    require_roles("AssetAccountant")
    data = get_body()
    rec = db.disposals.get(did)
    if rec is None:
        raise errors.not_found("Disposal not found")
    if rec["status"] != "REJECTED":
        raise errors.invalid_state("Disposal is not REJECTED")
    asset = db.fixed_assets.get(rec["asset_id"])
    if asset is None:
        raise errors.not_found("Asset not found")
    if asset["status"] not in ("IN_SERVICE", "FULLY_DEPRECIATED"):
        raise errors.already_disposed()

    # Replace fields if provided
    proceeds = rec.get("proceeds_cents")
    transfer_to = rec.get("transfer_to_cost_center")
    effective_date = rec["effective_date"]
    if "proceeds_cents" in data:
        v = data["proceeds_cents"]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise errors.invalid_request("proceeds_cents must be an integer")
        proceeds = v
    if "transfer_to_cost_center" in data:
        v = data["transfer_to_cost_center"]
        if v is not None and not isinstance(v, str):
            raise errors.invalid_request("transfer_to_cost_center must be a string")
        transfer_to = v
    if "effective_date" in data:
        effective_date = require_date(data, "effective_date")

    # temporal (priority 7)
    _check_period_open(effective_date)
    # field-value (priority 8)
    proceeds = _validate_disposal_fields(asset, rec["disposal_type"], proceeds, transfer_to, effective_date)

    rec["proceeds_cents"] = proceeds
    rec["transfer_to_cost_center"] = transfer_to
    rec["effective_date"] = effective_date
    rec["status"] = "REQUESTED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(disposal_view(rec))


def _post_derecognition(disposal, asset):
    """SALE/SCRAP posting: final entries, gain/loss, DISPOSED, component cascade."""
    recompute_asset_derived(asset)
    period = dep.period_of_date(disposal["effective_date"])
    day = int(disposal["effective_date"][8:10])
    # Step 1: final-period depreciation (only if IN_SERVICE and day >= 15)
    if asset["status"] == "IN_SERVICE" and day >= dep.MID_MONTH_CUTOFF_DAY:
        changed = False
        if dep.book_eligible(asset, period):
            amt = dep.book_amount(asset, period)
            if amt < 0:
                amt = 0
            dep.create_entry(asset["id"], "BOOK", period, amt, "DISPOSAL_FINAL",
                             disposal_id=disposal["id"])
            changed = True
        if dep.tax_eligible(asset, period):
            amt = dep.tax_amount(asset, period)
            dep.create_entry(asset["id"], "TAX", period, amt, "DISPOSAL_FINAL",
                             disposal_id=disposal["id"])
            changed = True
        if changed:
            recompute_asset_derived(asset)
    # Step 2 & 3: gain/loss
    book_carrying = (asset["acquisition_cost_cents"]
                     - asset["accumulated_book_cents"]
                     - asset["impairment_total_cents"])
    tax_basis = asset["acquisition_cost_cents"] - asset["accumulated_tax_cents"]
    disposal["book_gain_loss_cents"] = disposal["proceeds_cents"] - book_carrying
    disposal["tax_gain_loss_cents"] = disposal["proceeds_cents"] - tax_basis
    # Transition asset
    if asset["status"] in ("IN_SERVICE", "FULLY_DEPRECIATED"):
        asset["status"] = "DISPOSED"
        asset["version"] += 1
        asset["updated_at"] = now_iso()


def _post_disposal(disposal):
    """Execute the post. Caller has validated state and gates."""
    asset = db.fixed_assets[disposal["asset_id"]]
    if disposal["disposal_type"] == "TRANSFER":
        asset["cost_center"] = disposal["transfer_to_cost_center"]
        asset["version"] += 1
        asset["updated_at"] = now_iso()
        disposal["book_gain_loss_cents"] = 0
        disposal["tax_gain_loss_cents"] = 0
    else:
        _post_derecognition(disposal, asset)
        # component cascade
        children = sorted(
            (a for a in db.fixed_assets.values() if a.get("parent_asset_id") == asset["id"]),
            key=lambda a: (a["created_at"], a["id"]),
        )
        for child in children:
            if child["status"] in ("IN_SERVICE", "FULLY_DEPRECIATED"):
                ts = now_iso()
                companion = {
                    "id": new_id(),
                    "asset_id": child["id"],
                    "disposal_type": "SCRAP",
                    "proceeds_cents": 0,
                    "transfer_to_cost_center": None,
                    "effective_date": disposal["effective_date"],
                    "requested_by_user_id": "system",
                    "approved_by_user_id": "system",
                    "book_gain_loss_cents": None,
                    "tax_gain_loss_cents": None,
                    "auto_created": True,
                    "status": "APPROVED",
                    "created_at": ts,
                    "updated_at": ts,
                    "version": 1,
                }
                db.disposals[companion["id"]] = companion
                _post_derecognition(companion, child)
                companion["status"] = "POSTED"
                companion["version"] += 1
                companion["updated_at"] = now_iso()
    disposal["status"] = "POSTED"
    disposal["version"] += 1
    disposal["updated_at"] = now_iso()


@bp.route("/disposals/<did>/post", methods=["POST"])
def post_disposal(did):
    require_roles("AssetAccountant")
    rec = db.disposals.get(did)
    if rec is None:
        raise errors.not_found("Disposal not found")
    if rec["status"] != "APPROVED":
        raise errors.invalid_state("Disposal is not APPROVED")
    asset = db.fixed_assets.get(rec["asset_id"])
    if asset is None:
        raise errors.not_found("Asset not found")
    # compliance gate (priority 5) before temporal period rules (priority 7)
    if rec["disposal_type"] in ("SALE", "TRANSFER"):
        recompute_asset_derived(asset)
        if asset["open_inventory_exception"]:
            raise errors.asset_under_inventory_review()
    # re-validate period (priority 7)
    _check_period_open(rec["effective_date"])
    _post_disposal(rec)
    return success_object(disposal_view(rec))
