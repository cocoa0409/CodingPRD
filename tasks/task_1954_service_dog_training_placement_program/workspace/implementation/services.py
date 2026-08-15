"""Business logic: calculations, serializers, state transitions and cascades."""
from datetime import timedelta
from decimal import Decimal

from core import (
    STORE,
    base_fields,
    fmt_date,
    fmt_ts,
    milestone_base_fields,
    new_id,
    now,
    round_half_up_1dp,
    round_half_up_int,
    today,
    touch,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TASK_CODES = {
    "RETRIEVE_ITEMS",
    "OPEN_DOORS",
    "BALANCE_SUPPORT",
    "INTERRUPT_ANXIETY",
    "ALERT_SOUND",
    "GUIDE_NAVIGATION",
    "DEEP_PRESSURE",
    "MEDICAL_ALERT",
}

PLACEMENT_TRACKS = {"MOBILITY", "PTSD", "AUTISM", "FACILITY"}

BASE_REQUIREMENT_CENTS = {
    "MOBILITY": 1500000,
    "PTSD": 1800000,
    "AUTISM": 1800000,
    "FACILITY": 900000,
}

URGENCY_PTS = {"STANDARD": 10, "HIGH": 25, "CRITICAL": 40}

HIP_PTS = {"EXCELLENT": 30, "GOOD": 24, "FAIR": 12, "POOR": 0}
ELBOW_PTS = {"NORMAL": 20, "GRADE1": 8, "GRADE2": 0}
EYE_PTS = {"CLEAR": 15, "ABNORMAL": 0}
CARDIAC_PTS = {"NORMAL": 15, "ABNORMAL": 0}
GENETIC_PTS = {"CLEAR": 20, "CARRIER": 10, "AFFECTED": 0}

DONATED_THRESHOLD = 84
BRED_THRESHOLD = 92

# ---------------------------------------------------------------------------
# Serializers (strip internals, format timestamps/dates)
# ---------------------------------------------------------------------------


def ser_applicant(a):
    return {
        "id": a["id"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
        "full_name": a["full_name"],
        "email": a["email"],
        "placement_track": a["placement_track"],
        "household_income_cents": a["household_income_cents"],
        "verified_income_cents": a["verified_income_cents"],
        "region": a["region"],
        "application_status": a["application_status"],
        "reviewed_by_user_id": a["reviewed_by_user_id"],
        "approved_by_user_id": a["approved_by_user_id"],
        "denial_reason": a["denial_reason"],
    }


def ser_assessment(t):
    return {
        "id": t["id"],
        "created_at": fmt_ts(t["created_at"]),
        "updated_at": fmt_ts(t["updated_at"]),
        "version": t["version"],
        "applicant_id": t["applicant_id"],
        "required_tasks": list(t["required_tasks"]),
        "task_urgency_tier": t["task_urgency_tier"],
        "home_environment_score": t["home_environment_score"],
        "status": t["status"],
        "finalized_by_user_id": t["finalized_by_user_id"],
        "notes": t["notes"],
    }


def effective_requirement(entry):
    if entry["requirement_final_cents"] is not None:
        return entry["requirement_final_cents"]
    return entry["requirement_provisional_cents"]


def ser_waitlist_entry(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
        "applicant_id": e["applicant_id"],
        "status": e["status"],
        "listed_at": fmt_ts(e["listed_at"]),
        "requirement_provisional_cents": e["requirement_provisional_cents"],
        "requirement_final_cents": e["requirement_final_cents"],
        "effective_requirement_cents": effective_requirement(e),
        "raised_cents": e["raised_cents"],
        "dissolved_match_count": e["dissolved_match_count"],
        "rank_score": e["rank_score"],
    }


def ser_contribution(c):
    return {
        "id": c["id"],
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
        "applicant_id": c["applicant_id"],
        "donor_name": c["donor_name"],
        "amount_cents": c["amount_cents"],
        "status": c["status"],
        "created_by_user_id": c["created_by_user_id"],
        "received_by_user_id": c["received_by_user_id"],
    }


def ser_raiser(r):
    return {
        "id": r["id"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
        "full_name": r["full_name"],
        "region": r["region"],
        "foster_capacity": r["foster_capacity"],
        "experience_score": r["experience_score"],
        "status": r["status"],
        "current_dog_count": r["current_dog_count"],
        "last_placement_ended_at": fmt_ts(r["last_placement_ended_at"]),
    }


def ser_trainer(t):
    return {
        "id": t["id"],
        "created_at": fmt_ts(t["created_at"]),
        "updated_at": fmt_ts(t["updated_at"]),
        "version": t["version"],
        "full_name": t["full_name"],
        "pat_certified": t["pat_certified"],
        "status": t["status"],
    }


def ser_dog(d):
    return {
        "id": d["id"],
        "created_at": fmt_ts(d["created_at"]),
        "updated_at": fmt_ts(d["updated_at"]),
        "version": d["version"],
        "name": d["name"],
        "origin": d["origin"],
        "breed": d["breed"],
        "sex": d["sex"],
        "born_on": d["born_on"],
        "region": d["region"],
        "sire_id": d["sire_id"],
        "dam_id": d["dam_id"],
        "donor_name": d["donor_name"],
        "status": d["status"],
        "clearance_score": d["clearance_score"],
        "primary_trainer_id": d["primary_trainer_id"],
        "certified_tasks": sorted(d["certified_tasks"]),
        "career_change_reason": d["career_change_reason"],
    }


def ser_screening(s):
    return {
        "id": s["id"],
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
        "dog_id": s["dog_id"],
        "hip_grade": s["hip_grade"],
        "elbow_grade": s["elbow_grade"],
        "eye_result": s["eye_result"],
        "cardiac_result": s["cardiac_result"],
        "genetic_panel": s["genetic_panel"],
        "clearance_score": s["clearance_score"],
        "status": s["status"],
        "veterinarian_user_id": s["veterinarian_user_id"],
    }


def ser_placement(p):
    return {
        "id": p["id"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
        "dog_id": p["dog_id"],
        "puppy_raiser_id": p["puppy_raiser_id"],
        "started_on": fmt_date(p["started_on"]),
        "ended_on": fmt_date(p["ended_on"]),
        "status": p["status"],
    }


def ser_milestone(m):
    return {
        "id": m["id"],
        "created_at": fmt_ts(m["created_at"]),
        "dog_id": m["dog_id"],
        "category": m["category"],
        "task_code": m["task_code"],
        "score": m["score"],
        "recorded_at": fmt_ts(m["recorded_at"]),
        "recorded_by_trainer_id": m["recorded_by_trainer_id"],
        "rolling_avg_3": m["rolling_avg_3"],
        "cumulative_gate_score": m["cumulative_gate_score"],
        "career_change_recommended": m["career_change_recommended"],
    }


def ser_match(m):
    return {
        "id": m["id"],
        "created_at": fmt_ts(m["created_at"]),
        "updated_at": fmt_ts(m["updated_at"]),
        "version": m["version"],
        "dog_id": m["dog_id"],
        "waitlist_entry_id": m["waitlist_entry_id"],
        "status": m["status"],
        "proposed_by_user_id": m["proposed_by_user_id"],
        "rank_score_at_match": m["rank_score_at_match"],
    }


def ser_class(c):
    return {
        "id": c["id"],
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
        "name": c["name"],
        "lead_trainer_id": c["lead_trainer_id"],
        "starts_on": fmt_date(c["starts_on"]),
        "ends_on": fmt_date(c["ends_on"]),
        "capacity": c["capacity"],
        "total_sessions": c["total_sessions"],
        "status": c["status"],
        "enrolled_count": c["enrolled_count"],
    }


def ser_enrollment(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
        "class_id": e["class_id"],
        "match_id": e["match_id"],
        "status": e["status"],
        "sessions_attended": e["sessions_attended"],
        "attendance_pct": e["attendance_pct"],
    }


def ser_pat(p):
    return {
        "id": p["id"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
        "enrollment_id": p["enrollment_id"],
        "evaluator_id": p["evaluator_id"],
        "scheduled_at": fmt_ts(p["scheduled_at"]),
        "location": p["location"],
        "attempt_number": p["attempt_number"],
        "status": p["status"],
        "exercise_scores": p["exercise_scores"],
        "section_percents": p["section_percents"],
        "official_score": p["official_score"],
        "passed_gates": p["passed_gates"],
    }


def ser_partnership(p):
    return {
        "id": p["id"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
        "applicant_id": p["applicant_id"],
        "dog_id": p["dog_id"],
        "enrollment_id": p["enrollment_id"],
        "status": p["status"],
        "activated_at": fmt_ts(p["activated_at"]),
        "recert_due_at": fmt_ts(p["recert_due_at"]),
        "followups_completed": p["followups_completed"],
        "last_recert_passed_at": fmt_ts(p["last_recert_passed_at"]),
    }


def ser_followup(f):
    return {
        "id": f["id"],
        "created_at": fmt_ts(f["created_at"]),
        "updated_at": fmt_ts(f["updated_at"]),
        "version": f["version"],
        "partnership_id": f["partnership_id"],
        "due_on": fmt_date(f["due_on"]),
        "auto_generated": f["auto_generated"],
        "status": f["status"],
        "outcome": f["outcome"],
        "completed_on": fmt_date(f["completed_on"]),
    }


def ser_recert(r):
    return {
        "id": r["id"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
        "partnership_id": r["partnership_id"],
        "scheduled_on": fmt_date(r["scheduled_on"]),
        "evaluator_id": r["evaluator_id"],
        "status": r["status"],
        "completed_on": fmt_date(r["completed_on"]),
    }


def ser_support(s):
    return {
        "id": s["id"],
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
        "partnership_id": s["partnership_id"],
        "raised_by_applicant_id": s["raised_by_applicant_id"],
        "category": s["category"],
        "description": s["description"],
        "severity": s["severity"],
        "priority": s["priority"],
        "status": s["status"],
        "assigned_trainer_id": s["assigned_trainer_id"],
        "resolved_at": fmt_ts(s["resolved_at"]),
    }


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def applicant_of_entry(entry):
    return STORE["applicants"].get(entry["applicant_id"])


def entry_of_applicant(applicant_id):
    """The applicant's active waitlist entry (any non-CLOSED status), newest first."""
    entries = [
        e
        for e in STORE["waitlist_entries"].values()
        if e["applicant_id"] == applicant_id
    ]
    if not entries:
        return None
    entries.sort(key=lambda e: e["_seq"], reverse=True)
    return entries[0]


def latest_accepted_assessment(applicant_id):
    finals = [
        t
        for t in STORE["assessments"].values()
        if t["applicant_id"] == applicant_id and t["status"] == "FINALIZED_ACCEPTED"
    ]
    if not finals:
        return None
    finals.sort(key=lambda t: t["_seq"], reverse=True)
    return finals[0]


def dog_milestones(dog_id):
    """Chronological: recorded_at ASC, ties by creation seq."""
    ms = [m for m in STORE["milestones"].values() if m["dog_id"] == dog_id]
    ms.sort(key=lambda m: (m["recorded_at"], m["_seq"]))
    return ms


def enrollment_for_match(match_id, statuses=None):
    out = [
        e for e in STORE["enrollments"].values() if e["match_id"] == match_id
    ]
    if statuses is not None:
        out = [e for e in out if e["status"] in statuses]
    out.sort(key=lambda e: e["_seq"])
    return out


# ---------------------------------------------------------------------------
# Calculation: fundraising requirement (dual variant)
# ---------------------------------------------------------------------------


def _credit_pct(income_cents):
    if income_cents < 3000000:
        return Decimal("0.60")
    if income_cents < 6000000:
        return Decimal("0.40")
    if income_cents < 10000000:
        return Decimal("0.20")
    return Decimal("0.00")


def fundraising_provisional(track, household_income_cents):
    gross = BASE_REQUIREMENT_CENTS[track]
    credit = round_half_up_int(Decimal(gross) * _credit_pct(household_income_cents))
    # subsidy tier keyed on GROSS; subsidy base is gross
    tier = Decimal("0.10") if gross >= 1000000 else Decimal("0.15")
    subsidy = round_half_up_int(Decimal(gross) * tier)
    return gross - credit - subsidy


def fundraising_final(track, verified_income_cents):
    gross = BASE_REQUIREMENT_CENTS[track]
    credit = round_half_up_int(Decimal(gross) * _credit_pct(verified_income_cents))
    provisional_net = gross - credit
    # subsidy tier keyed on provisional_net; subsidy base is provisional_net
    tier = Decimal("0.10") if provisional_net >= 1000000 else Decimal("0.15")
    subsidy = round_half_up_int(Decimal(provisional_net) * tier)
    return provisional_net - subsidy


# ---------------------------------------------------------------------------
# Calculation: waitlist rank score
# ---------------------------------------------------------------------------


def compute_rank_score(entry):
    assessment = latest_accepted_assessment(entry["applicant_id"])
    delta_seconds = (now() - entry["listed_at"]).total_seconds()
    wait_days = int(delta_seconds // 86400)
    wait_component = min(Decimal(40), Decimal(wait_days) * Decimal("0.5"))
    urgency_component = (
        URGENCY_PTS[assessment["task_urgency_tier"]] if assessment else 0
    )
    home_component = (
        min(20, assessment["home_environment_score"] * 2) if assessment else 0
    )
    bonus = 15 if entry["status"] == "ELIGIBLE" else 0
    penalty = 10 * entry["dissolved_match_count"]
    total = (
        wait_component
        + Decimal(urgency_component)
        + Decimal(home_component)
        + Decimal(bonus)
        - Decimal(penalty)
    )
    return round_half_up_1dp(total)


# ---------------------------------------------------------------------------
# Waitlist eligibility flips (+ applicant mirror)
# ---------------------------------------------------------------------------


def settle_entry(entry, mutated=False):
    """Re-evaluate PENDING<->ELIGIBLE flips, recompute rank, mirror applicant.

    `mutated` marks that the caller already changed entry fields this op
    (e.g. raised_cents), so the entry must be touched even without a flip.
    """
    req = effective_requirement(entry)
    flipped = False
    if entry["status"] == "PENDING" and entry["raised_cents"] >= req:
        entry["status"] = "ELIGIBLE"
        flipped = True
    elif entry["status"] == "ELIGIBLE" and entry["raised_cents"] < req:
        entry["status"] = "PENDING"
        flipped = True
    new_rank = compute_rank_score(entry)
    rank_changed = new_rank != entry["rank_score"]
    if rank_changed:
        entry["rank_score"] = new_rank
    if flipped or rank_changed or mutated:
        touch(entry)
    applicant = applicant_of_entry(entry)
    if applicant is not None:
        if (
            entry["status"] == "ELIGIBLE"
            and applicant["application_status"] == "WAITLISTED"
        ):
            applicant["application_status"] = "MATCH_ELIGIBLE"
            touch(applicant)
        elif (
            entry["status"] == "PENDING"
            and applicant["application_status"] == "MATCH_ELIGIBLE"
        ):
            applicant["application_status"] = "WAITLISTED"
            touch(applicant)


# ---------------------------------------------------------------------------
# Health clearance score
# ---------------------------------------------------------------------------


def screening_score_and_outcome(scr, dog_origin):
    pts = {
        "hip": HIP_PTS[scr["hip_grade"]],
        "elbow": ELBOW_PTS[scr["elbow_grade"]],
        "eye": EYE_PTS[scr["eye_result"]],
        "cardiac": CARDIAC_PTS[scr["cardiac_result"]],
        "genetic": GENETIC_PTS[scr["genetic_panel"]],
    }
    score = sum(pts.values())
    hard_fail = any(v == 0 for v in pts.values())
    if dog_origin == "DONATED":
        passed = (score >= DONATED_THRESHOLD) and not hard_fail
    else:  # BRED
        passed = (
            score >= BRED_THRESHOLD
            and scr["genetic_panel"] == "CLEAR"
            and not hard_fail
        )
    return score, passed


# ---------------------------------------------------------------------------
# Training milestone calculations + advancement
# ---------------------------------------------------------------------------


def milestone_figures(dog_id):
    """Compute rolling_avg_3 and cumulative_gate_score over the dog's milestones."""
    ms = dog_milestones(dog_id)
    scores = [m["score"] for m in ms]
    latest3 = scores[-3:]
    rolling = round_half_up_1dp(
        Decimal(sum(latest3)) / Decimal(len(latest3))
    )
    tw = [m["score"] for m in ms if m["category"] == "TASK_WORK"]
    pm = [m["score"] for m in ms if m["category"] == "PUBLIC_MANNERS"]
    ob_soc = [
        m["score"] for m in ms if m["category"] in ("OBEDIENCE", "SOCIALIZATION")
    ]
    numerator = Decimal(0)
    denom = Decimal(0)
    if tw:
        numerator += Decimal("0.5") * (Decimal(sum(tw)) / Decimal(len(tw)))
        denom += Decimal("0.5")
    if pm:
        numerator += Decimal("0.3") * (Decimal(sum(pm)) / Decimal(len(pm)))
        denom += Decimal("0.3")
    if ob_soc:
        numerator += Decimal("0.2") * (
            Decimal(sum(ob_soc)) / Decimal(len(ob_soc))
        )
        denom += Decimal("0.2")
    cumulative = (
        round_half_up_1dp(numerator / denom) if denom > 0 else 0.0
    )
    career_recommended = len(scores) >= 2 and scores[-1] < 50 and scores[-2] < 50
    return rolling, cumulative, career_recommended


def recompute_certified_tasks(dog):
    ms = dog_milestones(dog["id"])
    dog["certified_tasks"] = {
        m["task_code"]
        for m in ms
        if m["category"] == "TASK_WORK"
        and m["task_code"] is not None
        and m["score"] >= 80
    }


def check_advancement(dog):
    """IN_ADVANCED_TRAINING -> MATCH_READY when all five gates hold."""
    if dog["status"] != "IN_ADVANCED_TRAINING":
        return
    ms = dog_milestones(dog["id"])
    if len(ms) < 6:
        return
    rolling, cumulative, _ = milestone_figures(dog["id"])
    latest3 = [m["score"] for m in ms[-3:]]
    low_total = sum(1 for m in ms if m["score"] < 50)
    if (
        cumulative >= 80.0
        and rolling >= 70.0
        and all(s >= 40 for s in latest3)
        and low_total <= 1
    ):
        dog["status"] = "MATCH_READY"
        touch(dog)


# ---------------------------------------------------------------------------
# Match dissolve (shared by direct dissolve + cascades)
# ---------------------------------------------------------------------------


def dissolve_match(match, applicant_withdrawn=False, skip_dog_revert=False):
    """ACCEPTED -> DISSOLVED with revert side effects."""
    if match["status"] != "ACCEPTED":
        return
    match["status"] = "DISSOLVED"
    touch(match)
    dog = STORE["dogs"].get(match["dog_id"])
    if not skip_dog_revert and dog is not None:
        if dog["status"] in ("MATCHED", "TEAM_TRAINING"):
            dog["status"] = "MATCH_READY"
            touch(dog)
    entry = STORE["waitlist_entries"].get(match["waitlist_entry_id"])
    applicant = (
        applicant_of_entry(entry) if entry is not None else None
    )
    withdrawn = applicant_withdrawn or (
        applicant is not None
        and applicant["application_status"] == "WITHDRAWN"
    )
    if entry is not None:
        if withdrawn:
            if entry["status"] in ("PENDING", "ELIGIBLE", "MATCHED", "SUSPENDED"):
                entry["status"] = "CLOSED"
                touch(entry)
        else:
            if entry["status"] == "MATCHED":
                entry["status"] = "ELIGIBLE"
                entry["dissolved_match_count"] += 1
                new_rank = compute_rank_score(entry)
                entry["rank_score"] = new_rank
                touch(entry)
    if not withdrawn and applicant is not None:
        if applicant["application_status"] in ("MATCHED", "TEAM_TRAINING"):
            applicant["application_status"] = "MATCH_ELIGIBLE"
            touch(applicant)


# ---------------------------------------------------------------------------
# Enrollment withdrawal (direct / class-cancel / applicant-withdraw / career-change)
# ---------------------------------------------------------------------------


def withdraw_enrollment(enrollment, mode):
    """ENROLLED -> WITHDRAWN. mode in direct|class_cancel|applicant_withdraw|career_change."""
    if enrollment["status"] != "ENROLLED":
        return
    enrollment["status"] = "WITHDRAWN"
    touch(enrollment)
    cls = STORE["classes"].get(enrollment["class_id"])
    if cls is not None and cls["enrolled_count"] > 0:
        cls["enrolled_count"] -= 1
        touch(cls)
    match = STORE["matches"].get(enrollment["match_id"])
    if match is None:
        return
    if mode == "class_cancel":
        # match retained; dog and applicant revert TEAM_TRAINING -> MATCHED
        dog = STORE["dogs"].get(match["dog_id"])
        if dog is not None and dog["status"] == "TEAM_TRAINING":
            dog["status"] = "MATCHED"
            touch(dog)
        entry = STORE["waitlist_entries"].get(match["waitlist_entry_id"])
        applicant = applicant_of_entry(entry) if entry else None
        if applicant is not None and applicant["application_status"] == "TEAM_TRAINING":
            applicant["application_status"] = "MATCHED"
            touch(applicant)
    elif mode == "career_change":
        dissolve_match(
            match, applicant_withdrawn=False, skip_dog_revert=True
        )
    elif mode == "applicant_withdraw":
        dissolve_match(
            match, applicant_withdrawn=True, skip_dog_revert=False
        )
    else:  # direct
        dissolve_match(
            match, applicant_withdrawn=False, skip_dog_revert=False
        )


# ---------------------------------------------------------------------------
# Applicant withdraw cascade
# ---------------------------------------------------------------------------


def withdraw_applicant(applicant):
    """Fire the full compensation cascade; applicant lands in WITHDRAWN."""
    applicant["application_status"] = "WITHDRAWN"
    touch(applicant)

    # 1. Waitlist entry -> CLOSED (if active)
    entry = entry_of_applicant(applicant["id"])
    if entry is not None and entry["status"] in (
        "PENDING",
        "ELIGIBLE",
        "MATCHED",
        "SUSPENDED",
    ):
        entry["status"] = "CLOSED"
        touch(entry)

    # 2. Contributions: PLEDGED -> VOID first, then RECEIVED -> REFUNDED
    #    in created_at ASC order; raised_cents settles to exactly 0.
    contribs = [
        c
        for c in STORE["contributions"].values()
        if c["applicant_id"] == applicant["id"]
    ]
    contribs.sort(key=lambda c: c["_seq"])
    for c in contribs:
        if c["status"] == "PLEDGED":
            c["status"] = "VOID"
            touch(c)
    for c in contribs:
        if c["status"] == "RECEIVED":
            c["status"] = "REFUNDED"
            touch(c)
            if entry is not None:
                entry["raised_cents"] -= c["amount_cents"]
    if entry is not None and entry["raised_cents"] != 0:
        entry["raised_cents"] = 0
    if entry is not None:
        touch(entry)

    # 3 & 4. Enrollment withdrawal (TEAM_TRAINING) or bare match dissolve (MATCHED)
    matches = [
        m
        for m in STORE["matches"].values()
        if entry is not None and m["waitlist_entry_id"] == entry["id"]
    ]
    for m in matches:
        if m["status"] != "ACCEPTED":
            continue
        active_enrs = enrollment_for_match(m["id"], statuses={"ENROLLED"})
        if active_enrs:
            for enr in active_enrs:
                withdraw_enrollment(enr, mode="applicant_withdraw")
        else:
            dissolve_match(m, applicant_withdrawn=True, skip_dog_revert=False)


# ---------------------------------------------------------------------------
# Dog career-change cascade
# ---------------------------------------------------------------------------


def career_change_dog(dog, reason_category):
    """Career-change cascade; dog lands in CAREER_CHANGED."""
    # link 1: ACTIVE raiser placement -> EARLY_RETURN
    placements = [
        p
        for p in STORE["placements"].values()
        if p["dog_id"] == dog["id"] and p["status"] == "ACTIVE"
    ]
    for p in placements:
        end_placement_effects(p, outcome="EARLY_RETURN")

    # link 2 (MATCHED / TEAM_TRAINING): enrollment withdraw + match dissolve
    dog_matches = [
        m for m in STORE["matches"].values() if m["dog_id"] == dog["id"]
    ]
    for m in dog_matches:
        if m["status"] != "ACCEPTED":
            continue
        active_enrs = enrollment_for_match(m["id"], statuses={"ENROLLED"})
        if active_enrs:
            for enr in active_enrs:
                withdraw_enrollment(enr, mode="career_change")
        else:
            dissolve_match(m, applicant_withdrawn=False, skip_dog_revert=True)

    dog["status"] = "CAREER_CHANGED"
    dog["career_change_reason"] = reason_category
    touch(dog)


# ---------------------------------------------------------------------------
# Raiser placement helpers
# ---------------------------------------------------------------------------


def end_placement_effects(placement, outcome):
    """Shared effects for COMPLETED / EARLY_RETURN (minus dog advancement)."""
    placement["status"] = outcome
    placement["ended_on"] = today()
    touch(placement)
    raiser = STORE["puppy_raisers"].get(placement["puppy_raiser_id"])
    if raiser is not None:
        if raiser["current_dog_count"] > 0:
            raiser["current_dog_count"] -= 1
        raiser["last_placement_ended_at"] = now()
        if raiser["status"] == "ACTIVE" and raiser["current_dog_count"] == 0:
            raiser["status"] = "APPROVED"
        touch(raiser)


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------


def run_sweep():
    """FollowUp -> MISSED; Partnership ACTIVE -> RECERT_DUE; rank recompute.

    Entities processed ordered by due_on / recert_due_at ASC, ties created_at ASC.
    Returns (swept_followups_missed, swept_partnerships_recert_due).
    """
    current = now()
    current_date = current.date()

    followups = [
        f
        for f in STORE["followups"].values()
        if f["status"] == "SCHEDULED"
        and current_date > (f["due_on"] + timedelta(days=7))
    ]
    followups.sort(key=lambda f: (f["due_on"], f["_seq"]))
    missed = 0
    for f in followups:
        f["status"] = "MISSED"
        touch(f)
        missed += 1

    partnerships = [
        p
        for p in STORE["partnerships"].values()
        if p["status"] == "ACTIVE" and current > p["recert_due_at"]
    ]
    partnerships.sort(key=lambda p: (p["recert_due_at"], p["_seq"]))
    due = 0
    for p in partnerships:
        # no COMPLETED_PASS recertification covering the current recert window:
        # a pass at completed_on sets recert_due_at = completed_on + 365d, so a
        # pass "covers" the current window iff completed_on + 365d > recert_due_at.
        covering_pass = any(
            r["partnership_id"] == p["id"]
            and r["status"] == "COMPLETED_PASS"
            and r["completed_on"] is not None
            and (r["completed_on"] + timedelta(days=365)) > p["recert_due_at"].date()
            for r in STORE["recerts"].values()
        )
        if not covering_pass:
            p["status"] = "RECERT_DUE"
            touch(p)
            due += 1

    # rank recompute as wait days accumulate (non-terminal entries)
    for entry in STORE["waitlist_entries"].values():
        if entry["status"] == "CLOSED":
            continue
        new_rank = compute_rank_score(entry)
        if new_rank != entry["rank_score"]:
            entry["rank_score"] = new_rank
            touch(entry)

    return missed, due
