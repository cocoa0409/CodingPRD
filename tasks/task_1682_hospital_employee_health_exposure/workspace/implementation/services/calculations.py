"""Calculation rules (Scaffold Table 3 / PRD sections 2.9 and 3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import base_fields, now, store
from util import add_months

TITER_THRESHOLD = {"HEP_B": 10.0, "MEASLES": 1.0, "MUMPS": 1.0, "RUBELLA": 10.0,
                   "VARICELLA": 1.0}
REQUIRED_TITER_DISEASES = ["HEP_B", "VARICELLA"]

PEP_WINDOW_HOURS = 72
PEP_COURSE_DAYS = 28

SEROLOGY_OFFSET_DAYS = {"BASELINE": 0, "WEEK_6": 42, "WEEK_12": 84, "MONTH_6": 183}
WINDOW_OPEN_LEAD_DAYS = 7
WINDOW_CLOSE_LAG_DAYS = 28

DISEASE_INCUBATION_OFFSET_DAYS = {"COVID": 2, "INFLUENZA": 1, "PERTUSSIS": 7,
                                  "NOROVIRUS": 1, "MEASLES": 4}
DISEASE_MONITORING_WINDOW_DAYS = {"COVID": 14, "INFLUENZA": 7, "PERTUSSIS": 21,
                                  "NOROVIRUS": 3, "MEASLES": 21}

ANNIVERSARY_MONTHS = 12


def interpret_titer(disease, assay_type, numeric_value, qualitative_result):
    """immunity_interpretation: raw numeric threshold (inclusive), or label alone."""
    if assay_type == "QUANTITATIVE":
        return "IMMUNE" if float(numeric_value) >= TITER_THRESHOLD[disease] else "NON_IMMUNE"
    return {"REACTIVE": "IMMUNE", "NON_REACTIVE": "NON_IMMUNE",
            "EQUIVOCAL": "EQUIVOCAL"}[qualitative_result]


def latest_titer(employee_id, disease):
    """Greatest resulted_at wins; ties broken by greatest created_at (then latest row)."""
    cands = [t for t in store.titers.values()
             if t["employee_id"] == employee_id and t["disease"] == disease]
    if not cands:
        return None
    return max(cands, key=lambda t: (t["resulted_at"], t["created_at"], t["_seq"]))


def compute_cycle_due_dates(emp, cycle_year, cycle_mode):
    """cycle_due_date: CALENDAR_YEAR pins to Dec 31 23:59:59Z; ROLLING_ANNIVERSARY
    anchors to the greatest tb_completed_at among other SATISFIED cycles, else hire_date,
    plus twelve calendar months preserving the day of month."""
    from datetime import datetime, timezone

    if cycle_mode == "CALENDAR_YEAR":
        tb_due = datetime(cycle_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    else:
        anchor = None
        for c in store.cycles.values():
            if (c["employee_id"] == emp["id"] and c["status"] == "SATISFIED"
                    and c["tb_completed_at"] is not None):
                if anchor is None or c["tb_completed_at"] > anchor:
                    anchor = c["tb_completed_at"]
        if anchor is None:
            anchor = emp["hire_date"]
        tb_due = add_months(anchor, ANNIVERSARY_MONTHS)
    fit_due = tb_due if emp["requires_respirator"] else None
    return tb_due, fit_due


def cycle_is_satisfied(cycle, emp):
    """annual_compliance_satisfaction."""
    if cycle["tb_completed_at"] is None:
        return False
    if emp["requires_respirator"] and cycle["fit_test_completed_at"] is None:
        return False
    return True


def evaluate_cycle_satisfaction(cycle, emp):
    from db import touch

    if cycle["status"] in ("OPEN", "OVERDUE") and cycle_is_satisfied(cycle, emp):
        cycle["status"] = "SATISFIED"
        touch(cycle)


def classify_exposure(exposure_type, body_fluid, source_known):
    """exposure_risk_classification."""
    if body_fluid == "NON_INFECTIOUS":
        return "LOW"
    if exposure_type == "PERCUTANEOUS" and body_fluid == "BLOOD":
        return "HIGH" if source_known else "MEDIUM"
    if exposure_type in ("MUCOUS_MEMBRANE", "BITE") and body_fluid == "BLOOD":
        return "MEDIUM"
    if exposure_type == "PERCUTANEOUS" and body_fluid == "OTHER_POTENTIALLY_INFECTIOUS":
        return "MEDIUM"
    if exposure_type in ("MUCOUS_MEMBRANE", "BITE") and body_fluid == "OTHER_POTENTIALLY_INFECTIOUS":
        return "LOW"
    return "LOW"  # SKIN_CONTACT any fluid


def create_pep_regimen(case, medication="HIV_3DRUG"):
    pep = base_fields()
    pep.update(
        {
            "exposure_case_id": case["id"],
            "medication": medication,
            "recommended_at": now(),
            "window_deadline": case["exposure_datetime"] + timedelta(hours=PEP_WINDOW_HOURS),
            "started_at": None,
            "status": "RECOMMENDED",
        }
    )
    store.pep_regimens[pep["id"]] = pep
    return pep


def create_followup(case, milestone):
    """serology_schedule: offsets 0/42/84/183 days; window_open = scheduled - 7d
    (BASELINE: exposure_datetime); window_close = scheduled + 28d."""
    exposure_dt = case["exposure_datetime"]
    scheduled = exposure_dt + timedelta(days=SEROLOGY_OFFSET_DAYS[milestone])
    if milestone == "BASELINE":
        window_open = exposure_dt
    else:
        window_open = scheduled - timedelta(days=WINDOW_OPEN_LEAD_DAYS)
    window_close = scheduled + timedelta(days=WINDOW_CLOSE_LAG_DAYS)
    fu = base_fields()
    fu.update(
        {
            "exposure_case_id": case["id"],
            "milestone": milestone,
            "scheduled_date": scheduled,
            "window_open": window_open,
            "window_close": window_close,
            "result": "PENDING",
            "resulted_at": None,
            "status": "SCHEDULED",
        }
    )
    store.followups[fu["id"]] = fu
    return fu


def osha_recordable(injury):
    """osha_recordable_determination."""
    if injury["injury_type"] == "NEEDLESTICK":
        return True
    cid = injury.get("exposure_case_id")
    if cid:
        case = store.cases.get(cid)
        if case is not None:
            if case["risk_classification"] == "HIGH":
                return True
            if any(
                p["exposure_case_id"] == cid and p["status"] in ("STARTED", "COMPLETED")
                for p in store.pep_regimens.values()
            ):
                return True
    return False


def recompute_osha_for_case(case_id):
    """Recomputed on linkage events (PEP STARTED/COMPLETED on the linked case)."""
    from db import touch

    for injury in store.injuries.values():
        if injury.get("exposure_case_id") == case_id:
            new_value = osha_recordable(injury)
            if injury["osha_recordable"] != new_value:
                injury["osha_recordable"] = new_value
                touch(injury)


def campaign_coverage(campaign):
    """campaign_coverage_rate: round_half_up per department first (2dp), then the
    mean of department rates (2dp). Aggregate-first order is forbidden."""
    parts = [p for p in store.participations.values() if p["campaign_id"] == campaign["id"]]
    counts = {"ADMINISTERED": 0, "DECLINED": 0, "EXEMPTED": 0, "DELINQUENT": 0, "PENDING": 0}
    by_dept = {}
    for p in parts:
        counts[p["status"]] += 1
        dept = store.employees[p["employee_id"]]["department"]
        agg = by_dept.setdefault(dept, [0, 0])
        agg[1] += 1
        if p["status"] in ("ADMINISTERED", "EXEMPTED"):
            agg[0] += 1
    if by_dept:
        rates = []
        for num, den in by_dept.values():
            rate = (Decimal(100) * Decimal(num) / Decimal(den)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            rates.append(rate)
        mean = (sum(rates) / Decimal(len(rates))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        coverage = float(mean)
    else:
        coverage = 0.0
    return {
        "administered_count": counts["ADMINISTERED"],
        "declined_count": counts["DECLINED"],
        "exempted_count": counts["EXEMPTED"],
        "delinquent_count": counts["DELINQUENT"],
        "pending_count": counts["PENDING"],
        "coverage_rate": coverage,
    }
