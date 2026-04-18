"""Deferred-action sweep for time-based transitions."""
from datetime import timedelta
from decimal import Decimal
import math

from clock import get_now, parse_iso, format_iso
from common import stamp_update
from db import db
from services.bill import (
    get_or_create_draft_bill,
    add_bill_line,
    recompute_bill_totals,
    update_overdue_late_fee,
)
from services.pricing import final_fee
from services.tenant import recompute_tenant
from services.money import round_half_up_to_int


OVERSTAY_RATE_CENTS_PER_30MIN = 500


def run_sweep():
    now = get_now()
    affected_tenants = set()
    count = 0

    # 1. Reservations: CONFIRMED past end_at → NO_SHOW (if never checked in) else COMPLETED
    #    Also handle IN_USE past end_at → COMPLETED via sweep (actual_end_at := end_at)
    for r in list(db.reservations.values()):
        if r["status"] == "CONFIRMED":
            end_at = parse_iso(r["end_at"])
            if now >= end_at:
                # Never checked in — NO_SHOW
                r["status"] = "NO_SHOW"
                r["final_fee_cents"] = final_fee(r, "NO_SHOW")
                stamp_update(r)
                # Consolidate to DRAFT bill
                bill = get_or_create_draft_bill(r["tenant_id"])
                r["bill_id"] = bill["id"]
                line_kind = _reservation_line_kind(r)
                add_bill_line(bill, line_kind, r["id"], r["final_fee_cents"])
                recompute_bill_totals(bill)
                affected_tenants.add(r["tenant_id"])
                count += 1
        elif r["status"] == "IN_USE":
            end_at = parse_iso(r["end_at"])
            if now >= end_at:
                r["actual_end_at"] = r["end_at"]  # sweep: use end_at
                r["status"] = "COMPLETED"
                r["final_fee_cents"] = final_fee(r, "COMPLETED")
                stamp_update(r)
                bill = get_or_create_draft_bill(r["tenant_id"])
                r["bill_id"] = bill["id"]
                line_kind = _reservation_line_kind(r)
                add_bill_line(bill, line_kind, r["id"], r["final_fee_cents"])
                recompute_bill_totals(bill)
                affected_tenants.add(r["tenant_id"])
                count += 1

    # 2. CHECKED_IN visitors past expected_departure_at + 6h → CHECKED_OUT
    for v in list(db.visitors.values()):
        if v["status"] == "CHECKED_IN":
            exp_dep = parse_iso(v["expected_departure_at"])
            cutoff = exp_dep + timedelta(hours=6)
            if now >= cutoff:
                # actual_departure_at := expected_departure_at + 6h on sweep
                v["actual_departure_at"] = format_iso(cutoff)
                v["status"] = "CHECKED_OUT"
                fee = _visitor_overstay_fee(v)
                v["overstay_fee_cents"] = fee
                if fee > 0:
                    bill = get_or_create_draft_bill(v["tenant_id"])
                    v["bill_id"] = bill["id"]
                    add_bill_line(bill, "VISITOR_OVERSTAY", v["id"], fee)
                    recompute_bill_totals(bill)
                    affected_tenants.add(v["tenant_id"])
                count += 1

    # 3. REGISTERED visitors past expected_departure_at → NO_SHOW
    for v in list(db.visitors.values()):
        if v["status"] == "REGISTERED":
            exp_dep = parse_iso(v["expected_departure_at"])
            if now >= exp_dep:
                v["status"] = "NO_SHOW"
                count += 1

    # 4. ISSUED bills past due_at → OVERDUE (compute late_fee)
    for b in list(db.bills.values()):
        if b["status"] == "ISSUED":
            due_at = parse_iso(b["due_at"])
            if now >= due_at:
                b["status"] = "OVERDUE"
                update_overdue_late_fee(b, now)
                affected_tenants.add(b["tenant_id"])
                count += 1

    # 5. OVERDUE bills: recompute late fee weekly
    for b in list(db.bills.values()):
        if b["status"] == "OVERDUE":
            update_overdue_late_fee(b, now)
            affected_tenants.add(b["tenant_id"])

    # 6. Access badge suspend on lease termination_effective_date (if reached)
    for lease in list(db.leases.values()):
        if lease["status"] == "TERMINATED" and lease.get("termination_effective_date"):
            eff_date_str = lease["termination_effective_date"]
            eff_date = parse_iso(eff_date_str + "T00:00:00Z") if "T" not in eff_date_str else parse_iso(eff_date_str)
            if now.date() >= eff_date.date():
                # suspend all ACTIVE badges of members of this tenant
                tenant_members = {m["id"] for m in db.members.values() if m["tenant_id"] == lease["tenant_id"]}
                for badge in db.badges.values():
                    if badge["member_id"] in tenant_members and badge["status"] == "ACTIVE":
                        badge["status"] = "SUSPENDED"
                        stamp_update(badge)
                        count += 1

    # 7. Recompute tenant outstanding/access_posture for affected tenants
    for tid in affected_tenants:
        recompute_tenant(tid)

    return count


def _reservation_line_kind(reservation):
    resource = db.resources.get(reservation["resource_id"])
    if not resource:
        return "WORKSTATION_FEE"
    kind = resource["kind"]
    if kind == "WORKSTATION":
        return "WORKSTATION_FEE"
    if kind == "MEETING_ROOM":
        return "MEETING_ROOM_FEE"
    if kind == "EVENT_AREA":
        return "EVENT_AREA_FEE"
    return "WORKSTATION_FEE"


def _visitor_overstay_fee(visitor):
    exp = parse_iso(visitor["expected_departure_at"])
    act = parse_iso(visitor["actual_departure_at"])
    overstay_seconds = max(0, (act - exp).total_seconds())
    overstay_minutes = overstay_seconds / 60
    if overstay_minutes <= 0:
        return 0
    units = math.ceil(overstay_minutes / 30)
    return units * OVERSTAY_RATE_CENTS_PER_30MIN
