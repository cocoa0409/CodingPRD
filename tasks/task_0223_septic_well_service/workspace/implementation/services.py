"""Shared domain logic: derived-field reconciliation and cascades.

Every reconciliation that alters a resource bumps that resource's version and
updated_at (PRD §2.5), except the version-less Reminder.
"""
from db import db, common_create, touch, new_id
from timeutil import iso_ms, add_months, parse_date
from clock import clock
import calculations as calc


# ---------------------------------------------------------------------------
# Route counters
# ---------------------------------------------------------------------------
COUNTED_STATUSES = {"SCHEDULED", "DISPATCHED"}


def recompute_route_counters(route):
    """Recompute assigned_stop_count and booked_minutes from current WorkOrders.

    Always bumps the route (a reconciliation is a mutation). Caller decides when
    to invoke; it is invoked whenever a WO enters or leaves the counted set.
    """
    stop_count = 0
    minutes = 0
    for w in db.work_orders.values():
        if w["route_id"] == route["id"] and w["status"] in COUNTED_STATUSES:
            stop_count += 1
            end = w["window_end_minute"]
            start = w["window_start_minute"]
            if end is not None and start is not None:
                minutes += end - start
    route["assigned_stop_count"] = stop_count
    route["booked_minutes"] = minutes
    touch(route)


# ---------------------------------------------------------------------------
# Site next_pump_due_date projection + reminder emission
# ---------------------------------------------------------------------------
def active_service_plan(site_id):
    for p in db.service_plans.values():
        if p["site_id"] == site_id and p["status"] == "ACTIVE":
            return p
    return None


def compute_next_pump_due(site):
    """Projection: last_pumped_date + active plan frequency, else null."""
    plan = active_service_plan(site["id"])
    last = site["last_pumped_date"]
    if plan is not None and last is not None:
        due = add_months(parse_date(last), plan["frequency_months"])
        return due.isoformat()
    return None


def reconcile_site_due_date(site):
    """Recompute next_pump_due_date and bump the site."""
    site["next_pump_due_date"] = compute_next_pump_due(site)
    touch(site)


def emit_pump_due_reminder(site):
    """Append-only PUMP_DUE reminder for the site's current next_pump_due_date."""
    r = {
        "id": new_id(),
        "created_at": iso_ms(),
        "site_id": site["id"],
        "reminder_type": "PUMP_DUE",
        "due_date": site["next_pump_due_date"],
        "status": "PENDING",
    }
    r["_seq"] = db.next_seq()
    db.reminders[r["id"]] = r
    return r


# ---------------------------------------------------------------------------
# Site risk recompute helpers
# ---------------------------------------------------------------------------
def newest_active_asset_install_year(site_id):
    years = [
        a["install_year"]
        for a in db.assets.values()
        if a["site_id"] == site_id and a["status"] == "ACTIVE"
    ]
    return max(years) if years else None


# ---------------------------------------------------------------------------
# Account balance recompute
# ---------------------------------------------------------------------------
def site_account(site_id):
    site = db.sites.get(site_id)
    if site is None:
        return None
    return db.accounts.get(site["account_id"])
