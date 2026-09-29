"""Derived figures and record rendering.

Every computed field described in the PRD is derived here, either live at read
time (storage pressure, posture, capture adequacy, occupancy status) or from
values frozen onto the record at the moment the PRD says they freeze.
"""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

import clock
import config
from db import db, sorted_records

ZERO = Decimal("0")
ONE = Decimal("1")


# --- rounding helpers ------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q(value, places):
    return dec(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def q1(value):
    return q(value, 1)


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def f2(value):
    return float(q2(value))


def f3(value):
    return float(q3(value))


def fnum(value):
    if value is None:
        return None
    return float(dec(value))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def minutes_between(start, end):
    """Whole minutes, truncated down."""
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)


def days_between(start, end):
    seconds = Decimal(str((end - start).total_seconds()))
    return seconds / Decimal("86400")


def hours_between(start, end):
    seconds = Decimal(str((end - start).total_seconds()))
    return seconds / Decimal("3600")


# --- relations -------------------------------------------------------------

def studies_of_admission(admission_id):
    return [s for s in db.studies.values() if s["admission_id"] == admission_id]


def studies_of_unit(unit_id):
    result = []
    for study in db.studies.values():
        admission = db.admissions.get(study["admission_id"])
        if admission is not None and admission["unit_id"] == unit_id:
            result.append(study)
    return result


def packages_of_study(study_id):
    return [p for p in db.exports.values() if p["study_id"] == study_id]


def packages_of_unit(unit_id):
    ids = set(s["id"] for s in studies_of_unit(unit_id))
    return [p for p in db.exports.values() if p["study_id"] in ids]


def markings_of_study(study_id):
    return [m for m in db.markings.values() if m["study_id"] == study_id]


def markings_of_admission(admission_id):
    ids = set(s["id"] for s in studies_of_admission(admission_id))
    return [m for m in db.markings.values() if m["study_id"] in ids]


def markings_of_alert(alert_id):
    return [m for m in db.markings.values() if m.get("alert_id") == alert_id]


def alerts_of_study(study_id):
    return [a for a in db.alerts.values() if a["study_id"] == study_id]


def alerts_of_admission(admission_id):
    ids = set(s["id"] for s in studies_of_admission(admission_id))
    return [a for a in db.alerts.values() if a["study_id"] in ids]


def alerts_of_unit(unit_id):
    ids = set(s["id"] for s in studies_of_unit(unit_id))
    return [a for a in db.alerts.values() if a["study_id"] in ids]


def interventions_of_alert(alert_id):
    return [i for i in db.interventions.values() if i["alert_id"] == alert_id]


def reports_of_study(study_id):
    return [r for r in db.reports.values() if r["study_id"] == study_id]


def taper_plans_of_admission(admission_id):
    return [t for t in db.taper_plans.values() if t["admission_id"] == admission_id]


def votes_of_case(case_id):
    return [v for v in db.votes.values() if v["case_id"] == case_id]


def beds_of_unit(unit_id):
    return [b for b in db.beds.values() if b["unit_id"] == unit_id]


def shifts_of_unit(unit_id):
    return [s for s in db.shifts.values() if s["unit_id"] == unit_id]


def cases_of_export(export_id):
    return [c for c in db.cases.values() if c["export_id"] == export_id]


def unit_of_study(study):
    admission = db.admissions.get(study["admission_id"])
    if admission is None:
        return None
    return db.units.get(admission["unit_id"])


def unit_of_admission(admission):
    return db.units.get(admission["unit_id"])


def authorization_of_admission(admission):
    return db.authorizations.get(admission["authorization_id"])


def patient_of_admission(admission):
    return db.patients.get(admission["patient_id"])


# --- study segments and storage -------------------------------------------

def closed_segments(study):
    segments = study.get("_segments") or []
    return sorted(segments, key=lambda s: (s["started_at"], s["_seq"]))


def study_rate_gb_per_minute(study):
    factor = config.MODALITY_FACTOR[study["modality"]]
    return config.GB_PER_CHANNEL_MINUTE * Decimal(study["channel_count"]) * factor


def study_acquired_minutes(study):
    return sum(segment["minutes"] for segment in closed_segments(study))


def study_closed_segment_count(study):
    return len(closed_segments(study))


def study_stored_gb(study):
    """PRD 3.5: round per closed segment AND again after each accumulation."""
    rate = study_rate_gb_per_minute(study)
    total = ZERO
    for segment in closed_segments(study):
        segment_gb = q2(Decimal(segment["minutes"]) * rate)
        total = q2(total + segment_gb)
    return total


def open_segment_started_at(study):
    return study.get("current_segment_started_at")


def onset_inside_closed_segment(study, onset_at):
    for segment in closed_segments(study):
        if segment["started_at"] <= onset_at <= segment["ended_at"]:
            return True
    return False


# --- monitoring unit ------------------------------------------------------

def unit_storage_used_gb(unit):
    total = ZERO
    for study in studies_of_unit(unit["id"]):
        if study["data_state"] not in ("ONLINE", "EXPORT_HELD"):
            continue
        total += study_stored_gb(study)
        for package in packages_of_study(study["id"]):
            if package["status"] in ("BUILT", "DELIVERED"):
                total += dec(package["package_gb"])
    return q2(total)


def unit_storage_pressure_pct(unit, used=None):
    if used is None:
        used = unit_storage_used_gb(unit)
    quota = dec(unit["storage_quota_gb"])
    if quota <= ZERO:
        return ZERO
    return q2(used / quota * Decimal(100))


def unit_active_study_count(unit):
    return len([s for s in studies_of_unit(unit["id"])
                if s["acquisition_state"] == "ACQUIRING"])


def unit_coverage_capacity(unit):
    now = clock.now()
    total = 0
    for shift in shifts_of_unit(unit["id"]):
        if shift["state"] != "ACTIVE":
            continue
        if shift["starts_at"] <= now < shift["ends_at"]:
            total += shift["max_concurrent_studies"]
    return total


def unit_posture(unit):
    pressure = unit_storage_pressure_pct(unit)
    if pressure >= config.STORAGE_LOCK_PCT:
        return "STORAGE_LOCKED"
    active = unit_active_study_count(unit)
    if active > 0 and active >= unit_coverage_capacity(unit):
        return "COVERAGE_CONSTRAINED"
    return "OPEN"


def unit_beds_available(unit):
    return len([b for b in beds_of_unit(unit["id"]) if bed_status(b) == "AVAILABLE"])


def unit_late_response_count(unit):
    return len([a for a in alerts_of_unit(unit["id"])
                if a["response_state"] == "RESPONDED_LATE"])


# --- beds -----------------------------------------------------------------

def bed_current_admission_id(bed):
    for admission in db.admissions.values():
        if admission.get("bed_id") == bed["id"] and admission["clinical_state"] in (
            "ADMITTED",
            "CAPTURE_TARGET_MET",
        ):
            return admission["id"]
    return None


def bed_status(bed):
    if bed_current_admission_id(bed) is not None:
        return "OCCUPIED"
    released_at = bed.get("released_at")
    if released_at is not None:
        clear_at = bed.get("turnover_clear_at")
        if clear_at is not None and clock.now() < clear_at:
            return "TURNOVER"
    return "AVAILABLE"


def bed_is_available(bed):
    return bed_status(bed) == "AVAILABLE"


# --- technologist shifts --------------------------------------------------

def shift_assigned_study_count(shift):
    return len([s for s in db.studies.values()
                if s.get("shift_id") == shift["id"]
                and s["acquisition_state"] in ("ACQUIRING", "PAUSED")])


def shift_covers_now(shift):
    now = clock.now()
    return shift["state"] == "ACTIVE" and shift["starts_at"] <= now < shift["ends_at"]


# --- taper ----------------------------------------------------------------

def effective_taper_plan(admission_id):
    """The plan supplying current_step: ACTIVE, HELD or COMPLETED (never ABORTED)."""
    candidates = [p for p in taper_plans_of_admission(admission_id)
                  if p["status"] in ("ACTIVE", "HELD", "COMPLETED")]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return candidates[-1]


def taper_current_step(admission_id):
    plan = effective_taper_plan(admission_id)
    if plan is None:
        return 0
    return plan["current_step"]


# --- admission capture figures -------------------------------------------

def admission_elapsed_days(admission):
    if admission.get("admitted_at") is None:
        return ZERO
    if admission["clinical_state"] == "SCHEDULED":
        return ZERO
    end = admission.get("discharged_at") or clock.now()
    return q3(days_between(admission["admitted_at"], end))


def admission_weighted_event_count(admission):
    total = ZERO
    for marking in markings_of_admission(admission["id"]):
        if marking["status"] != "ADJUDICATED":
            continue
        if marking["event_class"] not in config.CAPTURE_WEIGHT_CLASSES:
            continue
        total += dec(marking["weight"])
    return q3(total)


def admission_capture(admission):
    """All six capture figures in one pass."""
    weighted = admission_weighted_event_count(admission)
    target = Decimal(admission["target_event_count"])
    deficit = q3(max(ZERO, target - weighted))
    elapsed = admission_elapsed_days(admission)
    if elapsed == ZERO:
        yield_rate = ZERO
    else:
        yield_rate = q3(weighted / elapsed)
    index = q3(min(ONE, weighted / target))
    authorization = authorization_of_admission(admission)
    days_available = Decimal(authorization["days_available"]) if authorization else ZERO
    prospective = q3((weighted + yield_rate * days_available) / target)
    return {
        "weighted_event_count": weighted,
        "deficit_weighted": deficit,
        "elapsed_monitored_days": elapsed,
        "projected_daily_yield": yield_rate,
        "capture_adequacy_index": index,
        "capture_adequacy_index_prospective": prospective,
    }


# --- alert deadline -------------------------------------------------------

def alert_response_deadline_minutes(study, detected_at):
    admission = db.admissions.get(study["admission_id"])
    base = config.TIER_BASE["LOW"]
    step = 0
    posture_adjust = 0
    if admission is not None:
        patient = patient_of_admission(admission)
        if patient is not None:
            base = config.TIER_BASE[patient["risk_tier"]]
        step = taper_current_step(admission["id"])
        unit = unit_of_admission(admission)
        if unit is not None and unit_posture(unit) == "COVERAGE_CONSTRAINED":
            posture_adjust = config.POSTURE_CONSTRAINED_DEADLINE_ADD
    hour = detected_at.hour
    night_adjust = config.NIGHT_DEADLINE_ADD if (hour >= 22 or hour <= 5) else 0
    raw = base - step + posture_adjust + night_adjust
    clamped = min(config.DEADLINE_CEILING_MINUTES, raw)
    return max(config.DEADLINE_FLOOR_MINUTES, clamped)


# --- interpretation turnaround -------------------------------------------

def turnaround_figures(completed_at, prelim_issued_at):
    calendar = q2(hours_between(completed_at, prelim_issued_at))
    covered_minutes = ZERO
    day = datetime(completed_at.year, completed_at.month, completed_at.day)
    last = datetime(prelim_issued_at.year, prelim_issued_at.month, prelim_issued_at.day)
    while day <= last:
        window_start = day + timedelta(hours=config.READING_WINDOW_START_HOUR)
        window_end = day + timedelta(hours=config.READING_WINDOW_END_HOUR)
        overlap_start = max(completed_at, window_start)
        overlap_end = min(prelim_issued_at, window_end)
        if overlap_end > overlap_start:
            seconds = Decimal(str((overlap_end - overlap_start).total_seconds()))
            covered_minutes += seconds / Decimal("60")
        day = day + timedelta(days=1)
    coverage = q2(covered_minutes / Decimal("60"))
    breached = coverage > config.SLA_PRELIM_COVERAGE_HOURS
    return calendar, coverage, breached


# --- length-of-stay extension --------------------------------------------

def evaluate_extension(admission):
    """calculations.los_extension_decision, pinned steps S1..S7."""
    capture = admission_capture(admission)
    elapsed = capture["elapsed_monitored_days"]
    deficit = capture["deficit_weighted"]
    yield_rate = capture["projected_daily_yield"]

    if yield_rate <= ZERO:
        yield_days = 0
    else:
        yield_days = max(0, ceil_int(deficit / yield_rate))

    patient = patient_of_admission(admission)
    tier = patient["risk_tier"] if patient else "LOW"
    unit = unit_of_admission(admission)
    posture_add = ZERO
    if unit is not None and unit_posture(unit) == "COVERAGE_CONSTRAINED":
        posture_add = config.POSTURE_CONSTRAINED_RISK_ADD
    step = Decimal(taper_current_step(admission["id"]))
    daily_risk = q1(config.BASE_RISK[tier] + config.TAPER_RISK_PER_STEP * step + posture_add)

    if daily_risk <= ZERO:
        risk_budget_days = 0
    else:
        risk_budget_days = floor_int(config.RISK_ALLOWANCE_UNITS / daily_risk)

    authorization = authorization_of_admission(admission)
    days_available = authorization["days_available"] if authorization else 0

    granted = min(yield_days, risk_budget_days, days_available)
    if granted <= 0:
        granted = 0
        outcome = "DENIED_RISK" if risk_budget_days <= 0 else "DENIED_AUTH_DAYS"
    else:
        outcome = "GRANTED"
    return {
        "elapsed": elapsed,
        "deficit": deficit,
        "yield_rate": yield_rate,
        "yield_days": yield_days,
        "daily_risk": daily_risk,
        "risk_budget_days": risk_budget_days,
        "days_available": days_available,
        "granted_days": granted,
        "outcome": outcome,
    }


# --- export package volume -----------------------------------------------

def export_package_gb(package, study):
    stored = study_stored_gb(study)
    if package["include_video"]:
        return q2(stored)
    factor = config.MODALITY_FACTOR[study["modality"]]
    return q2(stored / factor)


# --- conference tally ----------------------------------------------------

def case_tally(case):
    counted = [v for v in votes_of_case(case["id"])
               if v["counted"] and v["round_index"] == case["defer_round"]]
    eligible = len(counted)
    candidate = len([v for v in counted if v["vote"] == "CANDIDATE"])
    non_candidate = len([v for v in counted if v["vote"] == "NON_CANDIDATE"])
    defer = len([v for v in counted if v["vote"] == "DEFER"])
    specialties = len(set(v["specialty"] for v in counted))
    quorum = eligible >= config.QUORUM_MIN and specialties >= config.QUORUM_SPECIALTY_MIN
    return {
        "eligible_vote_count": eligible,
        "candidate_votes": candidate,
        "non_candidate_votes": non_candidate,
        "defer_votes": defer,
        "distinct_specialty_count": specialties,
        "quorum_met": quorum,
    }


def apply_case_tally(case):
    case.update(case_tally(case))


# --- rendering -----------------------------------------------------------

def _preamble(record, full=True):
    data = {
        "id": record["id"],
        "created_at": clock.iso(record["created_at"]),
    }
    if full:
        data["updated_at"] = clock.iso(record["updated_at"])
        data["version"] = record["version"]
    return data


def render_unit(unit):
    data = _preamble(unit)
    used = unit_storage_used_gb(unit)
    data.update({
        "name": unit["name"],
        "bed_count": unit["bed_count"],
        "storage_quota_gb": fnum(unit["storage_quota_gb"]),
        "storage_used_gb": f2(used),
        "storage_pressure_pct": f2(unit_storage_pressure_pct(unit, used)),
        "posture": unit_posture(unit),
        "beds_available": unit_beds_available(unit),
        "active_study_count": unit_active_study_count(unit),
        "coverage_capacity": unit_coverage_capacity(unit),
        "late_response_count": unit_late_response_count(unit),
        "retention_sweep_index": unit["retention_sweep_index"],
    })
    return data


def render_bed(bed):
    data = _preamble(bed)
    data.update({
        "unit_id": bed["unit_id"],
        "label": bed["label"],
        "status": bed_status(bed),
        "released_at": clock.iso(bed.get("released_at")),
        "turnover_clear_at": clock.iso(bed.get("turnover_clear_at")),
        "current_admission_id": bed_current_admission_id(bed),
    })
    return data


def render_shift(shift):
    data = _preamble(shift)
    data.update({
        "unit_id": shift["unit_id"],
        "technologist_user_id": shift["technologist_user_id"],
        "starts_at": clock.iso(shift["starts_at"]),
        "ends_at": clock.iso(shift["ends_at"]),
        "max_concurrent_studies": shift["max_concurrent_studies"],
        "state": shift["state"],
        "assigned_study_count": shift_assigned_study_count(shift),
    })
    return data


def render_patient(patient):
    data = _preamble(patient)
    data.update({
        "mrn": patient["mrn"],
        "display_name": patient["display_name"],
        "risk_tier": patient["risk_tier"],
    })
    return data


def render_authorization(authorization):
    data = _preamble(authorization)
    data.update({
        "patient_id": authorization["patient_id"],
        "requested_setting": authorization["requested_setting"],
        "requested_days": authorization["requested_days"],
        "status": authorization["status"],
        "authorized_setting": authorization.get("authorized_setting"),
        "authorized_days": authorization["authorized_days"],
        "days_reserved": authorization["days_reserved"],
        "days_consumed": authorization["days_consumed"],
        "days_available": authorization["days_available"],
        "resubmission_count": authorization["resubmission_count"],
        "payer_note": authorization.get("payer_note"),
    })
    return data


def render_admission(admission):
    data = _preamble(admission)
    capture = admission_capture(admission)
    data.update({
        "patient_id": admission["patient_id"],
        "authorization_id": admission["authorization_id"],
        "unit_id": admission["unit_id"],
        "bed_id": admission.get("bed_id"),
        "setting": admission["setting"],
        "scheduled_admit_at": clock.iso(admission["scheduled_admit_at"]),
        "target_event_count": admission["target_event_count"],
        "planned_days": admission["planned_days"],
        "admitted_at": clock.iso(admission.get("admitted_at")),
        "discharged_at": clock.iso(admission.get("discharged_at")),
        "planned_discharge_at": clock.iso(admission.get("planned_discharge_at")),
        "clinical_state": admission["clinical_state"],
        "authorization_state": admission["authorization_state"],
        "weighted_event_count": f3(capture["weighted_event_count"]),
        "capture_adequacy_index": f3(capture["capture_adequacy_index"]),
        "capture_adequacy_index_prospective": f3(capture["capture_adequacy_index_prospective"]),
        "projected_daily_yield": f3(capture["projected_daily_yield"]),
        "deficit_weighted": f3(capture["deficit_weighted"]),
        "elapsed_monitored_days": f3(capture["elapsed_monitored_days"]),
        "extension_count": admission["extension_count"],
        "last_extension_outcome": admission.get("last_extension_outcome"),
        "last_extension_granted_days": admission["last_extension_granted_days"],
        "disposition": admission.get("disposition"),
    })
    return data


def render_taper_plan(plan):
    data = _preamble(plan)
    data.update({
        "admission_id": plan["admission_id"],
        "total_steps": plan["total_steps"],
        "current_step": plan["current_step"],
        "status": plan["status"],
        "hold_reason": plan.get("hold_reason"),
    })
    return data


def render_study(study):
    data = _preamble(study)
    data.update({
        "admission_id": study["admission_id"],
        "shift_id": study.get("shift_id"),
        "channel_count": study["channel_count"],
        "modality": study["modality"],
        "acquisition_state": study["acquisition_state"],
        "data_state": study["data_state"],
        "acquired_minutes": study_acquired_minutes(study),
        "stored_gb": f2(study_stored_gb(study)),
        "closed_segment_count": study_closed_segment_count(study),
        "current_segment_started_at": clock.iso(study.get("current_segment_started_at")),
        "completed_at": clock.iso(study.get("completed_at")),
        "last_impedance_kohm": fnum(study.get("last_impedance_kohm")),
        "impedance_fail_count": study["impedance_fail_count"],
        "export_hold_reason": study.get("export_hold_reason"),
    })
    return data


def render_alert(alert):
    data = _preamble(alert)
    data.update({
        "study_id": alert["study_id"],
        "source": alert["source"],
        "detected_at": clock.iso(alert["detected_at"]),
        "triage_state": alert["triage_state"],
        "response_state": alert["response_state"],
        "response_deadline_minutes": alert["response_deadline_minutes"],
        "responded_at": clock.iso(alert.get("responded_at")),
        "latency_minutes": alert.get("latency_minutes"),
        "adjudicated_at": clock.iso(alert.get("adjudicated_at")),
    })
    return data


def render_intervention(intervention):
    data = _preamble(intervention, full=False)
    data.update({
        "alert_id": intervention["alert_id"],
        "nurse_user_id": intervention["nurse_user_id"],
        "interventions": list(intervention["interventions"]),
        "injury_observed": intervention["injury_observed"],
        "rescue_med_given": intervention["rescue_med_given"],
        "recorded_at": clock.iso(intervention["recorded_at"]),
    })
    return data


def render_marking(marking):
    data = _preamble(marking)
    data.update({
        "study_id": marking["study_id"],
        "alert_id": marking.get("alert_id"),
        "onset_at": clock.iso(marking["onset_at"]),
        "duration_seconds": marking["duration_seconds"],
        "event_class": marking["event_class"],
        "status": marking["status"],
        "taper_step_at_onset": marking["taper_step_at_onset"],
        "weight": f3(marking["weight"]),
        "adjudicated_at": clock.iso(marking.get("adjudicated_at")),
        "retraction_reason": marking.get("retraction_reason"),
    })
    return data


def render_report(report):
    data = _preamble(report)
    calendar = report.get("turnaround_calendar_hours")
    coverage = report.get("turnaround_coverage_hours")
    data.update({
        "study_id": report["study_id"],
        "status": report["status"],
        "localization": report.get("localization"),
        "prelim_issued_at": clock.iso(report.get("prelim_issued_at")),
        "final_issued_at": clock.iso(report.get("final_issued_at")),
        "prelim_author_user_id": report.get("prelim_author_user_id"),
        "final_author_user_id": report.get("final_author_user_id"),
        "turnaround_calendar_hours": None if calendar is None else f2(calendar),
        "turnaround_coverage_hours": None if coverage is None else f2(coverage),
        "sla_breached": report["sla_breached"],
        "addendum_count": report["addendum_count"],
        "addendum_reason": report.get("addendum_reason"),
    })
    return data


def render_export(package):
    data = _preamble(package)
    data.update({
        "study_id": package["study_id"],
        "include_video": package["include_video"],
        "supersedes_export_id": package.get("supersedes_export_id"),
        "status": package["status"],
        "package_gb": f2(package["package_gb"]),
        "built_at": clock.iso(package.get("built_at")),
        "delivered_at": clock.iso(package.get("delivered_at")),
        "recipient_center": package.get("recipient_center"),
        "retention_expires_at": clock.iso(package.get("retention_expires_at")),
        "blocked_reason": package.get("blocked_reason"),
        "revocation_reason": package.get("revocation_reason"),
    })
    return data


def render_case(case):
    data = _preamble(case)
    data.update({
        "admission_id": case["admission_id"],
        "export_id": case["export_id"],
        "status": case["status"],
        "presenter_user_id": case.get("presenter_user_id"),
        "defer_round": case["defer_round"],
        "eligible_vote_count": case["eligible_vote_count"],
        "candidate_votes": case["candidate_votes"],
        "non_candidate_votes": case["non_candidate_votes"],
        "defer_votes": case["defer_votes"],
        "distinct_specialty_count": case["distinct_specialty_count"],
        "quorum_met": case["quorum_met"],
        "decision_at": clock.iso(case.get("decision_at")),
    })
    return data


def render_vote(vote):
    data = _preamble(vote, full=False)
    data.update({
        "case_id": vote["case_id"],
        "voter_user_id": vote["voter_user_id"],
        "specialty": vote["specialty"],
        "vote": vote["vote"],
        "rationale": vote.get("rationale"),
        "counted": vote["counted"],
        "round_index": vote["round_index"],
    })
    return data


RENDERERS = {
    "unit": render_unit,
    "bed": render_bed,
    "shift": render_shift,
    "patient": render_patient,
    "authorization": render_authorization,
    "admission": render_admission,
    "taper_plan": render_taper_plan,
    "study": render_study,
    "alert": render_alert,
    "intervention": render_intervention,
    "marking": render_marking,
    "report": render_report,
    "export": render_export,
    "case": render_case,
    "vote": render_vote,
}


def render(record):
    return RENDERERS[record["_type"]](record)


def render_all(records):
    return [render(record) for record in records]


def ordered(records):
    return sorted_records(records)
