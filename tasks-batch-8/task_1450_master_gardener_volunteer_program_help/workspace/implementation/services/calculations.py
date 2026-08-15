"""Business-logic services: calculations, derived fields, cascades.

Implements scaffold §1.3 calculation rules and the derived-field
reconciliation described in PRD §2.10 / §3.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import db
import util
from util import D, round_half_up, round_quarter, hours_num


# =====================================================================
# Composite application score (§1.3 application_composite_score)
# =====================================================================

ESSAY_WEIGHT = Decimal("0.4")
INTERVIEW_WEIGHT = Decimal("0.6")
COUNTY_PRIORITY_BONUS = Decimal("4")
COMPOSITE_CAP = Decimal("100")


def experience_bonus(years):
    if years >= 10:
        return Decimal(8)
    if 5 <= years <= 9:
        return Decimal(5)
    if 2 <= years <= 4:
        return Decimal(3)
    return Decimal(0)


def composite_score(application, cycle):
    raw = (ESSAY_WEIGHT * D(application["essay_score"])
           + INTERVIEW_WEIGHT * D(application["interview_score"])
           + experience_bonus(application["prior_gardening_years"])
           + (COUNTY_PRIORITY_BONUS if application["county"] in (cycle.get("priority_counties") or []) else Decimal(0)))
    rounded = round_half_up(raw, 1)
    return float(min(COMPOSITE_CAP, rounded))


# =====================================================================
# Credit totals (§1.3 credit_totals + project_credit_cap)
# =====================================================================

def _entries_for(volunteer_id, cycle_id):
    return [e for e in db.credit_entries.values()
            if e["volunteer_id"] == volunteer_id and e["cycle_id"] == cycle_id]


def project_capped_contribution(volunteer_id, project):
    """Waterfall allocation of APPROVED SERVICE entries sourced from one project."""
    cap = project.get("max_creditable_hours_per_volunteer")
    if cap is None:
        cap = Decimal("20.0")
    cap = D(cap)
    entries = [e for e in db.credit_entries.values()
               if e["volunteer_id"] == volunteer_id
               and e["source_type"] == "PROJECT"
               and e["source_id"] == project["id"]
               and e["entry_kind"] == "SERVICE"
               and e["status"] == "APPROVED"]
    entries.sort(key=lambda e: (e["activity_date"], e["created_at"]))
    running = Decimal("0")
    for e in entries:
        remaining = cap - running
        counted = min(D(e["hours"]), max(remaining, Decimal("0")))
        running += counted
    return running


def compute_totals(volunteer_id, cycle_id):
    """Return (prov_service, prov_ce, official_service, official_ce) as Decimals."""
    entries = _entries_for(volunteer_id, cycle_id)
    prov_s = Decimal("0")
    prov_c = Decimal("0")
    off_s_nonproject = Decimal("0")
    off_c = Decimal("0")
    project_ids = set()
    for e in entries:
        hrs = D(e["hours"])
        if e["status"] in ("PENDING", "APPROVED"):
            if e["entry_kind"] == "SERVICE":
                prov_s += hrs
            else:
                prov_c += hrs
        if e["status"] == "APPROVED":
            if e["entry_kind"] == "CONTINUING_ED":
                off_c += hrs
            else:  # SERVICE
                if e["source_type"] == "PROJECT":
                    project_ids.add(e["source_id"])
                else:
                    off_s_nonproject += hrs
    project_part = Decimal("0")
    for pid in project_ids:
        project = db.community_projects.get(pid)
        if project is not None:
            project_part += project_capped_contribution(volunteer_id, project)
    off_s = off_s_nonproject + project_part
    return prov_s, prov_c, off_s, off_c


def compute_effective_requirements(record, cycle):
    factor = Decimal("0.5") if record.get("hardship_exemption") else Decimal("1.0")
    eff_h = round_quarter(D(cycle["hour_requirement"]) * factor)
    eff_c = round_quarter(D(cycle["ce_requirement"]) * factor)
    return eff_h, eff_c


def recompute_record(record, stamp_evaluated=False):
    """Recompute a RecertificationRecord's totals and effective requirements."""
    cycle = db.program_cycles.get(record["cycle_id"])
    prov_s, prov_c, off_s, off_c = compute_totals(record["volunteer_id"], record["cycle_id"])
    record["provisional_service_hours"] = hours_num(prov_s)
    record["provisional_ce_hours"] = hours_num(prov_c)
    record["official_service_hours"] = hours_num(off_s)
    record["official_ce_hours"] = hours_num(off_c)
    eff_h, eff_c = compute_effective_requirements(record, cycle)
    record["effective_hour_requirement"] = hours_num(eff_h)
    record["effective_ce_requirement"] = hours_num(eff_c)
    if stamp_evaluated:
        record["evaluated_at"] = util.logical_clock_iso()
    util.touch(record)


def record_for(volunteer_id, cycle_id):
    for r in db.recertification_records.values():
        if r["volunteer_id"] == volunteer_id and r["cycle_id"] == cycle_id:
            return r
    return None


# =====================================================================
# Recognition (§1.3 recognition_tier_and_points) — pinned 3-step order
# =====================================================================

TIER_SILVER_MIN = Decimal("20.0")
TIER_GOLD_MIN = Decimal("40.0")
GOLD_OUTREACH_BONUS = Decimal("0.25")


def _official_service_hours(volunteer_id, cycle_id):
    _, _, off_s, _ = compute_totals(volunteer_id, cycle_id)
    return off_s


def _current_cycle_outreach_hours(volunteer_id):
    """Current-cycle (non-closed) APPROVED SERVICE hours with activity_type OUTREACH."""
    total = Decimal("0")
    for e in db.credit_entries.values():
        if e["volunteer_id"] != volunteer_id:
            continue
        if e["entry_kind"] != "SERVICE" or e["status"] != "APPROVED":
            continue
        if e["activity_type"] != "OUTREACH":
            continue
        cycle = db.program_cycles.get(e["cycle_id"])
        if cycle is not None and cycle["status"] != "CLOSED":
            total += D(e["hours"])
    return total


def recompute_recognition(volunteer):
    """Recompute lifetime_base_hours, recognition_tier, recognition_points."""
    vid = volunteer["id"]
    closed_total = Decimal("0")
    current_total = Decimal("0")
    for r in db.recertification_records.values():
        if r["volunteer_id"] != vid:
            continue
        cycle = db.program_cycles.get(r["cycle_id"])
        if cycle is None:
            continue
        off_s = _official_service_hours(vid, r["cycle_id"])
        if cycle["status"] == "CLOSED":
            closed_total += off_s
        else:
            current_total += off_s
    base = closed_total + current_total
    if base >= TIER_GOLD_MIN:
        tier = "GOLD"
    elif base >= TIER_SILVER_MIN:
        tier = "SILVER"
    else:
        tier = "BRONZE"
    points = base
    if tier == "GOLD":
        points = base + GOLD_OUTREACH_BONUS * _current_cycle_outreach_hours(vid)
    volunteer["lifetime_base_hours"] = hours_num(base)
    volunteer["recognition_tier"] = tier
    volunteer["recognition_points"] = hours_num(points)
    util.touch(volunteer)


# =====================================================================
# Recertification record provisioning
# =====================================================================

def provision_record(volunteer_id, cycle_id):
    """Create a PENDING RecertificationRecord for (volunteer, cycle) if absent."""
    existing = record_for(volunteer_id, cycle_id)
    if existing is not None:
        return existing
    record = util.new_resource({
        "volunteer_id": volunteer_id,
        "cycle_id": cycle_id,
        "status": "PENDING",
        "hardship_exemption": False,
        "exemption_reason": None,
        "provisional_service_hours": 0.0,
        "provisional_ce_hours": 0.0,
        "official_service_hours": 0.0,
        "official_ce_hours": 0.0,
        "effective_hour_requirement": None,
        "effective_ce_requirement": None,
        "evaluated_at": None,
        "finalized_at": None,
    })
    db.recertification_records[record["id"]] = record
    recompute_record(record)
    return record


# =====================================================================
# Shift credit hours (§1.3 shift_credit_hours)
# =====================================================================

def shift_credit_hours(shift):
    start = util.parse_dt(shift["start_time"])
    end = util.parse_dt(shift["end_time"])
    minutes = Decimal(int((end - start).total_seconds() // 60))
    quarters = (minutes / Decimal(15)).quantize(Decimal("1"), rounding="ROUND_HALF_UP")
    return quarters * Decimal("0.25")


# =====================================================================
# Deactivation cascade (volunteer -> signups/entries/enrollments)
# =====================================================================

def deactivation_cascade(volunteer):
    """SIGNED_UP signups -> CANCELLED (shift.filled_count -= 1, FULL -> OPEN);
    PENDING CreditEntries -> VOIDED; ENROLLED TrainingEnrollments -> DROPPED."""
    vid = volunteer["id"]
    for s in list(db.shift_signups.values()):
        if s["volunteer_id"] == vid and s["status"] == "SIGNED_UP":
            s["status"] = "CANCELLED"
            util.touch(s)
            shift = db.shifts.get(s["shift_id"])
            if shift is not None:
                shift["filled_count"] = max(0, shift["filled_count"] - 1)
                if shift["status"] == "FULL":
                    shift["status"] = "OPEN"
                util.touch(shift)
    affected_records = set()
    for e in list(db.credit_entries.values()):
        if e["volunteer_id"] == vid and e["status"] == "PENDING":
            e["status"] = "VOIDED"
            util.touch(e)
            affected_records.add((e["volunteer_id"], e["cycle_id"]))
    for t in list(db.training_enrollments.values()):
        if t["volunteer_id"] == vid and t["status"] == "ENROLLED":
            t["status"] = "DROPPED"
            util.touch(t)
            cycle = db.program_cycles.get(t["cycle_id"])
            if cycle is not None:
                cycle["enrolled_count"] = max(0, cycle["enrolled_count"] - 1)
                util.touch(cycle)
    for (v, c) in affected_records:
        rec = record_for(v, c)
        if rec is not None and rec["status"] == "PENDING":
            recompute_record(rec)


# =====================================================================
# Specialist performance score (§1.3 specialist_performance_score)
# =====================================================================

LATE_PENALTY = 5
RETURN_PENALTY = 3
ROLLING_WINDOW_DAYS = 90


def specialist_scores(specialist):
    """Return (rolling_score, lifetime_score) as floats (integer-valued)."""
    sid = specialist["id"]
    clock = util.logical_clock()
    window_start = clock - timedelta(days=ROLLING_WINDOW_DAYS)

    late_all = 0
    late_roll = 0
    ret_all = 0
    ret_roll = 0
    for r in db.diagnosis_referrals.values():
        if r.get("answered_by_specialist_id") == sid and r.get("answered_at"):
            answered_at = util.parse_dt(r["answered_at"])
            due_at = util.parse_dt(r["due_at"])
            if answered_at > due_at:
                late_all += 1
                if answered_at >= window_start:
                    late_roll += 1
        if r.get("returned_by_specialist_id") == sid and r.get("returned_at"):
            returned_at = util.parse_dt(r["returned_at"])
            ret_all += 1
            if returned_at >= window_start:
                ret_roll += 1
    lifetime = max(0, 100 - LATE_PENALTY * late_all - RETURN_PENALTY * ret_all)
    rolling = max(0, 100 - LATE_PENALTY * late_roll - RETURN_PENALTY * ret_roll)
    return float(rolling), float(lifetime)


def recompute_specialist_scores(specialist):
    rolling, lifetime = specialist_scores(specialist)
    specialist["rolling_score"] = rolling
    specialist["lifetime_score"] = lifetime
    util.touch(specialist)


def select_specialist(inquiry, exclude_specialist_id=None):
    """specialist_assignment_selector (§1.3). Returns Specialist or None."""
    category = inquiry.get("category")
    pool = [s for s in db.specialists.values()
            if s["accepting_referrals"]
            and s["open_referral_count"] < s["max_concurrent_referrals"]
            and (exclude_specialist_id is None or s["id"] != exclude_specialist_id)]
    exact = [s for s in pool if s["specialty"] == category]
    candidates = exact if exact else [s for s in pool if s["specialty"] == "GENERAL"]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["open_referral_count"],
                                   -s.get("rolling_score", 100.0),
                                   s["created_at"]))
    return candidates[0]
