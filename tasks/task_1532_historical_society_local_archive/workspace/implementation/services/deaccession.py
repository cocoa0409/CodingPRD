"""Deaccession finalize cascade (PRD §3.8) and the cooling-off clock sweep
(PR§2.5)."""

from __future__ import annotations

import db
from services.rollup import recompute_collection, recompute_project_active_count

DEACCESSIONABLE_ITEM_STATES = (
    "PENDING_CATALOG", "CATALOGED", "AVAILABLE", "FLAGGED_CONSERVATION", "ZONE_HOLD",
)


def sweep_cooling_off() -> None:
    """Clock-set sweep: APPROVED proposals whose finalize_not_before has been
    reached become COOLED_OFF. No other transitions (pinned)."""
    now = db.get_now()
    for prop in db.proposals.values():
        if prop["status"] != "APPROVED":
            continue
        fnb = prop.get("_finalize_not_before_dt")
        if fnb is not None and fnb <= now:
            prop["status"] = "COOLED_OFF"
            db.touch(prop)


def finalize_cascade(prop: dict) -> None:
    """Full fan-chain for COOLED_OFF -> FINALIZED. Caller has already run all
    precondition checks; this executes side effects atomically."""
    # --- SALE proceeds (per-item rounding then sum) --------------------------
    if prop["disposal_method"] == "SALE":
        from services.calc import deaccession_proceeds
        prop["proceeds_cents"] = deaccession_proceeds(prop["hammer_prices"], prop["item_ids"])

    # --- Link 1: items -> DEACCESSIONED ---------------------------------------
    deaccessioned: set[str] = set()
    affected_collection_ids: set[str] = set()
    for item_id in prop["item_ids"]:
        item = db.items.get(item_id)
        if item is None or item["status"] not in DEACCESSIONABLE_ITEM_STATES:
            continue
        item["status"] = "DEACCESSIONED"
        db.touch(item)
        deaccessioned.add(item_id)
        affected_collection_ids.add(item["collection_id"])

    # --- Bubble-up: emptied collections deaccession; published aids retire ----
    for cid in affected_collection_ids:
        coll = db.collections.get(cid)
        if coll is None:
            continue
        recompute_collection(coll, touch_it=False)
        if coll["status"] == "ACTIVE" and coll["item_count"] == 0:
            coll["status"] = "DEACCESSIONED"
            for fa in db.finding_aids.values():
                if fa["collection_id"] == cid and fa["status"] == "PUBLISHED":
                    fa["status"] = "RETIRED"
                    db.touch(fa)
            recompute_collection(coll, touch_it=False)
        db.touch(coll)

    # --- Link 2: open requests intersecting the deaccessioned set -> DENIED ---
    denied_request_ids: set[str] = set()
    for req in db.requests.values():
        if req["status"] not in ("SUBMITTED", "IN_REVIEW", "APPROVED"):
            continue
        if any(iid in deaccessioned for iid in req["item_ids"]):
            req["status"] = "DENIED"
            req["decision_reason"] = "AUTO_DEACCESSION"
            db.touch(req)
            denied_request_ids.add(req["id"])

    # --- Link 3: appointments of denied requests -> CANCELLED -----------------
    for appt in db.appointments.values():
        if appt["status"] in ("CONFIRMED", "NEEDS_RESCHEDULE") \
                and appt["research_request_id"] in denied_request_ids:
            appt["status"] = "CANCELLED"
            db.touch(appt)

    # --- Fan-out: active/queued tickets on deaccessioned items -> CANCELLED ---
    touched_projects: set[str] = set()
    for ticket in db.tickets.values():
        if ticket["status"] in ("QUEUED", "CLAIMED", "IN_CAPTURE", "QC_REVIEW") \
                and ticket["item_id"] in deaccessioned:
            was_active = ticket["status"] in ("CLAIMED", "IN_CAPTURE", "QC_REVIEW")
            ticket["status"] = "CANCELLED"
            db.touch(ticket)
            if was_active:
                touched_projects.add(ticket["project_id"])
    for pid in touched_projects:
        proj = db.projects.get(pid)
        if proj is not None:
            recompute_project_active_count(proj)

    # --- Fan-out: QUOTED/APPROVED orders intersecting -> CANCELLED ------------
    for order in db.orders.values():
        if order["status"] in ("QUOTED", "APPROVED") \
                and any(iid in deaccessioned for iid in order["item_ids"]):
            order["status"] = "CANCELLED"
            db.touch(order)

    prop["status"] = "FINALIZED"
    db.touch(prop)
