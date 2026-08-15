"""Shared helpers: record construction, serializers, clock-driven sweeps,
owner-standing derivation, and entitlement ledger movements."""
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import CLOCK, format_iso, parse_iso

FULL_SHARE_HOURS = 800
PEAK_SURCHARGE_BP = 1500
MARKET_VALUE_BP = 8200
EARLY_EXIT_BP = 2000
MIN_HOLD_YEARS = 3


# ---------------------------------------------------------------------------
# Record construction helpers
# ---------------------------------------------------------------------------

def new_common():
    """Fresh system-managed fields for common_fields entities."""
    ts = CLOCK.now_iso()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(rec):
    """Refresh updated_at and bump version on a common_fields entity."""
    rec["updated_at"] = CLOCK.now_iso()
    rec["version"] += 1


def hours_str(value):
    """Render an hour quantity quantized to exactly two decimal places (PRD 2.6).

    Hour quantities are numeric: the value is rounded half-up to two decimal
    places and returned as a JSON number."""
    return float(
        Decimal(str(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def program_view(p):
    return {
        "id": p["id"],
        "program_code": p["program_code"],
        "currency": p["currency"],
        "program_posture": p["program_posture"],
        "contract_year_start_month": p["contract_year_start_month"],
        "peak_day_calendar": list(p["peak_day_calendar"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def class_view(c):
    return {
        "id": c["id"],
        "class_code": c["class_code"],
        "program_id": c["program_id"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "interchange_upgrade_multiplier_bp": c["interchange_upgrade_multiplier_bp"],
        "monthly_fee_base_cents": c["monthly_fee_base_cents"],
        "seats": c["seats"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def aircraft_view(a):
    return {
        "id": a["id"],
        "tail_number": a["tail_number"],
        "program_id": a["program_id"],
        "class_id": a["class_id"],
        "aircraft_status": a["aircraft_status"],
        "total_hours_flown": hours_str(a["total_hours_flown"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def owner_view(o):
    return {
        "id": o["id"],
        "legal_name": o["legal_name"],
        "program_id": o["program_id"],
        "owner_standing": o["owner_standing"],
        "deposit_balance_cents": o["deposit_balance_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def share_view(s):
    return {
        "id": s["id"],
        "owner_id": s["owner_id"],
        "class_id": s["class_id"],
        "fraction_numerator": s["fraction_numerator"],
        "fraction_denominator": s["fraction_denominator"],
        "annual_entitlement_hours": (
            None if s["annual_entitlement_hours"] is None
            else hours_str(s["annual_entitlement_hours"])
        ),
        "hours_remaining_cy": (
            None if s["hours_remaining_cy"] is None
            else hours_str(s["hours_remaining_cy"])
        ),
        "contract_year_index": s["contract_year_index"],
        "share_status": s["share_status"],
        "purchase_price_cents": s["purchase_price_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def booking_view(b):
    return {
        "id": b["id"],
        "share_id": b["share_id"],
        "requested_class_id": b["requested_class_id"],
        "scheduled_departure_utc": b["scheduled_departure_utc"],
        "estimated_block_hours": hours_str(b["estimated_block_hours"]),
        "notice_tier": b["notice_tier"],
        "booking_status": b["booking_status"],
        "billing_status": b["billing_status"],
        "assigned_aircraft_id": b["assigned_aircraft_id"],
        "interchange_direction": b["interchange_direction"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def flight_leg_view(fl):
    return {
        "id": fl["id"],
        "booking_id": fl["booking_id"],
        "aircraft_id": fl["aircraft_id"],
        "actual_block_hours": hours_str(fl["actual_block_hours"]),
        "peak_day_flag": fl["peak_day_flag"],
        "completed_at": fl["completed_at"],
        "created_at": fl["created_at"],
    }


def invoice_view(inv):
    return {
        "id": inv["id"],
        "owner_id": inv["owner_id"],
        "billing_period": inv["billing_period"],
        "invoice_status": inv["invoice_status"],
        "management_fee_cents": inv["management_fee_cents"],
        "occupied_hours_fee_cents": inv["occupied_hours_fee_cents"],
        "total_due_cents": inv["total_due_cents"],
        "tax_adjustment_cents": inv["tax_adjustment_cents"],
        "issued_at": inv["issued_at"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def invoice_line_view(l):
    return {
        "id": l["id"],
        "invoice_id": l["invoice_id"],
        "line_kind": l["line_kind"],
        "booking_id": l["booking_id"],
        "share_id": l["share_id"],
        "quantity_hours": hours_str(l["quantity_hours"]),
        "amount_cents": l["amount_cents"],
        "created_at": l["created_at"],
    }


def listing_view(t):
    return {
        "id": t["id"],
        "share_id": t["share_id"],
        "asking_price_cents": t["asking_price_cents"],
        "listing_status": t["listing_status"],
        "buyer_owner_id": t["buyer_owner_id"],
        "program_repurchase_flag": t["program_repurchase_flag"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def maintenance_view(m):
    return {
        "id": m["id"],
        "aircraft_id": m["aircraft_id"],
        "window_start_utc": m["window_start_utc"],
        "window_end_utc": m["window_end_utc"],
        "event_status": m["event_status"],
        "cost_cents": m["cost_cents"],
        "unscheduled_flag": m["unscheduled_flag"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def schedule_view(d):
    return {
        "id": d["id"],
        "share_id": d["share_id"],
        "schedule_method": d["schedule_method"],
        "recovery_years": d["recovery_years"],
        "basis_cents": d["basis_cents"],
        "accumulated_depreciation_cents": d["accumulated_depreciation_cents"],
        "current_year_allowance_cents": d["current_year_allowance_cents"],
        "created_at": d["created_at"],
    }


def exit_view(x):
    return {
        "id": x["id"],
        "share_id": x["share_id"],
        "exit_status": x["exit_status"],
        "buyout_amount_cents": x["buyout_amount_cents"],
        "early_exit_penalty_cents": x["early_exit_penalty_cents"],
        "settlement_cents": x["settlement_cents"],
        "created_at": x["created_at"],
        "updated_at": x["updated_at"],
        "version": x["version"],
    }


# ---------------------------------------------------------------------------
# Owner standing
# ---------------------------------------------------------------------------

def has_past_due_invoice(owner_id):
    return any(
        inv["owner_id"] == owner_id and inv["invoice_status"] == "PAST_DUE"
        for inv in db.invoices.values()
    )


def recompute_owner_standing(owner):
    """After an invoice leaves PAST_DUE, restore DELINQUENT -> GOOD when clean."""
    if owner["owner_standing"] == "DELINQUENT" and not has_past_due_invoice(owner["id"]):
        owner["owner_standing"] = "GOOD"
        touch(owner)


# ---------------------------------------------------------------------------
# Clock-driven sweeps (PRD 2.4)
# ---------------------------------------------------------------------------

def _anniversaries_between(start, end, month):
    """Yield contract-year anniversary instants (day 1, 00:00Z of `month`)
    strictly after `start` and <= `end`."""
    out = []
    for year in range(start.year - 1, end.year + 2):
        try:
            a = datetime(year, month, 1, tzinfo=timezone.utc)
        except ValueError:
            continue
        if start < a <= end:
            out.append(a)
    out.sort()
    return out


def clock_advance():
    """Run every due system transition after the clock moves to CLOCK.now()."""
    now = CLOCK.now()

    # 1. Booking expiry: REQUESTED whose departure has been reached -> EXPIRED
    for b in db.bookings.values():
        if b["booking_status"] == "REQUESTED":
            if parse_iso(b["scheduled_departure_utc"]) <= now:
                b["booking_status"] = "EXPIRED"
                touch(b)

    # 2. Listing expiry: LISTED for 180 days -> EXPIRED (share back to ACTIVE)
    for t in db.transfer_listings.values():
        if t["listing_status"] == "LISTED":
            created = parse_iso(t["created_at"])
            if (now - created).total_seconds() >= 180 * 86400:
                t["listing_status"] = "EXPIRED"
                touch(t)
                share = db.shares.get(t["share_id"])
                if share and share["share_status"] == "LISTED":
                    share["share_status"] = "ACTIVE"
                    touch(share)

    # 3. Invoice aging: ISSUED past issued_at + 30 days -> PAST_DUE
    for inv in db.invoices.values():
        if inv["invoice_status"] == "ISSUED" and inv["issued_at"]:
            issued = parse_iso(inv["issued_at"])
            if (now - issued).total_seconds() > 30 * 86400:
                inv["invoice_status"] = "PAST_DUE"
                touch(inv)
                owner = db.owners.get(inv["owner_id"])
                if owner and owner["owner_standing"] == "GOOD":
                    owner["owner_standing"] = "DELINQUENT"
                    touch(owner)

    # 4. Contract-year rollover (per program, in chronological order)
    prev = getattr(clock_advance, "_prev", parse_iso("2026-08-01T00:00:00Z"))
    for p in db.programs.values():
        month = p["contract_year_start_month"]
        for _ in _anniversaries_between(prev, now, month):
            for s in db.shares.values():
                cls = db.aircraft_classes.get(s["class_id"])
                if not cls or cls["program_id"] != p["id"]:
                    continue
                if s["share_status"] == "ACTIVE":
                    s["contract_year_index"] += 1
                    s["hours_remaining_cy"] = s["annual_entitlement_hours"]
                    touch(s)
    clock_advance._prev = now
