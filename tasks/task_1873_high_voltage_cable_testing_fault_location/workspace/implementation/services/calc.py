"""Calculation rules (scaffold table 3 / PRD sections 2.8 and 3).

All rounding is round-half-up; money is integer cents; pinned rounding orders
are followed exactly as specified.
"""
from decimal import Decimal

import db
import util

# ------------------------------------------------------------------ constants
U0_KV = {
    "KV_15": Decimal("8.7"),
    "KV_25": Decimal("14.4"),
    "KV_35": Decimal("20.3"),
    "KV_69": Decimal("39.8"),
}
VF_STD = {
    "KV_15": Decimal("0.52"),
    "KV_25": Decimal("0.52"),
    "KV_35": Decimal("0.52"),
    "KV_69": Decimal("0.53"),
}
VELOCITY_M_PER_US = Decimal("300")
CORRIDOR_MIN_M = Decimal("5.0")

TD_PASS_MAX = Decimal("5.0")
TD_FAIL_MIN = Decimal("80.0")
TIP_UP_FAIL = Decimal("12.0")
PD_MONITOR_MIN = Decimal("500")
PD_FAIL_MIN = Decimal("2000")

GRACE_MIN = 15
RATE_T1 = Decimal("400")
RATE_T2 = Decimal("650")
RATE_T3 = Decimal("900")
EMERGENCY_MULT = Decimal("1.25")
ESTIMATE_OVERRUN_FRACTION = Decimal("0.10")

CALLOUT_CENTS = 180000
PER_METER_CENTS = 125
METHOD_FEE = {"VLF_TAN_DELTA": 95000, "VLF_WITH_PD": 145000, "PD_MAPPING": 120000}
COMPLEX_THRESHOLD_CENTS = 400000
RATE_COMPLEX = Decimal("0.12")
RATE_STANDARD = Decimal("0.06")

MARKUP = Decimal("0.085")

W_TD = Decimal("0.35")
W_PD = Decimal("0.30")
W_FAULT = Decimal("0.20")
W_AGE = Decimal("0.15")

VOLTAGE_CLASSES = ("KV_15", "KV_25", "KV_35", "KV_69")
TEST_METHODS = ("VLF_TAN_DELTA", "VLF_WITH_PD", "PD_MAPPING")
VLF_METHODS = ("VLF_TAN_DELTA", "VLF_WITH_PD")
WINDOW_KINDS = ("PLANNED_DIAGNOSTIC", "EMERGENCY_FAULT", "REPAIR_RESTORE")
SPLICE_TYPES = ("HEAT_SHRINK", "COLD_SHRINK", "PREMOLDED")
UNIT_CAPABILITIES = ("VLF", "PD", "TDR")
PINPOINT_METHODS = ("PULSE_ECHO", "ARC_REFLECTION")
ASSESSMENT_BASES = ("FORMAL", "PROVISIONAL")

METHOD_CAPABILITY = {
    "VLF_TAN_DELTA": {"VLF"},
    "VLF_WITH_PD": {"VLF", "PD"},
    "PD_MAPPING": {"PD"},
}

_WORSE = {"PASS": 0, "MONITOR": 1, "FAIL": 2}


# ------------------------------------------------------------------ verdicts
def _td_part(rounded_by_step):
    """Tan-delta part verdict; rounded_by_step maps step_index -> Decimal."""
    vals = list(rounded_by_step.values())
    max_td = max(vals)
    if max_td >= TD_FAIL_MIN:
        return "FAIL"
    if (rounded_by_step[2] - rounded_by_step[0]) >= TIP_UP_FAIL:
        return "FAIL"
    if max_td < TD_PASS_MAX:
        return "PASS"
    return "MONITOR"


def _pd_part(pd_vals):
    max_pd = max(pd_vals)
    if max_pd >= PD_FAIL_MIN:
        return "FAIL"
    if max_pd >= PD_MONITOR_MIN:
        return "MONITOR"
    return "PASS"


def _correction_factor(ambient_temp_c):
    k = Decimal("1") + (Decimal("20") - ambient_temp_c) * Decimal("0.01")
    if k < Decimal("0.9"):
        return Decimal("0.9")
    if k > Decimal("1.1"):
        return Decimal("1.1")
    return k


def compute_verdicts(method, readings, use_temperature_correction):
    """Return (verdict_as_tested, verdict_temp_corrected, official, max_td, max_pd).

    readings: list of reading records (all steps present, enforced by caller).
    """
    by_step = {r["step_index"]: r for r in readings}
    steps = sorted(by_step)

    as_tested = None
    corrected = None
    max_td = None
    max_pd = None

    if method in VLF_METHODS:
        raw = {i: util.dec(by_step[i]["tan_delta_e3"]) for i in steps}
        rounded_raw = {i: util.rhu(raw[i], 1) for i in steps}
        max_td = max(rounded_raw.values())
        as_tested = _td_part(rounded_raw)
        rounded_corr = {
            i: util.rhu(raw[i] * _correction_factor(util.dec(by_step[i]["ambient_temp_c"])), 1)
            for i in steps
        }
        corrected = _td_part(rounded_corr)

    if method in ("VLF_WITH_PD", "PD_MAPPING"):
        pd_vals = [util.dec(by_step[i]["pd_level_pc"]) for i in steps]
        max_pd = max(pd_vals)
        pd_verdict = _pd_part(pd_vals)
        as_tested = pd_verdict if as_tested is None else (
            as_tested if _WORSE[as_tested] >= _WORSE[pd_verdict] else pd_verdict
        )
        corrected = pd_verdict if corrected is None else (
            corrected if _WORSE[corrected] >= _WORSE[pd_verdict] else pd_verdict
        )

    official = corrected if use_temperature_correction else as_tested
    return as_tested, corrected, official, max_td, max_pd


# ------------------------------------------------------------------ pinpoint
def pinpoint_distances(circuit, trace_time_us, use_calibrated_velocity):
    """Return dict of velocity_factor_used, pinpointed_distance_m,
    alternate_distance_m, corridor_start_m, corridor_end_m (Decimals)."""
    vf_standard = VF_STD[circuit["voltage_class"]]
    cal = circuit.get("calibrated_velocity_factor")
    vf_calibrated = util.dec(cal) if cal is not None else vf_standard
    t = util.dec(trace_time_us)

    def dist(vf):
        return util.rhu(vf * VELOCITY_M_PER_US * t / Decimal("2"), 1)

    selected = vf_calibrated if use_calibrated_velocity else vf_standard
    other = vf_standard if use_calibrated_velocity else vf_calibrated
    d_sel = dist(selected)
    d_alt = dist(other)
    half_width = max(CORRIDOR_MIN_M, util.rhu(Decimal("0.10") * d_sel, 1))
    return {
        "velocity_factor_used": selected,
        "pinpointed_distance_m": d_sel,
        "alternate_distance_m": d_alt,
        "corridor_start_m": util.rhu(d_sel - half_width, 1),
        "corridor_end_m": util.rhu(d_sel + half_width, 1),
    }


# ------------------------------------------------------------------ overrun charge
def overrun_charge_cents(overrun_min, kind):
    chargeable = overrun_min - GRACE_MIN if overrun_min > GRACE_MIN else 0
    t1 = min(chargeable, 60)
    t2 = min(max(chargeable - 60, 0), 120)
    t3 = max(chargeable - 180, 0)
    mult = EMERGENCY_MULT if kind == "EMERGENCY_FAULT" else Decimal("1.0")
    seg1 = util.rhu(Decimal(t1) * RATE_T1 * mult, 0)
    seg2 = util.rhu(Decimal(t2) * RATE_T2 * mult, 0)
    seg3 = util.rhu(Decimal(t3) * RATE_T3 * mult, 0)
    return int(seg1 + seg2 + seg3)


def estimated_charge_cents(duration_minutes, kind):
    est_overrun = util.ceil_dec(Decimal(duration_minutes) * ESTIMATE_OVERRUN_FRACTION)
    return overrun_charge_cents(est_overrun, kind)


# ------------------------------------------------------------------ job estimate / invoice
def job_estimate_cents(circuit, requested_methods):
    subtotal = (
        CALLOUT_CENTS
        + int(util.rhu(Decimal(PER_METER_CENTS) * Decimal(circuit["length_m"]), 0))
        + sum(METHOD_FEE[m] for m in requested_methods)
    )
    rate = RATE_COMPLEX if subtotal > COMPLEX_THRESHOLD_CENTS else RATE_STANDARD
    return int(util.rhu(Decimal(subtotal) * (Decimal("1") + rate), 0))


def job_invoice(job):
    job_fault_ids = [f["id"] for f in db.faults.values() if f["test_job_id"] == job["id"]]
    exc_total = 0
    for e in db.excavations.values():
        if e["fault_record_id"] in job_fault_ids and e["status"] != "CANCELLED":
            exc_total += int(util.rhu(Decimal(e["cost_cents"]) * (Decimal("1") + MARKUP), 0))
    splice_total = 0
    for s in db.splices.values():
        if s["fault_record_id"] in job_fault_ids:
            splice_total += int(util.rhu(Decimal(s["cost_cents"]) * (Decimal("1") + MARKUP), 0))
    estimate = job["estimate_cents"]
    total = (estimate or 0) + exc_total + splice_total
    return {
        "estimate_cents": estimate,
        "excavation_total_cents": exc_total,
        "splice_total_cents": splice_total,
        "invoice_total_cents": total,
    }


# ------------------------------------------------------------------ health score
def _band(score):
    if score >= Decimal("80"):
        return "GOOD"
    if score >= Decimal("60"):
        return "FAIR"
    if score >= Decimal("40"):
        return "POOR"
    return "CRITICAL"


_ACTION = {
    "GOOD": "NONE",
    "FAIR": "MONITOR",
    "POOR": "PLAN_REPLACEMENT",
    "CRITICAL": "URGENT_REPLACEMENT",
}


def _td_pen(metric):
    if metric is None:
        return 0
    if metric < Decimal("5"):
        return 0
    if metric < Decimal("20"):
        return 20
    if metric < Decimal("80"):
        return 60
    return 100


def _pd_pen(metric):
    if metric is None:
        return 0
    if metric < Decimal("100"):
        return 0
    if metric < Decimal("500"):
        return 25
    if metric < Decimal("2000"):
        return 55
    return 100


def compute_health(circuit, basis):
    circuit_job_ids = [j["id"] for j in db.jobs.values() if j["circuit_id"] == circuit["id"]]
    if basis == "FORMAL":
        wanted = ("ACCEPTED",)
    else:
        wanted = ("EVALUATED", "ACCEPTED")
    included = [
        s for s in db.series.values()
        if s["test_job_id"] in circuit_job_ids and s["status"] in wanted
    ]
    td_vals = [s["max_tan_delta_e3"] for s in included if s["max_tan_delta_e3"] is not None]
    pd_vals = [s["max_pd_pc"] for s in included if s["max_pd_pc"] is not None]
    td_pen = _td_pen(max(td_vals) if td_vals else None)
    pd_pen = _pd_pen(max(pd_vals) if pd_vals else None)
    fault_pen = min(
        100,
        25 * circuit["unresolved_fault_count"] + 10 * circuit["resolved_fault_count_24m"],
    )
    age_years = db.now().year - circuit["installation_year"]
    age_pen = min(100, max(0, (age_years - 25) * 5))
    penalty = util.rhu(
        W_TD * td_pen + W_PD * pd_pen + W_FAULT * fault_pen + W_AGE * age_pen, 1
    )
    score = util.rhu(Decimal("100") - penalty, 1)
    band = _band(score)
    return {
        "health_index_score": score,
        "band": band,
        "recommended_action": _ACTION[band],
        "penalty_components": {
            "td_pen": td_pen,
            "pd_pen": pd_pen,
            "fault_pen": fault_pen,
            "age_pen": age_pen,
        },
    }
