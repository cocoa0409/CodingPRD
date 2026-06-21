"""State-machine transitions and cascades (PRD §3.3, §3.6, §3.7, §3.8, SCAFFOLD §1.2).

Each transition: state gate first (ERR_INVALID_STATE), then the ordered business
rules per the PRD workflow, then side effects with per-resource version bumps.
"""
import db
import errors
from clock import now_iso
from services import lookups


# ---------------------------------------------------------------------------
# Admission: activate (PENDING -> ACTIVE | NON_COVERED)  (PRD §3.3)
# ---------------------------------------------------------------------------
def activate_admission(adm, allow_non_covered):
    # State (priority 5): must be PENDING.
    if adm["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "admission is not PENDING")

    pasrr = db.pasrr_screenings.get(adm["pasrr_screening_id"])
    # PASRR clearance is checked first (PRD §3.3 ordering, priority 6).
    if pasrr is None or pasrr["status"] != "CLEARED":
        raise errors.err(errors.ERR_PASRR_NOT_CLEARED, "linked PASRR screening is not CLEARED")

    # Qualifying-stay requirement, evaluated before bed availability (priority 7).
    is_medicare = adm["payer_source"] == "MEDICARE_A"
    qs = db.qualifying_stays.get(adm["qualifying_stay_id"]) if adm.get("qualifying_stay_id") else None
    qs_met = bool(qs and qs.get("qualifies"))
    if is_medicare and not qs_met and not allow_non_covered:
        raise errors.err(errors.ERR_QUALIFYING_STAY_NOT_MET,
                         "Medicare-A admission requires a qualifying 3-midnight stay")

    # Bed availability (priority 8).
    facility = db.facilities.get(adm["facility_id"])
    if facility is None or facility["occupied_bed_count"] >= facility["certified_bed_count"]:
        raise errors.err(errors.ERR_NO_BEDS_AVAILABLE, "facility has no available beds")

    # Decide outcome.
    if is_medicare and not qs_met:
        # allow_non_covered must be true to reach here (else rejected above).
        adm["medicare_covered"] = False
        adm["status"] = "NON_COVERED"
    else:
        adm["medicare_covered"] = bool(is_medicare and qs_met)
        adm["status"] = "ACTIVE"
    db.touch(adm)

    # Resident PROSPECTIVE -> ADMITTED.
    res = db.residents.get(adm["resident_id"])
    if res is not None:
        res["status"] = "ADMITTED"
        db.touch(res)

    # Facility census recomputed.
    lookups.recompute_facility_census(adm["facility_id"])


# ---------------------------------------------------------------------------
# Admission: plan-discharge (ACTIVE|NON_COVERED -> DISCHARGE_PLANNED)  (PRD §3.8)
# ---------------------------------------------------------------------------
def plan_discharge(adm):
    if adm["status"] not in ("ACTIVE", "NON_COVERED"):
        raise errors.err(errors.ERR_INVALID_STATE, "admission is not ACTIVE or NON_COVERED")

    # At least one ACTIVE care plan (priority 16).
    plans = lookups.care_plans_for_admission(adm["id"])
    if not any(p["status"] == "ACTIVE" for p in plans):
        raise errors.err(errors.ERR_NO_ACTIVE_CARE_PLAN,
                         "admission has no ACTIVE care plan")

    # For an ACTIVE admission, no OPEN bed-hold may exist (PRD §3.8).
    if adm["status"] == "ACTIVE":
        if any(b["status"] == "OPEN" for b in lookups.bed_holds_for_admission(adm["id"])):
            raise errors.err(errors.ERR_INVALID_STATE,
                             "an open bed-hold exists for the admission")

    adm["status"] = "DISCHARGE_PLANNED"
    db.touch(adm)

    # Side effect: scheduled DISCHARGE assessments -> IN_PROGRESS.
    for a in lookups.assessments_for_admission(adm["id"]):
        if a["assessment_type"] == "DISCHARGE" and a["status"] == "SCHEDULED":
            a["status"] = "IN_PROGRESS"
            db.touch(a)


# ---------------------------------------------------------------------------
# Admission: discharge (DISCHARGE_PLANNED -> DISCHARGED)  (PRD §3.8)
# ---------------------------------------------------------------------------
def discharge_admission(adm, discharge_at):
    if adm["status"] != "DISCHARGE_PLANNED":
        raise errors.err(errors.ERR_INVALID_STATE, "admission is not DISCHARGE_PLANNED")

    # Every DISCHARGE-type assessment must be SUBMITTED (priority 17).
    for a in lookups.assessments_for_admission(adm["id"]):
        if a["assessment_type"] == "DISCHARGE" and a["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_DISCHARGE_ASSESSMENT_INCOMPLETE,
                             "a DISCHARGE assessment is not SUBMITTED")

    # Every care plan must be ACTIVE or CLOSED (PRD §3.8).
    for p in lookups.care_plans_for_admission(adm["id"]):
        if p["status"] not in ("ACTIVE", "CLOSED"):
            raise errors.err(errors.ERR_INVALID_STATE,
                             "a care plan is neither ACTIVE nor CLOSED")

    # Resident must be ADMITTED (not ON_LEAVE) (PRD §3.8).
    res = db.residents.get(adm["resident_id"])
    if res is not None and res["status"] == "ON_LEAVE":
        raise errors.err(errors.ERR_INVALID_STATE, "resident is ON_LEAVE")

    adm["status"] = "DISCHARGED"
    adm["discharge_at"] = discharge_at
    db.touch(adm)

    if res is not None:
        res["status"] = "DISCHARGED"
        db.touch(res)

    _cascade_close_plans(adm["id"])
    lookups.recompute_facility_census(adm["facility_id"])


def _cascade_close_plans(admission_id):
    """Depth-3 cascade: ACTIVE care plans -> CLOSED; their OPEN/IN_PROGRESS
    goals -> DISCONTINUED (PRD §3.7, §3.8)."""
    for p in lookups.care_plans_for_admission(admission_id):
        if p["status"] == "ACTIVE":
            p["status"] = "CLOSED"
            db.touch(p)
            _cascade_discontinue_goals(p["id"])


def _cascade_discontinue_goals(care_plan_id):
    changed = False
    for g in lookups.goals_for_plan(care_plan_id):
        if g["status"] in ("OPEN", "IN_PROGRESS"):
            g["status"] = "DISCONTINUED"
            db.touch(g)
            changed = True
    if changed:
        lookups.recompute_open_goal_count(care_plan_id)


# ---------------------------------------------------------------------------
# BedHold close (PRD §3.6)
# ---------------------------------------------------------------------------
def close_bed_hold(bh, return_outcome, actual_return_at):
    from services import calc

    if bh["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "bed-hold is not OPEN")

    adm = db.admissions.get(bh["admission_id"])
    res = db.residents.get(adm["resident_id"]) if adm else None

    if return_outcome == "RETURNED":
        # actual_return_at required and strictly after leave_start_at (PRD §3.6).
        if actual_return_at is None:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "actual_return_at is required for RETURNED")
        from clock import parse_iso
        if not (parse_iso(actual_return_at) > parse_iso(bh["leave_start_at"])):
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "actual_return_at must be strictly after leave_start_at")
        bh["actual_return_at"] = actual_return_at
        leave_days, paid = calc.bed_hold_days(
            bh["leave_start_at"], actual_return_at, adm["payer_source"])
        bh["leave_day_count"] = leave_days
        bh["paid_day_count"] = paid
        bh["status"] = "CLOSED"
        db.touch(bh)
        if res is not None:
            res["status"] = "ADMITTED"
            db.touch(res)
        # Admission.covered_day_count reduced by unpaid portion.
        unpaid = leave_days - paid
        adm["covered_day_count"] = adm["covered_day_count"] - unpaid
        db.touch(adm)
    elif return_outcome == "DID_NOT_RETURN":
        bh["status"] = "CONVERTED_TO_DISCHARGE"
        db.touch(bh)
        if res is not None:
            res["status"] = "DISCHARGED"
            db.touch(res)
        adm["status"] = "DISCHARGED"
        adm["discharge_at"] = bh["leave_start_at"]
        db.touch(adm)
        _cascade_close_plans(adm["id"])
        lookups.recompute_facility_census(adm["facility_id"])
    else:
        raise errors.err(errors.ERR_INVALID_REQUEST, "unknown return_outcome")
