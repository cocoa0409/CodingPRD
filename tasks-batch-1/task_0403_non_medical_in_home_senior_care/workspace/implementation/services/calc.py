"""Calculation rules (PRD §3.6, §3.7, §3.9, §3.11; SCAFFOLD §1.3)."""
import math
from decimal import Decimal

import db
from money import D, round_half_up, round_int_half_up


# ----------------------------------------------------------------------------
# billable_minutes (PRD §3.6)
# ----------------------------------------------------------------------------
def compute_billable_minutes(clock_in_at, clock_out_at, evv_rounding_minutes):
    """raw whole minutes (floor) rounded to nearest evv_rounding_minutes (round-half-up)."""
    delta_seconds = (clock_out_at - clock_in_at).total_seconds()
    raw_minutes = math.floor(delta_seconds / 60.0)
    if raw_minutes < 0:
        raw_minutes = 0
    quotient = round_int_half_up(D(raw_minutes) / D(evv_rounding_minutes))
    return quotient * int(evv_rounding_minutes)


# ----------------------------------------------------------------------------
# Provisional visit charge (PRD §3.6, forward variant)
# ----------------------------------------------------------------------------
def compute_visit_charge(billing_mode, billable_minutes, agency):
    if billing_mode == "HOURLY":
        amount = (D(billable_minutes) / D(60)) * D(agency["base_hourly_rate"])
        return round_half_up(amount)
    # LIVE_IN
    started_days = math.ceil(billable_minutes / 1440) if billable_minutes > 0 else 0
    amount = D(started_days) * D(agency["live_in_day_rate"])
    return round_half_up(amount)


# ----------------------------------------------------------------------------
# Continuity score (PRD §3.7)
# ----------------------------------------------------------------------------
def primary_caregiver_id(client_id):
    """The caregiver of the client's ACTIVE primary match; else the caregiver of
    the earliest-created ACTIVE match (created_at ASC, tie-break by _seq); else None."""
    active = [
        m for m in db.matches.values()
        if m["client_id"] == client_id and m["match_status"] == "ACTIVE"
    ]
    if not active:
        return None
    primary = [m for m in active if m.get("is_primary")]
    if primary:
        primary.sort(key=lambda m: (m["created_at"], m.get("_seq", 0)))
        return primary[0]["caregiver_id"]
    active.sort(key=lambda m: (m["created_at"], m.get("_seq", 0)))
    return active[0]["caregiver_id"]


def recompute_continuity_score(client):
    """Recompute and store the client's continuity_score. Bumps version/updated_at."""
    client_id = client["id"]
    client_visits = [v for v in db.visits.values() if v["client_id"] == client_id]
    terminal = [v for v in client_visits if v["status"] in ("COMPLETED", "CANCELLED", "MISSED")]
    completed = [v for v in client_visits if v["status"] == "COMPLETED"]

    if len(terminal) == 0:
        score = 0
    else:
        prim = primary_caregiver_id(client_id)
        if len(completed) == 0:
            continuity_ratio = D(0)
        else:
            served_by_primary = sum(1 for v in completed if v["caregiver_id"] == prim)
            continuity_ratio = D(served_by_primary) / D(len(completed))
        reliability = D(len(completed)) / D(len(terminal))
        raw = D("0.6") * continuity_ratio + D("0.4") * reliability
        score = round_half_up(raw)

    new_val = score
    if client.get("continuity_score") != new_val:
        client["continuity_score"] = new_val
        db.touch(client)
    return new_val


# ----------------------------------------------------------------------------
# Final / chronological invoice labor (PRD §3.9)
# ----------------------------------------------------------------------------
def compute_invoice_lines(invoice, agency):
    """Build lines + labor_total + mileage_total for finalize (PRD §3.9)."""
    period_start = invoice["_period_start_dt"]
    period_end = invoice["_period_end_dt"]
    caregiver_id = invoice["caregiver_id"]
    client_id = invoice["client_id"]

    completed = []
    for v in db.visits.values():
        if v["status"] != "COMPLETED":
            continue
        if v["caregiver_id"] != caregiver_id or v["client_id"] != client_id:
            continue
        ci = v.get("_clock_in_dt")
        if ci is None:
            continue
        if period_start <= ci < period_end:
            completed.append(v)

    # Order by clock_in_at ASC, tie-break by created_at ASC (then _seq for stability).
    completed.sort(key=lambda v: (v["_clock_in_dt"], v["created_at"], v.get("_seq", 0)))

    base_rate = D(agency["base_hourly_rate"])
    ot_mult = D(agency["overtime_multiplier"])
    ot_threshold = D(agency["overtime_threshold_hours"])
    live_in_rate = D(agency["live_in_day_rate"])

    lines = []
    running_hours = D(0)

    for v in completed:
        if v["billing_mode"] == "LIVE_IN":
            bm = v["billable_minutes"]
            started_days = math.ceil(bm / 1440) if bm > 0 else 0
            amount = round_half_up(D(started_days) * live_in_rate)
            lines.append({
                "line_type": "LIVE_IN",
                "source_visit_id": v["id"],
                "hours": 0,
                "rate": agency["live_in_day_rate"],
                "amount": amount,
            })
            continue

        h = D(v["billable_minutes"]) / D(60)
        reg_remaining = ot_threshold - running_hours
        if reg_remaining < 0:
            reg_remaining = D(0)
        reg_h = h if h < reg_remaining else reg_remaining
        if reg_h > h:
            reg_h = h
        ot_h = h - reg_h

        if reg_h > 0:
            lines.append({
                "line_type": "REGULAR",
                "source_visit_id": v["id"],
                "hours": _num(reg_h),
                "rate": agency["base_hourly_rate"],
                "amount": round_half_up(reg_h * base_rate),
            })
        if ot_h > 0:
            ot_rate = base_rate * ot_mult
            lines.append({
                "line_type": "OVERTIME",
                "source_visit_id": v["id"],
                "hours": _num(ot_h),
                "rate": _num(ot_rate),
                "amount": round_half_up(ot_h * ot_rate),
            })
        running_hours += h

    labor_total = round_half_up(sum(D(l["amount"]) for l in lines)) if lines else 0.0

    # Mileage: RECORDED entries whose visit is a COMPLETED visit in window.
    completed_ids = {v["id"] for v in completed}
    mileage_rows = [
        me for me in db.mileage_entries.values()
        if me["status"] == "RECORDED" and me["visit_id"] in completed_ids
    ]
    mileage_rows.sort(key=lambda me: me.get("_seq", 0))
    mileage_total = D(0)
    for me in mileage_rows:
        mileage_total += D(me["line_charge"])
        lines.append({
            "line_type": "MILEAGE",
            "source_visit_id": me["visit_id"],
            "hours": 0,
            "rate": agency["mileage_rate"],
            "amount": me["line_charge"],
        })
    mileage_total = round_half_up(mileage_total) if mileage_rows else 0.0

    return lines, labor_total, mileage_total


def _num(dec):
    """Return an int if the Decimal is integral, else a float."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


# ----------------------------------------------------------------------------
# Claim covered amount (PRD §3.11)
# ----------------------------------------------------------------------------
def compute_covered_amount(invoice_total, covered_pct, daily_benefit_max, covered_days):
    pct_covered = round_half_up(D(invoice_total) * D(covered_pct))
    benefit_cap = D(daily_benefit_max) * D(covered_days)
    covered = min(D(pct_covered), benefit_cap)
    return round_half_up(covered)
