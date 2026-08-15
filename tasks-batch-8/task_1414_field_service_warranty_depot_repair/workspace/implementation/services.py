"""Business logic: calculations, state-machine helpers, notifications."""
from datetime import date, timedelta

from db import store, new_id, now_wall_iso, clock_now, clock_iso, touch

# Calculation constants (pinned by PRD)
HANDLING_PCT = 5
TAX_RATE_PCT = 8
EXPEDITE_FEE_CENTS = 7500
LOYALTY_TIER1_CENTS = 50000
LOYALTY_TIER2_CENTS = 20000
RECENT_WINDOW_DAYS = 90
HISTORY_WINDOW_DAYS = 365
CURRENT_RMA_WEIGHT = 2
DAILY_LATE_FEE_CENTS = 2500
MONITORING_DAYS = 90
AUTO_CANCEL_DAYS = 30

RMA_TERMINAL = {"CLOSED", "SCRAPPED", "CANCELLED"}
SLA_TRACKED_STATUSES = {
    "RECEIVED", "TRIAGED", "DIAGNOSED", "AWAITING_QUOTE_APPROVAL",
    "QUOTE_DECLINED", "IN_REPAIR", "AWAITING_PARTS", "QA_HOLD",
    "READY_TO_SHIP", "REPLACEMENT_PENDING",
}
BAY_OCCUPYING_STATUSES = {"TRIAGED", "DIAGNOSED", "IN_REPAIR", "AWAITING_PARTS", "QA_HOLD", "READY_TO_SHIP"}
ESCALATION_DEDUP_STATES = {"OPEN", "ACKNOWLEDGED", "CONTAINMENT_ACTIVE", "MONITORING"}


def round_half_up(numerator, denominator=1):
    """Integer round-half-up of numerator/denominator (non-negative values)."""
    # (2*n + d) // (2*d) rounds half up for non-negative n
    return (2 * numerator + denominator) // (2 * denominator)


def floor_div(numerator, denominator):
    return numerator // denominator


def business_days(d1, d2):
    """Count of Mon-Fri dates strictly after d1 and on-or-before d2."""
    if d2 <= d1:
        return 0
    count = 0
    cur = d1 + timedelta(days=1)
    while cur <= d2:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


# ---------------------------------------------------------------- notifications

def notify(rma, event_type, message):
    customer = store.customers.get(rma["customer_id"])
    recipient = customer["email"] if customer else ""
    ev = {
        "id": new_id(),
        "created_at": now_wall_iso(),
        "rma_id": rma["id"],
        "event_type": event_type,
        "recipient": recipient,
        "message": message,
    }
    store.notification_events[ev["id"]] = ev
    return ev


# ----------------------------------------------------------------- entities

def get_model(rma):
    unit = store.units.get(rma["unit_id"])
    return store.product_models.get(unit["model_id"]) if unit else None


def get_unit(rma):
    return store.units.get(rma["unit_id"])


# ------------------------------------------------------------- warranty calc

def warranty_eligibility(unit, model, as_of_date):
    """Return (coverage_path, warranty_end_date_used_iso)."""
    if unit["channel"] == "RETAIL":
        purchase = date.fromisoformat(unit["purchase_date"])
        basis_end = purchase + timedelta(days=model["standard_warranty_days"])
        if unit.get("registration_date"):
            reg = date.fromisoformat(unit["registration_date"])
            reg_end = reg + timedelta(days=model["standard_warranty_days"] + model["registration_bonus_days"])
            if reg_end > basis_end:
                basis_end = reg_end
    else:  # ENTERPRISE
        ship = date.fromisoformat(unit["ship_date"])
        basis_end = ship + timedelta(days=model["standard_warranty_days"])
    coverage = "IN_WARRANTY" if as_of_date <= basis_end else "OUT_OF_WARRANTY"
    return coverage, basis_end.isoformat()


# ----------------------------------------------------------- recurring score

def recurring_failure_score(unit_id, failure_code_id, as_of_dt, current_rma=None):
    """Score for (unit, failure code) as of the logical clock.

    History: CLOSED RMAs of the unit with matching primary_failure_code_id whose
    closed_at is within [as_of - 365d, as_of]; weight 2 if closed within the
    last 90 days of that window, else 1. Plus 2 when the evaluating (current,
    non-terminal) RMA has evidence of the code.
    """
    as_of_date = as_of_dt.date()
    window_start = as_of_date - timedelta(days=HISTORY_WINDOW_DAYS)
    recent_start = as_of_date - timedelta(days=RECENT_WINDOW_DAYS)
    score = 0
    for r in store.rmas.values():
        if r["unit_id"] != unit_id or r["status"] != "CLOSED" or not r.get("closed_at"):
            continue
        if r.get("primary_failure_code_id") != failure_code_id:
            continue
        closed_date = r["closed_at"][:10]
        closed_d = date.fromisoformat(closed_date)
        if window_start <= closed_d <= as_of_date:
            score += 2 if closed_d >= recent_start else 1
    if current_rma is not None and current_rma["status"] not in RMA_TERMINAL:
        evidence = current_rma.get("primary_failure_code_id") == failure_code_id
        if not evidence:
            for line in store.repair_lines.values():
                if (line["rma_id"] == current_rma["id"] and line["status"] == "CONSUMED"
                        and line["failure_code_id"] == failure_code_id):
                    evidence = True
                    break
        if evidence:
            score += CURRENT_RMA_WEIGHT
    return score


def evaluate_recurring_and_escalate(rma, failure_code_id):
    """Recompute score for (unit, code); open escalation on threshold crossing.

    Returns True if an escalation was opened / engineering_review_pending set.
    """
    unit = store.units.get(rma["unit_id"])
    model = store.product_models.get(unit["model_id"]) if unit else None
    if not unit or not model:
        return False
    now = clock_now()
    score = recurring_failure_score(unit["id"], failure_code_id, now, current_rma=rma)
    if score < model["recurring_failure_threshold"]:
        return False
    # Dedup: skip if an escalation for (model, code) exists in active states
    for esc in store.engineering_escalations.values():
        if (esc["model_id"] == model["id"] and esc["failure_code_id"] == failure_code_id
                and esc["status"] in ESCALATION_DEDUP_STATES):
            if not rma.get("engineering_review_pending"):
                rma["engineering_review_pending"] = True
                touch(rma)
            return False
    esc = {
        "id": new_id(),
        "created_at": now_wall_iso(),
        "updated_at": now_wall_iso(),
        "version": 1,
        "rma_id": rma["id"],
        "model_id": model["id"],
        "failure_code_id": failure_code_id,
        "trigger_source": "AUTO_RECURRING",
        "status": "OPEN",
        "monitoring_until": None,
        "recurrence_count": 0,
        "resolution_note": None,
    }
    store.engineering_escalations[esc["id"]] = esc
    if not rma.get("engineering_review_pending"):
        rma["engineering_review_pending"] = True
        touch(rma)
    notify(rma, "ESCALATION_OPENED", "Engineering escalation opened for recurring failure")
    return True


# --------------------------------------------------------------- estimates

def final_estimate(model, labor_minutes_est, planned_parts):
    labor = round_half_up(labor_minutes_est * model["labor_rate_cents_per_minute"])
    parts_total = 0
    for line in planned_parts:
        part = store.parts.get(line["part_id"])
        if part:
            parts_total += line["quantity"] * part["unit_cost_cents"]
    return labor + parts_total


def repair_vs_replace_decision(rma, model, final_estimate_cents, repairability):
    threshold_cents = floor_div(model["replacement_cost_cents"] * model["replace_threshold_pct"], 100)
    if repairability == "BER":
        return "REPLACE"
    score = recurring_failure_score(rma["unit_id"], rma.get("primary_failure_code_id"), clock_now(), current_rma=rma)
    if score >= model["recurring_failure_threshold"]:
        return "REPLACE"
    if final_estimate_cents >= threshold_cents:
        return "REPLACE"
    return "REPAIR"


# ------------------------------------------------------------------ quoting

def quote_line_totals(parts_lines):
    """Per-line rounding first, then sum (pinned order)."""
    lines = []
    subtotal = 0
    for line in parts_lines:
        part = store.parts.get(line["part_id"])
        unit_cost = part["unit_cost_cents"] if part else line.get("unit_cost_cents", 0)
        raw = line["quantity"] * unit_cost
        # round_half_up(raw * (1 + HANDLING_PCT/100)) = round_half_up(raw * 105 / 100)
        line_total = round_half_up(raw * (100 + HANDLING_PCT), 100)
        lines.append({
            "part_id": line["part_id"],
            "quantity": line["quantity"],
            "unit_cost_cents": unit_cost,
            "line_total_cents": line_total,
        })
        subtotal += line_total
    return lines, subtotal


def build_quote(rma, model, labor_minutes, parts_lines, discount_pct, expedite):
    """Create a SENT quote with pinned rounding. Returns the quote dict."""
    lines, parts_subtotal = quote_line_totals(parts_lines)
    labor_cents = round_half_up(labor_minutes * model["labor_rate_cents_per_minute"])
    subtotal = parts_subtotal + labor_cents
    discount_cents = round_half_up(subtotal * discount_pct, 100)
    taxable = subtotal - discount_cents
    tax_cents = round_half_up(taxable * TAX_RATE_PCT, 100)
    expedite_fee = EXPEDITE_FEE_CENTS if expedite else 0
    total = taxable + tax_cents + expedite_fee

    seq = 1
    for q in store.quotes.values():
        if q["rma_id"] == rma["id"]:
            seq = max(seq, q["quote_seq"] + 1)

    now = clock_now()
    sent_at = clock_iso()
    expires = now + timedelta(days=model["quote_valid_days"])
    expires_at = expires.strftime("%Y-%m-%dT%H:%M:%S.") + f"{expires.microsecond // 1000:03d}Z"

    quote = {
        "id": new_id(),
        "created_at": now_wall_iso(),
        "updated_at": now_wall_iso(),
        "version": 1,
        "rma_id": rma["id"],
        "quote_seq": seq,
        "status": "SENT",
        "lines": lines,
        "labor_minutes": labor_minutes,
        "labor_cents": labor_cents,
        "parts_subtotal_cents": parts_subtotal,
        "discount_pct": discount_pct,
        "discount_cents": discount_cents,
        "taxable_cents": taxable,
        "tax_cents": tax_cents,
        "expedite": bool(expedite),
        "expedite_fee_cents": expedite_fee,
        "total_cents": total,
        "sent_at": sent_at,
        "expires_at": expires_at,
        "decided_at": None,
        "payment_reference": None,
    }
    store.quotes[quote["id"]] = quote
    return quote


def latest_quote(rma_id):
    """Latest quote (highest quote_seq) for an RMA, or None."""
    best = None
    for q in store.quotes.values():
        if q["rma_id"] == rma_id and (best is None or q["quote_seq"] > best["quote_seq"]):
            best = q
    return best


# -------------------------------------------------------------- SLA pauses

def open_sla_pause(rma):
    """Open an SLA pause interval (tracked as a pending 'from' on the RMA)."""
    if rma.get("_pause_open_from") is None:
        rma["_pause_open_from"] = clock_iso()


def close_sla_pause(rma):
    """Close the open SLA pause interval, appending {from, to}."""
    start = rma.get("_pause_open_from")
    if start is not None:
        rma["sla_pause_intervals"].append({"from": start, "to": clock_iso()})
        rma["_pause_open_from"] = None


# --------------------------------------------------------------- settlement

def settlement(rma):
    """Compute (gross, loyalty_credit, total). Tier keyed on gross."""
    gross = 0
    if rma.get("current_quote_id"):
        q = store.quotes.get(rma["current_quote_id"])
        if q and q["status"] == "APPROVED":
            gross += q["total_cents"]
    for res in store.loaner_reservations.values():
        if res["rma_id"] == rma["id"]:
            gross += res.get("late_fee_cents", 0) + res.get("damage_fee_cents", 0) + res.get("forfeit_charge_cents", 0)
    if gross >= LOYALTY_TIER1_CENTS:
        tier_pct = 10
    elif gross >= LOYALTY_TIER2_CENTS:
        tier_pct = 5
    else:
        tier_pct = 0
    credit = round_half_up(gross * tier_pct, 100)
    return gross, credit, gross - credit


# --------------------------------------------------------------- late fees

def compute_late_fee(reservation, as_of_date):
    """LOANER mode late fee as of a date. Zero when due_date unset or not past due."""
    if reservation["mode"] != "LOANER":
        return 0
    due = reservation.get("due_date")
    if not due:
        return 0
    due_d = date.fromisoformat(due)
    if as_of_date <= due_d:
        return 0
    days_late = (as_of_date - due_d).days
    unit = store.loaner_units.get(reservation["loaner_unit_id"])
    cap = unit["deposit_value_cents"] if unit else 0
    return min(days_late * DAILY_LATE_FEE_CENTS, cap)


def release_deposit(reservation):
    """Decrement customer deposit exposure for a reservation leaving RESERVED/SHIPPED."""
    rma = store.rmas.get(reservation["rma_id"])
    if not rma:
        return
    customer = store.customers.get(rma["customer_id"])
    unit = store.loaner_units.get(reservation["loaner_unit_id"])
    if customer and unit:
        customer["deposit_exposure_cents"] = customer.get("deposit_exposure_cents", 0) - unit["deposit_value_cents"]
        touch(customer)


# --------------------------------------------------------------- serialization

def _strip_internal(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize(entity):
    return _strip_internal(entity)


def serialize_list(entities):
    return [_strip_internal(e) for e in entities]
