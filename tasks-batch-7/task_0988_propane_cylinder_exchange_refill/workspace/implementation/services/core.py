"""Shared computed-field logic: cage counts, posture, policies, selectors,
reconciliation expectations, serialization."""
from decimal import Decimal

import db

# Calculation constants (SCAFFOLD calculations table).
INITIAL_CERT_YEARS = 12
VISUAL_RECERT_YEARS = 5
HYDROSTATIC_RECERT_YEARS = 7
PROPANE_FILL_FACTOR = Decimal("0.42")
TARE_TOLERANCE_LBS = Decimal("0.10")
LEAK_PENALTY_CENTS = 25000
MAX_STATEMENT_PERIOD_DAYS = 62
VARIANCE_TOLERANCE_CENTS = 500
FORECAST_WINDOW_DAYS = 14
FULL_CYLINDER_LBS = 37
EMPTY_CYLINDER_LBS = 17
# PAR_FLOOR_RATIO = 0.5 -> reorder_floor_full = ceil(par_level_full / 2)


# ---------------------------------------------------------------------------
# Site derived values
# ---------------------------------------------------------------------------

def cage_counts(site_id):
    """site_cage_counts: FLEET only, at site, not in transit, not CONDEMNED."""
    full = empty = quar = 0
    for c in db.cylinders.values():
        if c["owner_kind"] != "FLEET":
            continue
        if c["current_site_id"] != site_id:
            continue
        if c["in_transit_run_id"] is not None:
            continue
        if c["cert_status"] == "CONDEMNED":
            continue
        fs = c["fill_status"]
        if fs == "FULL":
            full += 1
        elif fs == "EMPTY":
            empty += 1
        elif fs == "QUARANTINED":
            quar += 1
    return full, empty, quar


def reorder_floor_full(site):
    # ceil(par_level_full * 0.5)
    return -(-site["par_level_full"] // 2)


def sales_posture(site_id):
    for r in db.leak_reports.values():
        if (
            r["site_id"] == site_id
            and r["status"] == "CONFIRMED"
            and (r["severity"] == "MAJOR" or r["quarantine_cage"])
        ):
            return "SALES_BLOCKED"
    return "SALES_OPEN"


def restock_alert(site_id):
    site = db.sites[site_id]
    full, _, _ = cage_counts(site_id)
    return full <= reorder_floor_full(site)


# ---------------------------------------------------------------------------
# Pricing policies
# ---------------------------------------------------------------------------

def current_policy(site_id):
    today = db.current_date()
    for p in db.policies.values():
        if p["site_id"] != site_id:
            continue
        if p["effective_from"] <= today and (p["effective_to"] is None or today < p["effective_to"]):
            return p
    return None


def windows_overlap(f1, t1, f2, t2):
    """Half-open [from, to) overlap; None 'to' is open-ended. Adjacency allowed."""
    if t1 is not None and f2 >= t1:
        return False
    if t2 is not None and f1 >= t2:
        return False
    return True


# ---------------------------------------------------------------------------
# Cylinder selectors
# ---------------------------------------------------------------------------

def _selector_sort_key(c):
    return (c["certified_on"], c["_created_seq"])


def issue_selector(site_id):
    """cylinder_issue_selector: FLEET, CERTIFIED, FULL, at site, not in transit;
    rank certified_on ASC, tie-break created_at ASC."""
    cands = [
        c for c in db.cylinders.values()
        if c["owner_kind"] == "FLEET"
        and c["cert_status"] == "CERTIFIED"
        and c["fill_status"] == "FULL"
        and c["current_site_id"] == site_id
        and c["in_transit_run_id"] is None
    ]
    cands.sort(key=_selector_sort_key)
    return cands[0] if cands else None


def depot_pool():
    cands = [
        c for c in db.cylinders.values()
        if c["owner_kind"] == "FLEET"
        and c["cert_status"] == "CERTIFIED"
        and c["fill_status"] == "FULL"
        and c["current_site_id"] is None
        and c["in_transit_run_id"] is None
    ]
    cands.sort(key=_selector_sort_key)
    return cands


def assigned_cylinder_count(run_id):
    return sum(1 for c in db.cylinders.values() if c["in_transit_run_id"] == run_id)


# ---------------------------------------------------------------------------
# Reconciliation expectations
# ---------------------------------------------------------------------------

def cash_events_total(site_id, business_date):
    """exchange completes +total, refill closes +total, refunds -total on the date."""
    total = 0
    for o in db.exchange_orders.values():
        if o["site_id"] != site_id:
            continue
        if o["business_date"] == business_date and o["status"] in ("COMPLETED", "REFUNDED"):
            total += o["total_cents"]
        if o["refunded_on"] == business_date:
            total -= o["total_cents"]
    for t in db.refill_tickets.values():
        if (
            t["site_id"] == site_id
            and t["business_date"] == business_date
            and t["status"] == "CLOSED"
        ):
            total += t["total_cents"]
    return total


def refresh_session_expected(session):
    session["expected_cash_cents"] = (
        session["opening_baseline_cents"]
        + cash_events_total(session["site_id"], session["business_date"])
    )


def refresh_open_sessions(site_id, business_date):
    """Keep non-terminal same-day sessions current as cash events land."""
    for s in db.recon_sessions.values():
        if (
            s["site_id"] == site_id
            and s["business_date"] == business_date
            and s["status"] in ("OPEN", "VARIANCE_FLAGGED")
        ):
            refresh_session_expected(s)
            db.touch(s)


def find_session(site_id, business_date):
    for s in db.recon_sessions.values():
        if s["site_id"] == site_id and s["business_date"] == business_date:
            return s
    return None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize(entity, computed=None):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            v = float(v)
        out[k] = v
    if computed:
        out.update(computed)
    return out


def serialize_site(site):
    full, empty, quar = cage_counts(site["id"])
    floor = reorder_floor_full(site)
    return serialize(site, {
        "reorder_floor_full": floor,
        "full_on_hand": full,
        "empty_on_hand": empty,
        "quarantined_on_hand": quar,
        "sales_posture": sales_posture(site["id"]),
        "restock_alert": full <= floor,
    })


def serialize_policy(p):
    today = db.current_date()
    is_current = p["effective_from"] <= today and (
        p["effective_to"] is None or today < p["effective_to"]
    )
    return serialize(p, {"is_current": is_current})


def serialize_run(run):
    return serialize(run, {"assigned_cylinder_count": assigned_cylinder_count(run["id"])})
