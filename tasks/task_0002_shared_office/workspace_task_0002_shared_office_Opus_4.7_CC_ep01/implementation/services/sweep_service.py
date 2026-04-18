from datetime import timedelta, datetime, timezone
from decimal import Decimal

from db import db
from util import parse_iso, now_iso_string, bump
from services.bill_service import get_or_create_draft_bill, append_line, recompute_bill_totals, recompute_late_fee
from services.tenant_service import refresh_tenant
from services.pricing import compute_final_fee


def _consolidate_reservation(reservation: dict):
    tenant_id = reservation["tenant_id"]
    tenant = db.tenants.get(tenant_id)
    bill = get_or_create_draft_bill(tenant_id)
    reservation["bill_id"] = bill["id"]
    amount = reservation.get("final_fee_cents", 0) or 0
    resource = db.resources.get(reservation["resource_id"])
    kind = resource["kind"] if resource else None
    line_kind_map = {
        "WORKSTATION": "WORKSTATION_FEE",
        "MEETING_ROOM": "MEETING_ROOM_FEE",
        "EVENT_AREA": "EVENT_AREA_FEE",
    }
    line_kind = line_kind_map.get(kind, "WORKSTATION_FEE")
    if amount > 0:
        append_line(bill, line_kind, reservation["id"], amount)
    recompute_bill_totals(bill)
    bump(bill, db.now())
    refresh_tenant(tenant)


def _consolidate_visitor(visitor: dict):
    if visitor.get("overstay_fee_cents", 0) <= 0:
        return
    tenant_id = visitor["tenant_id"]
    tenant = db.tenants.get(tenant_id)
    bill = get_or_create_draft_bill(tenant_id)
    visitor["bill_id"] = bill["id"]
    append_line(bill, "VISITOR_OVERSTAY", visitor["id"], visitor["overstay_fee_cents"])
    recompute_bill_totals(bill)
    bump(bill, db.now())
    refresh_tenant(tenant)


def _compute_visitor_overstay(visitor: dict):
    expected = parse_iso(visitor["expected_departure_at"])
    actual = parse_iso(visitor["actual_departure_at"])
    delta = (actual - expected).total_seconds() if actual > expected else 0
    if delta <= 0:
        visitor["overstay_fee_cents"] = 0
        return
    minutes = delta / 60
    # Billable units = ceil(overstay_minutes / 30)
    import math
    units = math.ceil(minutes / 30)
    visitor["overstay_fee_cents"] = units * 500


def run_sweep():
    """Execute deferred-action sweep per PRD §2.6 and cascades."""
    now = db.now()
    affected_tenants = set()

    # 1. Reservation transitions
    for r in list(db.reservations.values()):
        end_at = parse_iso(r["end_at"])
        if end_at is None:
            continue
        if now >= end_at and r["status"] in ("PENDING", "CONFIRMED"):
            # NO_SHOW
            r["status"] = "NO_SHOW"
            r["final_fee_cents"] = r.get("provisional_fee_cents", 0) or 0
            bump(r, now)
            _consolidate_reservation(r)
            affected_tenants.add(r["tenant_id"])
        elif now >= end_at and r["status"] == "IN_USE":
            # COMPLETED via sweep; actual_end_at = end_at
            r["status"] = "COMPLETED"
            r["actual_end_at"] = r["end_at"]
            # Compute final fee
            tenant = db.tenants.get(r["tenant_id"])
            resource = db.resources.get(r["resource_id"])
            # parse actual_start
            actual_start_dt = parse_iso(r.get("actual_start_at")) or parse_iso(r["start_at"])
            actual_end_dt = parse_iso(r["actual_end_at"])
            # Ensure _start/_end dt present for pricing
            r["_start_at_dt"] = parse_iso(r["start_at"])
            r["_end_at_dt"] = parse_iso(r["end_at"])
            r["final_fee_cents"] = compute_final_fee(r, resource, r["tenant_id"], actual_start_dt, actual_end_dt)
            bump(r, now)
            _consolidate_reservation(r)
            affected_tenants.add(r["tenant_id"])

    # 2. Visitor: CHECKED_IN past expected_departure_at + 6h
    for v in list(db.visitors.values()):
        exp_dep = parse_iso(v.get("expected_departure_at"))
        if exp_dep is None:
            continue
        if v["status"] == "CHECKED_IN" and now >= (exp_dep + timedelta(hours=6)):
            v["status"] = "CHECKED_OUT"
            v["actual_departure_at"] = now_iso_string(exp_dep + timedelta(hours=6))
            _compute_visitor_overstay(v)
            _consolidate_visitor(v)
            affected_tenants.add(v["tenant_id"])

    # 3. Visitor: REGISTERED past expected_departure_at
    for v in list(db.visitors.values()):
        exp_dep = parse_iso(v.get("expected_departure_at"))
        if exp_dep is None:
            continue
        if v["status"] == "REGISTERED" and now >= exp_dep:
            v["status"] = "NO_SHOW"
            affected_tenants.add(v["tenant_id"])

    # 4. Bills ISSUED past due_at -> OVERDUE
    for b in list(db.bills.values()):
        due_at = parse_iso(b.get("due_at")) if b.get("due_at") else None
        if due_at is None:
            continue
        if b["status"] == "ISSUED" and now >= due_at:
            b["status"] = "OVERDUE"
            recompute_late_fee(b)
            b["total_due_cents"] = b["subtotal_cents"] + b["tax_cents"] + b["late_fee_cents"]
            bump(b, now)
            affected_tenants.add(b["tenant_id"])

    # 5. OVERDUE bills: recompute late fee
    for b in list(db.bills.values()):
        if b["status"] == "OVERDUE":
            prev_total = b["total_due_cents"]
            recompute_late_fee(b)
            new_total = b["subtotal_cents"] + b["tax_cents"] + b["late_fee_cents"]
            if new_total != prev_total:
                b["total_due_cents"] = new_total
                bump(b, now)
                affected_tenants.add(b["tenant_id"])

    # Also scheduled badge suspends on lease termination_effective_date
    _apply_scheduled_badge_suspends(now, affected_tenants)

    # 6. Recompute tenant outstanding balance and access_posture
    for tid in affected_tenants:
        tenant = db.tenants.get(tid)
        if tenant is None:
            continue
        refresh_tenant(tenant)
        bump(tenant, now)


def _apply_scheduled_badge_suspends(now: datetime, affected_tenants: set):
    """For any AccessBadge with scheduled_suspend_on <= today and status ACTIVE -> SUSPENDED."""
    today = now.date()
    from util import parse_date
    for badge in list(db.access_badges.values()):
        ss = badge.get("scheduled_suspend_on")
        if ss is None:
            continue
        ssd = parse_date(ss) if isinstance(ss, str) else ss
        if ssd is None:
            continue
        if badge["status"] == "ACTIVE" and today >= ssd:
            badge["status"] = "SUSPENDED"
            badge["scheduled_suspend_on"] = None
            bump(badge, now)
            # identify tenant for affected
            member = db.members.get(badge["member_id"])
            if member:
                affected_tenants.add(member["tenant_id"])
