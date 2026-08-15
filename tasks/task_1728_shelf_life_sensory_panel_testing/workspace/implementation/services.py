"""Business logic: serializers, calculations (SCAFFOLD §1.3 / PRD §3),
and the cross-entity cascades."""
import math
from decimal import Decimal, ROUND_FLOOR

import clock
import db
from util import render_dt, round_half_up, touch

# ---------------------------------------------------------------- constants
ATTRIBUTES = ("APPEARANCE", "AROMA", "FLAVOR", "TEXTURE", "OFF_FLAVOR", "OVERALL")
PACKAGING_VARIANTS = ("STANDARD_FILM", "HIGH_BARRIER", "MAP", "VACUUM")
TEST_TYPES = ("APC", "YEAST_MOLD", "LACTIC", "PEROXIDE_VALUE", "PH",
              "WATER_ACTIVITY")
CLAIM_TYPES = ("SHELF_LIFE_DAYS", "PACKAGING_SUPERIORITY")
VERDICT_INPUTS = ("SUPPORTED", "NOT_SUPPORTED", "INSUFFICIENT_DATA")
TIERS = ("STANDARD", "PREMIUM")
STUDY_TYPES = ("REAL_TIME", "ACCELERATED")
UNIT_PURPOSES = ("EVALUATION", "RETAIN")

MEASURE_RANGES = {
    "APC": (0, 12),
    "YEAST_MOLD": (0, 10),
    "LACTIC": (0, 10),
    "PEROXIDE_VALUE": (0, 500),
    "PH": (0, 14),
    "WATER_ACTIVITY": (0, 1),
}
TRIP_LIMITS = {
    "APC": 6.0,
    "YEAST_MOLD": 5.0,
    "LACTIC": 7.0,
    "PEROXIDE_VALUE": 20.0,
    "PH": 8.0,
    "WATER_ACTIVITY": 0.95,
}
TEST_HOURS = {
    "APC": 1.5,
    "YEAST_MOLD": 2.0,
    "LACTIC": 2.0,
    "PEROXIDE_VALUE": 1.0,
    "PH": 0.5,
    "WATER_ACTIVITY": 0.5,
}

ACTIVE_STUDY_STATUSES = ("SCHEDULED", "IN_PROGRESS", "ANALYSIS", "REPORTING")

Z_ALPHA = 1.96
Z_BETA = 0.84
DEFAULT_VARIANCE = 2.25
MIN_PANELISTS = 4
MAX_PANELISTS = 12
PANEL_SD = 1.5
SAFETY_FACTOR = Decimal("0.2")
INCREMENT_SMALL = 7
INCREMENT_LARGE = 30
INCREMENT_TIER_BOUNDARY = 90

BASE_RESERVE_HOURS = 10
PER_TIME_POINT_HOURS = 2
PER_ARM_HOURS = 4
ASSIGNMENT_FEE_HOURS = Decimal("0.5")


# ---------------------------------------------------------------- lookups
def arms_of_study(study_id):
    return [a for a in db.store["arms"].values() if a["study_id"] == study_id]


def tps_of_study(study_id):
    return [t for t in db.store["time_points"].values()
            if t["study_id"] == study_id]


def sessions_of_study(study_id):
    return [s for s in db.store["sessions"].values()
            if s["study_id"] == study_id]


def sessions_of_tp(tp_id):
    return [s for s in db.store["sessions"].values()
            if s["time_point_id"] == tp_id]


def assignments_of_session(session_id):
    return [a for a in db.store["assignments"].values()
            if a["session_id"] == session_id]


def scores_of_assignment(assignment_id):
    return [s for s in db.store["scores"].values()
            if s["assignment_id"] == assignment_id]


def submitted_assignments(session_id):
    return [a for a in assignments_of_session(session_id)
            if a["status"] == "SUBMITTED"]


def chamber_reserved(chamber_id):
    """Derived occupancy counter (PRD §2.9): units STORED or CHECKED_OUT."""
    return sum(
        1 for u in db.store["sample_units"].values()
        if u["chamber_id"] == chamber_id and u["status"] in ("STORED",
                                                             "CHECKED_OUT"))


def client_active_study_count(client_id):
    """Derived count of studies in SCHEDULED/IN_PROGRESS/ANALYSIS/REPORTING."""
    return sum(
        1 for s in db.store["studies"].values()
        if s["client_id"] == client_id and s["status"] in ACTIVE_STUDY_STATUSES)


def study_day(study):
    """Current study day (PRD §2.4): whole days since actual_start_utc."""
    if study["actual_start_utc"] is None:
        return None
    elapsed = (clock.now() - study["actual_start_utc"]).total_seconds()
    return math.floor(elapsed / 86400)


# ---------------------------------------------------------------- serializers
def ser_client(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "contact_email": c["contact_email"],
        "tier": c["tier"],
        "retainer_hours_balance": c["retainer_hours_balance"],
        "active_study_count": client_active_study_count(c["id"]),
        "created_at": render_dt(c["created_at"]),
        "updated_at": render_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_study(s):
    return {
        "id": s["id"],
        "client_id": s["client_id"],
        "product_name": s["product_name"],
        "study_type": s["study_type"],
        "storage_temp_c": s["storage_temp_c"],
        "reference_temp_c": s["reference_temp_c"],
        "q10_factor": s["q10_factor"],
        "target_shelf_life_days": s["target_shelf_life_days"],
        "sensory_fail_threshold": s["sensory_fail_threshold"],
        "min_detectable_difference": s["min_detectable_difference"],
        "planned_start_utc": render_dt(s["planned_start_utc"]),
        "actual_start_utc": render_dt(s["actual_start_utc"]),
        "reserved_hours_escrow": s["reserved_hours_escrow"],
        "consumed_hours": s["consumed_hours"],
        "earliest_failure_day_equiv": s["earliest_failure_day_equiv"],
        "status": s["status"],
        "created_at": render_dt(s["created_at"]),
        "updated_at": render_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_arm(a):
    return {
        "id": a["id"],
        "study_id": a["study_id"],
        "packaging_variant": a["packaging_variant"],
        "is_control": a["is_control"],
        "computed_failure_day_equiv": a["computed_failure_day_equiv"],
        "created_at": render_dt(a["created_at"]),
        "updated_at": render_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_tp(t):
    return {
        "id": t["id"],
        "study_id": t["study_id"],
        "day_index": t["day_index"],
        "status": t["status"],
        "created_at": render_dt(t["created_at"]),
        "updated_at": render_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_chamber(c):
    return {
        "id": c["id"],
        "chamber_code": c["chamber_code"],
        "temp_c": c["temp_c"],
        "capacity_units": c["capacity_units"],
        "reserved_units": chamber_reserved(c["id"]),
        "created_at": render_dt(c["created_at"]),
        "updated_at": render_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_unit(u):
    return {
        "id": u["id"],
        "study_id": u["study_id"],
        "arm_id": u["arm_id"],
        "chamber_id": u["chamber_id"],
        "time_point_id": u["time_point_id"],
        "unit_purpose": u["unit_purpose"],
        "session_id": u["session_id"],
        "retention_until_utc": render_dt(u["retention_until_utc"]),
        "status": u["status"],
        "created_at": render_dt(u["created_at"]),
        "updated_at": render_dt(u["updated_at"]),
        "version": u["version"],
    }


def ser_panelist(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "email": p["email"],
        "qualified_attributes": list(p["qualified_attributes"]),
        "screening_acuity_score": p["screening_acuity_score"],
        "training_sessions_completed": p["training_sessions_completed"],
        "consecutive_no_shows": p["consecutive_no_shows"],
        "consistency_index_provisional": p["consistency_index_provisional"],
        "consistency_index_final": p["consistency_index_final"],
        "status": p["status"],
        "created_at": render_dt(p["created_at"]),
        "updated_at": render_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_session(s):
    return {
        "id": s["id"],
        "study_id": s["study_id"],
        "time_point_id": s["time_point_id"],
        "arm_id": s["arm_id"],
        "scheduled_start_utc": render_dt(s["scheduled_start_utc"]),
        "scheduled_end_utc": render_dt(s["scheduled_end_utc"]),
        "makeup_of_id": s["makeup_of_id"],
        "required_panelist_count": s["required_panelist_count"],
        "overall_mean": s["overall_mean"],
        "significance_delta": s["significance_delta"],
        "sensory_failed": s["sensory_failed"],
        "status": s["status"],
        "created_at": render_dt(s["created_at"]),
        "updated_at": render_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "session_id": a["session_id"],
        "panelist_id": a["panelist_id"],
        "status": a["status"],
        "created_at": render_dt(a["created_at"]),
        "updated_at": render_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_score(s):
    # Immutable event record: id + created_at only (PRD §2.5).
    return {
        "id": s["id"],
        "assignment_id": s["assignment_id"],
        "attribute": s["attribute"],
        "score": s["score"],
        "created_at": render_dt(s["created_at"]),
    }


def ser_lab_result(r):
    # Immutable event record: id + created_at only (PRD §2.5).
    return {
        "id": r["id"],
        "study_id": r["study_id"],
        "arm_id": r["arm_id"],
        "time_point_id": r["time_point_id"],
        "test_type": r["test_type"],
        "measured_value": r["measured_value"],
        "tripped": r["tripped"],
        "created_at": render_dt(r["created_at"]),
    }


def ser_recommendation(r):
    return {
        "id": r["id"],
        "study_id": r["study_id"],
        "arm_id": r["arm_id"],
        "basis": r["basis"],
        "computed_days": r["computed_days"],
        "status": r["status"],
        "created_at": render_dt(r["created_at"]),
        "updated_at": render_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "study_id": r["study_id"],
        "title": r["title"],
        "author_user_id": r["author_user_id"],
        "pinned_recommendation_id": r["pinned_recommendation_id"],
        "snapshot_days": r["snapshot_days"],
        "requires_revision": r["requires_revision"],
        "revision_count": r["revision_count"],
        "status": r["status"],
        "created_at": render_dt(r["created_at"]),
        "updated_at": render_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "report_id": c["report_id"],
        "claim_type": c["claim_type"],
        "claim_text": c["claim_text"],
        "claimed_value": c["claimed_value"],
        "arm_id": c["arm_id"],
        "verdict": c["verdict"],
        "verified_by": c["verified_by"],
        "created_at": render_dt(c["created_at"]),
        "updated_at": render_dt(c["updated_at"]),
        "version": c["version"],
    }


# ---------------------------------------------------------------- calculations
def q10_factor(study):
    return float(study["q10_factor"]) ** (
        (float(study["storage_temp_c"]) - float(study["reference_temp_c"]))
        / 10.0)


def equivalent_days(study, day_index):
    """shelf_life_equivalent_days: day_index * factor, 3dp round-half-up."""
    return round_half_up(day_index * q10_factor(study), 3)


def required_panelist_count(study):
    """Power sizing with pinned evaluation order (PRD §3.5)."""
    analyzed = [s for s in sessions_of_study(study["id"])
                if s["status"] == "ANALYZED"]
    if not analyzed:
        sigma2 = DEFAULT_VARIANCE
    else:
        scores = []
        for sess in analyzed:
            for asg in submitted_assignments(sess["id"]):
                for sc in scores_of_assignment(asg["id"]):
                    if sc["attribute"] == "OVERALL":
                        scores.append(sc["score"])
        n = len(scores)
        if n < 2:
            sigma2 = DEFAULT_VARIANCE
        else:
            mean = sum(scores) / n
            sigma2 = sum((x - mean) ** 2 for x in scores) / (n - 1)
    delta = float(study["min_detectable_difference"])
    if delta == 0:
        n_raw = math.inf
    else:
        n_raw = 2 * (Z_ALPHA + Z_BETA) ** 2 * sigma2 / delta ** 2
    n = math.ceil(n_raw)
    # clamp applies AFTER ceil (SCAFFOLD §1.3 required_panelist_count)
    return max(MIN_PANELISTS, min(MAX_PANELISTS, n))


def date_code_for(arm, study):
    """date_code_recommendation: nested floors with tiered increment."""
    if arm["computed_failure_day_equiv"] is not None:
        base = Decimal(str(arm["computed_failure_day_equiv"]))
        basis = "ENDPOINT_MIN"
    else:
        base = Decimal(str(study["target_shelf_life_days"]))
        basis = "TARGET_FALLBACK"
    safety_days = int((base * (Decimal(1) - SAFETY_FACTOR)).to_integral_value(
        rounding=ROUND_FLOOR))
    increment = INCREMENT_SMALL if safety_days < INCREMENT_TIER_BOUNDARY \
        else INCREMENT_LARGE
    computed_days = (safety_days // increment) * increment
    return basis, computed_days


def overall_mean_of(session):
    """attribute_mean_score for OVERALL over SUBMITTED assignments, 2dp."""
    vals = []
    for asg in submitted_assignments(session["id"]):
        for sc in scores_of_assignment(asg["id"]):
            if sc["attribute"] == "OVERALL":
                vals.append(sc["score"])
    if not vals:
        return None
    return round_half_up(Decimal(sum(vals)) / Decimal(len(vals)), 2)


def consumed_hours_for(study):
    """retainer_hours_settlement: per-session 0.25h quantum FIRST, then sum,
    grand total 2dp round-half-up (PRD §3.7 pinned order)."""
    total = Decimal(0)
    for sess in sessions_of_study(study["id"]):
        if sess["status"] != "ANALYZED":
            continue
        duration_minutes = Decimal(str(
            (sess["scheduled_end_utc"] - sess["scheduled_start_utc"])
            .total_seconds())) / Decimal(60)
        quanta = int((duration_minutes / Decimal(15)).to_integral_value(
            rounding="ROUND_CEILING"))
        room_hours = Decimal(quanta) * Decimal("0.25")
        total += room_hours
        total += ASSIGNMENT_FEE_HOURS * len(submitted_assignments(sess["id"]))
    for lr in db.store["lab_results"].values():
        if lr["study_id"] == study["id"]:
            total += Decimal(str(TEST_HOURS[lr["test_type"]]))
    return round_half_up(total, 2)


def consistency_index(panelist_id, variant):
    """panelist_consistency_index. PROVISIONAL: sessions in {LOCKED, ANALYZED},
    reference mean includes own score. FINAL: ANALYZED only, leave-one-out."""
    statuses = ("LOCKED", "ANALYZED") if variant == "PROVISIONAL" \
        else ("ANALYZED",)
    penalties = []
    for sess in db.store["sessions"].values():
        if sess["status"] not in statuses:
            continue
        own_asg = None
        for asg in assignments_of_session(sess["id"]):
            if asg["panelist_id"] == panelist_id and asg["status"] == "SUBMITTED":
                own_asg = asg
                break
        if own_asg is None:
            continue
        own_scores = {sc["attribute"]: sc["score"]
                      for sc in scores_of_assignment(own_asg["id"])}
        # gather the session's SUBMITTED cell scores per attribute
        cell = {}
        for asg in submitted_assignments(sess["id"]):
            for sc in scores_of_assignment(asg["id"]):
                cell.setdefault(sc["attribute"], []).append(
                    (asg["panelist_id"], sc["score"]))
        for attribute, own in own_scores.items():
            entries = cell.get(attribute, [])
            if variant == "PROVISIONAL":
                ref = Decimal(sum(v for _, v in entries)) / Decimal(
                    len(entries))
            else:
                others = [v for pid, v in entries if pid != panelist_id]
                if not others:
                    continue
                ref = Decimal(sum(others)) / Decimal(len(others))
            penalties.append(abs(Decimal(own) - ref))
    if not penalties:
        return None
    penalty = sum(penalties) / Decimal(len(penalties))
    index = Decimal(100) - Decimal(20) * penalty
    if index < 0:
        index = Decimal(0)
    return round_half_up(index, 2)


# ---------------------------------------------------------------- cascades
def flag_reports_for_superseded(rec_id):
    """Supersession report cascade (PRD §3.7)."""
    for report in db.store["reports"].values():
        if report["pinned_recommendation_id"] != rec_id:
            continue
        if report["status"] in ("DRAFT", "INTERNAL_REVIEW"):
            if not report["requires_revision"]:
                report["requires_revision"] = True
                touch(report)
        elif report["status"] == "CLIENT_REVIEW":
            report["status"] = "DRAFT"
            report["requires_revision"] = True
            report["revision_count"] += 1
            touch(report)


def supersede_recommendation(rec):
    if rec["status"] not in ("PROPOSED", "ACCEPTED"):
        return
    rec["status"] = "SUPERSEDED"
    touch(rec)
    flag_reports_for_superseded(rec["id"])


def recompute_arm_failure(arm):
    """Failure-day cascade (PRD §3.5/§3.6): arm min, study min, and — only
    when the arm's failure day changed — recommendation supersession."""
    study = db.store["studies"][arm["study_id"]]
    values = []
    for sess in db.store["sessions"].values():
        if (sess["arm_id"] == arm["id"]
                and sess["status"] in ("LOCKED", "ANALYZED")
                and sess["sensory_failed"]):
            tp = db.store["time_points"][sess["time_point_id"]]
            values.append(equivalent_days(study, tp["day_index"]))
    for lr in db.store["lab_results"].values():
        if lr["arm_id"] == arm["id"] and lr["tripped"]:
            tp = db.store["time_points"][lr["time_point_id"]]
            values.append(equivalent_days(study, tp["day_index"]))
    new_value = min(values) if values else None
    if new_value == arm["computed_failure_day_equiv"]:
        return
    arm["computed_failure_day_equiv"] = new_value
    touch(arm)
    arm_values = [a["computed_failure_day_equiv"]
                  for a in arms_of_study(study["id"])
                  if a["computed_failure_day_equiv"] is not None]
    new_earliest = min(arm_values) if arm_values else None
    if new_earliest != study["earliest_failure_day_equiv"]:
        study["earliest_failure_day_equiv"] = new_earliest
        touch(study)
    for rec in db.store["recommendations"].values():
        if rec["arm_id"] == arm["id"] and rec["status"] in ("PROPOSED",
                                                            "ACCEPTED"):
            supersede_recommendation(rec)


def recompute_provisional_for_session(session):
    seen = set()
    for asg in submitted_assignments(session["id"]):
        pid = asg["panelist_id"]
        if pid in seen:
            continue
        seen.add(pid)
        panelist = db.store["panelists"][pid]
        value = consistency_index(pid, "PROVISIONAL")
        if value != panelist["consistency_index_provisional"]:
            panelist["consistency_index_provisional"] = value
            touch(panelist)


def recompute_final_for_session(session):
    seen = set()
    for asg in submitted_assignments(session["id"]):
        pid = asg["panelist_id"]
        if pid in seen:
            continue
        seen.add(pid)
        panelist = db.store["panelists"][pid]
        value = consistency_index(pid, "FINAL")
        if value != panelist["consistency_index_final"]:
            panelist["consistency_index_final"] = value
            touch(panelist)


def excuse_assignment(asg):
    if asg["status"] != "ASSIGNED":
        return
    asg["status"] = "EXCUSED"
    touch(asg)


def cancel_session(session):
    session["status"] = "CANCELLED"
    touch(session)
    for asg in assignments_of_session(session["id"]):
        excuse_assignment(asg)


def discard_unit(unit):
    if unit["status"] not in ("STORED", "CHECKED_OUT"):
        return
    chamber = db.store["chambers"][unit["chamber_id"]]
    unit["status"] = "DISCARDED"
    unit["session_id"] = None
    touch(unit)
    touch(chamber)  # reserved_units derived; occupancy changed


def suspend_panelist(panelist):
    """QUALIFIED -> SUSPENDED with the excuse cascade (PRD §3.4)."""
    panelist["status"] = "SUSPENDED"
    touch(panelist)
    for asg in db.store["assignments"].values():
        if asg["panelist_id"] != panelist["id"] or asg["status"] != "ASSIGNED":
            continue
        sess = db.store["sessions"][asg["session_id"]]
        if sess["status"] in ("PLANNED", "OPEN"):
            excuse_assignment(asg)
