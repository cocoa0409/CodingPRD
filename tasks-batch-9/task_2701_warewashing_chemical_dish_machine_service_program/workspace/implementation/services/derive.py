"""Derived fields, the parallel health axis and the three named cascades."""

from datetime import timedelta

import db
from services import calc
from util import dec

OPEN_ALERT_STATUSES = calc.OPEN_ALERT_STATUSES
OPEN_TICKET_STATUSES = calc.OPEN_TICKET_STATUSES
TECH_LOAD_STATUSES = calc.TECH_LOAD_STATUSES
RETRIEVAL_BLOCKING_STATUSES = ("DISPATCHED", "ON_SITE", "PENDING_VERIFICATION")
LIVE_VISIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "SUBMITTED", "VERIFIED")


# --------------------------------------------------------------------------
# navigation helpers
# --------------------------------------------------------------------------

def placements_of_site(site_id):
    return [p for p in db.rows("machine_placements") if p["site_id"] == site_id]


def placements_of_agreement(agreement_id):
    return [
        p for p in db.rows("machine_placements")
        if p["agreement_id"] == agreement_id
    ]


def dispensers_of_placement(placement_id):
    return [
        d for d in db.rows("dispensers") if d["placement_id"] == placement_id
    ]


def dispensers_of_site(site_id):
    out = []
    for dispenser in db.rows("dispensers"):
        placement = db.get("machine_placements", dispenser["placement_id"])
        if placement is not None and placement["site_id"] == site_id:
            out.append(dispenser)
    return out


def alerts_of_placement(placement_id):
    return [
        a for a in db.rows("telemetry_alerts")
        if a["placement_id"] == placement_id
    ]


def tickets_of_placement(placement_id):
    return [
        t for t in db.rows("service_tickets")
        if t["placement_id"] == placement_id
    ]


def visits_of_ticket(ticket_id):
    return [
        v for v in db.rows("service_visits") if v["ticket_id"] == ticket_id
    ]


def records_of_visit(visit_id):
    return [
        r for r in db.rows("calibration_records") if r["visit_id"] == visit_id
    ]


def site_of_placement(placement):
    return db.get("sites", placement["site_id"])


def customer_of_placement(placement):
    site = site_of_placement(placement)
    if site is None:
        return None
    return db.get("customers", site["customer_id"])


def owning_customer_id_of_placement(placement):
    site = db.get("sites", placement["site_id"])
    return site["customer_id"] if site else None


def model_of_placement(placement):
    return db.get("machine_models", placement["machine_model_id"])


def agreements_of_customer(customer_id):
    return [
        a for a in db.rows("service_agreements")
        if a["customer_id"] == customer_id
    ]


def live_agreements_of_customer(customer_id):
    return [
        a for a in agreements_of_customer(customer_id)
        if a["status"] in calc.LIVE_AGREEMENT_STATUSES
    ]


def covering_agreement_of_site(site):
    """The agreement a review or delivery is judged against (PRD 3.7)."""
    live = live_agreements_of_customer(site["customer_id"])
    if live:
        return live[0]
    ended = [
        a for a in agreements_of_customer(site["customer_id"])
        if a["status"] in ("TERMINATED", "EXPIRED")
    ]
    if not ended:
        return None
    ended.sort(key=lambda a: (a.get("updated_at") or a["created_at"], a["_seq"]))
    return ended[-1]


def covered_product_ids_of_site(site):
    covered = set()
    for agreement in live_agreements_of_customer(site["customer_id"]):
        for product_id in agreement["covered_product_ids"]:
            covered.add(product_id)
    return covered


# --------------------------------------------------------------------------
# derived counters
# --------------------------------------------------------------------------

def _assign(row, field, value):
    if row.get(field) != value:
        row[field] = value
        db.mark(row)


def recompute_site(site):
    if site is None:
        return
    open_tickets = []
    for placement in placements_of_site(site["id"]):
        for ticket in tickets_of_placement(placement["id"]):
            if ticket["status"] in OPEN_TICKET_STATUSES:
                open_tickets.append(ticket)
    posture = "NORMAL"
    if any(t["priority_score"] >= 700 for t in open_tickets):
        posture = "CRITICAL"
    elif open_tickets:
        posture = "ELEVATED"
    _assign(site, "open_ticket_count", len(open_tickets))
    _assign(site, "service_posture", posture)


def recompute_customer(customer):
    if customer is None:
        return
    total = 0
    for site in db.rows("sites"):
        if site["customer_id"] != customer["id"]:
            continue
        for placement in placements_of_site(site["id"]):
            if placement["placement_status"] in calc.EQUIPMENT_PLACEMENT_STATUSES:
                model = model_of_placement(placement)
                if model is not None:
                    total += model["equipment_value_cents"]
    active = len(live_agreements_of_customer(customer["id"]))
    _assign(customer, "equipment_on_placement_value_cents", total)
    _assign(customer, "active_agreement_count", active)


def recompute_agreement_placements(agreement):
    if agreement is None:
        return
    # PRD 3.3: cancelling a never-installed placement and completing a
    # retrieval both drop placement_count by one, so only the three live
    # lifecycle states count.
    count = len([
        p for p in placements_of_agreement(agreement["id"])
        if p["placement_status"] in calc.EQUIPMENT_PLACEMENT_STATUSES
    ])
    _assign(agreement, "placement_count", count)


def recompute_technician(technician):
    if technician is None:
        return
    load = 0
    flags = 0
    for ticket in db.rows("service_tickets"):
        if (ticket["assigned_technician_id"] == technician["id"]
                and ticket["status"] in TECH_LOAD_STATUSES):
            load += 1
    for visit in db.rows("service_visits"):
        if (visit["technician_id"] == technician["id"]
                and visit["visit_status"] == "REJECTED"):
            flags += 1
    _assign(technician, "open_ticket_count", load)
    _assign(technician, "quality_flag_count", flags)


def recompute_placement_alerts(placement):
    if placement is None:
        return
    count = len([
        a for a in alerts_of_placement(placement["id"])
        if a["status"] in OPEN_ALERT_STATUSES
    ])
    _assign(placement, "open_alert_count", count)


def recompute_cycles(placement):
    reading = calc.latest_device_reading(placement["id"])
    if reading is None:
        last = placement["initial_cycle_count"]
    else:
        last = reading["cycle_count_total"]
    _assign(placement, "last_cycle_count", last)
    baseline = placement.get("_calibration_baseline", placement["initial_cycle_count"])
    delta = last - baseline
    _assign(placement, "cycles_since_calibration", delta if delta > 0 else 0)


# --------------------------------------------------------------------------
# the machine health axis
# --------------------------------------------------------------------------

def drive_down(placement, alert=None):
    if placement["placement_status"] != "INSTALLED":
        return
    if placement["operational_status"] not in ("UP", "DEGRADED"):
        return
    placement["operational_status"] = "DOWN"
    db.mark(placement)
    if alert is not None:
        auto_ticket(placement, alert)


def drive_degraded(placement):
    if placement["placement_status"] != "INSTALLED":
        return
    if placement["operational_status"] != "UP":
        return
    placement["operational_status"] = "DEGRADED"
    db.mark(placement)


def has_open_ticket(placement_id):
    for ticket in tickets_of_placement(placement_id):
        if ticket["status"] in OPEN_TICKET_STATUSES:
            return True
    return False


def create_ticket(placement, site, origin, symptom, alert, reported_by):
    score = calc.priority_score(placement, site, symptom, db.now())
    ticket = db.insert("service_tickets", {
        "placement_id": placement["id"],
        "alert_id": alert["id"] if alert is not None else None,
        "assigned_technician_id": None,
        "origin": origin,
        "reported_symptom": symptom,
        "requires_sanitation_cert": calc.requires_sanitation_cert(symptom, alert),
        "priority_score": score,
        "response_deadline_at": calc.response_deadline(db.now(), score),
        "status": "QUEUED",
        "sla_breached": False,
        "escalation_level": 0,
        "reported_by_user_id": reported_by,
    })
    # PRD 3.5: a customer report of MACHINE_DOWN is scored against the placement's
    # health as it was *before* the request, "because that request's own drive of the
    # machine to DOWN is applied only after the score has been stamped". The drive
    # carries no triggering alert, so it raises no auto-ticket of its own (and cascade
    # beta link 4 would skip it anyway, this very ticket now standing in QUEUED).
    if origin == "CUSTOMER_REPORT" and symptom == "MACHINE_DOWN":
        drive_down(placement)
    recompute_site(site)
    return ticket


def auto_ticket(placement, alert):
    """Cascade beta link 4: the machine going DOWN raises its own ticket."""
    if has_open_ticket(placement["id"]):
        return None
    site = site_of_placement(placement)
    if site is None:
        return None
    return create_ticket(
        placement, site, "TELEMETRY_AUTO", "MACHINE_DOWN", alert, None
    )


# --------------------------------------------------------------------------
# dispenser lockout
# --------------------------------------------------------------------------

def lock_out(dispenser, reason):
    dispenser["dispenser_status"] = "LOCKED_OUT"
    dispenser["lockout_reason"] = reason
    db.mark(dispenser)


def suppress_open_alerts(placement):
    for alert in alerts_of_placement(placement["id"]):
        if alert["status"] in OPEN_ALERT_STATUSES:
            alert["status"] = "SUPPRESSED"
            db.mark(alert)
    recompute_placement_alerts(placement)


def cancel_queued_tickets(placement):
    for ticket in tickets_of_placement(placement["id"]):
        if ticket["status"] != "QUEUED":
            continue
        ticket["status"] = "CANCELLED"
        db.mark(ticket)
        for visit in visits_of_ticket(ticket["id"]):
            if visit["visit_status"] == "SCHEDULED":
                visit["visit_status"] = "CANCELLED"
                db.mark(visit)
    recompute_site(site_of_placement(placement))


def end_placement_chemistry(placement, reason="AGREEMENT_ENDED"):
    for dispenser in dispensers_of_placement(placement["id"]):
        if dispenser["dispenser_status"] != "ACTIVE":
            continue
        lock_out(dispenser, reason)
        suppress_open_alerts(placement)
    cancel_queued_tickets(placement)


# --------------------------------------------------------------------------
# cascade alpha - an agreement stops covering its fleet
# --------------------------------------------------------------------------

def cascade_alpha(agreement, retrieval_due_days=30):
    """Run after the agreement's own status has been set to a terminal one."""
    customer = db.get("customers", agreement["customer_id"])
    recompute_customer(customer)
    due_date = db.now().date() + timedelta(days=retrieval_due_days)
    for placement in placements_of_agreement(agreement["id"]):
        if placement["placement_status"] != "INSTALLED":
            continue
        placement["placement_status"] = "RETRIEVAL_SCHEDULED"
        placement["retrieval_due_date"] = due_date
        db.mark(placement)
        end_placement_chemistry(placement)
    db.mark(agreement)


# --------------------------------------------------------------------------
# cascade gamma - an investigation case reaches a terminal status
# --------------------------------------------------------------------------

def cascade_gamma(case, review):
    review["status"] = "CLOSED"
    db.mark(review)
    if case["remediation"] != "DISPENSER_REPLACEMENT":
        return
    for dispenser in dispensers_of_site(review["site_id"]):
        if dispenser["product_id"] != review["product_id"]:
            continue
        if dispenser["dispenser_status"] != "ACTIVE":
            continue
        lock_out(dispenser, "INVESTIGATION_HOLD")
        placement = db.get("machine_placements", dispenser["placement_id"])
        if placement is not None:
            drive_degraded(placement)


# --------------------------------------------------------------------------
# repair-confirmed health reassessment (PRD 3.6, verified branch)
# --------------------------------------------------------------------------

def resolve_open_alerts(placement):
    for alert in alerts_of_placement(placement["id"]):
        if alert["status"] in OPEN_ALERT_STATUSES:
            alert["status"] = "RESOLVED"
            db.mark(alert)
    recompute_placement_alerts(placement)


def any_locked_out(placement):
    for dispenser in dispensers_of_placement(placement["id"]):
        if dispenser["dispenser_status"] == "LOCKED_OUT":
            return True
    return False


def rederive_health(placement):
    """Only after every alert of a confirmed repair has been resolved."""
    if placement["placement_status"] != "INSTALLED":
        return
    if placement["operational_status"] not in ("UP", "DEGRADED", "DOWN"):
        return
    open_alerts = [
        a for a in alerts_of_placement(placement["id"])
        if a["status"] in OPEN_ALERT_STATUSES
    ]
    target = "UP"
    if open_alerts or any_locked_out(placement):
        target = "DEGRADED"
    if placement["operational_status"] != target:
        placement["operational_status"] = target
        db.mark(placement)
