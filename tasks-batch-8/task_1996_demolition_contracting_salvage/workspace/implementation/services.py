"""Shared business logic: lookups, cascades, sweeps, and the calculation
helpers used across routes."""

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from db import store, now, touch
from errors import err, ERR_NOT_FOUND
from util import round4

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml calculations / PRD §2.5)
# ---------------------------------------------------------------------------
PERMIT_VALIDITY_DAYS = 90
RENEWAL_EXTENSION_DAYS = 90
NOTIFICATION_WAIT_HOURS = 72
DAILY_DELIVERY_CAP = 3
RAW_CAP = Decimal("1000")
DUST_EXCEEDANCE_THRESHOLD = Decimal("75.0")
MIN_FINAL_COVERAGE = Decimal("0.9")
GOLD_THRESHOLD = Decimal("0.75")
SILVER_THRESHOLD = Decimal("0.5")
RECONCILE_DELTA_CAP_TONS = Decimal("2.0")

BASE_FEE_CENTS = 150000
BASE_RATE_CENTS = 12
TIER2_THRESHOLD_CENTS = 500000
TIER2_RATE_CENTS = 18
TIER2_SURCHARGE_CENTS = 25000

PROJECT_ACTIVE_PHASES = ("DEMOLITION_ACTIVE", "DEBRIS_CLEARANCE", "BACKFILL_PHASE", "FINAL_REVIEW")
PERMIT_NON_TERMINAL = ("DRAFT", "UNDER_REVIEW", "REVISION_REQUIRED", "APPROVED", "ACTIVE")
BACKFILL_APPROVED_OR_LATER = ("APPROVED", "COMPACTION_VERIFIED", "EROSION_VERIFIED", "COMPLETE")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _lookup(table, rec_id, label):
    rec = table.get(rec_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, f"{label} not found: {rec_id}")
    return rec


def get_project(pid):
    return _lookup(store.projects, pid, "project")


def get_structure_survey(sid):
    return _lookup(store.structure_surveys, sid, "structure survey")


def get_abatement(aid):
    return _lookup(store.abatements, aid, "abatement")


def get_utility_disconnect(uid):
    return _lookup(store.utility_disconnects, uid, "utility disconnect")


def get_permit(pid):
    return _lookup(store.permits, pid, "permit")


def get_engineering_survey(eid):
    return _lookup(store.engineering_surveys, eid, "engineering survey")


def get_salvage_manifest(mid):
    return _lookup(store.salvage_manifests, mid, "salvage manifest")


def get_notification(nid):
    return _lookup(store.notifications, nid, "neighbor notification")


def get_debris_ticket(tid):
    return _lookup(store.debris_tickets, tid, "debris ticket")


def get_backfill_plan(bid):
    return _lookup(store.backfill_plans, bid, "backfill plan")


def get_final_inspection(iid):
    return _lookup(store.final_inspections, iid, "final inspection")


def children(table, fk, parent_id):
    return [r for r in table.values() if r[fk] == parent_id]


def project_surveys(project_id):
    return children(store.structure_surveys, "project_id", project_id)


def project_abatements(project_id):
    survey_ids = {s["id"] for s in project_surveys(project_id)}
    return [a for a in store.abatements.values() if a["structure_survey_id"] in survey_ids]


def project_disconnects(project_id):
    return children(store.utility_disconnects, "project_id", project_id)


def project_permits(project_id):
    return children(store.permits, "project_id", project_id)


def project_notifications(project_id):
    return children(store.notifications, "project_id", project_id)


def project_tickets(project_id):
    return children(store.debris_tickets, "project_id", project_id)


def project_backfill_plans(project_id):
    return children(store.backfill_plans, "project_id", project_id)


def project_inspections(project_id):
    return children(store.final_inspections, "project_id", project_id)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_permit_fee_cents(gross_floor_area_sqft):
    """Tiered fee, pinned evaluation order: provisional subtotal at the base
    rate selects the tier; the final fee uses the tier rate plus surcharge."""
    provisional_subtotal = BASE_FEE_CENTS + gross_floor_area_sqft * BASE_RATE_CENTS
    tier2 = provisional_subtotal >= TIER2_THRESHOLD_CENTS
    rate = TIER2_RATE_CENTS if tier2 else BASE_RATE_CENTS
    return BASE_FEE_CENTS + gross_floor_area_sqft * rate + (TIER2_SURCHARGE_CENTS if tier2 else 0)


def recompute_diversion(project):
    """Diversion rate from summed totals, rounded half-up exactly once to 4
    decimals; zero when the denominator is zero. Tier from the rounded rate."""
    denom = project["landfill_tons"] + project["diverted_tons"]
    if denom == 0:
        rate = Decimal("0")
    else:
        rate = round4(project["diverted_tons"] / denom)
    project["diversion_rate"] = rate
    if rate >= GOLD_THRESHOLD:
        project["diversion_tier"] = "GOLD"
    elif rate >= SILVER_THRESHOLD:
        project["diversion_tier"] = "SILVER"
    else:
        project["diversion_tier"] = "STANDARD"


def wind_factor(wind_speed_mph):
    w = wind_speed_mph
    if w < 5:
        return Decimal("0.5")
    if w <= 12:
        return Decimal("1.0")
    if w <= 20:
        return Decimal("1.6")
    return Decimal("2.4")


def quiet_window_intersects(start):
    """Delivery occupation [start, start+30min) must not intersect the nightly
    quiet window [19:00, 07:00) UTC."""
    end = start + timedelta(minutes=30)
    days = {start.date(), end.date()}
    for d in days:
        q1s = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        q1e = datetime.combine(d, time(7, 0), tzinfo=timezone.utc)
        q2s = datetime.combine(d, time(19, 0), tzinfo=timezone.utc)
        q2e = datetime.combine(d, time(0, 0), tzinfo=timezone.utc) + timedelta(days=1)
        for qs, qe in ((q1s, q1e), (q2s, q2e)):
            if max(start, qs) < min(end, qe):
                return True
    return False


def notification_wait_window_open(project_id, at_time):
    """True when the 72h wait after the latest DELIVERED notification has not
    yet elapsed at at_time. Boundary (exactly 72h) is satisfied -> not open."""
    delivered = [n for n in project_notifications(project_id) if n["status"] == "DELIVERED"]
    if not delivered:
        return True
    latest = max(n["delivered_at"] for n in delivered)
    return at_time < latest + timedelta(hours=NOTIFICATION_WAIT_HOURS)


# ---------------------------------------------------------------------------
# Cascades and the permit expiry sweep
# ---------------------------------------------------------------------------

def _void_pending_notifications(project):
    for n in project_notifications(project["id"]):
        if n["status"] == "PENDING_DELIVERY":
            n["status"] = "VOIDED"
            touch(n)


def _cancel_manifested_tickets(project):
    for t in project_tickets(project["id"]):
        if t["status"] == "MANIFESTED":
            t["status"] = "CANCELLED"
            touch(t)
            project["in_transit_tons"] -= t["gross_tons"]
            project["removed_tons"] += t["gross_tons"]


def cascade_release_readiness_lost(project):
    """Project falls from RELEASED back to PRECONDITIONS_PENDING (pin-stale or
    permit-expiry trigger): pin fields kept but stale, PENDING notifications
    voided, version +1."""
    project["status"] = "PRECONDITIONS_PENDING"
    _void_pending_notifications(project)
    touch(project)


def cascade_permit_expired_under_active(project):
    """Project in DEMOLITION_ACTIVE when its permit expires: back to
    PRECONDITIONS_PENDING, MANIFESTED tickets CANCELLED with counter moves."""
    project["status"] = "PRECONDITIONS_PENDING"
    _cancel_manifested_tickets(project)
    touch(project)


def run_permit_expiry_sweep():
    """Every ACTIVE permit with expires_at strictly before the current logical
    time goes EXPIRED (boundary: equal is NOT expired) and cascades into its
    project when the project is RELEASED or DEMOLITION_ACTIVE."""
    current = store.clock
    for permit in list(store.permits.values()):
        if permit["status"] != "ACTIVE":
            continue
        if not (permit["expires_at"] < current):
            continue
        permit["status"] = "EXPIRED"
        touch(permit)
        project = store.projects.get(permit["project_id"])
        if project is None:
            continue
        if project["status"] == "RELEASED":
            cascade_release_readiness_lost(project)
        elif project["status"] == "DEMOLITION_ACTIVE":
            cascade_permit_expired_under_active(project)
