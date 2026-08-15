"""Derived rollups (PRD §2.10) — recomputed synchronously on each trigger.

Stored rollups (collection item_count / published_finding_aid_present, project
active_ticket_count) are recomputed from the stores at every event that can
change them, and the owning entity is touched (updated_at + version bump)
because the recomputation is a mutation of the resource (PRD §2.4).

The researcher's no_show_strikes depends on the moving logical-clock window,
so it is computed fresh at serialization time instead.
"""

from __future__ import annotations

from datetime import timedelta

import db

STRIKE_WINDOW_DAYS = 180
STRIKE_SUSPEND_THRESHOLD = 3

ACTIVE_TICKET_STATES = ("CLAIMED", "IN_CAPTURE", "QC_REVIEW")


# ---------------------------------------------------------------------------
# Collection rollups
# ---------------------------------------------------------------------------

def recompute_collection(coll: dict, touch_it: bool = True) -> None:
    cid = coll["id"]
    coll["item_count"] = sum(
        1 for it in db.items.values()
        if it["collection_id"] == cid and it["status"] != "DEACCESSIONED"
    )
    coll["published_finding_aid_present"] = any(
        fa["collection_id"] == cid and fa["status"] == "PUBLISHED"
        for fa in db.finding_aids.values()
    )
    if touch_it:
        db.touch(coll)


# ---------------------------------------------------------------------------
# Volunteer project rollups
# ---------------------------------------------------------------------------

def recompute_project_active_count(proj: dict, touch_it: bool = True) -> None:
    pid = proj["id"]
    proj["active_ticket_count"] = sum(
        1 for t in db.tickets.values()
        if t["project_id"] == pid and t["status"] in ACTIVE_TICKET_STATES
    )
    if touch_it:
        db.touch(proj)


# ---------------------------------------------------------------------------
# Researcher rollups
# ---------------------------------------------------------------------------

def compute_no_show_strikes(researcher_id: str) -> int:
    """Rolling 180-day window over NO_SHOW appointments; boundary inclusive."""
    floor = (db.get_now() - timedelta(days=STRIKE_WINDOW_DAYS)).date()
    return sum(
        1 for ap in db.appointments.values()
        if ap["researcher_id"] == researcher_id
        and ap["status"] == "NO_SHOW"
        and ap["_scheduled_date"] >= floor
    )


def serialize_researcher(r: dict) -> dict:
    view = {k: v for k, v in r.items() if not k.startswith("_")}
    view["no_show_strikes"] = compute_no_show_strikes(r["id"])
    return view
