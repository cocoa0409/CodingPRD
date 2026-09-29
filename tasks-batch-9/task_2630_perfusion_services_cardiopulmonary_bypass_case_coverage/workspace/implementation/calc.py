"""The eight calculations of SCAFFOLD / PRD section 3, plus money helpers.

Money is integer cents throughout and every rounding step is ROUND_HALF_UP
(PRD 2.6).  Nothing here uses binary floating point for arithmetic.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import constants as C
from store import db

D = Decimal
ONE = D(1)


def cents(value):
    """Round a Decimal amount to whole cents, half-up."""
    return int(D(value).quantize(D("1"), rounding=ROUND_HALF_UP))


def dp(value, places):
    q = D(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def floor_div(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def minutes_between(start, end):
    """Exact elapsed minutes as a Decimal."""
    if start is None or end is None:
        return D(0)
    return D(str((end - start).total_seconds())) / D(60)


def num(value):
    """Render a Decimal for JSON output."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


# ---------------------------------------------------------------- selectors

def select_preference_card(surgeon_id, procedure_type):
    """disposable_pack_cost selector: the ACTIVE card for this surgeon and
    procedure type, ordered by revision DESC then created_at DESC."""
    rows = [
        c for c in db.preference_cards.values()
        if c["surgeon_id"] == surgeon_id
        and c["procedure_type"] == procedure_type
        and c["status"] == "ACTIVE"
    ]
    if not rows:
        return None
    rows.sort(key=lambda c: (c["revision"], c["created_at"], c["_seq"]), reverse=True)
    return rows[0]


def ccp_certification(perfusionist_id):
    """The governing CCP certification: greatest issued_on, created_at breaks ties."""
    rows = [
        c for c in db.certifications.values()
        if c["perfusionist_id"] == perfusionist_id and c["cert_code"] == "CCP"
    ]
    if not rows:
        return None
    rows.sort(key=lambda c: (c["issued_on"], c["created_at"], c["_seq"]), reverse=True)
    return rows[0]


# ------------------------------------------------------- case fee settlement

def prolonged_units(minutes, threshold):
    minutes = D(minutes)
    threshold = D(threshold)
    if minutes < threshold:
        return 0
    return floor_div((minutes - threshold) / D(C.PROLONGED_UNIT_MINUTES)) + 1


def case_fee_settlement(contract, case, variant, card=None):
    """variant PROVISIONAL uses the selected card's standard_pump_minutes;
    variant FINAL uses the case's recorded pump_time_minutes (PRD 3.4 / 3.10)."""
    if variant == "PROVISIONAL":
        minutes = D(card["standard_pump_minutes"]) if card else D(0)
    else:
        minutes = D(case.get("pump_time_minutes") or 0)
    units = prolonged_units(minutes, contract["prolonged_pump_threshold_minutes"])
    acuity_pct = C.ACUITY_UPLIFT_PCT[case["acuity"]]
    surcharge_pct = D(units) * D(contract["prolonged_surcharge_pct"])
    base = D(contract["per_case_fee_cents"])
    return cents(base * (ONE + acuity_pct + surcharge_pct))


# --------------------------------------------------------- disposable pack

def disposable_pack_cost(contract, card, substitutions):
    """Per-line rounding; the pack total is the sum of the rounded lines."""
    subs = {}
    for s in (substitutions or []):
        subs[s["line_code"]] = s
    discount = D(contract["disposable_discount_pct"])
    markup = D(contract["disposable_markup_pct"])
    lines = []
    for tpl in card["pack_line_items"]:
        code = tpl["line_code"]
        quantity = tpl["quantity"]
        sub = subs.get(code)
        if sub is not None:
            out_code = sub["replacement_code"]
            unit_cost = sub["replacement_unit_cost_cents"]
            substituted = True
        else:
            out_code = code
            unit_cost = tpl["unit_cost_cents"]
            substituted = False
        gross = D(quantity) * D(unit_cost)
        discounted = gross * (ONE - discount)
        marked = discounted * (ONE + markup)
        lines.append({
            "line_code": out_code,
            "quantity": quantity,
            "unit_cost_cents": unit_cost,
            "substituted": substituted,
            "line_total_cents": cents(marked),
        })
    lines.sort(key=lambda l: l["line_code"])
    total = sum(l["line_total_cents"] for l in lines)
    return lines, total


# ----------------------------------------------------------- ECMO billing

def ecmo_run_billing(contract, run, end_at=None):
    end = end_at if end_at is not None else run.get("decannulated_at")
    total_minutes = minutes_between(run.get("cannulated_at"), end)
    if total_minutes < 0:
        total_minutes = D(0)
    hours = ceil_int(total_minutes / D(60))
    mode_pct = C.ECMO_MODE_UPLIFT_PCT[run["mode"]]
    if hours <= C.ECMO_PROLONGED_HOUR_THRESHOLD:
        prolonged_pct = D(0)
    else:
        prolonged_pct = D(contract["prolonged_surcharge_pct"]) * D(hours - C.ECMO_PROLONGED_HOUR_THRESHOLD)
    fee = cents(D(hours) * D(contract["ecmo_hourly_fee_cents"]) * (ONE + mode_pct + prolonged_pct))
    return hours, fee


def run_reference_instant(run):
    """COALESCE(last_handoff_at, cannulated_at) -- PRD 3.8."""
    return run.get("last_handoff_at") or run.get("cannulated_at")


def run_uninterrupted_minutes(run):
    start = run_reference_instant(run)
    if start is None:
        return D(0)
    if run["status"] == "DECANNULATED":
        end = run.get("decannulated_at") or db.now()
    else:
        end = db.now()
    value = minutes_between(start, end)
    return value if value > 0 else D(0)


def run_staffing_breach(run):
    return run_uninterrupted_minutes(run) >= D(C.ECMO_MAX_UNINTERRUPTED_MINUTES)


# ------------------------------------------------------- coverage posture

def _clip_merge(intervals, horizon_start, horizon_end):
    clipped = []
    for start, end in intervals:
        s = max(start, horizon_start)
        e = min(end, horizon_end)
        if e > s:
            clipped.append((s, e))
    clipped.sort()
    merged = []
    for s, e in clipped:
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    total = D(0)
    for s, e in merged:
        total += minutes_between(s, e)
    return total


def contract_coverage_posture(contract_id):
    horizon_start = db.now()
    horizon_end = horizon_start + timedelta(hours=C.COVERAGE_HORIZON_HOURS)
    buckets = {"PRIMARY_CALL": [], "BACKUP_CALL": []}
    for slot in db.call_rotation_slots.values():
        if slot["contract_id"] != contract_id:
            continue
        if slot["status"] not in C.LIVE_SLOT_STATUSES:
            continue
        if slot["slot_type"] not in buckets:
            continue
        buckets[slot["slot_type"]].append((slot["window_start"], slot["window_end"]))
    primary = _clip_merge(buckets["PRIMARY_CALL"], horizon_start, horizon_end)
    backup = _clip_merge(buckets["BACKUP_CALL"], horizon_start, horizon_end)
    horizon = C.COVERAGE_HORIZON_MINUTES
    if primary == horizon and backup >= horizon * C.BACKUP_COVERAGE_MIN_RATIO:
        return "COVERED"
    if primary >= horizon * C.THIN_PRIMARY_MIN_RATIO:
        return "THIN"
    return "UNCOVERED"


# --------------------------------------------------- device reservation ledger

def device_open_reservation_count(device_id):
    """Recomputed from scratch on every trigger (PRD 3.5)."""
    count = 0
    for case in db.bypass_cases.values():
        if case["bypass_status"] not in C.RESERVATION_HOLDING_STATUSES:
            continue
        if case.get("primary_device_id") == device_id or case.get("backup_device_id") == device_id:
            count += 1
    return count


# ------------------------------------------------------------- CE ledger

def in_cycle_window(activity_date, cert):
    """Half-open cycle window: issued_on inclusive, expires_on exclusive (PRD 2.5)."""
    if cert is None:
        return False
    return cert["issued_on"] <= activity_date < cert["expires_on"]


def ce_ledger(perfusionist_id):
    """Returns (verified, pending) credit hours inside the current CCP window."""
    cert = ccp_certification(perfusionist_id)
    if cert is None:
        return D("0.0"), D("0.0")
    verified = D(0)
    pending = D(0)
    for act in db.ce_activities.values():
        if act["perfusionist_id"] != perfusionist_id:
            continue
        when = act["activity_date"]
        if not in_cycle_window(when, cert):
            continue
        hours = D(act["credit_hours"])
        if act["status"] == "VERIFIED":
            verified += hours
        elif act["status"] == "SUBMITTED":
            pending += hours
    return dp(verified, 1), dp(pending, 1)


# ------------------------------------------------------------ fatigue

def consecutive_case_count_24h(perfusionist_id):
    now = db.now()
    lo = now - timedelta(hours=24)
    count = 0
    for case in db.bypass_cases.values():
        if case.get("assigned_perfusionist_id") != perfusionist_id:
            continue
        started = case.get("bypass_started_at")
        if started is None:
            continue
        if lo <= started < now:
            count += 1
    return count


def ecmo_hours_rolling_7d(perfusionist_id):
    now = db.now()
    lo = now - timedelta(hours=168)
    total = 0
    for run in db.ecmo_runs.values():
        if run.get("primary_perfusionist_id") != perfusionist_id:
            continue
        started = run.get("cannulated_at")
        if started is None:
            continue
        if lo <= started < now:
            total += int(run.get("billable_hours") or 0)
    return total


# ----------------------------------------------------------- readiness

def perfusionist_readiness_score(perf, variant):
    cert = ccp_certification(perf["id"])
    verified = D(perf.get("ce_credits_verified") or 0)
    pending = D(perf.get("ce_credits_pending") or 0)
    credits = verified + pending if variant == "ADMISSION" else verified
    if cert is None or D(cert["cycle_credit_requirement"]) <= 0:
        credit_ratio = D(0)
    else:
        credit_ratio = min(ONE, credits / D(cert["cycle_credit_requirement"]))
    experience_ratio = min(ONE, D(perf.get("career_case_count") or 0) / C.READINESS_EXPERIENCE_TARGET)
    fatigue = (C.FATIGUE_CASE_WEIGHT * D(consecutive_case_count_24h(perf["id"]))
               + C.FATIGUE_ECMO_WEIGHT * D(ecmo_hours_rolling_7d(perf["id"])))
    raw = C.CREDIT_WEIGHT * credit_ratio + C.EXPERIENCE_WEIGHT * experience_ratio - fatigue
    if raw < 0:
        raw = D(0)
    if raw > ONE:
        raw = ONE
    return dp(raw, 3)


# ------------------------------------------------------ monthly settlement

def volume_credit_pct(gross_cents):
    if gross_cents >= C.VOLUME_TIER_2_CENTS:
        return C.VOLUME_TIER_2_PCT
    if gross_cents >= C.VOLUME_TIER_1_CENTS:
        return C.VOLUME_TIER_1_PCT
    return D(0)
