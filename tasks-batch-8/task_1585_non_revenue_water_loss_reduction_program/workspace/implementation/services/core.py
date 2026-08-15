"""Shared derived-state recompute helpers: DMA posture, latest_nrw_pct,
open_leak_count. Every recompute that changes a stored value increments the
DMA version by one and refreshes updated_at (PRD 2.4, 2.6)."""

import db
from db import touch

OPEN_LEAK_STATUSES = {"REPORTED", "VERIFIED", "REPAIR_SCHEDULED", "REOPENED"}
LEAK_TERMINAL = {"VERIFIED_REPAIR", "WITHDRAWN"}


def get_dma(dma_id):
    return db.store["dmas"].get(dma_id)


def recompute_posture(dma):
    frozen = any(
        dma["id"] in r["dma_ids"] and r["status"] in ("SUBMITTED", "ACCEPTED")
        for r in db.store["benchmark_reports"].values()
    )
    if frozen:
        new = "FROZEN"
    else:
        restricted = any(
            b["dma_id"] == dma["id"] and b["status"] == "SUBMITTED"
            for b in db.store["water_balance_periods"].values()
        ) or any(
            p["dma_id"] == dma["id"] and p["status"] == "ACTIVE"
            for p in db.store["pressure_projects"].values()
        )
        new = "RESTRICTED" if restricted else "OPEN"
    if new != dma["posture"]:
        dma["posture"] = new
        touch(dma)


def recompute_latest_nrw(dma):
    from services import calc
    bal = calc.latest_finalized_balance(dma["id"])
    new = bal["nrw_pct"] if bal is not None else None
    if new != dma["latest_nrw_pct"]:
        dma["latest_nrw_pct"] = new
        touch(dma)


def recompute_open_leak_count(dma):
    survey_dma = {s["id"]: s["dma_id"] for s in db.store["leak_surveys"].values()}
    count = sum(
        1 for lk in db.store["leaks"].values()
        if survey_dma.get(lk["survey_id"]) == dma["id"]
        and lk["status"] in OPEN_LEAK_STATUSES
    )
    if count != dma["open_leak_count"]:
        dma["open_leak_count"] = count
        touch(dma)


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching boundaries allowed."""
    return a_start < b_end and b_start < a_end
