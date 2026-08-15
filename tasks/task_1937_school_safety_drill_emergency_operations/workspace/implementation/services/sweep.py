"""System clock sweep (PRD 2.5): fires when the logical clock advances."""
from db import db
from services.core import (
    apply_changes, ca_is_overdue, refresh_site, stale_reports_for_drill,
)
from util import CLOCK, parse_date


def run_sweep():
    today = CLOCK.today()

    for d in list(db["drill_events"].values()):
        if d["status"] in ("SCHEDULED", "IN_PROGRESS") and parse_date(d["scheduled_date"]) < today:
            apply_changes(d, {"status": "MISSED"})
            stale_reports_for_drill(d["site_id"], d["scheduled_date"])

    for w in list(db["walkthroughs"].values()):
        if w["status"] == "SCHEDULED" and parse_date(w["scheduled_date"]) < today:
            apply_changes(w, {"status": "MISSED"})

    for doc in list(db["site_plan_documents"].values()):
        if doc["status"] == "CURRENT" and parse_date(doc["review_by_date"]) < today:
            apply_changes(doc, {"status": "EXPIRED"})

    for plan in list(db["eops"].values()):
        if plan["status"] == "ACTIVE" and parse_date(plan["review_due_date"]) < today:
            apply_changes(plan, {"status": "EXPIRED"})

    for ca in list(db["corrective_actions"].values()):
        apply_changes(ca, {"is_overdue": ca_is_overdue(ca)})

    for site in list(db["sites"].values()):
        refresh_site(site["id"])
