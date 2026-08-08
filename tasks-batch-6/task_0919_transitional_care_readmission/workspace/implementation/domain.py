"""Calculations, derived fields and cascades (PRD sections 2.7-2.9 and 3)."""
from datetime import timedelta

import constants as C
import store
from store import DB, dec, round_half_up, touch


# =========================================================================
# 3.2 Readmission risk scoring and the tier fork
# =========================================================================
def risk_components(stay_type, los_days, los_hours, acuity, comorbidity, ed_visits,
                    admissions, social_flags):
    """Each component is rounded half up to a whole number on its own BEFORE
    the five whole numbers are summed (PRD 2.8)."""
    if stay_type == "INPATIENT":
        los_variant = "INPATIENT_DAYS"
        raw = dec(los_days or 0) * dec(C.LOS_INPATIENT_POINTS_PER_DAY)
        los_points = min(C.LOS_INPATIENT_POINT_CAP, round_half_up(raw))
    else:
        los_variant = "OBSERVATION_HOURS"
        raw = dec(los_hours or 0) / dec(C.LOS_OBSERVATION_HOURS_PER_POINT)
        los_points = min(C.LOS_OBSERVATION_POINT_CAP, round_half_up(raw))

    acuity_points = C.ACUITY_POINTS[acuity]

    comorbidity_points = min(
        C.COMORBIDITY_POINT_CAP,
        round_half_up(dec(comorbidity) * dec(C.COMORBIDITY_POINTS_PER_CONDITION)),
    )

    utilization_points = min(
        C.UTILIZATION_POINT_CAP,
        ed_visits * C.UTILIZATION_POINTS_PER_ED_VISIT
        + admissions * C.UTILIZATION_POINTS_PER_ADMISSION,
    )

    social_modifier_points = min(
        C.SOCIAL_POINT_CAP,
        round_half_up(dec(social_flags) * dec(C.SOCIAL_POINTS_PER_FLAG)),
    )

    risk_score = min(
        C.RISK_SCORE_CAP,
        los_points + acuity_points + comorbidity_points + utilization_points
        + social_modifier_points,
    )
    return {
        "los_variant": los_variant,
        "los_points": los_points,
        "acuity_points": acuity_points,
        "comorbidity_points": comorbidity_points,
        "utilization_points": utilization_points,
        "social_modifier_points": social_modifier_points,
        "risk_score": risk_score,
    }


def risk_tier(risk_score):
    if risk_score >= C.RISK_TIER_SEVERE_FLOOR:
        return "SEVERE"
    if risk_score >= C.RISK_TIER_HIGH_FLOOR:
        return "HIGH"
    if risk_score >= C.RISK_TIER_MODERATE_FLOOR:
        return "MODERATE"
    return "LOW"


# =========================================================================
# 3.3 Contact deadline (dual variant on the payer's basis)
# =========================================================================
def contact_deadline_at(episode):
    payer = DB["payers"].get(episode["payer_id"])
    n = episode["contact_sla_business_days"]
    basis = payer["contact_deadline_basis"] if payer else "BUSINESS_DAYS"
    if basis == "CALENDAR_HOURS":
        return episode["discharge_datetime"] + timedelta(
            hours=n * C.HOURS_PER_SLA_DAY_CALENDAR_VARIANT
        )
    reached = store.walk_business_days(episode["discharge_date"], n)
    return store.end_of_day(reached)


def visit_due_date(required_complexity, discharge_date):
    days = (
        C.VISIT_DUE_DAYS_HIGH_COMPLEXITY
        if required_complexity == "HIGH_COMPLEXITY"
        else C.VISIT_DUE_DAYS_MODERATE_COMPLEXITY
    )
    return store.add_days(discharge_date, days)


def apply_tier_to_episode(episode, assessment):
    """Rewrites every tier-driven programme parameter onto the episode."""
    tier = assessment["risk_tier"]
    episode["risk_score"] = assessment["risk_score"]
    episode["risk_tier"] = tier
    episode["current_risk_assessment_id"] = assessment["id"]
    episode["contact_sla_business_days"] = C.CONTACT_SLA_BUSINESS_DAYS[tier]
    episode["required_visit_complexity"] = C.REQUIRED_COMPLEXITY[tier]
    episode["contact_deadline_at"] = contact_deadline_at(episode)
    episode["visit_due_date"] = visit_due_date(
        episode["required_visit_complexity"], episode["discharge_date"]
    )


# =========================================================================
# 3.4 Visit deadline status and slot conflicts
# =========================================================================
def visit_deadline_status(visit):
    deadline = store.end_of_day(visit["visit_due_date"])
    status = visit["encounter_status"]
    if status == "COMPLETED":
        return "MET" if visit["completed_at"] <= deadline else "MISSED"
    if status in ("NO_SHOW", "CANCELLED"):
        if store.now() > deadline:
            return "MISSED"
        return visit["deadline_status"]
    return "SCHEDULED_IN_WINDOW" if visit["scheduled_start"] <= deadline else "SCHEDULED_LATE"


def slot_conflict(navigator_id, new_start, new_end, exclude_visit_id=None):
    """Trailing-only 20 minute turnaround buffer appended to each candidate's end."""
    buffer = timedelta(minutes=C.VISIT_TURNAROUND_BUFFER_MINUTES)
    for candidate in DB["visits"].values():
        if candidate["navigator_id"] != navigator_id:
            continue
        if candidate["encounter_status"] != "SCHEDULED":
            continue
        if exclude_visit_id is not None and candidate["id"] == exclude_visit_id:
            continue
        if new_start < candidate["scheduled_end"] + buffer and candidate["scheduled_start"] < new_end:
            return True
    return False


# =========================================================================
# Aggregate recomputations - these are the conservation invariants
# =========================================================================
def _assign(row, values):
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def recompute_navigator(navigator_id):
    navigator = DB["navigators"].get(navigator_id)
    if navigator is None:
        return
    active = [
        e
        for e in DB["episodes"].values()
        if e["navigator_id"] == navigator_id and e["status"] in C.OPEN_EPISODE_STATUSES
    ]
    count = len(active)
    if navigator["cap_policy"] == "COUNT":
        workload = count
    else:
        workload = sum(C.WORKLOAD_WEIGHT[e["risk_tier"]] for e in active)
    _assign(
        navigator,
        {
            "active_episode_count": count,
            "workload_score": workload,
            "availability_status": "AVAILABLE"
            if workload < navigator["active_episode_cap"]
            else "AT_CAP",
        },
    )


def incoming_weight(navigator, episode):
    if navigator["cap_policy"] == "COUNT":
        return 1
    return C.WORKLOAD_WEIGHT[episode["risk_tier"]]


def recompute_patient(patient_id):
    patient = DB["patients"].get(patient_id)
    if patient is None:
        return
    episodes = [e for e in DB["episodes"].values() if e["patient_id"] == patient_id]
    episode_ids = {e["id"] for e in episodes}
    counted = 0
    for event in DB["readmissions"].values():
        if (
            event["episode_id"] in episode_ids
            and event["status"] == "RECORDED"
            and event["counts_toward_rate"]
        ):
            counted += 1
    _assign(
        patient,
        {
            "open_episode_count": len(
                [e for e in episodes if e["status"] in C.OPEN_EPISODE_STATUSES]
            ),
            "lifetime_episode_count": len(episodes),
            "lifetime_readmission_count": counted,
        },
    )


def recompute_episode_readmission_counters(episode):
    events = [e for e in DB["readmissions"].values() if e["episode_id"] == episode["id"]]
    recorded = [e for e in events if e["status"] == "RECORDED"]
    _assign(
        episode,
        {
            "readmission_event_count": len(events),
            "counted_readmission_count": len([e for e in recorded if e["counts_toward_rate"]]),
            "excluded_readmission_count": len(
                [e for e in recorded if not e["counts_toward_rate"]]
            ),
            "retracted_readmission_count": len([e for e in events if e["status"] == "RETRACTED"]),
        },
    )


def recompute_episode_red_flags(episode):
    open_flags = len(
        [
            f
            for f in DB["red_flags"].values()
            if f["episode_id"] == episode["id"] and f["status"] in ("RAISED", "ACKNOWLEDGED")
        ]
    )
    _assign(
        episode,
        {
            "open_red_flag_count": open_flags,
            "escalation_state": "ACTIVE" if open_flags > 0 else "NONE",
        },
    )


def recompute_episode_contact_attempts(episode):
    _assign(
        episode,
        {
            "contact_attempt_count": len(
                [a for a in DB["contact_attempts"].values() if a["episode_id"] == episode["id"]]
            )
        },
    )


def recompute_medrec_counters(recon):
    items = [d for d in DB["discrepancies"].values() if d["med_reconciliation_id"] == recon["id"]]
    _assign(
        recon,
        {
            "discrepancy_count": len(items),
            "resolved_count": len([d for d in items if d["status"] == "RESOLVED"]),
            "unresolved_count": len([d for d in items if d["status"] == "UNRESOLVED"]),
            "deferred_count": len([d for d in items if d["status"] == "DEFERRED"]),
            "blocking_unresolved_count": len(
                [
                    d
                    for d in items
                    if d["status"] == "UNRESOLVED"
                    and d["severity"] in C.BLOCKING_DISCREPANCY_SEVERITIES
                ]
            ),
        },
    )


# =========================================================================
# Episode lookups
# =========================================================================
def episode_claim(episode):
    """The episode's single current claim, as pointed at by episode.claim_id."""
    if episode.get("claim_id"):
        return DB["claims"].get(episode["claim_id"])
    return None


def episode_medrec(episode):
    for recon in DB["med_reconciliations"].values():
        if recon["episode_id"] == episode["id"]:
            return recon
    return None


def has_non_terminal_claim(episode):
    for claim in DB["claims"].values():
        if claim["episode_id"] == episode["id"] and claim["status"] in C.NON_TERMINAL_CLAIM_STATUSES:
            return True
    return False


def has_open_blocking_barrier(episode):
    for barrier in DB["barriers"].values():
        if (
            barrier["episode_id"] == episode["id"]
            and barrier["blocking_class"]
            and barrier["status"] in ("OPEN", "ESCALATED")
        ):
            return True
    return False


# =========================================================================
# 2.9 / 3.3 / 3.4 / 3.5 compliance flags (frozen at service-period closure)
# =========================================================================
def recompute_contact_timely(episode):
    if episode["_flags_frozen"]:
        return
    value = (
        episode["successful_contact_at"] is not None
        and episode["successful_contact_at"] <= episode["contact_deadline_at"]
    )
    _assign(episode, {"contact_timely": value})


def recompute_visit_timely(episode):
    if episode["_flags_frozen"]:
        return
    value = episode["visit_completed_at"] is not None and episode[
        "visit_completed_at"
    ] <= store.end_of_day(episode["visit_due_date"])
    _assign(episode, {"visit_timely": value})


def set_medrec_complete(episode, value):
    if episode["_flags_frozen"]:
        return
    _assign(episode, {"medrec_complete": value})


# =========================================================================
# 2.7 Record posture: the global write gate
# =========================================================================
def evaluate_freeze(episode):
    if episode["record_posture"] == "OPEN":
        if episode["status"] in C.FROZEN_EPISODE_STATUSES and not has_non_terminal_claim(episode):
            _assign(episode, {"record_posture": "FROZEN"})
            freeze_cascade(episode)
    else:
        if episode["status"] not in C.FROZEN_EPISODE_STATUSES:
            _assign(episode, {"record_posture": "OPEN"})


def freeze_cascade(episode):
    """Three-branch cascade over the episode's children (PRD 2.7)."""
    for handoff in DB["handoffs"].values():
        if handoff["episode_id"] == episode["id"] and handoff["status"] == "PROPOSED":
            handoff["status"] = "SUPERSEDED"
            handoff["superseded_by_id"] = None
            touch(handoff)
    for flag in DB["red_flags"].values():
        if flag["episode_id"] == episode["id"] and flag["status"] in ("RAISED", "ACKNOWLEDGED"):
            flag["status"] = "CLOSED_ADMINISTRATIVE"
            touch(flag)
    for barrier in DB["barriers"].values():
        if barrier["episode_id"] == episode["id"] and barrier["status"] in ("OPEN", "ESCALATED"):
            barrier["status"] = "CLOSED_ADMINISTRATIVE"
            barrier["closed_at"] = store.now()
            touch(barrier)
    recompute_episode_red_flags(episode)


def void_claim(claim):
    claim["status"] = "VOIDED"
    claim["net_payable_cents"] = 0
    touch(claim)


# =========================================================================
# Red flag creation (clinician-raised and system-raised alike)
# =========================================================================
def create_red_flag(episode, category, tier, raised_by_user_id, source_barrier_id=None):
    raised_at = store.now()
    flag = store.new_row(
        "red_flags",
        {
            "episode_id": episode["id"],
            "source_barrier_id": source_barrier_id,
            "category": category,
            "initial_tier": tier,
            "tier": tier,
            "promotion_count": 0,
            "status": "RAISED",
            "raised_by_user_id": raised_by_user_id,
            "raised_at": raised_at,
            "ack_due_at": raised_at + timedelta(minutes=C.REDFLAG_ACK_SLA_MINUTES[tier]),
            "acknowledged_by_user_id": None,
            "acknowledged_at": None,
            "resolution_outcome": None,
            "spawned_readmission_id": None,
            "ed_event_suppressed": False,
        },
    )
    recompute_episode_red_flags(episode)
    return flag


def create_readmission_event(episode, readmission_date, classification, recorded_by_user_id,
                             source_red_flag_id=None):
    event = store.new_row(
        "readmissions",
        {
            "episode_id": episode["id"],
            "source_red_flag_id": source_red_flag_id,
            "readmission_date": readmission_date,
            "day_index": store.day_diff(readmission_date, episode["discharge_date"]),
            "classification": classification,
            "counts_toward_rate": classification in C.READMISSION_COUNTING_CLASSES,
            "status": "RECORDED",
            "retraction_reason": None,
            "recorded_by_user_id": recorded_by_user_id,
        },
    )
    recompute_episode_readmission_counters(episode)
    recompute_patient(episode["patient_id"])
    return event


# =========================================================================
# 3.8 TCM claim money waterfall
# =========================================================================
def claim_code_selection(episode, visit):
    """Returns (payable_code, payable_variant, base_rate_cents) or None when the
    visit missed both deadlines."""
    high_deadline = store.end_of_day(
        store.add_days(episode["discharge_date"], C.VISIT_DUE_DAYS_HIGH_COMPLEXITY)
    )
    moderate_deadline = store.end_of_day(
        store.add_days(episode["discharge_date"], C.VISIT_DUE_DAYS_MODERATE_COMPLEXITY)
    )
    required = episode["required_visit_complexity"]
    achieved = visit["achieved_complexity"]
    completed_at = visit["completed_at"]

    if (
        required == "HIGH_COMPLEXITY"
        and achieved == "HIGH_COMPLEXITY"
        and completed_at <= high_deadline
    ):
        code = C.TCM_HIGH_CODE
    elif completed_at <= moderate_deadline:
        code = C.TCM_MODERATE_CODE
    else:
        return None
    variant = (
        "DOWNGRADED"
        if (required == "HIGH_COMPLEXITY" and code == C.TCM_MODERATE_CODE)
        else "FULL"
    )
    base = C.TCM_HIGH_BASE_RATE_CENTS if code == C.TCM_HIGH_CODE else C.TCM_MODERATE_BASE_RATE_CENTS
    return code, variant, base


def claim_money(base_rate_cents, payer):
    """Strictly ordered waterfall; each multiplication rounds half up to whole cents."""
    allowed = round_half_up(dec(base_rate_cents) * dec(payer["tcm_rate_multiplier"]))
    coinsurance = round_half_up(dec(allowed) * dec(payer["coinsurance_rate"]))
    net_before = allowed - coinsurance
    withhold_pct = (
        float(C.WITHHOLD_PCT_ABOVE_THRESHOLD)
        if net_before >= C.WITHHOLD_TIER_THRESHOLD_CENTS
        else float(C.WITHHOLD_PCT_BELOW_THRESHOLD)
    )
    withhold_src = (
        C.WITHHOLD_PCT_ABOVE_THRESHOLD
        if net_before >= C.WITHHOLD_TIER_THRESHOLD_CENTS
        else C.WITHHOLD_PCT_BELOW_THRESHOLD
    )
    withhold = round_half_up(dec(net_before) * dec(withhold_src))
    return {
        "allowed_cents": allowed,
        "coinsurance_cents": coinsurance,
        "net_before_withhold_cents": net_before,
        "withhold_pct": withhold_pct,
        "withhold_cents": withhold,
        "net_payable_cents": net_before - withhold,
    }
