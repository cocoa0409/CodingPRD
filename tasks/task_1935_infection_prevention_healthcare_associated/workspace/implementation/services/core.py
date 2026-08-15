"""Core shared services: entity factory, posture recompute, summary recompute, cluster detection."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from util import cal_date, clock, midnight_utc, new_id, parse_dt, end_of_day_utc
from util import now_ts  # noqa: F401  (kept for parity with sibling implementations)


# ---------------------------------------------------------------------------
# Entity factory
# ---------------------------------------------------------------------------
def new_entity(extra=None):
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc)
    e = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    if extra:
        e.update(extra)
    return e


def touch(e):
    """Every mutation refreshes updated_at and increments version (PRD §2.4)."""
    from datetime import datetime, timezone
    e["updated_at"] = datetime.now(timezone.utc)
    e["version"] += 1


# ---------------------------------------------------------------------------
# Rounding helpers (PRD §2.7)
# ---------------------------------------------------------------------------
def round3(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def round1(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Unit surveillance posture (PRD §2.9)
# ---------------------------------------------------------------------------
ELEVATED_CAP_STATUSES = ("ACTIVE", "VERIFICATION_PENDING", "ESCALATED")


def compute_posture(unit_id: str) -> str:
    for o in db.outbreak_investigations.values():
        if o["unit_id"] == unit_id and o["status"] == "CONFIRMED":
            return "OUTBREAK"
    for o in db.outbreak_investigations.values():
        if o["unit_id"] == unit_id and o["status"] == "TRIGGERED":
            return "ELEVATED"
    for c in db.corrective_action_plans.values():
        if c["unit_id"] == unit_id and c["status"] in ELEVATED_CAP_STATUSES:
            return "ELEVATED"
    return "NORMAL"


def recompute_posture(unit_id: str):
    """Recompute a unit's posture. A posture change mutates the unit (version bump).

    Cascades never skip a target that 'looks unchanged' for *summary recomputes*;
    posture, however, is a pure derived function — we bump the unit version only
    when the computed value actually changes (a recompute that yields the same
    posture is a no-op on the unit row).
    """
    unit = db.units.get(unit_id)
    if unit is None:
        return
    new = compute_posture(unit_id)
    if new != unit["surveillance_posture"]:
        unit["surveillance_posture"] = new
        touch(unit)


# ---------------------------------------------------------------------------
# MonthlySummary computation (PRD §3.7)
# ---------------------------------------------------------------------------
MUTABLE_SUMMARY_STATUSES = ("OPEN", "REJECTED", "UNDER_AMENDMENT")


def risk_weight(proc) -> Decimal:
    if proc["asa_score"] >= 4 or proc["wound_class"] in ("CONTAMINATED", "DIRTY"):
        return Decimal("2.0")
    if proc["asa_score"] <= 2 and proc["wound_class"] == "CLEAN":
        return Decimal("1.0")
    return Decimal("1.5")


def _month_bounds(month: str):
    y, m = int(month[:4]), int(month[5:7])
    start = midnight_utc(__import__("datetime").date(y, m, 1))
    if m == 12:
        end = midnight_utc(__import__("datetime").date(y + 1, 1, 1))
    else:
        end = midnight_utc(__import__("datetime").date(y, m + 1, 1))
    return start, end  # half-open [start, end)


def find_covering_summary(unit_id: str, dt):
    """MonthlySummary for (unit, calendar month of dt), or None."""
    d = cal_date(dt)
    month = f"{d.year:04d}-{d.month:02d}"
    for s in db.monthly_summaries.values():
        if s["unit_id"] == unit_id and s["month"] == month:
            return s
    return None


def summary_locked(unit_id: str, dt) -> bool:
    s = find_covering_summary(unit_id, dt)
    return s is not None and s["status"] not in MUTABLE_SUMMARY_STATUSES


def recompute_summary(summary):
    """Full recompute of a summary's derived fields; increments its version."""
    from datetime import date as _date
    unit = db.units[summary["unit_id"]]
    facility = db.facilities[unit["facility_id"]]
    start, end = _month_bounds(summary["month"])

    cl_days = uc_days = vent_days = pat_days = 0
    for r in db.device_day_counts.values():
        if r["unit_id"] == summary["unit_id"] and start <= r["count_date"] < end:
            cl_days += r["central_line_days"]
            uc_days += r["urinary_catheter_days"]
            vent_days += r["ventilator_days"]
            pat_days += r["patient_days"]

    procs = [
        p for p in db.surgical_procedures.values()
        if p["unit_id"] == summary["unit_id"] and start <= p["performed_at"] < end
    ]
    procedure_count = len(procs)
    total_risk = sum((risk_weight(p) for p in procs), Decimal("0"))

    def _count_final(case_type):
        n = 0
        for c in db.infection_cases.values():
            if (
                c["unit_id"] == summary["unit_id"]
                and c["case_type"] == case_type
                and c["status"] == "ADJUDICATED_HAI"
                and c["date_of_event"] is not None
                and start <= c["date_of_event"] < end
            ):
                n += 1
        return n

    def _count_provisional(case_type, final):
        n = final
        for c in db.infection_cases.values():
            if (
                c["unit_id"] == summary["unit_id"]
                and c["case_type"] == case_type
                and c["status"] == "UNDER_REVIEW"
                and start <= c["first_positive_specimen_at"] < end
            ):
                n += 1
        return n

    clabsi = _count_final("CLABSI")
    cauti = _count_final("CAUTI")
    ssi = _count_final("SSI")

    pred_clabsi = round3(Decimal(str(facility["clabsi_baseline_per_1000"])) * Decimal(cl_days) / Decimal(1000))
    pred_cauti = round3(Decimal(str(facility["cauti_baseline_per_1000"])) * Decimal(uc_days) / Decimal(1000))
    pred_ssi = round3(Decimal(str(facility["ssi_baseline_per_procedure"])) * total_risk)

    def _sir(observed, predicted):
        if predicted < Decimal("1.0"):
            return None
        return round3(Decimal(observed) / predicted)

    sir_clabsi = _sir(clabsi, pred_clabsi)
    sir_cauti = _sir(cauti, pred_cauti)
    sir_ssi = _sir(ssi, pred_ssi)

    prov_clabsi = _count_provisional("CLABSI", clabsi)
    prov_cauti = _count_provisional("CAUTI", cauti)
    prov_ssi = _count_provisional("SSI", ssi)
    prov_sir_clabsi = _sir(prov_clabsi, pred_clabsi)
    prov_sir_cauti = _sir(prov_cauti, pred_cauti)
    prov_sir_ssi = _sir(prov_ssi, pred_ssi)

    sirs = [s for s in (sir_clabsi, sir_cauti, sir_ssi) if s is not None]
    threshold = Decimal(str(facility["sir_high_threshold"]))
    if not sirs:
        flag = "NOT_CALCULATED"
    elif any(s >= threshold for s in sirs):
        flag = "HIGH"
    else:
        flag = "NORMAL"

    summary.update({
        "central_line_days": cl_days,
        "urinary_catheter_days": uc_days,
        "ventilator_days": vent_days,
        "patient_days_total": pat_days,
        "procedure_count": procedure_count,
        "clabsi_count": clabsi,
        "cauti_count": cauti,
        "ssi_count": ssi,
        "provisional_clabsi_count": prov_clabsi,
        "provisional_cauti_count": prov_cauti,
        "provisional_ssi_count": prov_ssi,
        "predicted_clabsi": pred_clabsi,
        "predicted_cauti": pred_cauti,
        "predicted_ssi": pred_ssi,
        "sir_clabsi": sir_clabsi,
        "sir_cauti": sir_cauti,
        "sir_ssi": sir_ssi,
        "provisional_sir_clabsi": prov_sir_clabsi,
        "provisional_sir_cauti": prov_sir_cauti,
        "provisional_sir_ssi": prov_sir_ssi,
        "sir_flag": flag,
    })
    touch(summary)


def recompute_covering_summary(unit_id: str, dt):
    """Recompute the covering summary if it exists and is mutable."""
    s = find_covering_summary(unit_id, dt)
    if s is not None and s["status"] in MUTABLE_SUMMARY_STATUSES:
        recompute_summary(s)


# ---------------------------------------------------------------------------
# Cluster detection (PRD §3.8)
# ---------------------------------------------------------------------------
CLUSTER_THRESHOLD = 3
WINDOW_DAYS = 14


def _organism_eq(a: str, b: str) -> bool:
    return (a or "").lower() == (b or "").lower()


def _cluster_cases(unit_id: str, organism: str, win_start_date, win_end_date):
    cases = []
    for c in db.infection_cases.values():
        if (
            c["unit_id"] == unit_id
            and _organism_eq(c["suspected_organism"], organism)
            and c["status"] == "ADJUDICATED_HAI"
            and c["date_of_event"] is not None
            and win_start_date <= cal_date(c["date_of_event"]) <= win_end_date
        ):
            cases.append(c)
    cases.sort(key=lambda c: (c["date_of_event"], c["created_at"]))
    return cases


def _open_investigation_exists(unit_id: str, organism: str) -> bool:
    for o in db.outbreak_investigations.values():
        if (
            o["unit_id"] == unit_id
            and _organism_eq(o["organism"], organism)
            and o["status"] in ("TRIGGERED", "CONFIRMED")
        ):
            return True
    return False


def run_cluster_detection(unit_id: str, organism: str):
    """Auto-create an OutbreakInvestigation when the threshold is crossed."""
    today = cal_date(clock.get())
    win_start_date = today - timedelta(days=13)
    cases = _cluster_cases(unit_id, organism, win_start_date, today)
    if len(cases) >= CLUSTER_THRESHOLD and not _open_investigation_exists(unit_id, organism):
        inv = new_entity({
            "unit_id": unit_id,
            "organism": organism,
            "origin": "AUTO_THRESHOLD",
            "detection_window_start": midnight_utc(win_start_date),
            "detection_window_end": end_of_day_utc(today),
            "trigger_case_ids": [c["id"] for c in cases],
            "contributing_case_count": len(cases),
            "status": "TRIGGERED",
        })
        db.outbreak_investigations[inv["id"]] = inv
        recompute_posture(unit_id)


def manual_investigation(unit_id: str, organism: str):
    """Manual open: snapshot current matching cluster (same windowing rule)."""
    today = cal_date(clock.get())
    win_start_date = today - timedelta(days=13)
    cases = _cluster_cases(unit_id, organism, win_start_date, today)
    inv = new_entity({
        "unit_id": unit_id,
        "organism": organism,
        "origin": "MANUAL",
        "detection_window_start": midnight_utc(win_start_date),
        "detection_window_end": end_of_day_utc(today),
        "trigger_case_ids": [c["id"] for c in cases],
        "contributing_case_count": len(cases),
        "status": "TRIGGERED",
    })
    db.outbreak_investigations[inv["id"]] = inv
    recompute_posture(unit_id)
    return inv
