"""Entity serialization with computed-field reconciliation (PRD §2.4, §3.1).

Audit-tracked entities expose id, created_at, updated_at, version.
Write-once records (MembershipPlan, ConsentRecord, Payment, MaintenanceLog)
expose only id and created_at — never updated_at or version.

Computed fields (is_minor, completed_uv_session_count, account_credit_cents,
sessions_since_service, stock_on_hand, units_sold, end_at, allowed_seconds,
ledger totals) are stored on the record and serialized as-is, except those
explicitly recomputed-on-read (is_minor) which we recompute here against the
logical clock.
"""
from clock import clock
from timeutil import to_iso

YEAR_SECONDS = None  # not used; minor classification uses calendar-aware age


def _is_minor(member):
    """True when (clock_now - date_of_birth) < 18 years (PRD §3.1)."""
    dob = member["date_of_birth"]
    now = clock.now()
    # Calendar-accurate age in whole years.
    years = now.year - dob.year - ((now.month, now.day, now.hour, now.minute, now.second, now.microsecond)
                                   < (dob.month, dob.day, dob.hour, dob.minute, dob.second, dob.microsecond))
    return years < 18


def member_out(member):
    return {
        "id": member["id"],
        "created_at": to_iso(member["created_at"]),
        "updated_at": to_iso(member["updated_at"]),
        "version": member["version"],
        "full_name": member["full_name"],
        "date_of_birth": to_iso(member["date_of_birth"]),
        "skin_type": member["skin_type"],
        "plan_id": member["plan_id"],
        "is_minor": _is_minor(member),
        "completed_uv_session_count": member["completed_uv_session_count"],
        "account_credit_cents": member["account_credit_cents"],
        "status": member["status"],
        "billing_status": member["billing_status"],
        "cycle_anchor_at": to_iso(member["cycle_anchor_at"]),
        "frozen_at": to_iso(member["frozen_at"]),
    }


def plan_out(plan):
    return {
        "id": plan["id"],
        "created_at": to_iso(plan["created_at"]),
        "tier_code": plan["tier_code"],
        "monthly_fee_cents": plan["monthly_fee_cents"],
        "retail_discount_pct": plan["retail_discount_pct"],
        "weekly_uv_session_cap": plan["weekly_uv_session_cap"],
        "includes_spray": plan["includes_spray"],
    }


def equipment_out(eq):
    return {
        "id": eq["id"],
        "created_at": to_iso(eq["created_at"]),
        "updated_at": to_iso(eq["updated_at"]),
        "version": eq["version"],
        "name": eq["name"],
        "kind": eq["kind"],
        "max_exposure_seconds": eq["max_exposure_seconds"],
        "turnaround_seconds": eq["turnaround_seconds"],
        "status": eq["status"],
        "sessions_since_service": eq["sessions_since_service"],
    }


def spray_room_out(room):
    return {
        "id": room["id"],
        "created_at": to_iso(room["created_at"]),
        "updated_at": to_iso(room["updated_at"]),
        "version": room["version"],
        "name": room["name"],
        "ventilation_buffer_seconds": room["ventilation_buffer_seconds"],
        "status": room["status"],
    }


def consent_out(c):
    return {
        "id": c["id"],
        "created_at": to_iso(c["created_at"]),
        "member_id": c["member_id"],
        "guardian_name": c["guardian_name"],
        "expires_at": to_iso(c["expires_at"]),
    }


def session_out(s):
    return {
        "id": s["id"],
        "created_at": to_iso(s["created_at"]),
        "updated_at": to_iso(s["updated_at"]),
        "version": s["version"],
        "member_id": s["member_id"],
        "kind": s["kind"],
        "booking_mode": s["booking_mode"],
        "equipment_id": s["equipment_id"],
        "spray_room_id": s["spray_room_id"],
        "start_at": to_iso(s["start_at"]),
        "requested_seconds": s["requested_seconds"],
        "end_at": to_iso(s["end_at"]),
        "allowed_seconds": s["allowed_seconds"],
        "status": s["status"],
    }


def product_out(p):
    return {
        "id": p["id"],
        "created_at": to_iso(p["created_at"]),
        "updated_at": to_iso(p["updated_at"]),
        "version": p["version"],
        "sku": p["sku"],
        "name": p["name"],
        "unit_price_cents": p["unit_price_cents"],
        "initial_stock": p["initial_stock"],
        "stock_on_hand": p["stock_on_hand"],
        "units_sold": p["units_sold"],
    }


def retail_order_out(o):
    return {
        "id": o["id"],
        "created_at": to_iso(o["created_at"]),
        "updated_at": to_iso(o["updated_at"]),
        "version": o["version"],
        "member_id": o["member_id"],
        "lines": [{"product_id": ln["product_id"], "quantity": ln["quantity"]} for ln in o["lines"]],
        "subtotal_cents": o["subtotal_cents"],
        "credit_applied_cents": o["credit_applied_cents"],
        "charged_cents": o["charged_cents"],
        "status": o["status"],
    }


def payment_out(p):
    return {
        "id": p["id"],
        "created_at": to_iso(p["created_at"]),
        "member_id": p["member_id"],
        "kind": p["kind"],
        "amount_cents": p["amount_cents"],
        "outcome": p["outcome"],
        "retail_order_id": p["retail_order_id"],
    }


def ledger_out(ledger):
    return {
        "id": ledger["id"],
        "created_at": to_iso(ledger["created_at"]),
        "updated_at": to_iso(ledger["updated_at"]),
        "version": ledger["version"],
        "singleton_key": ledger["singleton_key"],
        "deferred_revenue_cents": ledger["deferred_revenue_cents"],
        "collected_dues_cents": ledger["collected_dues_cents"],
        "collected_retail_cents": ledger["collected_retail_cents"],
    }


def maintenance_log_out(m):
    return {
        "id": m["id"],
        "created_at": to_iso(m["created_at"]),
        "equipment_id": m["equipment_id"],
        "reason": m["reason"],
        "sessions_at_service": m["sessions_at_service"],
    }
