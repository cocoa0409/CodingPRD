"""Domain helpers: serializers, derived fields, calculations, shared logic."""
from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP

import db
from db import fmt_dt, fmt_date, now, parse_date, parse_dt, touch
from errors import raise_error

# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------
BASE_RATE_BY_TIER = {"CORE": 12000, "REMOTE": 6000}
SHIFT_MULTIPLIER = {"DAY": Decimal("1.0"), "NIGHT": Decimal("0.75"),
                    "ROTATING": Decimal("0.85"), "SPLIT": Decimal("1.1")}
SUBSIDY_PCT = {"DAY": Decimal("0.10"), "NIGHT": Decimal("0.40"),
               "ROTATING": Decimal("0.25"), "SPLIT": Decimal("0.15")}
SHIFT_PRIORITY = {"NIGHT": 3, "ROTATING": 2, "SPLIT": 1, "DAY": 0}

BASE_FINE_BY_CODE = {
    "EXPIRED_PERMIT": 5000,
    "WRONG_LOT": 3500,
    "NO_PERMIT_DISPLAY": 2500,
    "BLOCKED_LANE": 7500,
    "PARKED_AFTER_REVOCATION": 10000,
}
ESCALATION_STEP = Decimal("0.5")
VIOLATION_WINDOW_DAYS = 365

TOW_BASE_CENTS = 15000
STORAGE_DAILY_CENTS = 2500

NON_TERMINAL_PERMIT_STATUSES = {"REQUESTED", "WAITLISTED", "OFFERED", "ACTIVE", "SUSPENDED"}
TERMINAL_PERMIT_STATUSES = {"REVOKED", "DECLINED", "EXPIRED", "CANCELLED"}


def round_half_up(value):
    """Round a Decimal (or numeric) half-up to integer."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round half-up to two decimals; returns a float suitable for JSON."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise_error("ERR_NOT_FOUND", "Resource not found")
    return rec


def employee_program(employee):
    return db.programs.get(employee["program_id"])


def permit_employee(permit):
    return db.employees.get(permit["employee_id"])


def permit_lot(permit):
    return db.lots.get(permit["lot_id"])


def permit_program(permit):
    lot = permit_lot(permit)
    return db.programs.get(lot["program_id"]) if lot else None


def program_of_lot(lot):
    return db.programs.get(lot["program_id"])


def route_program(route):
    lot = db.lots.get(route["lot_id"])
    return db.programs.get(lot["program_id"]) if lot else None


def cycle_program(cycle):
    return db.programs.get(cycle["program_id"])


def open_cycle_for_program(program_id):
    for c in db.billing_cycles.values():
        if c["program_id"] == program_id and c["status"] == "OPEN":
            return c
    return None


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def employee_balance_due(employee_id):
    total = 0
    for e in db.charge_entries.values():
        if e["employee_id"] == employee_id and e["status"] == "DEDUCTION_FAILED":
            total += e["amount_cents"]
    return max(0, total)


def employee_standing(employee_id):
    return "BILLING_HOLD" if employee_balance_due(employee_id) > 0 else "GOOD_STANDING"


def lot_occupied(lot_id):
    return sum(1 for p in db.permits.values()
               if p["lot_id"] == lot_id and p["status"] == "ACTIVE")


def lot_reserved(lot_id):
    current = now()
    return sum(1 for p in db.permits.values()
               if p["lot_id"] == lot_id and p["status"] == "OFFERED"
               and p.get("offer_expires_at") and parse_dt(p["offer_expires_at"]) >= current)


def lot_available(lot):
    return lot["capacity"] - lot_occupied(lot["id"]) - lot_reserved(lot["id"])


def lot_bookable(lot):
    return lot["status"] in ("ACTIVE", "ACTIVATED")


def cycle_total(cycle_id):
    total = 0
    for e in db.charge_entries.values():
        if e["cycle_id"] == cycle_id and e["status"] != "REVERSED":
            total += e["amount_cents"]
    return total


def unpaid_violation_count(permit_id):
    return sum(1 for v in db.violations.values()
               if v["permit_id"] == permit_id and v["payment_status"] == "UNPAID")


# ---------------------------------------------------------------------------
# Fee calculations
# ---------------------------------------------------------------------------

def gross_fee_for_permit(permit):
    lot = db.lots.get(permit["lot_id"])
    base = BASE_RATE_BY_TIER[lot["tier"]]
    mult = SHIFT_MULTIPLIER[permit["queue_shift_pattern"]]
    return round_half_up(Decimal(base) * mult)


def subsidy_full(gross, shift_pattern, cap):
    pct_amount = round_half_up(SUBSIDY_PCT[shift_pattern] * Decimal(gross))
    return min(pct_amount, cap, gross)


def prorate(net_full, span_start, span_end, period_start, period_end, mode, is_truncation):
    """Prorate net_full over [span_start, span_end] within closed period.
    span_start/span_end, period_start/period_end are datetime.date objects.
    is_truncation: True when span ends on a suspension/revocation date.
    Returns integer cents.
    """
    days_in_period = (period_end - period_start).days + 1
    # active days = span intersected with period, both inclusive
    lo = max(span_start, period_start)
    hi = min(span_end, period_end)
    active_days = max(0, (hi - lo).days + 1)
    if mode == "CALENDAR_DAY":
        return round_half_up(Decimal(net_full) * Decimal(active_days) / Decimal(days_in_period))
    # HALF_MONTH
    if is_truncation:
        end_index = (span_end - period_start).days + 1
        if end_index > 15:
            return int(net_full)
        return round_half_up(Decimal(net_full) / Decimal(2))
    else:
        day_index = (span_start - period_start).days + 1
        if day_index <= 15:
            return int(net_full)
        return round_half_up(Decimal(net_full) / Decimal(2))


def prorate_subsidy(subsidy_full_amount, span_start, span_end, period_start, period_end, mode, is_truncation):
    """Same shape as proration for the subsidy component."""
    if mode == "CALENDAR_DAY":
        days_in_period = (period_end - period_start).days + 1
        lo = max(span_start, period_start)
        hi = min(span_end, period_end)
        active_days = max(0, (hi - lo).days + 1)
        return round_half_up(Decimal(subsidy_full_amount) * Decimal(active_days) / Decimal(days_in_period))
    # HALF_MONTH
    if is_truncation:
        end_index = (span_end - period_start).days + 1
        if end_index > 15:
            return int(subsidy_full_amount)
        return round_half_up(Decimal(subsidy_full_amount) / Decimal(2))
    else:
        day_index = (span_start - period_start).days + 1
        if day_index <= 15:
            return int(subsidy_full_amount)
        return round_half_up(Decimal(subsidy_full_amount) / Decimal(2))


def post_permit_fee(permit, cycle, span_start_d, span_end_d, is_truncation):
    """Post a PENDING PERMIT_FEE entry into cycle for the permit over the span.
    span dates are datetime.date. Returns the created entry."""
    program = db.programs.get(cycle["program_id"])
    gross = permit["monthly_fee_cents"]
    if gross is None:
        gross = gross_fee_for_permit(permit)
    cap = cycle["subsidy_per_capita_cap_cents"]
    sub_full = subsidy_full(gross, permit["queue_shift_pattern"], cap)
    net_full = gross - sub_full
    period_start = parse_date(cycle["period_start"])
    period_end = parse_date(cycle["period_end"])
    amount = prorate(net_full, span_start_d, span_end_d, period_start, period_end,
                     program["proration_mode"], is_truncation)
    subsidy = prorate_subsidy(sub_full, span_start_d, span_end_d, period_start, period_end,
                              program["proration_mode"], is_truncation)
    entry = db.new_record({
        "cycle_id": cycle["id"],
        "employee_id": permit["employee_id"],
        "permit_id": permit["id"],
        "charge_type": "PERMIT_FEE",
        "amount_cents": amount,
        "subsidy_cents": subsidy,
        "span_start": fmt_date(span_start_d),
        "span_end": fmt_date(span_end_d),
        "status": "PENDING",
        "description": None,
    })
    db.charge_entries[entry["id"]] = entry
    touch(cycle)
    return entry


def truncate_pending_fee(permit, event_date_d):
    """Reverse the permit's PENDING PERMIT_FEE in the OPEN cycle whose span contains
    event_date_d, and repost truncated span [span_start, event_date]. Skipped when
    no OPEN cycle exists or no containing entry."""
    program = permit_program(permit)
    if program is None:
        return
    cycle = open_cycle_for_program(program["id"])
    if cycle is None:
        return
    for e in list(db.charge_entries.values()):
        if (e["permit_id"] == permit["id"] and e["charge_type"] == "PERMIT_FEE"
                and e["status"] == "PENDING" and e.get("span_start") and e.get("span_end")):
            s = parse_date(e["span_start"])
            en = parse_date(e["span_end"])
            if s <= event_date_d <= en:
                e["status"] = "REVERSED"
                touch(e)
                post_permit_fee(permit, cycle, s, event_date_d, is_truncation=True)
            # spans already ended before the suspension date are untouched


def suspend_permit(permit, reason):
    """ACTIVE -> SUSPENDED with bookkeeping (fee truncation)."""
    permit["status"] = "SUSPENDED"
    permit["suspended_at"] = fmt_dt(now())
    permit["suspension_reason"] = reason
    touch(permit)
    truncate_pending_fee(permit, now().date())


def reinstate_permit(permit):
    """SUSPENDED -> ACTIVE; clears reason; posts fresh fee span [reinstate date, period_end]."""
    permit["status"] = "ACTIVE"
    permit["suspension_reason"] = None
    touch(permit)
    program = permit_program(permit)
    cycle = open_cycle_for_program(program["id"]) if program else None
    if cycle is not None:
        period_end = parse_date(cycle["period_end"])
        post_permit_fee(permit, cycle, now().date(), period_end, is_truncation=False)


def revoke_permit(permit, run_promotion=True):
    """Revoke from ACTIVE / SUSPENDED / OFFERED / WAITLISTED with side effects."""
    from_status = permit["status"]
    if from_status == "ACTIVE":
        truncate_pending_fee(permit, now().date())
    permit["status"] = "REVOKED"
    touch(permit)
    if run_promotion and from_status in ("ACTIVE", "SUSPENDED", "OFFERED"):
        promotion_pass(permit["lot_id"])


# ---------------------------------------------------------------------------
# Waitlist promotion
# ---------------------------------------------------------------------------

def promotion_pass(lot_id):
    """Promote WAITLISTED permits of one lot while slots are available.
    Requires lot bookable and program posture PROGRAM_NORMAL."""
    lot = db.lots.get(lot_id)
    if lot is None or not lot_bookable(lot):
        return
    program = db.programs.get(lot["program_id"])
    if program is None or program["posture"] != "PROGRAM_NORMAL":
        return
    while lot_available(lot) >= 1:
        candidates = [p for p in db.permits.values()
                      if p["lot_id"] == lot_id and p["status"] == "WAITLISTED"]
        if not candidates:
            return
        def rank_key(p):
            emp = db.employees.get(p["employee_id"])
            badge = emp["badge_number"] if emp else ""
            return (-SHIFT_PRIORITY.get(p["queue_shift_pattern"], 0), p["created_at"], badge)
        candidates.sort(key=rank_key)
        top = candidates[0]
        top["status"] = "OFFERED"
        top["offered_at"] = fmt_dt(now())
        top["offer_expires_at"] = fmt_dt(now() + timedelta(hours=program["waitlist_offer_ttl_hours"]))
        touch(top)


def promotion_pass_program(program):
    """Run promotion passes over all bookable lots of a program, created_at ASC."""
    lots = [l for l in db.lots.values() if l["program_id"] == program["id"]]
    lots.sort(key=lambda l: l["created_at"])
    for lot in lots:
        if lot_bookable(lot):
            promotion_pass(lot["id"])


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def serialize_program(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "posture": p["posture"],
        "proration_mode": p["proration_mode"],
        "monthly_subsidy_pool_cents": p["monthly_subsidy_pool_cents"],
        "waitlist_offer_ttl_hours": p["waitlist_offer_ttl_hours"],
        "violation_suspension_threshold": p["violation_suspension_threshold"],
        "tow_hold_hours": p["tow_hold_hours"],
        "ops_run_index": p["ops_run_index"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_employee(e):
    balance = employee_balance_due(e["id"])
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "badge_number": e["badge_number"],
        "full_name": e["full_name"],
        "employer_code": e["employer_code"],
        "shift_pattern": e["shift_pattern"],
        "hire_date": e["hire_date"],
        "employment_status": e["employment_status"],
        "terminated_at": e["terminated_at"],
        "balance_due_cents": balance,
        "standing": "BILLING_HOLD" if balance > 0 else "GOOD_STANDING",
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_lot(l):
    return {
        "id": l["id"],
        "program_id": l["program_id"],
        "code": l["code"],
        "tier": l["tier"],
        "capacity": l["capacity"],
        "monthly_maintenance_cents": l["monthly_maintenance_cents"],
        "status": l["status"],
        "occupied_slots": lot_occupied(l["id"]),
        "reserved_slots": lot_reserved(l["id"]),
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_permit(p):
    return {
        "id": p["id"],
        "employee_id": p["employee_id"],
        "lot_id": p["lot_id"],
        "vehicle_plate": p["vehicle_plate"],
        "queue_shift_pattern": p["queue_shift_pattern"],
        "status": p["status"],
        "offered_at": p["offered_at"],
        "offer_expires_at": p["offer_expires_at"],
        "activated_at": p["activated_at"],
        "suspended_at": p["suspended_at"],
        "suspension_reason": p["suspension_reason"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "term_end": p["term_end"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_renewal(r):
    return {
        "id": r["id"],
        "permit_id": r["permit_id"],
        "status": r["status"],
        "requested_at": r["requested_at"],
        "decided_by": r["decided_by"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_route(r):
    return {
        "id": r["id"],
        "lot_id": r["lot_id"],
        "code": r["code"],
        "headway_target_minutes": r["headway_target_minutes"],
        "operating_cost_per_trip_cents": r["operating_cost_per_trip_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_trip(t):
    return {
        "id": t["id"],
        "route_id": t["route_id"],
        "scheduled_departure_at": t["scheduled_departure_at"],
        "actual_departure_at": t["actual_departure_at"],
        "status": t["status"],
        "boarded_count": t["boarded_count"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_notice(n):
    return {
        "id": n["id"],
        "lot_id": n["lot_id"],
        "route_id": n["route_id"],
        "notice_type": n["notice_type"],
        "headline": n["headline"],
        "effective_from": n["effective_from"],
        "effective_to": n["effective_to"],
        "new_headway_minutes": n["new_headway_minutes"],
        "status": n["status"],
        "published_at": n["published_at"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def serialize_violation(v):
    return {
        "id": v["id"],
        "permit_id": v["permit_id"],
        "violation_code": v["violation_code"],
        "issued_by": v["issued_by"],
        "issued_at": v["issued_at"],
        "fine_cents": v["fine_cents"],
        "payment_status": v["payment_status"],
        "appeal_status": v["appeal_status"],
        "charge_entry_id": v["charge_entry_id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_tow(t):
    return {
        "id": t["id"],
        "permit_id": t["permit_id"],
        "violation_id": t["violation_id"],
        "authorized_by": t["authorized_by"],
        "status": t["status"],
        "towed_at": t["towed_at"],
        "released_at": t["released_at"],
        "impound_fee_cents": t["impound_fee_cents"],
        "charge_entry_id": t["charge_entry_id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_cycle(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "period_start": c["period_start"],
        "period_end": c["period_end"],
        "status": c["status"],
        "subsidy_per_capita_cap_cents": c["subsidy_per_capita_cap_cents"],
        "total_charges_cents": cycle_total(c["id"]),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_entry(e):
    return {
        "id": e["id"],
        "cycle_id": e["cycle_id"],
        "employee_id": e["employee_id"],
        "permit_id": e["permit_id"],
        "charge_type": e["charge_type"],
        "amount_cents": e["amount_cents"],
        "subsidy_cents": e["subsidy_cents"],
        "span_start": e["span_start"],
        "span_end": e["span_end"],
        "status": e["status"],
        "description": e["description"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_peak_window(w):
    return {
        "id": w["id"],
        "lot_id": w["lot_id"],
        "starts_at": w["starts_at"],
        "ends_at": w["ends_at"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }
