"""Business logic: calculations (SCAFFOLD calculations table) and cascades.

All monetary values are integer cents. Fractional-cent results are rounded
half-up exactly once, at the pinned point in each calculation.
"""
from decimal import Decimal, ROUND_HALF_UP

import db

# --- rework_penalty constants ---
REJECT_PENALTY = 10
DENY_PENALTY = 5
EXPIRY_PENALTY = 7
DELIVERY_EXCEPTION_PENALTY = 3
LATE_DELIVERY_PENALTY = 5
LOST_PENALTY = 8
WATCH_THRESHOLD = 20
ESCALATED_THRESHOLD = 40


def round_half_up(value):
    """Round a Decimal to whole cents, half-up. Returns int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------- posture ledger (§2.9) ----------

def derive_posture(score):
    if score >= ESCALATED_THRESHOLD:
        return "ESCALATED"
    if score >= WATCH_THRESHOLD:
        return "WATCH"
    return "NORMAL"


def add_penalty(project, points):
    """Monotonic accumulator; re-derives posture; one version bump per event."""
    project["rework_penalty_score"] = project.get("rework_penalty_score", 0) + points
    project["posture"] = derive_posture(project["rework_penalty_score"])
    db.touch(project)


# ---------- lookups ----------

def get_project(project_id):
    return db.collections["projects"].get(project_id)


def get_client(client_id):
    return db.collections["clients"].get(client_id)


def project_of_assignment(assignment):
    return get_project(assignment["project_id"]) if assignment else None


def project_store_rows(project_id):
    return [ps for ps in db.collections["project_stores"].values() if ps["project_id"] == project_id]


def visits_of_project(project_id):
    out = []
    for v in db.collections["store_visits"].values():
        a = db.collections["assignments"].get(v["assignment_id"])
        if a and a["project_id"] == project_id:
            out.append(v)
    return out


def open_visit_of_assignment(assignment_id):
    for v in db.collections["store_visits"].values():
        if v["assignment_id"] == assignment_id:
            return v
    return None


# ---------- mileage / travel pay (§3.8) ----------

def compute_mileage_pay_cents(log, rep):
    if rep["mileage_policy"] == "HOME_BASED":
        payable = max(0, log["round_trip_miles"] - 2 * rep["home_base_commute_miles"])
    else:  # FIRST_STOP
        payable = max(0, log["round_trip_miles"] - log["home_to_first_stop_miles"])
    return payable * rep["mileage_rate_cents"]


def compute_travel_time_pay_cents(log, rep):
    if rep["employment_type"] == "C1099":
        return 0
    m = log["drive_minutes"]
    rate = rep["travel_minute_rate_cents"]
    t1 = min(m, 60)
    t2 = min(max(m - 60, 0), 60)
    t3 = max(m - 120, 0)
    # Pinned rounding order: each tier rounded half-up to whole cents BEFORE summing.
    return (
        t1 * rate
        + round_half_up(Decimal(t2 * rate) * Decimal("1.25"))
        + round_half_up(Decimal(t3 * rate) * Decimal("1.5"))
    )


# ---------- visit billing (§3.7) ----------

def compute_visit_billable_cents(visit, project, client):
    if visit["is_rework"]:
        return 0
    if project["effective_billing_model"] == "PER_STORE":
        return client["per_store_rate_cents"]
    # HOURLY: on_site_minutes * hourly_rate / 60, rounded half-up per visit.
    return round_half_up(
        Decimal(visit["on_site_minutes"]) * Decimal(client["hourly_rate_cents"]) / Decimal(60)
    )


# ---------- invoice totals (§3.7) ----------

def compute_line_total_cents(project_id):
    """Exact integer sum of VERIFIED visits' billable amounts; never re-rounded.
    REJECTED / PENDING_REVIEW excluded; rework visits contribute 0."""
    total = 0
    for v in visits_of_project(project_id):
        if v["verification_status"] == "VERIFIED":
            total += v.get("billable_amount_cents") or 0
    return total


def find_live_invoice(project_id):
    """The single live (OPEN or FINALIZED) invoice for a project, if any."""
    for inv in db.collections["invoices"].values():
        if inv["project_id"] == project_id and inv["status"] in ("OPEN", "FINALIZED"):
            return inv
    return None


def find_open_invoice(project_id):
    for inv in db.collections["invoices"].values():
        if inv["project_id"] == project_id and inv["status"] == "OPEN":
            return inv
    return None


def create_invoice(client_id, project_id, adjustment_cents=0):
    inv = db.base_fields()
    inv.update({
        "client_id": client_id,
        "project_id": project_id,
        "status": "OPEN",
        "line_total_cents": compute_line_total_cents(project_id),
        "adjustment_cents": adjustment_cents,
        "grand_total_cents": None,
    })
    db.collections["invoices"][inv["id"]] = inv
    return inv


# ---------- project aggregates / cascades (§3.5) ----------

def recompute_completed_store_count(project):
    """Count of ProjectStore rows whose latest StoreVisit is VERIFIED (== COMPLETED rows)."""
    rows = project_store_rows(project["id"])
    return sum(1 for r in rows if r["status"] == "COMPLETED")


def all_stores_terminal(project):
    rows = project_store_rows(project["id"])
    if not rows:
        return False
    if not all(r["status"] in ("COMPLETED", "DROPPED") for r in rows):
        return False
    return any(r["status"] == "COMPLETED" for r in rows)


def maybe_cascade_reconciling(project):
    """IN_FIELD -> RECONCILING when every store row reached a terminal outcome
    with at least one COMPLETED. Auto-creates an OPEN invoice if none exists."""
    if project["status"] != "IN_FIELD":
        return False
    if not all_stores_terminal(project):
        return False
    project["completed_store_count"] = recompute_completed_store_count(project)
    project["status"] = "RECONCILING"
    if find_live_invoice(project["id"]) is None:
        create_invoice(project["client_id"], project["id"], 0)
    db.touch(project)
    return True


def refresh_open_invoice_total(project_id):
    """While an invoice is OPEN, visit verifications recompute line_total_cents."""
    inv = find_open_invoice(project_id)
    if inv is not None:
        new_total = compute_line_total_cents(project_id)
        if new_total != inv["line_total_cents"]:
            inv["line_total_cents"] = new_total
            db.touch(inv)


# ---------- rework authorization expiry sweep (logical clock) ----------

def rework_expiry_sweep():
    """REQUESTED/APPROVED authorizations whose store due_date is before the new
    current logical date move to EXPIRED with a +7 penalty each."""
    from middleware import parse_date  # local import to avoid cycle
    today = db.now().date()
    for ra in list(db.collections["rework_auths"].values()):
        if ra["status"] not in ("REQUESTED", "APPROVED"):
            continue
        ps = db.collections["project_stores"].get(ra["project_store_id"])
        if ps is None:
            continue
        due = parse_date(ps.get("due_date"))
        if due is None:
            continue
        if today > due:
            ra["status"] = "EXPIRED"
            db.touch(ra)
            project = get_project(ra["project_id"])
            if project is not None:
                add_penalty(project, EXPIRY_PENALTY)


# ---------- fixture delivery gating (§3.3 / §3.6) ----------

def shipments_for_store(project_store_id):
    return [s for s in db.collections["shipments"].values()
            if s["project_store_id"] == project_store_id]


def depart_blocked_by_shipments(project, project_store_id):
    """Depart gate: FIXTURE_INSTALL only; a shipment in LABEL_CREATED/IN_TRANSIT
    with promised_date <= current logical date blocks departure."""
    if project["scope_type"] != "FIXTURE_INSTALL":
        return False
    from middleware import parse_date
    today = db.now().date()
    for s in shipments_for_store(project_store_id):
        if s["status"] in ("LABEL_CREATED", "IN_TRANSIT"):
            promised = parse_date(s.get("promised_date"))
            if promised is not None and promised <= today:
                return True
    return False


def checkin_blocked_by_shipments(project, project_store_id):
    """Check-in gate: FIXTURE_INSTALL only; any shipment in LABEL_CREATED,
    IN_TRANSIT, or DELIVERY_EXCEPTION blocks check-in regardless of date."""
    if project["scope_type"] != "FIXTURE_INSTALL":
        return False
    for s in shipments_for_store(project_store_id):
        if s["status"] in ("LABEL_CREATED", "IN_TRANSIT", "DELIVERY_EXCEPTION"):
            return True
    return False
