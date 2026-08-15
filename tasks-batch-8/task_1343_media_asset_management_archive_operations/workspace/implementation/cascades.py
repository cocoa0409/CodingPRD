"""Cross-aggregate side effects. These operate directly on the store so route
modules never import each other (no circular imports).

Asset version policy (PRD-literal): an Asset's version increments ONLY where
the PRD explicitly states it — metadata PATCH, legal-hold place, disposal-order
create, migration-job create, migration-job complete. The disposal pipeline's
system-driven catalog transitions (approve/execute/block/withdraw-revert) never
bump the asset version, which is what makes the pinned-version mechanics work.
"""
from datetime import timedelta

import calc
from db import STORE, now, touch


def _bump_asset(asset):
    """Explicitly-specified asset version increment."""
    asset["version"] += 1
    asset["updated_at"] = now()


def legal_hold_place_cascade(asset):
    """On LegalHold create: asset version +1; PENDING_APPROVAL|APPROVED orders
    -> BLOCKED (an APPROVED order also reverts the asset DISPOSAL_SCHEDULED ->
    ARCHIVED); QUEUED migration jobs -> HOLD_PAUSED."""
    _bump_asset(asset)
    t = now()
    for o in STORE.orders.values():
        if o["asset_id"] != asset["id"]:
            continue
        if o["status"] in ("PENDING_APPROVAL", "APPROVED"):
            if o["status"] == "APPROVED" and asset["catalog_status"] == "DISPOSAL_SCHEDULED":
                asset["catalog_status"] = "ARCHIVED"  # no version bump (pin mechanics)
            o["status"] = "BLOCKED"
            o["updated_at"] = t
            o["version"] += 1
    for j in STORE.jobs.values():
        if j["asset_id"] == asset["id"] and j["status"] == "QUEUED":
            j["status"] = "HOLD_PAUSED"
            j["updated_at"] = t
            j["version"] += 1


def legal_hold_release_cascade(asset):
    """On release of the last ACTIVE hold: HOLD_PAUSED jobs -> QUEUED.
    BLOCKED disposal orders deliberately stay BLOCKED. No asset version bump."""
    if calc.hold_status(asset) == "HELD":
        return
    t = now()
    for j in STORE.jobs.values():
        if j["asset_id"] == asset["id"] and j["status"] == "HOLD_PAUSED":
            j["status"] = "QUEUED"
            j["updated_at"] = t
            j["version"] += 1


def disposal_execute_cascade(asset):
    """On DisposalOrder execute: asset -> DISPOSED; non-terminal retrieval
    requests, QUEUED|HOLD_PAUSED migration jobs and QUEUED|ASSIGNED
    digitization tickets are cancelled (each child bumped)."""
    asset["catalog_status"] = "DISPOSED"  # no version bump (pin mechanics)
    t = now()
    for r in STORE.requests.values():
        if r["asset_id"] == asset["id"] and r["status"] in (
            "SUBMITTED", "UNDER_REVIEW", "RECALLING", "STAGED",
        ):
            r["status"] = "CANCELLED"
            r["updated_at"] = t
            r["version"] += 1
    for j in STORE.jobs.values():
        if j["asset_id"] == asset["id"] and j["status"] in ("QUEUED", "HOLD_PAUSED"):
            j["status"] = "CANCELLED"
            j["updated_at"] = t
            j["version"] += 1
    for k in STORE.tickets.values():
        if k["asset_id"] == asset["id"] and k["status"] in ("QUEUED", "ASSIGNED"):
            k["status"] = "CANCELLED"
            k["updated_at"] = t
            k["version"] += 1


def migration_complete_cascade(asset, job):
    """On MigrationJob complete: asset tier := target_tier, version +1; if the
    target is not DEEP_ARCHIVE, RECALLING retrieval requests -> STAGED with
    staged_at := completion time."""
    t = now()
    asset["storage_tier"] = job["target_tier"]
    asset["version"] += 1
    asset["updated_at"] = t
    if job["target_tier"] != "DEEP_ARCHIVE":
        for r in STORE.requests.values():
            if r["asset_id"] == asset["id"] and r["status"] == "RECALLING":
                r["status"] = "STAGED"
                r["staged_at"] = t
                r["updated_at"] = t
                r["version"] += 1


def clock_sweep():
    """On clock set: STAGED retrieval requests whose staged_at lies more than
    72 hours in the past -> EXPIRED. This is the only time-based sweep."""
    t = now()
    for r in STORE.requests.values():
        if r["status"] == "STAGED" and r["staged_at"] is not None:
            if t > r["staged_at"] + calc.STAGE_HOLD:
                r["status"] = "EXPIRED"
                r["updated_at"] = t
                r["version"] += 1
