"""Lazy sweeps, derived occupancy, and multi-hop cascades (scaffold §1.2).

Every flipped entity is touched (updated_at refreshed, version incremented).
Occupancy is derived, never stored: a FinishedGoodsLot occupies its zone's
pallets while its private _occupying flag is set — from put-away until release,
expiry sweep, or rejection; BLOCKED lots keep whatever occupancy they had.
"""
from db import clock_today, store, touch

_RUN_ACTIVE_STATES = ("SCHEDULED", "MIXING", "EXTRUDING", "DRYING", "PACKAGING")


# ------------------------------------------------------------------ sweeps ---
def sweep_contract(contract):
    """Lazy EXPIRED: ACTIVE contract whose window lapsed flips on read/reference."""
    if contract["status"] == "ACTIVE" and contract["effective_end"] < clock_today():
        contract["status"] = "EXPIRED"
        touch(contract)


def sweep_all_contracts():
    for contract in store.contracts.values():
        sweep_contract(contract)


def sweep_goods_lot(goods_lot):
    """Lazy EXPIRED on GET reads only: STORED lot past its expiry date."""
    if (goods_lot["status"] == "STORED"
            and goods_lot["expiry_date"] is not None
            and clock_today() > goods_lot["expiry_date"]):
        goods_lot["status"] = "EXPIRED"
        goods_lot["_occupying"] = False
        touch(goods_lot)


def sweep_all_goods_lots():
    for goods_lot in store.finished_goods_lots.values():
        sweep_goods_lot(goods_lot)


# --------------------------------------------------------------- occupancy ---
def occupied_pallets(zone_id):
    return sum(lot["pallet_count"] for lot in store.finished_goods_lots.values()
               if lot["zone_id"] == zone_id and lot.get("_occupying"))


def zone_view(zone):
    view = dict(zone)
    view["occupied_pallets"] = occupied_pallets(zone["id"])
    return view


# --------------------------------------------------------------- cascades ----
def lot_reject_cascade(lot):
    """Semolina re-reject: runs -> HELD; their jobs -> BLOCKED; their goods
    lots -> BLOCKED (hop 3 keyed on the run flip, independent of the job)."""
    flipped_runs = [r for r in store.production_runs.values()
                    if r["semolina_lot_id"] == lot["id"]
                    and r["production_status"] in _RUN_ACTIVE_STATES
                    and r["quality_disposition"] == "PENDING_QA"]
    for run in flipped_runs:
        run["quality_disposition"] = "HELD"
        touch(run)
    for run in flipped_runs:
        for job in store.packaging_jobs.values():
            if job["run_id"] == run["id"] and job["status"] in ("CREATED", "LABEL_VERIFIED"):
                job["status"] = "BLOCKED"
                touch(job)
        for goods in store.finished_goods_lots.values():
            if goods["run_id"] == run["id"] and goods["status"] in ("CREATED", "STORED"):
                goods["status"] = "BLOCKED"
                touch(goods)


def pest_critical_cascade(zone):
    """Zone QUARANTINED: its STORED lots -> BLOCKED (keep occupying); each
    blocked lot's run flips PENDING_QA -> HELD."""
    blocked = [lot for lot in store.finished_goods_lots.values()
               if lot["zone_id"] == zone["id"] and lot["status"] == "STORED"]
    for lot in blocked:
        lot["status"] = "BLOCKED"
        touch(lot)
    for lot in blocked:
        run = store.production_runs.get(lot["run_id"])
        if run is not None and run["quality_disposition"] == "PENDING_QA":
            run["quality_disposition"] = "HELD"
            touch(run)


def run_quality_reject_cascade(run):
    """Write off the run's goods lots; occupying lots stop occupying."""
    for lot in store.finished_goods_lots.values():
        if lot["run_id"] == run["id"] and lot["status"] in ("CREATED", "STORED", "BLOCKED"):
            lot["status"] = "REJECTED"
            lot["_occupying"] = False
            touch(lot)


def run_quality_release_cascade(run):
    """Conditionally unblock the run's BLOCKED lots: back to STORED iff the
    lot's zone exists and is not QUARANTINED."""
    for lot in store.finished_goods_lots.values():
        if lot["run_id"] == run["id"] and lot["status"] == "BLOCKED" and lot["zone_id"]:
            zone = store.warehouse_zones.get(lot["zone_id"])
            if zone is not None and zone["pest_posture"] != "QUARANTINED":
                lot["status"] = "STORED"
                touch(lot)


def lift_quarantine_cascade(zone):
    """Conditionally restore the zone's BLOCKED lots: back to STORED iff the
    lot's run quality_disposition is RELEASED."""
    for lot in store.finished_goods_lots.values():
        if lot["zone_id"] == zone["id"] and lot["status"] == "BLOCKED":
            run = store.production_runs.get(lot["run_id"])
            if run is not None and run["quality_disposition"] == "RELEASED":
                lot["status"] = "STORED"
                touch(lot)
