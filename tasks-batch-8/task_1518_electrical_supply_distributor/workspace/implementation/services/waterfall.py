"""Backorder waterfall (SCAFFOLD §1.3 / PRD §3.7).

Runs on every stock receipt, after the received quantity lands in
stock_on_hand. Visits OPEN BackorderAllocations for the received item whose
owning release is PARTIALLY_ALLOCATED, ordered by owning release.created_at
ASC then release line created_at ASC (never by id). Each candidate is filled
with min(qty_open, remaining stock_on_hand).
"""

from __future__ import annotations

import db
from db import touch


def run_backorder_waterfall(item: dict) -> None:
    candidates = []
    for bo in db.backorder_allocations.values():
        if bo["catalog_item_id"] != item["id"] or bo["status"] != "OPEN":
            continue
        line = db.release_lines.get(bo["release_line_id"])
        if line is None:
            continue
        release = db.releases.get(line["release_id"])
        if release is None or release["status"] != "PARTIALLY_ALLOCATED":
            continue
        candidates.append((bo, line, release))

    candidates.sort(
        key=lambda t: (
            t[2]["created_at"],
            t[2]["_seq"],
            t[1]["created_at"],
            t[1]["_seq"],
        )
    )

    for bo, line, release in candidates:
        if item["stock_on_hand"] <= 0:
            break
        if release["status"] != "PARTIALLY_ALLOCATED" or bo["status"] != "OPEN":
            continue
        fill = min(bo["qty_open"], item["stock_on_hand"])
        if fill <= 0:
            continue
        bo["qty_open"] -= fill
        line["qty_allocated"] += fill
        item["stock_on_hand"] -= fill
        item["stock_allocated"] += fill
        if bo["qty_open"] == 0:
            bo["status"] = "FILLED"
        touch(bo)
        if line["qty_allocated"] == line["qty_requested"]:
            line["status"] = "ALLOCATED"
        touch(line)
        siblings = [l for l in db.release_lines.values() if l["release_id"] == release["id"]]
        if all(l["status"] == "ALLOCATED" for l in siblings):
            release["status"] = "ALLOCATED"
            touch(release)
