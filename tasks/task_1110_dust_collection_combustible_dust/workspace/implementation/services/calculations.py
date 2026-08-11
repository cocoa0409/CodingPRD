"""Calculation rules per SCAFFOLD §1.3 and PRD §2.4, §2.7, §3."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dec(value):
    return Decimal(str(value))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return _dec(value).quantize(q, rounding=ROUND_HALF_UP)


def _to_float(d):
    return float(d)


# ---------------------------------------------------------------------------
# kst_classify
# ---------------------------------------------------------------------------
def kst_classify(sample, site):
    """Derive sample_class and combustible for a DustSample.

    Insurer-conservative variant when site.insurer_id startswith 'IC-':
      ST1 <= 150, ST2 <= 250, ST3 > 250.
    Default NFPA bands: ST1 <= 200, ST2 <= 300, ST3 > 300.
    """
    kst = _dec(sample["kst_bar_m_per_s"])
    conservative = str(site.get("insurer_id", "")).startswith("IC-")
    st1_max = Decimal("150") if conservative else Decimal("200")
    st2_max = Decimal("250") if conservative else Decimal("300")

    if kst == 0:
        sample["sample_class"] = "ST0"
    elif kst <= st1_max:
        sample["sample_class"] = "ST1"
    elif kst <= st2_max:
        sample["sample_class"] = "ST2"
    else:
        sample["sample_class"] = "ST3"
    sample["combustible"] = bool(kst > 0)


# ---------------------------------------------------------------------------
# explosion_protection_design
# ---------------------------------------------------------------------------
def explosion_protection_design(collector, dust_sample):
    """Compute pred_max_bar_g, required_vent_area_m2, vent_adequate,
    air_to_cloth_ratio for a Collector."""
    kst = _dec(dust_sample["kst_bar_m_per_s"])
    pmax = _dec(dust_sample["pmax_bar_g"])
    v = _dec(collector["internal_volume_m3"])

    # Pred_max = min(Pmax * 0.5, 0.5 + 0.04 * Kst**0.5)
    half_pmax = pmax * Decimal("0.5")
    # sqrt on Decimal: use float for the power then back to Decimal
    kst_sqrt = Decimal(str(float(kst) ** 0.5))
    alt = Decimal("0.5") + Decimal("0.04") * kst_sqrt
    pred_max = half_pmax if half_pmax < alt else alt

    # Av0 = 0.1 * Kst * V**(2/3)
    v_pow = Decimal(str(float(v) ** (2.0 / 3.0)))
    av0 = Decimal("0.1") * kst * v_pow

    denom = pred_max if pred_max > Decimal("0.05") else Decimal("0.05")
    ratio = Decimal(str(float(pmax / denom) ** 0.5))
    req_area = av0 * ratio

    # performance-based variant: internal_volume_m3 > 25 -> 1.20 multiplier
    if float(v) > 25:
        req_area = req_area * Decimal("1.20")

    collector["pred_max_bar_g"] = _to_float(round_half_up(pred_max, 3))
    collector["required_vent_area_m2"] = _to_float(round_half_up(req_area, 3))
    collector["vent_adequate"] = bool(
        _dec(collector.get("installed_vent_area_m2", 0))
        >= _dec(collector["required_vent_area_m2"])
    )

    # air_to_cloth_ratio 4dp
    if _dec(collector["filter_area_ft2"]) > 0:
        ratio_ac = _dec(collector["design_airflow_acfm"]) / _dec(collector["filter_area_ft2"])
        collector["air_to_cloth_ratio"] = _to_float(round_half_up(ratio_ac, 4))


# ---------------------------------------------------------------------------
# dp_trend_derivation
# ---------------------------------------------------------------------------
DP_HIGH_ALARM = Decimal("6.0")
DP_SLOPE_DELTA = Decimal("1.5")
FILTER_MAX_AGE_DAYS = 180
LOOKBACK = 5


def dp_trend_derivation(collector):
    """Recompute dp_trend and filter_change_due for a Collector from its
    last-5 readings plus last_filter_change_at."""
    readings = db.dp_readings.get(collector["id"], [])
    window = readings[-LOOKBACK:]
    current = _dec(collector["dp_current_inwc"])

    if current >= DP_HIGH_ALARM:
        collector["dp_trend"] = "ALARM_HIGH"
    elif len(window) >= 3:
        delta = _dec(window[-1]["dp_inwc"]) - _dec(window[-3]["dp_inwc"])
        if delta >= DP_SLOPE_DELTA:
            collector["dp_trend"] = "RISING"
        else:
            collector["dp_trend"] = "STABLE"
    else:
        collector["dp_trend"] = "STABLE"

    due = current >= DP_HIGH_ALARM
    lfca = collector.get("last_filter_change_at_dt")
    if lfca is not None:
        if db.now_dt() - lfca >= timedelta(days=FILTER_MAX_AGE_DAYS):
            due = True
    collector["filter_change_due"] = bool(due)


# ---------------------------------------------------------------------------
# housekeeping_schedule
# ---------------------------------------------------------------------------
DUE_SOON_WINDOW_HOURS = 24


def housekeeping_schedule(program):
    """Derive current_posture and next_due_at for a HousekeepingProgram."""
    last = program.get("last_audit_at_dt")
    if last is None:
        program["current_posture"] = "OVERDUE"
        program["next_due_at"] = None
        program["next_due_at_dt"] = None
        return
    next_due = last + timedelta(hours=program["frequency_hours"])
    program["next_due_at_dt"] = next_due
    program["next_due_at"] = db.iso(next_due)
    now = db.now_dt()
    if now > next_due:
        program["current_posture"] = "OVERDUE"
    elif now > next_due - timedelta(hours=DUE_SOON_WINDOW_HOURS):
        program["current_posture"] = "DUE_SOON"
    else:
        program["current_posture"] = "CURRENT"


# ---------------------------------------------------------------------------
# dha_kst_rollup
# ---------------------------------------------------------------------------
RANK = {"ST0": 0, "ST1": 1, "ST2": 2, "ST3": 3}


def dha_kst_rollup(dha):
    linked_ids = db.dha_samples.get(dha["id"], [])
    highest = "ST0"
    for sid in linked_ids:
        sample = db.dust_samples.get(sid)
        if sample and sample.get("combustible"):
            if RANK[sample["sample_class"]] > RANK[highest]:
                highest = sample["sample_class"]
    dha["kst_class_highest"] = highest


# ---------------------------------------------------------------------------
# dha_risk_score
# ---------------------------------------------------------------------------
def dha_risk_score(dha, site):
    dust_sub_total = Decimal("0")
    for sid in db.dha_samples.get(dha["id"], []):
        sample = db.dust_samples.get(sid)
        if sample and sample.get("combustible"):
            sub = Decimal(RANK[sample["sample_class"]] * 8) + max(
                Decimal("0"), Decimal("10") - _dec(sample["mie_mj"])
            )
            dust_sub_total += round_half_up(sub, 2)

    collector_sub = Decimal("0")
    for col in db.collectors.values():
        if col["site_id"] == site["id"] and col["status"] == "IN_SERVICE":
            sub = Decimal("0")
            if col.get("filter_change_due"):
                sub += Decimal("3")
            if col.get("dp_trend") == "ALARM_HIGH":
                sub += Decimal("5")
            if col.get("dp_trend") == "RISING":
                sub += Decimal("3")
            if not col.get("vent_adequate"):
                sub += Decimal("12")
            collector_sub += round_half_up(sub, 2)

    finding_sub = Decimal(6 * site.get("open_critical_findings", 0)) + Decimal(
        2 * site.get("open_overdue_housekeeping", 0)
    )
    hotwork_sub = Decimal(4 * site.get("hot_work_in_progress", 0))

    raw = dust_sub_total + collector_sub + finding_sub + hotwork_sub
    score = raw if raw <= Decimal("100") else Decimal("100")
    dha["risk_score"] = _to_float(score)


# ---------------------------------------------------------------------------
# site_posture_derivation
# ---------------------------------------------------------------------------
def site_posture_derivation(site):
    score = 100
    score -= 25 * min(site.get("open_critical_findings", 0), 2)
    score -= 10 * min(site.get("open_overdue_housekeeping", 0), 3)
    score -= 5 * min(site.get("hot_work_in_progress", 0), 3)

    for col in db.collectors.values():
        if (
            col["site_id"] == site["id"]
            and col["status"] == "IN_SERVICE"
            and not col.get("vent_adequate")
        ):
            score -= 20
            break

    for inc in db.incidents.values():
        if inc["site_id"] == site["id"] and inc["status"] in (
            "OPEN",
            "INVESTIGATING",
            "CAPA_DEFINED",
        ):
            score -= 15
            break

    for proj in db.retrofit_projects.values():
        if proj["site_id"] == site["id"] and proj["status"] in (
            "APPROVED",
            "IN_EXECUTION",
        ):
            score -= 8
            break

    posture_score = max(0, score)
    site["posture_score"] = posture_score

    if site.get("open_critical_findings", 0) >= 2:
        site["posture"] = "STOP_WORK"
    elif posture_score >= 85:
        site["posture"] = "COMPLIANT"
    elif posture_score >= 60:
        site["posture"] = "CONDITIONAL"
    else:
        site["posture"] = "DEFICIENT"


# ---------------------------------------------------------------------------
# retrofit_contingency
# ---------------------------------------------------------------------------
RATES = {
    "LOW": Decimal("0.05"),
    "MEDIUM": Decimal("0.12"),
    "HIGH": Decimal("0.22"),
}


def retrofit_contingency(project, site):
    """Recompute estimated_cost_cents, contingency_cents,
    contingency_rounding_cents, total_projected_cents."""
    lines = [
        li for li in db.retrofit_line_items.values() if li["project_id"] == project["id"]
    ]
    estimated = sum(int(li["cost_cents"]) for li in lines)

    conservative = str(site.get("insurer_id", "")).startswith("IC-")

    if not conservative:
        # per_line_then_sum (default)
        per_line = []
        for li in lines:
            raw = Decimal(int(li["cost_cents"])) * RATES[li["risk_tier"]]
            rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            per_line.append(rounded)
        contingency_gross = sum(per_line)
        contingency = contingency_gross
    else:
        # sum_then_round variant
        gross = Decimal("0")
        for li in lines:
            gross += Decimal(int(li["cost_cents"])) * RATES[li["risk_tier"]]
        contingency = int(gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        contingency_gross = contingency

    rounding_remainder = (estimated + contingency) - (estimated + contingency_gross)

    project["estimated_cost_cents"] = estimated
    project["contingency_cents"] = contingency
    project["contingency_rounding_cents"] = rounding_remainder
    project["total_projected_cents"] = estimated + contingency


# ---------------------------------------------------------------------------
# overdue_housekeeping_counter
# ---------------------------------------------------------------------------
def recompute_open_overdue_housekeeping(site):
    count = 0
    for audit in db.housekeeping_audits.values():
        if audit["status"] != "OVERDUE":
            continue
        program = db.housekeeping_programs.get(audit["program_id"])
        if program and program["site_id"] == site["id"]:
            count += 1
    site["open_overdue_housekeeping"] = count
