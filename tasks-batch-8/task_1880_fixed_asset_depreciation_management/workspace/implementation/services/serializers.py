"""Serializers converting stored entities to API representations."""
import db


# ---------- AssetClass ----------
def asset_class_view(rec):
    return {
        "id": rec["id"],
        "class_code": rec["class_code"],
        "name": rec["name"],
        "capitalization_threshold_cents": rec["capitalization_threshold_cents"],
        "default_useful_life_months": rec["default_useful_life_months"],
        "book_method": rec["book_method"],
        "tax_method": rec["tax_method"],
        "bonus_depreciation_allowed": rec["bonus_depreciation_allowed"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- CapitalProject ----------
def capital_project_view(rec):
    return {
        "id": rec["id"],
        "project_code": rec["project_code"],
        "name": rec["name"],
        "asset_class_id": rec["asset_class_id"],
        "created_by_user_id": rec["created_by_user_id"],
        "total_accumulated_cents": rec["total_accumulated_cents"],
        "status": rec["status"],
        "capitalized_asset_id": rec.get("capitalized_asset_id"),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- CIPCostLine ----------
def cip_cost_line_view(rec):
    return {
        "id": rec["id"],
        "project_id": rec["project_id"],
        "amount_cents": rec["amount_cents"],
        "cost_type": rec["cost_type"],
        "incurred_date": rec["incurred_date"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- FixedAsset ----------
def recompute_asset_derived(rec):
    """Recompute accumulated/impairment/NBV/open_inventory_exception from stores."""
    acc_book = 0
    acc_tax = 0
    for e in db.depreciation_entries.values():
        if e["asset_id"] == rec["id"]:
            if e["ledger"] == "BOOK":
                acc_book += e["amount_cents"]
            else:
                acc_tax += e["amount_cents"]
    rec["accumulated_book_cents"] = acc_book
    rec["accumulated_tax_cents"] = acc_tax
    imp = 0
    for r in db.impairment_reviews.values():
        if r["asset_id"] == rec["id"] and r["status"] == "WRITTEN_DOWN":
            imp += r.get("write_down_cents") or 0
    rec["impairment_total_cents"] = imp
    rec["net_book_value_cents"] = rec["acquisition_cost_cents"] - acc_book - imp
    # open_inventory_exception
    exc = False
    for line in db.inventory_count_lines.values():
        if line["asset_id"] != rec["id"]:
            continue
        if line["reconciliation_status"] not in ("MISSING", "LOCATION_MISMATCH"):
            continue
        run = db.inventory_runs.get(line["run_id"])
        if run and run["status"] != "CLOSED":
            exc = True
            break
    rec["open_inventory_exception"] = exc


def fixed_asset_view(rec):
    return {
        "id": rec["id"],
        "asset_tag": rec["asset_tag"],
        "description": rec["description"],
        "asset_class_id": rec["asset_class_id"],
        "parent_asset_id": rec.get("parent_asset_id"),
        "source": rec["source"],
        "acquisition_cost_cents": rec["acquisition_cost_cents"],
        "salvage_value_cents": rec["salvage_value_cents"],
        "useful_life_months": rec["useful_life_months"],
        "book_method": rec["book_method"],
        "tax_method": rec["tax_method"],
        "bonus_elected": rec["bonus_elected"],
        "cost_center": rec["cost_center"],
        "location": rec["location"],
        "in_service_date": rec.get("in_service_date"),
        "status": rec["status"],
        "accumulated_book_cents": rec["accumulated_book_cents"],
        "accumulated_tax_cents": rec["accumulated_tax_cents"],
        "impairment_total_cents": rec["impairment_total_cents"],
        "net_book_value_cents": rec["net_book_value_cents"],
        "open_inventory_exception": rec["open_inventory_exception"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- DepreciationRun ----------
def depreciation_run_view(rec):
    return {
        "id": rec["id"],
        "period": rec["period"],
        "status": rec["status"],
        "entries_created_count": rec["entries_created_count"],
        "total_book_amount_cents": rec["total_book_amount_cents"],
        "total_tax_amount_cents": rec["total_tax_amount_cents"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- DepreciationEntry ----------
def depreciation_entry_view(rec):
    return {
        "id": rec["id"],
        "run_id": rec.get("run_id"),
        "disposal_id": rec.get("disposal_id"),
        "asset_id": rec["asset_id"],
        "ledger": rec["ledger"],
        "period": rec["period"],
        "amount_cents": rec["amount_cents"],
        "source": rec["source"],
        "created_at": rec["created_at"],
    }


# ---------- Disposal ----------
def disposal_view(rec):
    return {
        "id": rec["id"],
        "asset_id": rec["asset_id"],
        "disposal_type": rec["disposal_type"],
        "proceeds_cents": rec.get("proceeds_cents"),
        "transfer_to_cost_center": rec.get("transfer_to_cost_center"),
        "effective_date": rec["effective_date"],
        "requested_by_user_id": rec["requested_by_user_id"],
        "approved_by_user_id": rec.get("approved_by_user_id"),
        "book_gain_loss_cents": rec.get("book_gain_loss_cents"),
        "tax_gain_loss_cents": rec.get("tax_gain_loss_cents"),
        "auto_created": rec.get("auto_created", False),
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- InventoryRun ----------
def inventory_run_view(rec):
    return {
        "id": rec["id"],
        "name": rec["name"],
        "scope_type": rec["scope_type"],
        "scope_value": rec.get("scope_value"),
        "status": rec["status"],
        "expected_count": rec["expected_count"],
        "matched_count": rec["matched_count"],
        "missing_count": rec["missing_count"],
        "mismatch_count": rec["mismatch_count"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- InventoryCountLine ----------
def inventory_count_line_view(rec):
    return {
        "id": rec["id"],
        "run_id": rec["run_id"],
        "asset_id": rec["asset_id"],
        "found": rec.get("found"),
        "counted_location": rec.get("counted_location"),
        "condition": rec.get("condition"),
        "reconciliation_status": rec["reconciliation_status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- ImpairmentReview ----------
def impairment_review_view(rec):
    return {
        "id": rec["id"],
        "asset_id": rec["asset_id"],
        "indicator": rec["indicator"],
        "source": rec["source"],
        "created_by_user_id": rec["created_by_user_id"],
        "recoverable_value_cents": rec.get("recoverable_value_cents"),
        "write_down_cents": rec.get("write_down_cents"),
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ---------- ExternalSchedule ----------
def external_schedule_view(rec):
    return {
        "id": rec["id"],
        "asset_id": rec["asset_id"],
        "schedule_type": rec["schedule_type"],
        "schedule_year": rec["schedule_year"],
        "assessed_value_cents": rec.get("assessed_value_cents"),
        "annual_premium_cents": rec.get("annual_premium_cents"),
        "property_tax_amount_cents": rec.get("property_tax_amount_cents"),
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }
