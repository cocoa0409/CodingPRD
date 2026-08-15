"""Business logic: calculations, cascades, auto-close, settlement, daily sweep."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import (DB, CONDITION_MULT, VALUATION_GRADE_MULT, CLEANING_BUFFER_DAYS,
                CLEANING_BASE_FEE_CENTS, BACKLOG_THRESHOLD, RUSH_MULTIPLIER,
                STRIKE_ALLOWANCE_DAYS, LOST_GRACE_DAYS, USEFUL_LIFE_YEARS,
                SALVAGE_FLOOR_PCT, HOLD_HOURS, new_record, touch, now_iso,
                now_dt, today, sort_key)


def D(x):
    return Decimal(str(x))


def round_half_up(x):
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Derived renter aggregates (renter_credit_recompute)
# ---------------------------------------------------------------------------

def recompute_renter_credit(renter):
    outstanding = 0
    for inv in DB.invoices.values():
        if inv["_renter_id"] == renter["id"] and inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
            outstanding += inv["balance_cents"]
    credit_hold = outstanding > renter["credit_limit_cents"]
    if outstanding != renter["outstanding_balance_cents"] or credit_hold != renter["credit_hold"]:
        renter["outstanding_balance_cents"] = outstanding
        renter["credit_hold"] = credit_hold
        touch(renter)


def recompute_item_serviceable(item):
    count = sum(1 for u in DB.units.values()
                if u["item_id"] == item["id"]
                and u["status"] not in ("AWAITING_DISPOSAL", "DISPOSED"))
    if count != item["serviceable_unit_count"]:
        item["serviceable_unit_count"] = count
        touch(item)


# ---------------------------------------------------------------------------
# Production date math (production_dates)
# ---------------------------------------------------------------------------

def compute_run_weeks(performance_start, closing):
    # floor((closing_date - performance_start_date + 1) / 7)
    return ((closing - performance_start).days + 1) // 7


def compute_return_by(closing):
    return closing + timedelta(days=STRIKE_ALLOWANCE_DAYS)


def pinned_rate_card(production):
    rcid = production.get("rate_card_id")
    return DB.rate_cards.get(rcid) if rcid else None


# ---------------------------------------------------------------------------
# Rental quote (rental_quote)
# ---------------------------------------------------------------------------

def compute_quote(production, item, quantity, window_start, window_end):
    """Returns (rate_variant, quoted_charge_cents)."""
    window_days = (window_end - window_start).days + 1
    long_run = bool(production.get("long_run"))
    if long_run:
        variant = "LONG_RUN"
    elif window_days >= 7:
        variant = "WEEKLY"
    else:
        variant = "DAILY"

    if variant == "DAILY":
        charge = D(quantity) * D(item["base_daily_rate_cents"]) * D(window_days)
    else:
        weeks = -(-window_days // 7)  # ceil(window_days / 7)
        weekly = D(quantity) * D(item["base_weekly_rate_cents"]) * D(weeks)
        if variant == "LONG_RUN":
            card = pinned_rate_card(production)
            if card is not None:
                if production.get("run_weeks", 0) >= card["deep_run_threshold_weeks"]:
                    discount = D(card["deep_run_discount_pct"])
                else:
                    discount = D(card["long_run_discount_pct"])
                charge = weekly * (D(1) - discount)
            else:
                charge = weekly
        else:
            charge = weekly
    return variant, round_half_up(charge)


# ---------------------------------------------------------------------------
# Availability (availability_for_window) — inclusive interval overlap
# ---------------------------------------------------------------------------

def windows_overlap(s1, e1, s2, e2):
    return s1 <= e2 and s2 <= e1


def availability_for_window(item_id, start, end, exclude_reservation_id=None):
    item = DB.items[item_id]
    serviceable = item["serviceable_unit_count"]
    held = 0
    for r in DB.reservations.values():
        if r["item_id"] != item_id:
            continue
        if r["status"] not in ("HELD", "CONFIRMED"):
            continue
        if exclude_reservation_id and r["id"] == exclude_reservation_id:
            continue
        if windows_overlap(r["_window_start"], r["_window_end"], start, end):
            held += r["quantity"]
    line_allocated = 0
    for ln in DB.lines.values():
        if ln["status"] not in ("PENDING", "PICKED", "OUT"):
            continue
        r = DB.reservations.get(ln["reservation_id"])
        if r is None or r["item_id"] != item_id:
            continue
        if windows_overlap(r["_window_start"], r["_window_end"], start, end):
            line_allocated += 1
    return serviceable - held - line_allocated


# ---------------------------------------------------------------------------
# Unit selector (unit_selector) — strict buffered per-unit exclusion
# ---------------------------------------------------------------------------

def select_units(reservation, quantity, extra_staged_lines):
    """Pick up to `quantity` units for the reservation window. Returns the list
    of chosen units, or None when the pool is short."""
    item = DB.items[reservation["item_id"]]
    buffer_days = CLEANING_BUFFER_DAYS[item["category"]]
    start = reservation["_window_start"]
    end = reservation["_window_end"]

    staged_by_unit = {}
    for ln in extra_staged_lines:
        staged_by_unit.setdefault(ln["item_unit_id"], []).append(ln)

    def has_conflict(unit_id):
        active = [ln for ln in DB.lines.values()
                  if ln["item_unit_id"] == unit_id
                  and ln["status"] in ("PENDING", "PICKED", "OUT")]
        active += staged_by_unit.get(unit_id, [])
        for ln in active:
            r = DB.reservations.get(ln["reservation_id"])
            if r is None:
                r = ln["_reservation_ref"]
            occ_start = r["_window_start"]
            occ_end = r["_window_end"] + timedelta(days=buffer_days)
            if start <= occ_end and occ_start <= end:
                return True
        return False

    candidates = []
    for u in DB.units.values():
        if u["item_id"] != reservation["item_id"]:
            continue
        if u["status"] != "AVAILABLE":
            continue
        if u["condition_grade"] == "D":
            continue
        if has_conflict(u["id"]):
            continue
        candidates.append(u)

    def rank(u):
        # condition_grade ASC (A first), last_returned_date ASC nulls first, created_at ASC
        lrd = u.get("last_returned_date")
        return (u["condition_grade"], 0 if lrd is None else 1,
                lrd or "", u["created_at"], u["_seq"])

    candidates.sort(key=rank)
    if len(candidates) < quantity:
        return None
    return candidates[:quantity]


def compute_line_rental_charge(reservation, unit):
    per_unit = round_half_up(D(reservation["quoted_charge_cents"]) / D(reservation["quantity"]))
    mult = D(CONDITION_MULT[unit["condition_grade"]])
    return round_half_up(D(per_unit) * mult)


# ---------------------------------------------------------------------------
# Late fee (late_fee)
# ---------------------------------------------------------------------------

def compute_late_fee(late_days, item, condition_grade, production):
    card = pinned_rate_card(production)
    pct = D(card["late_fee_daily_pct"]) if card else D(0)
    mult = D(CONDITION_MULT.get(condition_grade, "1.00"))
    return round_half_up(D(late_days) * D(item["base_daily_rate_cents"]) * mult * pct)


# ---------------------------------------------------------------------------
# Damage valuation (damage_valuation)
# ---------------------------------------------------------------------------

def compute_damage_valuation(claim_type, unit, item, renter, assessment_date):
    """Returns (valuation_method, assessed_value_cents)."""
    if claim_type == "LOSS":
        # Total loss: always full replacement value, no grade multiplier.
        return "AGREED_VALUE", item["replacement_value_cents"]

    grade = unit["condition_grade"]
    grade_mult = D(VALUATION_GRADE_MULT[grade])

    agreed = False
    for c in DB.certificates.values():
        if c["renter_id"] != renter["id"] or c["status"] != "VERIFIED":
            continue
        if c["coverage_cents"] >= item["replacement_value_cents"] and \
                c["_expiry_date"] >= assessment_date:
            agreed = True
            break

    if agreed:
        return "AGREED_VALUE", round_half_up(D(item["replacement_value_cents"]) * grade_mult)

    age_years = (assessment_date - unit["_acquisition_date"]).days // 365
    raw = D(unit["acquisition_cost_cents"]) * (D(1) - D(age_years) / D(USEFUL_LIFE_YEARS))
    salvage_floor = D(SALVAGE_FLOOR_PCT) * D(item["replacement_value_cents"])
    value = round_half_up(max(raw, salvage_floor) * grade_mult)
    return "DEPRECIATED_REPLACEMENT", value


# ---------------------------------------------------------------------------
# Cleaning fee (cleaning_fee)
# ---------------------------------------------------------------------------

def compute_cleaning_fee(item, queue_depth):
    base = CLEANING_BASE_FEE_CENTS[item["category"]]
    if queue_depth >= BACKLOG_THRESHOLD:
        return round_half_up(D(base) * D(RUSH_MULTIPLIER))
    return base


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_renter_suspended(renter):
    """Release/expire all HELD/CONFIRMED reservations on the renter's productions."""
    expired, released = [], []
    for r in DB.reservations.values():
        p = DB.productions.get(r["production_id"])
        if p is None or p["renter_id"] != renter["id"]:
            continue
        if r["status"] == "HELD":
            r["status"] = "EXPIRED"
            touch(r)
            expired.append(r["id"])
        elif r["status"] == "CONFIRMED":
            r["status"] = "RELEASED"
            touch(r)
            released.append(r["id"])
    return expired, released


def suspend_renter(renter):
    if renter["status"] == "ACTIVE":
        renter["status"] = "SUSPENDED"
        touch(renter)
        return cascade_renter_suspended(renter)
    return [], []


def has_verified_cert(renter_id, min_date):
    for c in DB.certificates.values():
        if c["renter_id"] == renter_id and c["status"] == "VERIFIED" \
                and c["_expiry_date"] >= min_date:
            return True
    return False


# ---------------------------------------------------------------------------
# Pull-list auto-close + production settlement bubble-up
# ---------------------------------------------------------------------------

def evaluate_pull_list_close(pull_list):
    if pull_list["status"] != "DISPATCHED":
        return False
    lines = [ln for ln in DB.lines.values() if ln["pull_list_id"] == pull_list["id"]]
    if not lines:
        return False
    for ln in lines:
        if ln["status"] not in ("RETURNED", "DAMAGED", "LOST"):
            return False
    for f in DB.fittings.values():
        ln = DB.lines.get(f["pull_list_line_id"])
        if ln is None or ln["pull_list_id"] != pull_list["id"]:
            continue
        if f["status"] == "APPROVED":
            return False
    for ln in lines:
        if ln["status"] in ("DAMAGED", "LOST"):
            ok = any(c["pull_list_line_id"] == ln["id"]
                     and c["status"] in ("POSTED", "WAIVED")
                     for c in DB.claims.values())
            if not ok:
                return False
    pull_list["status"] = "CLOSED"
    touch(pull_list)
    evaluate_production_settle(DB.productions.get(pull_list["production_id"]))
    return True


def production_has_unbilled(production_id):
    for ln in DB.lines.values():
        pl = DB.pull_lists.get(ln["pull_list_id"])
        if pl is None or pl["production_id"] != production_id:
            continue
        if ln["status"] in ("OUT", "RETURNED", "DAMAGED", "LOST") and not ln["rental_invoiced"]:
            return True
        if ln["status"] in ("RETURNED", "DAMAGED", "LOST") and not ln["late_fee_invoiced"]:
            return True
    for c in DB.claims.values():
        ln = DB.lines.get(c["pull_list_line_id"])
        pl = DB.pull_lists.get(ln["pull_list_id"]) if ln else None
        if pl is None or pl["production_id"] != production_id:
            continue
        if c["status"] == "POSTED" and c["invoice_id"] is None:
            return True
    for t in DB.tickets.values():
        if t["_production_id"] == production_id and not t["invoiced"]:
            return True
    return False


def evaluate_production_settle(production):
    if production is None or production["status"] != "WRAP":
        return False
    pid = production["id"]
    for pl in DB.pull_lists.values():
        if pl["production_id"] == pid and pl["status"] not in ("CLOSED", "CANCELLED"):
            return False
    for inv in DB.invoices.values():
        if inv["production_id"] == pid and inv["status"] not in ("PAID", "CREDITED", "VOID"):
            return False
    if production_has_unbilled(pid):
        return False
    production["status"] = "SETTLED"
    touch(production)
    return True


# ---------------------------------------------------------------------------
# Check-in / loss shared effects
# ---------------------------------------------------------------------------

def finalize_terminal_line(line, production):
    """After a line reaches a terminal state, run auto-close evaluation."""
    pl = DB.pull_lists.get(line["pull_list_id"])
    if pl is not None:
        evaluate_pull_list_close(pl)


# ---------------------------------------------------------------------------
# Daily operations sweep (run_daily_ops)
# ---------------------------------------------------------------------------

def run_daily_ops():
    expired_certificate_ids = []
    expired_reservation_ids = []
    released_reservation_ids = []
    advanced_production_ids = []
    auto_lost_line_ids = []
    settled_production_ids = []
    cur_date = today()
    cur_dt = now_dt()

    # 1. Certificate expiry (SUBMITTED/VERIFIED past expiry_date)
    for c in sorted(DB.certificates.values(), key=sort_key):
        if c["status"] in ("SUBMITTED", "VERIFIED") and c["_expiry_date"] < cur_date:
            was_verified = c["status"] == "VERIFIED"
            c["status"] = "EXPIRED"
            touch(c)
            expired_certificate_ids.append(c["id"])
            if was_verified:
                renter = DB.renters.get(c["renter_id"])
                if renter is not None and renter["status"] == "ACTIVE" \
                        and not has_verified_cert(renter["id"], cur_date):
                    exp, rel = suspend_renter(renter)
                    expired_reservation_ids.extend(exp)
                    released_reservation_ids.extend(rel)

    # 2. HELD reservations past hold_expires_at -> EXPIRED
    for r in sorted(DB.reservations.values(), key=sort_key):
        if r["status"] == "HELD" and r["_hold_expires_dt"] < cur_dt:
            r["status"] = "EXPIRED"
            touch(r)
            expired_reservation_ids.append(r["id"])

    # 3. Production date advancement (transitive within a single run)
    for p in sorted(DB.productions.values(), key=sort_key):
        advanced = False
        if p["status"] == "CONFIRMED" and cur_date >= p["_performance_start_date"]:
            p["status"] = "IN_RUN"
            advanced = True
        if p["status"] == "IN_RUN" and cur_date > p["_closing_date"]:
            p["status"] = "WRAP"
            advanced = True
        if advanced:
            touch(p)
            advanced_production_ids.append(p["id"])

    # 4. Auto-loss: OUT lines whose due_back_date is more than 7 days past
    for ln in sorted(DB.lines.values(), key=sort_key):
        if ln["status"] == "OUT" and ln.get("_due_back_date") is not None \
                and (cur_date - ln["_due_back_date"]).days > LOST_GRACE_DAYS:
            apply_line_loss(ln)
            auto_lost_line_ids.append(ln["id"])

    # 5. Production settle evaluation
    for p in sorted(DB.productions.values(), key=sort_key):
        if p["status"] == "WRAP" and evaluate_production_settle(p):
            settled_production_ids.append(p["id"])

    return {
        "current_utc": now_iso(),
        "expired_certificate_ids": expired_certificate_ids,
        "expired_reservation_ids": expired_reservation_ids,
        "released_reservation_ids": released_reservation_ids,
        "advanced_production_ids": advanced_production_ids,
        "auto_lost_line_ids": auto_lost_line_ids,
        "settled_production_ids": settled_production_ids,
    }


def apply_line_loss(line):
    """Shared effects for report-lost and auto-loss."""
    line["status"] = "LOST"
    reservation = DB.reservations.get(line["reservation_id"])
    item = DB.items.get(reservation["item_id"]) if reservation else None
    unit = DB.units.get(line["item_unit_id"])
    production = DB.productions.get(reservation["production_id"]) if reservation else None
    if item is not None and production is not None and unit is not None:
        line["late_fee_cents"] = compute_late_fee(
            LOST_GRACE_DAYS, item, unit["condition_grade"], production)
    if unit is not None and unit["status"] == "OUT":
        unit["status"] = "DISPOSED"
        touch(unit)
        if item is not None:
            recompute_item_serviceable(item)
    touch(line)
    finalize_terminal_line(line, production)
