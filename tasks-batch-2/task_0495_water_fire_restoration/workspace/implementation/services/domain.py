"""Derived-state recomputation, auto-transitions, and cascades (PRD §2.5, §3.4, §3.6)."""
from db import db, touch
from services import calc


# ----------------------------------------------------------------------------
# Reverse-reachability collection helpers
# ----------------------------------------------------------------------------
def job_chambers(job_id):
    return [c for c in db.chambers.values() if c["job_id"] == job_id]


def non_decommissioned_chambers(job_id):
    return [c for c in db.chambers.values()
            if c["job_id"] == job_id and c["status"] != "DECOMMISSIONED"]


def open_chambers(job_id):
    return [c for c in db.chambers.values()
            if c["job_id"] == job_id and c["status"] == "OPEN"]


def chamber_readings(chamber_id):
    return [r for r in db.readings.values() if r["chamber_id"] == chamber_id]


def job_placements(job_id):
    return [p for p in db.placements.values() if p["job_id"] == job_id]


def active_placements_for_job(job_id):
    return [p for p in db.placements.values()
            if p["job_id"] == job_id and p["status"] == "ACTIVE"]


def active_placements_for_chamber(chamber_id):
    return [p for p in db.placements.values()
            if p["chamber_id"] == chamber_id and p["status"] == "ACTIVE"]


def job_contents(job_id):
    return [c for c in db.contents.values() if c["job_id"] == job_id]


def job_estimates(job_id):
    return [e for e in db.estimates.values() if e["job_id"] == job_id]


def _newest_reading(chamber_id):
    """Newest reading by created_at DESC; _seq breaks ties (append-only -> strictly increasing)."""
    readings = chamber_readings(chamber_id)
    if not readings:
        return None
    return max(readings, key=lambda r: (r["created_at"], r["_seq"]))


# ----------------------------------------------------------------------------
# Chamber dry-state recompute + auto OPEN<->DRIED transition (PRD §3.4)
# ----------------------------------------------------------------------------
def recompute_chamber_dry(chamber):
    """Recompute latest_moisture_content_pct and is_dry from the newest reading,
    auto-transition OPEN<->DRIED, and bump the chamber version on any mutation."""
    newest = _newest_reading(chamber["id"])
    latest = newest["moisture_content_pct"] if newest is not None else None
    new_is_dry = calc.is_dry(latest, chamber["dry_standard_pct"])

    chamber["latest_moisture_content_pct"] = latest
    chamber["is_dry"] = new_is_dry

    # Auto-transition only applies to non-DECOMMISSIONED chambers.
    if chamber["status"] == "OPEN" and new_is_dry:
        chamber["status"] = "DRIED"
    elif chamber["status"] == "DRIED" and not new_is_dry:
        chamber["status"] = "OPEN"

    touch(chamber)


def recompute_job_drying_status(job):
    """Derive drying_status from the dry flags of non-DECOMMISSIONED chambers.

    NOT_STARTED  -> no readings have established progress yet (no chamber DRIED and
                    no moisture content recorded anywhere).
    DRY_STANDARD_MET -> at least one non-DECOMMISSIONED chamber and every such
                    chamber is DRIED.
    DRYING       -> otherwise.
    """
    chambers = non_decommissioned_chambers(job["id"])
    old = job["drying_status"]

    if chambers and all(c["status"] == "DRIED" for c in chambers):
        new = "DRY_STANDARD_MET"
    else:
        any_progress = any(c["latest_moisture_content_pct"] is not None or c["status"] == "DRIED"
                           for c in chambers)
        new = "DRYING" if any_progress else "NOT_STARTED"

    if new != old:
        job["drying_status"] = new
        touch(job)


def on_reading_logged(chamber, job):
    """After a reading is written: recompute the chamber, then the job."""
    recompute_chamber_dry(chamber)
    recompute_job_drying_status(job)


def on_chamber_decommissioned(job):
    recompute_job_drying_status(job)


# ----------------------------------------------------------------------------
# Cancellation cascade (PRD §3.6)
# ----------------------------------------------------------------------------
def cancel_cascade_full(job):
    """Three-hop equipment release + chamber decommission + contents return.

    Used when cancelling a MITIGATION or MONITORING job. Every touched entity is
    independently mutated (updated_at refreshed, version bumped).
    """
    # hop1: each ACTIVE placement -> REMOVED (stamp billable days as on a normal remove)
    for placement in active_placements_for_job(job["id"]):
        placement["removed_on_day"] = job["monitoring_day"]
        placement["billable_days"] = max(1, placement["removed_on_day"] - placement["placed_on_day"])
        placement["status"] = "REMOVED"
        touch(placement)
        # hop2: the freed unit -> AVAILABLE; active_placement_id cleared
        unit = db.units.get(placement["equipment_unit_id"])
        if unit is not None:
            unit["status"] = "AVAILABLE"
            unit["active_placement_id"] = None
            touch(unit)

    # hop3: each OPEN chamber -> DECOMMISSIONED
    for chamber in list(open_chambers(job["id"])):
        chamber["status"] = "DECOMMISSIONED"
        touch(chamber)

    # contents: PACKED_OUT or STORED -> RETURNED
    for item in job_contents(job["id"]):
        if item["status"] in ("PACKED_OUT", "STORED"):
            item["status"] = "RETURNED"
            touch(item)
