"""Pure arithmetic: money, tiers, scores, overlap geometry.

All money is whole cents held as int; every fractional result is rounded HALF UP
exactly where the PRD pins the rounding step.  No float ever touches a monetary
computation.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

ONE = Decimal(1)


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def rhu(value):
    """Round half up to a whole cent."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_dp(value, places):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# escalating_false_alarm_fee  (PRD 3.5)
# ---------------------------------------------------------------------------

def marginal_tier_base(sched, index):
    base = 0
    for tier in (sched.get("fee_tiers") or []):
        if not isinstance(tier, dict):
            continue
        frm = tier.get("from_index")
        to = tier.get("to_index")
        if frm is None:
            continue
        if index >= frm and (to is None or index <= to):
            base = int(tier.get("base_fee_cents") or 0)
            break
    if index <= int(sched.get("free_alarm_allowance") or 0):
        base = 0
    return base


def occupancy_multiplier(sched, occupancy_class):
    table = sched.get("occupancy_multipliers") or {}
    if occupancy_class in table:
        return D(table[occupancy_class])
    return ONE


def compute_false_alarm_fee(sched, site, req, index, aggravated):
    """Four pinned steps with exactly one rounding (step 3)."""
    tier_base = marginal_tier_base(sched, index)
    occ_mult = occupancy_multiplier(sched, site.get("occupancy_class"))
    non_ecv = req.get("verification_method") in ("NONE", "SINGLE_CALL")
    surcharge_factor = (ONE + D(sched.get("non_ecv_surcharge_pct"))) if non_ecv else ONE
    unpermitted = req.get("system_permitted_at_occurrence") is False
    unpermitted_factor = D(sched.get("unpermitted_multiplier")) if unpermitted else ONE

    raw = rhu(D(tier_base) * occ_mult * surcharge_factor * unpermitted_factor)
    cap = int(sched.get("per_incident_fee_cap_cents") or 0)
    cap_applied = raw > cap
    capped = cap if cap_applied else raw
    aggravation = int(sched.get("suspension_period_aggravation_cents") or 0) if aggravated else 0
    assessed = capped + aggravation

    basis = {
        "tier_base_cents": tier_base,
        "occupancy_multiplier": float(occ_mult),
        "non_ecv_surcharge_applied": bool(non_ecv),
        "unpermitted_multiplier_applied": bool(unpermitted),
        "cap_applied": bool(cap_applied),
        "aggravation_cents": aggravation,
    }
    detail = {
        "tier_base_cents": tier_base,
        "line_multiplier": occ_mult * surcharge_factor * unpermitted_factor,
        "cap_applied": bool(cap_applied),
        "cap_cents": cap,
        "aggravation_cents": aggravation,
    }
    return assessed, basis, detail


# ---------------------------------------------------------------------------
# invoice_assembly  (PRD 3.8)
# ---------------------------------------------------------------------------

def make_line(code, description, unit_amount_cents, quantity, multiplier):
    extended = rhu(D(unit_amount_cents) * D(quantity) * D(multiplier))
    return {
        "code": code,
        "description": description,
        "unit_amount_cents": int(unit_amount_cents),
        "quantity": int(quantity),
        "multiplier": float(D(multiplier)),
        "extended_cents": extended,
    }


def false_alarm_lines(sched, detail):
    lines = []
    line = make_line("FALSE_ALARM_BASE", "False alarm base fee",
                     detail["tier_base_cents"], 1, detail["line_multiplier"])
    if detail["cap_applied"]:
        line["extended_cents"] = int(detail["cap_cents"])
    lines.append(line)
    if detail["aggravation_cents"] > 0:
        lines.append(make_line("SUSPENSION_PERIOD_AGGRAVATION",
                               "Suspension period aggravation",
                               detail["aggravation_cents"], 1, ONE))
    return lines


def permit_issue_lines(sched):
    return [make_line("PERMIT_ISSUE", "Alarm permit issuance fee",
                      int(sched.get("permit_issue_fee_cents") or 0), 1, ONE)]


def permit_renewal_lines(sched, late_fee_cents):
    lines = [make_line("PERMIT_RENEWAL", "Alarm permit renewal fee",
                       int(sched.get("permit_renewal_fee_cents") or 0), 1, ONE)]
    if late_fee_cents > 0:
        lines.append(make_line("LATE_RENEWAL", "Late renewal fee",
                               int(late_fee_cents), 1, ONE))
    return lines


def unpermitted_penalty_lines(sched):
    return [make_line("UNPERMITTED_OPERATION", "Unpermitted operation penalty",
                      int(sched.get("unpermitted_operation_penalty_cents") or 0),
                      1, ONE)]


def reinstatement_lines(sched, prior_lifted_count):
    multiplier = ONE + D(sched.get("reinstatement_escalation_pct")) * D(prior_lifted_count)
    return [make_line("REINSTATEMENT", "Police response reinstatement fee",
                      int(sched.get("reinstatement_base_fee_cents") or 0), 1,
                      multiplier)]


def admin_fee_for(sched, subtotal_cents):
    raw = rhu(D(subtotal_cents) * D(sched.get("admin_fee_pct")))
    lo = int(sched.get("admin_fee_min_cents") or 0)
    hi = int(sched.get("admin_fee_max_cents") or 0)
    return min(max(raw, lo), hi)


def reinstatement_fee_cents(sched, prior_lifted_count):
    return rhu(D(sched.get("reinstatement_base_fee_cents"))
               * (ONE + D(sched.get("reinstatement_escalation_pct"))
                  * D(prior_lifted_count)))


# ---------------------------------------------------------------------------
# permit_renewal_fee  (PRD 3.3)
# ---------------------------------------------------------------------------

def late_renewal_fee(sched, days_late):
    if days_late <= 0:
        return 0
    for tier in (sched.get("late_renewal_tiers") or []):
        if not isinstance(tier, dict):
            continue
        cap = tier.get("max_days_late")
        if cap is None or days_late <= int(cap):
            return int(tier.get("fee_cents") or 0)
    return 0


# ---------------------------------------------------------------------------
# delinquency_escalation  (PRD 3.8)
# ---------------------------------------------------------------------------

def collections_admin_charge(interim_total):
    if interim_total <= 25000:
        return 2000
    if interim_total <= 100000:
        return rhu(D(interim_total) * D("0.08"))
    return 10000


def referral_total(interim_total):
    return interim_total + collections_admin_charge(interim_total)


# ---------------------------------------------------------------------------
# compliance_report_period_metrics / company score  (PRD 3.10)
# ---------------------------------------------------------------------------

def period_metrics(reported_dispatch_count, ecv_attempt_count, system_dispatch_count):
    variance_count = abs(int(reported_dispatch_count) - int(system_dispatch_count))
    denom = max(1, int(system_dispatch_count))
    variance_pct = rhu_dp(D(variance_count) / D(denom), 4)
    accuracy = rhu_dp(ONE - min(ONE, variance_pct), 4)
    ecv_denom = max(1, int(reported_dispatch_count))
    ecv_rate = rhu_dp(min(ONE, D(ecv_attempt_count) / D(ecv_denom)), 4)
    score = rhu_dp(D("0.6") * accuracy + D("0.4") * ecv_rate, 2)
    return {
        "variance_count": variance_count,
        "variance_pct": float(variance_pct),
        "period_accuracy": float(accuracy),
        "period_ecv_rate": float(ecv_rate),
        "period_score": float(score),
    }


def company_score(score_mode, periods):
    """periods: list of (period_score, system_dispatch_count) already windowed."""
    if not periods:
        return float(rhu_dp(ONE, 2))
    if score_mode == "PERIOD_EQUAL":
        total = sum((D(p[0]) for p in periods), Decimal(0))
        return float(rhu_dp(total / D(len(periods)), 2))
    weight = sum(int(p[1]) for p in periods)
    if weight == 0:
        total = sum((D(p[0]) for p in periods), Decimal(0))
        return float(rhu_dp(total / D(len(periods)), 2))
    numer = sum((D(p[0]) * D(p[1]) for p in periods), Decimal(0))
    return float(rhu_dp(numer / D(weight), 2))


# ---------------------------------------------------------------------------
# overlap geometry
# ---------------------------------------------------------------------------

BUFFER = timedelta(minutes=15)


def docket_sessions_conflict(new_start, new_end, old_start, old_end):
    """Half-open intervals, symmetric 15-minute buffer, both arms strict."""
    return new_start < (old_end + BUFFER) and old_start < (new_end + BUFFER)


def suspension_periods_conflict(new_from, new_through, old_from, old_through):
    """Closed intervals, zero buffer; touching endpoints collide."""
    return new_from <= old_through and old_from <= new_through
