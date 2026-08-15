"""All calculation rules from the scaffold calculations table."""
import calendar
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

import db
from db import _parse_iso, _format_iso
from services.common import dec, round2, get_policy_for_class


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_months(d, months):
    """Add months to a date, clamping to end of month."""
    if isinstance(d, datetime):
        d = d.date() if not isinstance(d, date) else d
    if isinstance(d, str):
        d = _parse_iso(d).date()
    m = months
    # Handle fractional months by truncating toward zero for integer month arithmetic
    # interval_months / 4 and / 2 may produce non-integer; we compute using integer
    # division approach: multiply by 12/months equivalent
    # Actually per spec: interval = interval_months / 4 or / 2. If interval_months
    # is not divisible, the result may be fractional. We use integer months rounded
    # down (the PRD says "interval halved" or "quartered", meaning the month count).
    # For odd interval_months, interval_months/2 could be e.g. 6/2=3, 12/4=3.
    # We keep it as integer months — the spec uses whole ISO dates.
    if isinstance(m, float) and m == int(m):
        m = int(m)
    if not isinstance(m, int):
        m = int(m)  # truncate toward zero
    total_months = d.year * 12 + (d.month - 1) + m
    y, mo = divmod(total_months, 12)
    mo += 1
    last_day = calendar.monthrange(y, mo)[1]
    day = min(d.day, last_day)
    return date(y, mo, day)


def _add_days(d, days):
    if isinstance(d, str):
        d = _parse_iso(d).date()
    elif isinstance(d, datetime):
        d = d.date()
    return d + timedelta(days=days)


def _months_ago(dt, months):
    """Subtract months from a datetime."""
    total_months = dt.year * 12 + (dt.month - 1) - months
    y, mo = divmod(total_months, 12)
    mo += 1
    last_day = calendar.monthrange(y, mo)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=y, month=mo, day=day)


# ---------------------------------------------------------------------------
# calculations.insulation_resistance_evaluation
# ---------------------------------------------------------------------------

def evaluate_insulation_resistance(value_primary, ambient_temp_c, policy):
    """Temperature-corrected IR grading. Comparison on unrounded corrected value."""
    ir_corrected = value_primary * (2 ** ((ambient_temp_c - 40) / 10))
    ir_min = policy["ir_min_mohm"]
    if ir_corrected >= ir_min:
        return "PASS"
    elif ir_corrected >= 0.5 * ir_min:
        return "MARGINAL"
    else:
        return "FAIL"


# ---------------------------------------------------------------------------
# calculations.oil_moisture_evaluation
# ---------------------------------------------------------------------------

def evaluate_oil_moisture(value_primary, policy):
    """Oil moisture grading. Inclusive boundaries."""
    if value_primary >= policy["oil_critical_ppm"]:
        return "FAIL"
    elif value_primary >= policy["oil_warn_ppm"]:
        return "MARGINAL"
    else:
        return "PASS"


# ---------------------------------------------------------------------------
# calculations.relay_timing_evaluation
# ---------------------------------------------------------------------------

def evaluate_relay_timing(value_primary, value_secondary, policy):
    """Relay timing deviation grading. Strictly-greater boundaries."""
    deviation_pct = abs(value_primary - value_secondary) / value_secondary * 100
    if deviation_pct > policy["relay_timing_fail_pct"]:
        return "FAIL"
    elif deviation_pct > policy["relay_timing_warn_pct"]:
        return "MARGINAL"
    else:
        return "PASS"


# ---------------------------------------------------------------------------
# calculations.asset_condition_score
# ---------------------------------------------------------------------------

SCORE_MAP = {"PASS": 100, "MARGINAL": 70, "FAIL": 30}
PENALTY_MAP = {"C1": 5, "C2": 2, "C3": 1}
TRAILING_MONTHS = 24


def compute_condition_score(asset_id):
    """Weighted, renormalized condition score with open-defect penalties.
    Returns float rounded to 2 decimal places, round_half_up."""
    asset = db.assets[asset_id]
    policy = get_policy_for_class(asset["asset_class"])
    if policy is None:
        return 100.00

    now = db.now_dt()
    cutoff = _months_ago(now, TRAILING_MONTHS)

    components = {}
    weights = {
        "INSULATION_RESISTANCE": policy["w_insulation"],
        "OIL_MOISTURE": policy["w_oil"],
        "RELAY_TIMING": policy["w_relay"],
    }

    for test_type in ("INSULATION_RESISTANCE", "OIL_MOISTURE", "RELAY_TIMING"):
        candidates = []
        for te in db.test_events.values():
            if te["asset_id"] != asset_id:
                continue
            if te["test_type"] != test_type:
                continue
            if te["status"] != "ACCEPTED":
                continue
            measured = _parse_iso(te["measured_at"])
            if measured < cutoff or measured > now:
                continue
            candidates.append(te)
        if candidates:
            # latest measured_at; tie-break created_at ASC
            candidates.sort(key=lambda te: (_parse_iso(te["measured_at"]), te["created_at"]))
            # For tie-break created_at ASC, we want the earliest created_at when measured_at ties
            # So sort by measured_at DESC, then created_at ASC
            candidates.sort(key=lambda te: te["created_at"])
            candidates.sort(key=lambda te: _parse_iso(te["measured_at"]), reverse=True)
            chosen = candidates[0]
            components[test_type] = SCORE_MAP[chosen["result"]]

    if not components:
        base = Decimal("100")
    else:
        num = Decimal("0")
        den = Decimal("0")
        for tt, score_val in components.items():
            w = dec(weights[tt])
            num += w * dec(score_val)
            den += w
        base = num / den

    # Penalty from open defects
    penalty = Decimal("0")
    for defect in db.defects.values():
        if defect["asset_id"] != asset_id:
            continue
        if defect["status"] in ("OPEN", "WORK_ORDERED", "DEFERRED"):
            penalty += dec(PENALTY_MAP.get(defect["severity"], 0))

    score = base - penalty
    if score < 0:
        score = Decimal("0")
    return float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# calculations.maintenance_next_due
# ---------------------------------------------------------------------------

def compute_next_due_baseline(asset_id):
    """Interval-baseline variant: baseline_date + interval_months."""
    asset = db.assets[asset_id]
    policy = get_policy_for_class(asset["asset_class"])
    if policy is None:
        return None
    baseline_str = asset.get("last_maintenance_completed_at") or asset.get("install_date")
    if baseline_str is None:
        return None
    baseline_dt = _parse_iso(baseline_str)
    baseline_date = baseline_dt.date()
    result = _add_months(baseline_date, policy["interval_months"])
    return result.isoformat()


def compute_next_due_condition_adjusted(asset_id):
    """Condition-adjusted variant (authoritative for Asset.next_due_date)."""
    asset = db.assets[asset_id]
    policy = get_policy_for_class(asset["asset_class"])
    if policy is None:
        return None
    baseline_str = asset.get("last_maintenance_completed_at") or asset.get("install_date")
    if baseline_str is None:
        return None
    baseline_dt = _parse_iso(baseline_str)
    baseline_date = baseline_dt.date()
    score = asset.get("condition_score", 100.0)
    interval = policy["interval_months"]
    if score < policy["condition_critical_threshold"]:
        interval = interval / 4
    elif score < policy["condition_escalation_threshold"]:
        interval = interval / 2
    # Convert to integer months (truncate)
    interval = int(interval)
    if interval < 1:
        interval = 1
    result = _add_months(baseline_date, interval)
    return result.isoformat()


def refresh_asset_condition_and_due(asset_id):
    """Recompute condition_score and next_due_date, and update needs_revalidation flags."""
    asset = db.assets[asset_id]
    old_score = asset.get("condition_score", 100.0)
    new_score = compute_condition_score(asset_id)
    asset["condition_score"] = new_score
    asset["next_due_date"] = compute_next_due_condition_adjusted(asset_id)
    db.touch(asset)

    # Update needs_revalidation on windows
    policy = get_policy_for_class(asset["asset_class"])
    if policy:
        threshold = policy["condition_escalation_threshold"]
        for w in db.outage_windows.values():
            if w["asset_id"] != asset_id:
                continue
            if w["status"] in ("REQUESTED", "APPROVED"):
                should_flag = new_score < threshold
                if w.get("needs_revalidation", False) != should_flag:
                    w["needs_revalidation"] = should_flag
                    db.touch(w)


# ---------------------------------------------------------------------------
# calculations.containment_requirement
# ---------------------------------------------------------------------------

def compute_containment(largest_vessel_gal, rainfall_freeboard_gal, method):
    """Returns required_capacity_gal rounded to 2dp half-up."""
    if method == "SPCC_SIMPLE":
        required = dec(largest_vessel_gal) * dec("1.10")
    else:  # SPCC_WITH_FREEBOARD
        required = dec(largest_vessel_gal) * dec("1.00") + dec(rainfall_freeboard_gal)
    return round2(required)


def compute_compliance(containment_capacity_gal, required_capacity_gal):
    """COMPLIANT when containment >= required (inclusive boundary)."""
    if dec(containment_capacity_gal) >= dec(required_capacity_gal):
        return "COMPLIANT"
    return "DEFICIENT"


# ---------------------------------------------------------------------------
# calculations.spare_selection_score
# ---------------------------------------------------------------------------

def select_spare_unit(unit_type, required_mva, required_voltage_kv, start_ts, end_ts,
                      preferred_impedance_pct=None, site_location=None):
    """Select the best SpareUnit. Returns unit dict or None if pool is empty."""
    candidates = []
    for unit in db.spare_units.values():
        if unit["status"] != "AVAILABLE":
            continue
        if unit["unit_type"] != unit_type:
            continue
        if unit["voltage_class_kv"] != required_voltage_kv:
            continue
        # rating check with mobile derating
        factor = 0.9 if unit_type == "MOBILE_SUBSTATION" else 1.0
        if unit["rating_mva"] < required_mva * factor:
            continue
        # check no ACTIVE reservation overlapping
        has_overlap = False
        for res in db.spare_reservations.values():
            if res["spare_unit_id"] != unit["id"]:
                continue
            if res["status"] != "ACTIVE":
                continue
            r_start = _parse_iso(res["start_ts"])
            r_end = _parse_iso(res["end_ts"])
            if start_ts < r_end and r_start < end_ts:
                has_overlap = True
                break
        if has_overlap:
            continue

        # Compute score
        adequacy = 100.0 * min(1.0, unit["rating_mva"] / required_mva)
        impedance_bonus = 0.0
        if preferred_impedance_pct is not None:
            diff = abs(unit["impedance_pct"] - preferred_impedance_pct)
            impedance_bonus = 25.0 * max(0.0, 1.0 - diff / 4.0)
        location_bonus = 0.0
        if site_location is not None and unit["home_location"] == site_location:
            location_bonus = 10.0
        score = adequacy + impedance_bonus + location_bonus
        candidates.append((score, unit["created_at"], unit))

    if not candidates:
        return None
    # Sort by score DESC, then created_at ASC
    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][2]


# ---------------------------------------------------------------------------
# calculations.work_order_cost_rollup
# ---------------------------------------------------------------------------

def compute_cost_rollup(labor_lines, parts_lines):
    """Returns (cost_subtotal, mobilization_fee, total_cost) all as floats."""
    subtotal = Decimal("0")
    for line in (labor_lines or []):
        hours = dec(line.get("hours", 0))
        rate = dec(line.get("rate_per_hour", 0))
        line_total = (hours * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal += line_total
    for line in (parts_lines or []):
        qty = dec(line.get("quantity", 0))
        price = dec(line.get("unit_price", 0))
        line_total = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal += line_total

    cost_subtotal = float(subtotal)
    # Tier keyed on subtotal
    fee_rate = Decimal("0.04") if subtotal >= Decimal("500.00") else Decimal("0.05")
    mobilization_fee = float((fee_rate * subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    total_cost = float((subtotal + dec(mobilization_fee)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return cost_subtotal, mobilization_fee, total_cost


# ---------------------------------------------------------------------------
# calculations.defect_sla_due_date
# ---------------------------------------------------------------------------

SLA_DAYS = {"C1": 30, "C2": 90, "C3": 365}


def compute_defect_due_date(created_at_iso, severity):
    """due_date = date(created_at) + SLA_DAYS[severity] days, as ISO date string."""
    created = _parse_iso(created_at_iso)
    created_date = created.date()
    due = created_date + timedelta(days=SLA_DAYS[severity])
    return due.isoformat()


# ---------------------------------------------------------------------------
# calculations.certification_status
# ---------------------------------------------------------------------------

def compute_certification_status(cert):
    """Derived status from revoked_at, expires_at, and logical clock."""
    if cert.get("revoked_at") is not None:
        return "REVOKED"
    now = db.now_dt()
    expires = _parse_iso(cert["expires_at"])
    if now >= expires:
        return "EXPIRED"
    return "ACTIVE"


# ---------------------------------------------------------------------------
# calculations.certification_gate
# ---------------------------------------------------------------------------

CERT_RANK = {
    "NETA_LEVEL_2": 2,
    "NETA_LEVEL_3": 3,
    "NETA_LEVEL_4": 4,
    "SWITCHING_QUALIFIED": 0,
}


def check_certification_gate(technician_id, required_cert_type):
    """Check if technician holds at least one ACTIVE cert with rank >= required.
    Returns True/False."""
    required_rank = CERT_RANK.get(required_cert_type, 0)
    for cert in db.technician_certifications.values():
        if cert["technician_id"] != technician_id:
            continue
        cert_rank = CERT_RANK.get(cert["cert_type"], 0)
        if cert_rank < required_rank:
            continue
        if compute_certification_status(cert) == "ACTIVE":
            return True
    return False
