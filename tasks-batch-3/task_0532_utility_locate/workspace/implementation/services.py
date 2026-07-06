"""Business logic: calculations, posture reconciliation, clock auto-transitions."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from models import touch

# --- Constants (from SCAFFOLD calculations) ---
EMERGENCY_WINDOW_HOURS = 2
NORMAL_WINDOW_BUSINESS_DAYS = 2
WITHIN_MARKS_EXCAVATOR_PCT = Decimal("0.25")
OUTSIDE_MARKS_EXCAVATOR_PCT = Decimal("0.75")
NORMAL_ASSIGNMENT_MINUTES = 240
HIGH_PRIORITY_FACTOR = Decimal("0.5")
LOAD_THRESHOLD = 3
LOAD_SLACK_MINUTES = 60
MARKOUT_VALID_DAYS = 21


def markout_valid_until(completed_at):
    return completed_at + timedelta(days=MARKOUT_VALID_DAYS)


# ---------------------------------------------------------------------------
# calc sla_due_at
# ---------------------------------------------------------------------------
def compute_sla_due_at(ticket_type, base):
    if ticket_type == "EMERGENCY":
        return base + timedelta(hours=EMERGENCY_WINDOW_HOURS)
    remaining = NORMAL_WINDOW_BUSINESS_DAYS
    cursor = base
    while remaining > 0:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() in (0, 1, 2, 3, 4):
            remaining -= 1
    return cursor


# ---------------------------------------------------------------------------
# calc assignment_sla
# ---------------------------------------------------------------------------
def compute_assignment_deadline(ticket, member, notification, tech, dispatched_at):
    if ticket["ticket_type"] == "EMERGENCY":
        minutes = member["emergency_contact_minutes"]
    else:
        minutes = NORMAL_ASSIGNMENT_MINUTES
    if notification["is_high_priority"]:
        minutes = math.ceil(Decimal(minutes) * HIGH_PRIORITY_FACTOR)
    if tech["active_assignment_count"] >= LOAD_THRESHOLD:
        minutes = minutes + LOAD_SLACK_MINUTES
    return dispatched_at + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# calc liability_apportionment
# ---------------------------------------------------------------------------
def compute_liability(cost, markout_id, dug_within_marks):
    if markout_id is None:
        excavator = cost
    else:
        pct = WITHIN_MARKS_EXCAVATOR_PCT if dug_within_marks else OUTSIDE_MARKS_EXCAVATOR_PCT
        excavator = int((Decimal(cost) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    member = cost - excavator
    return excavator, member


# ---------------------------------------------------------------------------
# Ticket posture / counter reconciliation
# ---------------------------------------------------------------------------
def ticket_notifications(ticket_id):
    return [n for n in db.utility_notifications.values() if n["ticket_id"] == ticket_id]


def compute_open_count(ticket_id):
    return sum(1 for n in ticket_notifications(ticket_id) if n["response_status"] == "PENDING")


def compute_posture(ticket):
    notes = ticket_notifications(ticket["id"])
    now = db.clock.get()
    if ticket["status"] == "INTAKE":
        return "INTAKE"
    pending = sum(1 for n in notes if n["response_status"] == "PENDING")
    conflict = sum(1 for n in notes if n["response_status"] == "CONFLICT")
    if ticket["sla_due_at"] is not None and now > ticket["sla_due_at"] and pending > 0:
        return "SLA_BREACHED"
    if conflict >= 1:
        return "CONFLICT"
    if pending > 0:
        return "AWAITING_RESPONSES"
    return "ALL_CLEAR"


def reconcile_ticket(ticket):
    """Recompute open_response_count and response_posture; bump version/updated_at."""
    ticket["open_response_count"] = compute_open_count(ticket["id"])
    ticket["response_posture"] = compute_posture(ticket)
    touch(ticket)


# ---------------------------------------------------------------------------
# Clock advance auto-transitions
# ---------------------------------------------------------------------------
def advance_clock_transitions():
    now = db.clock.get()

    # Ticket SLA expiry: SUBMITTED -> EXPIRED when clock past sla_due_at and open>0
    for ticket in db.locate_tickets.values():
        if ticket["status"] == "SUBMITTED" and ticket["sla_due_at"] is not None:
            if now > ticket["sla_due_at"] and compute_open_count(ticket["id"]) > 0:
                ticket["status"] = "EXPIRED"
                ticket["response_posture"] = "SLA_BREACHED"
                ticket["open_response_count"] = compute_open_count(ticket["id"])
                touch(ticket)

    # Ticket dig-window expiry: MARKED -> EXPIRED when clock past dig_window_expires_at
    for ticket in db.locate_tickets.values():
        if ticket["status"] == "MARKED" and ticket["dig_window_expires_at"] is not None:
            if now > ticket["dig_window_expires_at"]:
                ticket["status"] = "EXPIRED"
                touch(ticket)
                # Cascade: active COMPLETE mark-out -> EXPIRED
                for m in db.mark_outs.values():
                    if m["ticket_id"] == ticket["id"] and m["status"] == "COMPLETE":
                        m["status"] = "EXPIRED"
                        touch(m)

    # Assignment SLA breach: DISPATCHED/EN_ROUTE -> BREACHED when clock past deadline
    for a in db.locate_assignments.values():
        if a["status"] in ("DISPATCHED", "EN_ROUTE") and a["sla_deadline_at"] is not None:
            if now > a["sla_deadline_at"]:
                a["status"] = "BREACHED"
                a["sla_breached"] = True
                touch(a)
                _decrement_tech(a["locate_tech_id"])


def _decrement_tech(tech_id):
    tech = db.locate_techs.get(tech_id)
    if tech is None:
        return
    tech["active_assignment_count"] = max(0, tech["active_assignment_count"] - 1)
    touch(tech)
