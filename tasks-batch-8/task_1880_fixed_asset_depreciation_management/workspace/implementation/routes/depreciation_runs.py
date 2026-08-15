"""DepreciationRun and DepreciationEntry endpoints."""
from flask import Blueprint, request
import db
import errors
from db import new_id, now_iso
from middleware import require_roles, get_body, get_pagination, require_period
from response import success_object, success_list
from services.serializers import (depreciation_run_view, depreciation_entry_view,
                                  recompute_asset_derived)
from services import depreciation as dep

bp = Blueprint("depreciation_runs", __name__)
ALL_ROLES = ("AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst")


@bp.route("/depreciation-runs", methods=["POST"])
def create_run():
    require_roles("AssetAccountant")
    data = get_body()
    period = require_period(data, "period")
    # uniqueness (priority 6)
    for r in db.depreciation_runs.values():
        if r["period"] == period:
            if r["status"] == "OPEN":
                raise errors.duplicate_run_period()
            if r["status"] == "POSTED":
                raise errors.period_already_posted()
    # period gap (priority 7)
    latest = dep.latest_posted_period()
    if latest is not None:
        if period != dep.period_next(latest):
            raise errors.period_gap()
    ts = now_iso()
    rec = {
        "id": new_id(),
        "period": period,
        "status": "OPEN",
        "entries_created_count": 0,
        "total_book_amount_cents": 0,
        "total_tax_amount_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.depreciation_runs[rec["id"]] = rec
    return success_object(depreciation_run_view(rec), 201)


@bp.route("/depreciation-runs/<rid>", methods=["GET"])
def get_run(rid):
    require_roles(*ALL_ROLES)
    rec = db.depreciation_runs.get(rid)
    if rec is None:
        raise errors.not_found("Depreciation run not found")
    return success_object(depreciation_run_view(rec))


@bp.route("/depreciation-runs/<rid>/post", methods=["POST"])
def post_run(rid):
    require_roles("AssetAccountant")
    rec = db.depreciation_runs.get(rid)
    if rec is None:
        raise errors.not_found("Depreciation run not found")
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Run is not OPEN")
    period = rec["period"]
    entries_created = 0
    total_book = 0
    total_tax = 0
    # Sweep all IN_SERVICE assets, deterministic order
    assets = sorted(db.fixed_assets.values(), key=lambda a: (a["created_at"], a["id"]))
    for asset in assets:
        if asset["status"] != "IN_SERVICE":
            continue
        recompute_asset_derived(asset)
        changed = False
        # Book
        if dep.book_eligible(asset, period):
            amt = dep.book_amount(asset, period)
            if amt < 0:
                amt = 0
            dep.create_entry(asset["id"], "BOOK", period, amt, "RUN", run_id=rec["id"])
            entries_created += 1
            total_book += amt
            changed = True
        # Tax
        if dep.tax_eligible(asset, period):
            amt = dep.tax_amount(asset, period)
            if amt > 0 or True:
                dep.create_entry(asset["id"], "TAX", period, amt, "RUN", run_id=rec["id"])
                entries_created += 1
                total_tax += amt
                changed = True
        if changed:
            recompute_asset_derived(asset)
            # auto transition to FULLY_DEPRECIATED driven by book ledger
            basis = dep.depreciable_basis(asset)
            if asset["accumulated_book_cents"] >= basis:
                asset["status"] = "FULLY_DEPRECIATED"
            asset["version"] += 1
            asset["updated_at"] = now_iso()
    rec["entries_created_count"] = entries_created
    rec["total_book_amount_cents"] = total_book
    rec["total_tax_amount_cents"] = total_tax
    rec["status"] = "POSTED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(depreciation_run_view(rec))


@bp.route("/depreciation-entries", methods=["GET"])
def list_entries():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    f_run = request.args.get("run_id")
    f_asset = request.args.get("asset_id")
    f_disposal = request.args.get("disposal_id")
    f_ledger = request.args.get("ledger")
    f_period = request.args.get("period")
    items = sorted(db.depreciation_entries.values(), key=lambda r: (r["created_at"], r["id"]))
    out = []
    for e in items:
        if f_run is not None and e.get("run_id") != f_run:
            continue
        if f_asset is not None and e["asset_id"] != f_asset:
            continue
        if f_disposal is not None and e.get("disposal_id") != f_disposal:
            continue
        if f_ledger is not None and e["ledger"] != f_ledger:
            continue
        if f_period is not None and e["period"] != f_period:
            continue
        out.append(e)
    total = len(out)
    page = out[offset:offset + limit]
    return success_list([depreciation_entry_view(e) for e in page], limit, offset, total)


@bp.route("/depreciation-entries/<eid>", methods=["GET"])
def get_entry(eid):
    require_roles(*ALL_ROLES)
    rec = db.depreciation_entries.get(eid)
    if rec is None:
        raise errors.not_found("Depreciation entry not found")
    return success_object(depreciation_entry_view(rec))
