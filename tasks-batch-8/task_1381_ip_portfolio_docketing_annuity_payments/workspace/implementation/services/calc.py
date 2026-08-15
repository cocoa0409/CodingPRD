"""Calculation rules per SCAFFOLD §1.3 / PRD §3.

Covers: office_action_response_due, annuity_due_schedule, annuity_fee_amount,
budget_forecast, priority_window_deadline, client_risk_score,
pruning_savings_estimate, docket_audit_variance. Money is integer cents with
round-half-up at each pinned step (PRD §2.7); the risk score is kept as an
exact rational and rounded half up only at final presentation.
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import db as dbmod


# --- date arithmetic -----------------------------------------------------------

def add_months(d, months):
    """Shift a date by whole months; preserves day-of-month, clamps to the
    last day of the target month when that month is shorter."""
    total = (d.year * 12 + (d.month - 1)) + months
    y, m = divmod(total, 12)
    m += 1
    last = monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def whole_months_between(d1, d2):
    """Whole calendar months from d1 to d2 (d2 >= d1): largest m such that
    add_months(d1, m) <= d2."""
    m = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if m < 0:
        return 0
    if add_months(d1, m) > d2:
        m -= 1
    return m


def months_late(due_date, paid_date):
    """Calendar months begun after due_date up to paid_date: whole months,
    plus one whenever any day remainder exists. paid_date > due_date always
    yields >= 1."""
    full = whole_months_between(due_date, paid_date)
    if add_months(due_date, full) < paid_date:
        return full + 1
    return full


# --- money rounding --------------------------------------------------------------

def rhu_div(numer, denom):
    """round_half_up(numer / denom) to a whole integer, for non-negative ints."""
    return (2 * numer + denom) // (2 * denom)


# --- jurisdiction rule fee tiers --------------------------------------------------

def parse_tier_bounds(bounds):
    """'1-3|4-7|8-12|13-20' or '1|2|3|4-20' -> [(lo, hi), ...] (inclusive)."""
    tiers = []
    for segment in bounds.split("|"):
        segment = segment.strip()
        if "-" in segment:
            lo_s, hi_s = segment.split("-", 1)
        else:
            lo_s, hi_s = segment, segment
        tiers.append((int(lo_s), int(hi_s)))
    return tiers


def tier_base_cents(rule, period_year):
    for idx, (lo, hi) in enumerate(parse_tier_bounds(rule["fee_tier_bounds"]), start=1):
        if lo <= period_year <= hi:
            return rule[f"fee_tier_{idx}_cents"]
    # period_year outside every declared range: fall back to the last tier
    return rule["fee_tier_4_cents"]


def entity_adjusted_base(rule, entity_size, period_year):
    """Step 1-2 of annuity_fee_amount: tier base, then SMALL-entity multiplier
    rounded half up to whole local cents."""
    base = tier_base_cents(rule, period_year)
    if entity_size == "SMALL":
        base = rhu_div(base * rule["small_entity_multiplier_bps"], 10000)
    return base


def annuity_fee_amount(rule, entity_size, period_year, due_date, paid_date):
    """Full pinned pipeline (PRD §3.4). Returns (base_local, total_local, usd).
    paid_date None or <= due_date -> no surcharge."""
    base = entity_adjusted_base(rule, entity_size, period_year)
    surcharge = 0
    if paid_date is not None and paid_date > due_date:
        late = months_late(due_date, paid_date)
        bps = rule["surcharge_bps_month_1"] if late == 1 else rule["surcharge_bps_late"]
        surcharge = rhu_div(base * bps, 10000)
    total_local = base + surcharge
    usd = rhu_div(total_local * rule["fx_to_usd_cents_bps"], 10000)
    return base, total_local, usd


def on_time_estimate_usd(rule, entity_size, period_year):
    """Generation-time estimate: no paid date -> on-time amount in USD cents."""
    base = entity_adjusted_base(rule, entity_size, period_year)
    return base, rhu_div(base * rule["fx_to_usd_cents_bps"], 10000)


# --- obligation schedule -----------------------------------------------------------

def obligation_schedule(rule, grant_date):
    """annuity_due_schedule: one row per period_year in ascending order."""
    rows = []
    for period_year in range(rule["annuity_start_year"], rule["term_years"] + 1):
        due = add_months(grant_date, period_year * 12 - 6)
        window_end = add_months(due, rule["surcharge_window_months"])
        rows.append((period_year, due, window_end))
    return rows


# --- budget forecast (PRD §3.9) ------------------------------------------------------

COMMITTED_OBLIGATION_STATES = {"AUTHORIZED", "PAYMENT_INSTRUCTED", "CONFIRMATION_QUERY"}


def budget_forecast(family, variant):
    """Computed on read; sums per-line rounded integer cents, never re-rounds."""
    total = 0
    per_application = []
    for app in dbmod.DB["applications"].values():
        if app["family_id"] != family["id"]:
            continue
        if app["status"] not in ("PENDING", "GRANTED"):
            continue
        subtotal = 0
        for ob in dbmod.DB["obligations"].values():
            if ob["application_id"] != app["id"]:
                continue
            st = ob["status"]
            if st in COMMITTED_OBLIGATION_STATES:
                subtotal += ob["authorized_amount_cents"]
            elif st == "PAID_CONFIRMED":
                subtotal += ob["paid_amount_cents"]
            elif variant == "PROJECTED" and st in ("SCHEDULED", "PENDING_AUTHORIZATION"):
                subtotal += ob["estimated_amount_usd_cents"]
        per_application.append({"application_id": app["id"], "total_usd_cents": subtotal})
        total += subtotal
    return total, per_application


# --- client risk score (PRD §3.9) -----------------------------------------------------

RISK_WEIGHTS = {
    "STATUTORY": 10,
    "OFFICE_ACTION_RESPONSE": 4,
    "PARIS_PRIORITY": 8,
    "PCT_PHASE": 8,
    "ANNUITY": 6,
    "RECORDATION": 2,
}

APPLICATION_TERMINAL = {"ABANDONED", "LAPSED", "WITHDRAWN"}


def _urgency(days_to_due):
    if days_to_due < 0:
        return Fraction(8)
    if days_to_due <= 7:
        return Fraction(4)
    if days_to_due <= 30:
        return Fraction(2)
    if days_to_due <= 90:
        return Fraction(1)
    return Fraction(1, 2)


def present_score(value):
    """Exact rational -> 2 decimal places, round_half_up at presentation only."""
    dec = Decimal(value.numerator) / Decimal(value.denominator)
    return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def client_risk_score(client, variant, today):
    total = Fraction(0)
    per_family = []
    for family in dbmod.DB["families"].values():
        if family["client_id"] != client["id"]:
            continue
        fam_score = Fraction(0)
        for app in dbmod.DB["applications"].values():
            if app["family_id"] != family["id"]:
                continue
            if app["status"] in APPLICATION_TERMINAL:
                continue
            for entry in dbmod.DB["docket_entries"].values():
                if entry["application_id"] != app["id"]:
                    continue
                if entry["status"] not in ("PENDING", "IN_PROGRESS"):
                    continue
                if variant == "STATUTORY_ONLY" and entry["entry_type"] != "STATUTORY":
                    continue
                days = (entry["current_due_date"] - today).days
                fam_score += RISK_WEIGHTS[entry["entry_type"]] * _urgency(days)
        per_family.append({"family_id": family["id"], "score": present_score(fam_score)})
        total += fam_score
    if total >= 50:
        tier = "CRITICAL"
    elif total >= 20:
        tier = "ELEVATED"
    else:
        tier = "NORMAL"
    return total, tier, per_family


# --- pruning savings (PRD §3.6) ---------------------------------------------------------

PRUNE_ADMIN_FEE_CENTS = 15000


def pruning_savings_estimate(application_id):
    gross = sum(
        ob["estimated_amount_usd_cents"]
        for ob in dbmod.DB["obligations"].values()
        if ob["application_id"] == application_id and ob["status"] == "SCHEDULED"
    )
    return max(gross - PRUNE_ADMIN_FEE_CENTS, 0)


# --- docket audit variance (PRD §3.9) ------------------------------------------------------

AUDIT_INTERNAL_STATES = {"PENDING", "IN_PROGRESS", "RESPONSE_FILED", "COMPLETED"}


def audit_variances(application_id, window_start, window_end, register_entries):
    """Half-open [window_start, window_end) matching on (entry_type, due_date)."""
    internal = [
        e for e in dbmod.DB["docket_entries"].values()
        if e["application_id"] == application_id
        and e["status"] in AUDIT_INTERNAL_STATES
        and window_start <= e["current_due_date"] < window_end
    ]
    register = [
        r for r in register_entries
        if window_start <= r["due_date"] < window_end
    ]

    unmatched_internal = {e["id"] for e in internal}
    by_key = {}
    for e in internal:
        by_key.setdefault((e["entry_type"], e["current_due_date"]), []).append(e)

    variances = []
    for r in register:
        key = (r["entry_type"], r["due_date"])
        bucket = [e for e in by_key.get(key, []) if e["id"] in unmatched_internal]
        if bucket:
            unmatched_internal.discard(bucket[0]["id"])
            continue
        candidates = [
            (idx, e) for idx, e in enumerate(internal)
            if e["id"] in unmatched_internal
            and e["entry_type"] == r["entry_type"]
            and e["current_due_date"] != r["due_date"]
        ]
        if candidates:
            candidates.sort(
                key=lambda pair: (
                    abs((pair[1]["current_due_date"] - r["due_date"]).days),
                    pair[1]["created_at"],
                    pair[0],
                )
            )
            pick = candidates[0][1]
            unmatched_internal.discard(pick["id"])
            variances.append({
                "kind": "DATE_MISMATCH",
                "entry_type": r["entry_type"],
                "internal_due_date": pick["current_due_date"].isoformat(),
                "register_due_date": r["due_date"].isoformat(),
            })
        else:
            variances.append({
                "kind": "MISSING_INTERNAL",
                "entry_type": r["entry_type"],
                "register_due_date": r["due_date"].isoformat(),
            })

    for e in internal:
        if e["id"] in unmatched_internal:
            variances.append({
                "kind": "MISSING_REGISTER",
                "entry_type": e["entry_type"],
                "internal_due_date": e["current_due_date"].isoformat(),
            })

    def sort_key(v):
        due = v["internal_due_date"] if "internal_due_date" in v else v["register_due_date"]
        return (v["entry_type"], due)

    variances.sort(key=sort_key)
    return variances
