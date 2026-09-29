"""Multi-hop cascades and exact ledger compensation (PRD 2.9, 3.1-3.9)."""

from decimal import Decimal

import calc
from calc import d, rhu
from db import db, now, ordered, touch

ZERO2 = Decimal("0.00")


# ---------------------------------------------------------------------------
# allocation / allocation line
# ---------------------------------------------------------------------------

def active_lines_of_batch(batch):
    return ordered([line for line in db.allocation_lines.values()
                    if line["batch_id"] == batch["id"] and line["status"] == "ACTIVE"])


def active_lines_of_allocation(allocation):
    return ordered([line for line in db.allocation_lines.values()
                    if line["allocation_id"] == allocation["id"] and line["status"] == "ACTIVE"])


def recompute_allocation(allocation):
    lines = active_lines_of_allocation(allocation)
    allocated = rhu(sum((d(line["quantity_sqm"]) for line in lines), Decimal(0)), 2)
    allocation["allocated_quantity_sqm"] = allocated
    allocation["upgrade_cost_total_cents"] = sum(line["upgrade_cost_delta_cents"] for line in lines)
    if allocation["status"] in ("OPEN", "PARTIALLY_FILLED", "FILLED"):
        if allocated <= 0:
            allocation["status"] = "OPEN"
        elif allocated >= d(allocation["requested_quantity_sqm"]):
            allocation["status"] = "FILLED"
        else:
            allocation["status"] = "PARTIALLY_FILLED"
    touch(allocation)


def void_lines_on_batch(batch, reason, restore=True):
    """Void every ACTIVE line drawn on `batch` and step its allocations back."""
    owners = []
    for line in active_lines_of_batch(batch):
        line["status"] = "VOIDED"
        line["void_reason"] = reason
        touch(line)
        if restore:
            batch["available_quantity_sqm"] = rhu(
                d(batch["available_quantity_sqm"]) + d(line["quantity_sqm"]), 2)
        allocation = db.allocations.get(line["allocation_id"])
        if allocation is not None and allocation not in owners:
            owners.append(allocation)
    for allocation in owners:
        recompute_allocation(allocation)


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------

def hold_batch(batch, hold_reason, held_by_user_id, void_lines):
    batch["status"] = "HELD"
    batch["hold_reason"] = hold_reason
    batch["held_by_user_id"] = held_by_user_id
    if void_lines:
        void_lines_on_batch(batch, "BATCH_HELD", restore=True)
    touch(batch)


def scrap_batch(batch):
    batch["status"] = "SCRAPPED"
    void_lines_on_batch(batch, "BATCH_SCRAPPED", restore=False)
    batch["available_quantity_sqm"] = ZERO2
    touch(batch)


def batches_of_sku(sku, status=None):
    rows = [b for b in db.batches.values() if b["sku_id"] == sku["id"]]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    return ordered(rows)


def hold_sku_batches(sku, void_lines):
    for batch in batches_of_sku(sku, "IN_STOCK"):
        hold_batch(batch, "SKU_ON_HOLD", "system", void_lines)


# ---------------------------------------------------------------------------
# production run
# ---------------------------------------------------------------------------

def release_reservation(run):
    """Exact compensation of the reserved-volume ledger."""
    license_row = calc.license_of_run(run)
    if license_row is not None:
        license_row["reserved_volume_sqm"] = rhu(
            d(license_row["reserved_volume_sqm"]) - d(run["planned_quantity_sqm"]), 2)
        touch(license_row)


def abort_run(run, abort_reason):
    run["run_status"] = "ABORTED"
    run["abort_reason"] = abort_reason
    release_reservation(run)
    touch(run)


def abort_open_runs_of_sku(sku, abort_reason):
    runs = ordered([r for r in db.production_runs.values()
                    if r["sku_id"] == sku["id"] and r["run_status"] in ("PLANNED", "SETUP")])
    for run in runs:
        abort_run(run, abort_reason)


# ---------------------------------------------------------------------------
# product sku
# ---------------------------------------------------------------------------

def skus_of_formulation(formulation):
    return ordered([s for s in db.product_skus.values()
                    if s["formulation_id"] == formulation["id"]])


def skus_of_film(film):
    return ordered([s for s in db.product_skus.values() if s["print_film_id"] == film["id"]])


def refresh_pin_stale(formulation, force=False):
    """PRD 3.5: a pin goes stale on its own."""
    stale_recipe = force or formulation["status"] in ("SUPERSEDED", "RETIRED")
    for sku in skus_of_formulation(formulation):
        if sku["pin_stale"]:
            continue
        pinned = sku["pinned_formulation_version"]
        if stale_recipe or (pinned is not None and pinned != formulation["version"]):
            sku["pin_stale"] = True
            touch(sku)


def collapse_certification(sku):
    """A panel FAILED: certification collapses and PLANNED/SETUP runs abort."""
    before = sku["certification_status"]
    if before == "TESTING":
        sku["certification_status"] = "UNCERTIFIED"
    elif before in ("PROVISIONAL", "CERTIFIED"):
        sku["certification_status"] = "SUSPENDED"
    else:
        return
    abort_open_runs_of_sku(sku, "SKU_CERTIFICATION_LOST")
    if before == "CERTIFIED" and sku["commercial_status"] == "RELEASED":
        sku["commercial_status"] = "HOLD"
        hold_sku_batches(sku, void_lines=False)
    touch(sku)


def discontinue_sku(sku):
    """Commercial DISCONTINUED: decertify, cancel allocations, void their lines."""
    sku["commercial_status"] = "DISCONTINUED"
    sku["certification_status"] = "DECERTIFIED"
    allocations = ordered([a for a in db.allocations.values()
                           if a["sku_id"] == sku["id"]
                           and a["status"] in ("OPEN", "PARTIALLY_FILLED")])
    for allocation in allocations:
        allocation["status"] = "CANCELLED"
        for line in active_lines_of_allocation(allocation):
            line["status"] = "VOIDED"
            line["void_reason"] = "ALLOCATION_CANCELLED"
            touch(line)
            batch = db.batches.get(line["batch_id"])
            if batch is not None:
                batch["available_quantity_sqm"] = rhu(
                    d(batch["available_quantity_sqm"]) + d(line["quantity_sqm"]), 2)
                touch(batch)
        allocation["allocated_quantity_sqm"] = ZERO2
        allocation["upgrade_cost_total_cents"] = 0
        touch(allocation)
    touch(sku)


# ---------------------------------------------------------------------------
# raw material restriction — the five-hop chain
# ---------------------------------------------------------------------------

def raw_material_restricted(material):
    formulations = ordered([f for f in db.formulations.values()
                            if f["status"] in ("APPROVED", "SUPERSEDED")
                            and any(c["formulation_id"] == f["id"]
                                    and c["raw_material_id"] == material["id"]
                                    for c in db.formulation_components.values())])
    for formulation in formulations:
        formulation["status"] = "RETIRED"
        touch(formulation)
        for sku in skus_of_formulation(formulation):
            changed = False
            if sku["certification_status"] in ("TESTING", "PROVISIONAL", "CERTIFIED"):
                sku["certification_status"] = "SUSPENDED"
                changed = True
            held = False
            if sku["commercial_status"] == "RELEASED":
                sku["commercial_status"] = "HOLD"
                changed = True
                held = True
            if not sku["pin_stale"]:
                sku["pin_stale"] = True
                changed = True
            if changed:
                touch(sku)
            if held:
                hold_sku_batches(sku, void_lines=True)


# ---------------------------------------------------------------------------
# design licence cascades
# ---------------------------------------------------------------------------

def films_of_license(license_row, status=None):
    rows = [f for f in db.print_films.values() if f["license_id"] == license_row["id"]]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    return ordered(rows)


def license_suspended(license_row):
    """Three hops; no allocation lines are voided."""
    for film in films_of_license(license_row, "AVAILABLE"):
        film["status"] = "RESTRICTED"
        touch(film)
        for sku in skus_of_film(film):
            if sku["commercial_status"] != "RELEASED":
                continue
            sku["commercial_status"] = "HOLD"
            touch(sku)
            hold_sku_batches(sku, void_lines=False)


def license_reactivated(license_row):
    for film in films_of_license(license_row, "RESTRICTED"):
        film["status"] = "AVAILABLE"
        touch(film)


def license_terminated(license_row):
    """Four hops; allocation lines on the held batches are voided."""
    for film in films_of_license(license_row):
        if film["status"] != "WITHDRAWN":
            film["status"] = "WITHDRAWN"
            touch(film)
        for sku in skus_of_film(film):
            changed = False
            held = False
            if sku["commercial_status"] == "RELEASED":
                sku["commercial_status"] = "HOLD"
                changed = True
                held = True
            if sku["certification_status"] in ("PROVISIONAL", "CERTIFIED"):
                sku["certification_status"] = "SUSPENDED"
                changed = True
            if changed:
                touch(sku)
            if held:
                hold_sku_batches(sku, void_lines=True)


def license_superseded(license_row, successor):
    for film in films_of_license(license_row):
        film["license_id"] = successor["id"]
        touch(film)
