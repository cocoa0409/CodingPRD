"""Inventory reconciliation helpers."""
import db
from db import now_iso


def recompute_line_status(line):
    """Recompute a count line's reconciliation_status from its fields and asset."""
    asset = db.fixed_assets.get(line["asset_id"])
    if line.get("found") is None:
        line["reconciliation_status"] = "PENDING"
    elif line["found"] is False:
        line["reconciliation_status"] = "MISSING"
    elif asset is not None and line.get("counted_location") == asset.get("location"):
        line["reconciliation_status"] = "MATCHED"
    else:
        line["reconciliation_status"] = "LOCATION_MISMATCH"


def recompute_run_counters(run):
    matched = missing = mismatch = 0
    for line in db.inventory_count_lines.values():
        if line["run_id"] != run["id"]:
            continue
        st = line["reconciliation_status"]
        if st == "MATCHED":
            matched += 1
        elif st == "LOCATION_MISMATCH":
            mismatch += 1
        elif st == "MISSING":
            asset = db.fixed_assets.get(line["asset_id"])
            if asset is None or asset["status"] != "DISPOSED":
                missing += 1
    run["matched_count"] = matched
    run["missing_count"] = missing
    run["mismatch_count"] = mismatch


def refresh_asset_exceptions(asset_ids=None):
    """Recompute open_inventory_exception flags (all assets or a subset)."""
    targets = asset_ids if asset_ids is not None else list(db.fixed_assets.keys())
    for aid in targets:
        asset = db.fixed_assets.get(aid)
        if asset is None:
            continue
        exc = False
        for line in db.inventory_count_lines.values():
            if line["asset_id"] != aid:
                continue
            if line["reconciliation_status"] not in ("MISSING", "LOCATION_MISMATCH"):
                continue
            run = db.inventory_runs.get(line["run_id"])
            if run and run["status"] != "CLOSED":
                exc = True
                break
        asset["open_inventory_exception"] = exc
