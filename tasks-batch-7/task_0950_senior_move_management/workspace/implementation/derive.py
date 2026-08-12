"""Derived quantities.

Every field the scaffold marks `source: computed` that is a pure function of
other stored rows is computed here and never cached, which is observationally
identical to the eager reconciliation PRD 2.12 demands and cannot drift.
Fields that are genuine snapshots of a past moment (planned_trip_count,
commission_cents, holdback_cents, coordination_fee_cents, ...) stay stored.
"""

from decimal import Decimal

import calc
import constants as K
import store
from util import D, rhu, parse_dt, parse_date


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def milestones_of(engagement_id):
    rows = store.where("milestones", engagement_id=engagement_id)
    return sorted(rows, key=lambda m: m["sequence_index"])


def milestone_by_key(engagement_id, key):
    for m in milestones_of(engagement_id):
        if m["milestone_key"] == key:
            return m
    return None


def invoice_of(engagement_id):
    rows = store.where("invoices", engagement_id=engagement_id)
    return rows[0] if rows else None


def lines_of(invoice_id):
    return store.where("invoice_lines", invoice_id=invoice_id)


def items_of(engagement_id):
    return store.where("inventory_items", engagement_id=engagement_id)


def rooms_of(residence_id):
    return store.where("destination_rooms", destination_residence_id=residence_id)


def sort_plan_of(engagement_id):
    """The engagement's operative sort plan - the most recently created one."""
    rows = store.where("sort_plans", engagement_id=engagement_id)
    return rows[-1] if rows else None


def move_day_plan_of(engagement_id):
    rows = store.where("move_day_plans", engagement_id=engagement_id)
    return rows[-1] if rows else None


def assignments_of_plan(plan_id):
    return store.where("crew_assignments", move_day_plan_id=plan_id)


def entries_of_assignment(assignment_id):
    return store.where("time_entries", crew_assignment_id=assignment_id)


def holds_of_item(item_id):
    return store.where("family_holds", inventory_item_id=item_id)


# ---------------------------------------------------------------------------
# engagement
# ---------------------------------------------------------------------------

OPEN_MILESTONE_STATES = {"PENDING", "IN_PROGRESS", "REOPENED"}


def engagement_phase(engagement):
    open_rows = [m for m in milestones_of(engagement["id"])
                 if m["status"] in OPEN_MILESTONE_STATES]
    if not open_rows:
        return "DONE"
    return open_rows[0]["milestone_key"]


def engagement_client(engagement):
    return store.get("clients", engagement["client_id"])


def inventory_item_count(engagement_id):
    return len(items_of(engagement_id))


def total_inventory_volume_cft(engagement_id):
    return rhu(sum((D(i["volume_cft"]) for i in items_of(engagement_id)), D(0)), 2)


def keep_volume_cft(engagement_id):
    return rhu(sum((D(i["volume_cft"]) for i in items_of(engagement_id)
                    if i["disposition"] == "KEEP"), D(0)), 2)


def haul_volume_cft(engagement_id):
    return rhu(sum((D(i["volume_cft"]) for i in items_of(engagement_id)
                    if i["disposition"] == "HAUL_AWAY"), D(0)), 2)


def completed_assignments(engagement_id):
    plan = move_day_plan_of(engagement_id)
    if plan is None:
        return []
    return [a for a in assignments_of_plan(plan["id"]) if a["status"] == "COMPLETED"]


def accrued_labor_cents(engagement_id):
    return sum(assignment_money(a)["labor_cents"] for a in completed_assignments(engagement_id))


def billing_hours_total(engagement_id):
    total = sum((assignment_money(a)["applied_hours"] for a in completed_assignments(engagement_id)),
                D(0))
    return rhu(total, 2)


def consignment_credit_cents(engagement_id):
    invoice = invoice_of(engagement_id)
    if invoice is None:
        return 0
    return sum(l["amount_cents"] for l in lines_of(invoice["id"])
               if l["line_type"] in K.CREDIT_LINE_TYPES)


def billing_hold(engagement):
    invoice = invoice_of(engagement["id"])
    if invoice is None:
        return False
    return invoice_balance_due(invoice) > 0 and invoice["status"] in ("ISSUED", "DISPUTED")


def engagement_count(client_id):
    return len(store.where("engagements", client_id=client_id))


# ---------------------------------------------------------------------------
# invoice aggregates
# ---------------------------------------------------------------------------

def invoice_subtotal(invoice):
    return sum(l["amount_cents"] for l in lines_of(invoice["id"])
               if l["line_type"] not in K.SUBTOTAL_EXCLUDED_LINE_TYPES)


def invoice_credits(invoice):
    return sum(l["amount_cents"] for l in lines_of(invoice["id"])
               if l["line_type"] in K.CREDIT_LINE_TYPES)


def invoice_total(invoice):
    return invoice_subtotal(invoice) + invoice["coordination_fee_cents"] + invoice_credits(invoice)


def invoice_balance_due(invoice):
    return invoice_total(invoice) - invoice["payments_cents"]


# ---------------------------------------------------------------------------
# crew assignment money
# ---------------------------------------------------------------------------

def assignment_engagement(assignment):
    plan = store.get("move_day_plans", assignment["move_day_plan_id"])
    if plan is None:
        return None
    return store.get("engagements", plan["engagement_id"])


def assignment_money(assignment):
    """portal_hours, billing_hours, applied_hours, overtime_hours, labor_cents."""
    eligible_raw = []
    eligible_rounded = []
    for entry in entries_of_assignment(assignment["id"]):
        if entry["voided"] or entry["entry_kind"] not in ("LABOR", "TRAVEL"):
            continue
        eligible_raw.append(D(entry["raw_hours"]))
        eligible_rounded.append(D(entry["rounded_hours"]))
    portal, billing = calc.crew_billable_hours(eligible_raw, eligible_rounded)

    engagement = assignment_engagement(assignment)
    billing_mode = engagement["billing_mode"] if engagement else "HOURLY"
    applied = calc.crew_applied_hours(billing, billing_mode)
    regular, overtime = calc.crew_overtime_split(applied)

    member = store.get("crew_members", assignment["crew_member_id"])
    rate = member["hourly_rate_cents"] if member else 0
    labor = calc.crew_assignment_labor_cents(regular, overtime, rate)
    return {
        "portal_hours": portal,
        "billing_hours": billing,
        "applied_hours": applied,
        "overtime_hours": overtime,
        "labor_cents": labor,
    }


CREW_CONFIRMED_STATES = {"CONFIRMED", "CHECKED_IN", "COMPLETED"}
CREW_TERMINAL_STATES = {"COMPLETED", "REPLACED"}


def crew_confirmed_count(plan):
    return len([a for a in assignments_of_plan(plan["id"])
                if a["status"] in CREW_CONFIRMED_STATES])


def crew_lead_confirmed_count(plan):
    total = 0
    for a in assignments_of_plan(plan["id"]):
        if a["status"] not in CREW_CONFIRMED_STATES:
            continue
        member = store.get("crew_members", a["crew_member_id"])
        if member and member["crew_role"] == "LEAD":
            total += 1
    return total


def crew_lead_non_terminal_count(plan):
    total = 0
    for a in assignments_of_plan(plan["id"]):
        if a["status"] in CREW_TERMINAL_STATES or a["status"] == "NO_SHOW":
            continue
        member = store.get("crew_members", a["crew_member_id"])
        if member and member["crew_role"] == "LEAD":
            total += 1
    return total


def crew_min_required(plan):
    engagement = store.get("engagements", plan["engagement_id"])
    return calc.crew_min_required(engagement["home_tier"]) if engagement else 0


def crew_member_assignment_count(crew_member_id):
    return len(store.where("crew_assignments", crew_member_id=crew_member_id))


# ---------------------------------------------------------------------------
# rooms
# ---------------------------------------------------------------------------

def room_effective_capacity(room):
    residence = store.get("destination_residences", room["destination_residence_id"])
    status = residence["placement_status"] if residence else "DRAFT"
    return calc.room_effective_capacity(room["nominal_linear_inches"],
                                        room["approved_addendum_linear_inches"], status)


def room_keep_items(room_id, exclude_item_id=None):
    out = []
    for item in store.all_of("inventory_items"):
        if item["assigned_room_id"] != room_id or item["disposition"] != "KEEP":
            continue
        if exclude_item_id is not None and item["id"] == exclude_item_id:
            continue
        out.append(item)
    return out


def room_keep_load_linear(room_id, exclude_item_id=None):
    return rhu(sum((D(i["footprint_linear_inches"])
                    for i in room_keep_items(room_id, exclude_item_id)), D(0)), 2)


def room_keep_load_volume(room_id, exclude_item_id=None):
    return rhu(sum((D(i["volume_cft"])
                    for i in room_keep_items(room_id, exclude_item_id)), D(0)), 2)


def room_headroom(room):
    return rhu(room_effective_capacity(room) - room_keep_load_linear(room["id"]), 2)


def room_assigned_item_count(room_id):
    return len([i for i in store.all_of("inventory_items") if i["assigned_room_id"] == room_id])


def residence_room_count(residence_id):
    return len(rooms_of(residence_id))


def residence_total_capacity(residence_id):
    return rhu(sum((room_effective_capacity(r) for r in rooms_of(residence_id)), D(0)), 2)


# ---------------------------------------------------------------------------
# items, holds, portal parties, vendors
# ---------------------------------------------------------------------------

LIVE_HOLD_STATES = {"OPEN", "ESCALATED"}


def item_hold_state(item):
    for hold in holds_of_item(item["id"]):
        if hold["status"] in LIVE_HOLD_STATES:
            return "HELD"
    return "NONE"


def open_hold_count(engagement_id):
    total = 0
    for item in items_of(engagement_id):
        for hold in holds_of_item(item["id"]):
            if hold["status"] in LIVE_HOLD_STATES:
                total += 1
    return total


def item_donation_receipt(item):
    return calc.donation_receipt_value(item["disposition"], item["appraisal_source"],
                                       item["appraised_value_cents"])


def active_authorities_of_party(party_id):
    return [a for a in store.where("authority_records", holder_party_id=party_id)
            if a["status"] == "ACTIVE"]


def party_can_approve_dispositions(party_id):
    for record in active_authorities_of_party(party_id):
        if record["authority_scope"] in ("FULL", "DISPOSITION_ONLY"):
            return True
    return False


def party_active_ceiling(party_id):
    records = active_authorities_of_party(party_id)
    if not records:
        return 0
    return max(r["approval_ceiling_cents"] for r in records)


def vendor_blocked_assignment_count(vendor_id):
    return len([a for a in store.where("vendor_assignments", vendor_id=vendor_id)
                if a["status"] == "COI_BLOCKED"])


def lot_items(lot_id):
    return [i for i in store.all_of("inventory_items") if i["consignment_lot_id"] == lot_id]


def session_items_unpacked_count(session_id):
    return len([i for i in store.all_of("inventory_items")
                if i["unpack_session_id"] == session_id and i["handling_state"] == "UNPACKED"])


def punch_breached_sla(item):
    if item["status"] not in ("OPEN", "REOPENED"):
        return False
    return parse_dt(store.now_iso()) > parse_dt(calc.punch_due_at(item["created_at"],
                                                                 item["severity"]))


# ---------------------------------------------------------------------------
# unpack session selector
# ---------------------------------------------------------------------------

def next_unpack_session(engagement_id):
    candidates = [s for s in store.where("unpack_sessions", engagement_id=engagement_id)
                  if s["status"] in ("SCHEDULED", "REOPENED")]
    if not candidates:
        return None
    def rank(session):
        return (0 if session["priority"] == "ESSENTIALS" else 1,
                parse_dt(session["scheduled_start_utc"]),
                parse_dt(session["created_at"]),
                session["_seq"])
    return sorted(candidates, key=rank)[0]


# ---------------------------------------------------------------------------
# owning engagement of any record (gate 3 / gate 4)
# ---------------------------------------------------------------------------

def owning_engagement(collection, record):
    if record is None:
        return None
    if collection == "engagements":
        return record
    if "engagement_id" in record:
        return store.get("engagements", record["engagement_id"])
    if collection == "destination_rooms":
        residence = store.get("destination_residences", record["destination_residence_id"])
        return owning_engagement("destination_residences", residence)
    if collection == "family_holds":
        item = store.get("inventory_items", record["inventory_item_id"])
        return owning_engagement("inventory_items", item)
    if collection == "crew_assignments":
        plan = store.get("move_day_plans", record["move_day_plan_id"])
        return owning_engagement("move_day_plans", plan)
    if collection == "time_entries":
        assignment = store.get("crew_assignments", record["crew_assignment_id"])
        return owning_engagement("crew_assignments", assignment)
    if collection == "invoice_lines":
        invoice = store.get("invoices", record["invoice_id"])
        return owning_engagement("invoices", invoice)
    return None
