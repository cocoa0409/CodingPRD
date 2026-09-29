"""Calculations C1-C11 and every derived (source: computed) field."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    APPEAL_OVERRIDE_CONFIDENCE,
    CONFIDENCE_VERIFY_MIN,
    DISAGGREGATION_KEYS,
    GPA_SCALE_MAX,
    GRADE_RANK,
    IRREGULARITY_PENALTY,
    MAX_ATTEMPTS_PER_SUBJECT,
    MAX_SCALED_SCORE,
    MEASURE_PRECEDENCE,
    MIN_SUBGROUP_N,
    SCALED_SCORE_FACTOR,
    SELF_GUIDED_COMPONENT_VALUE,
    STALENESS_DIVISOR,
    STALENESS_FREE_DAYS,
    STALENESS_MAX,
    SUCCESS_GRADES,
    TERM_LENGTH_DAYS,
    THROUGHPUT_TERMS,
    VALIDITY_TIER_HIGH_MIN,
    VALIDITY_TIER_MID_MIN,
    W_SELF_GUIDED,
    W_TEST,
    W_TRANSCRIPT,
)
from db import db, order_key, sort_rows, touch

SUBJECTS_TRACKED = ("MATH", "ENGLISH", "ESL")


def rhu(value, places):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def floor_days(later, earlier):
    return int((later - earlier).total_seconds() // 86400)


# --------------------------------------------------------------------- student

def scored_attempt_counts(student_id):
    counts = dict((s, 0) for s in SUBJECTS_TRACKED)
    for attempt in db.attempts.values():
        if attempt["student_id"] == student_id and attempt["state"] == "SCORED":
            if attempt["subject_area"] in counts:
                counts[attempt["subject_area"]] += 1
    return counts


def student_computed(student):
    counts = scored_attempt_counts(student["id"])
    remaining = dict(
        (s, max(0, MAX_ATTEMPTS_PER_SUBJECT - counts[s])) for s in SUBJECTS_TRACKED
    )
    dets = [d for d in db.determinations.values() if d["student_id"] == student["id"]]
    if any(d["placement_state"] == "FINAL" for d in dets):
        status = "FINAL"
    elif any(d["placement_state"] in ("PROVISIONAL", "APPEALED") for d in dets):
        status = "PROVISIONAL"
    else:
        status = "UNPLACED"
    hold = any(d["evidence_state"] == "DISPUTED" for d in dets) or any(
        d["placement_state"] == "APPEALED" for d in dets
    )
    return {
        "attempt_counts": counts,
        "remaining_attempts": remaining,
        "placement_status": status,
        "advising_hold": bool(hold),
    }


# ---------------------------------------------------------------------- course

def course_computed(course):
    regs = [
        r for r in db.registrations.values()
        if section_course_id(r["section_id"]) == course["id"]
    ]
    enrolled = [r for r in regs if r["state"] in ("ENROLLED", "COMPLETED")]
    completed = [r for r in regs if r["state"] == "COMPLETED"]
    success = [r for r in completed if r["final_grade"] in SUCCESS_GRADES]
    rate = None
    if completed:
        rate = rhu(Decimal(len(success)) / Decimal(len(completed)), 4)
    return {
        "enrolled_count": len(enrolled),
        "success_count": len(success),
        "success_rate": rate,
    }


def section_course_id(section_id):
    section = db.sections.get(section_id)
    return section["course_id"] if section else None


# ------------------------------------------------------------ administrations

def admin_computed(admin):
    booked = [
        a for a in db.attempts.values()
        if a["administration_id"] == admin["id"]
        and a["state"] in ("BOOKED", "CHECKED_IN", "SCORED")
    ]
    duration = int((admin["ends_at"] - admin["starts_at"]).total_seconds() // 60)
    return {"duration_minutes": duration, "seats_booked": len(booked)}


# --------------------------------------------------------------- C4 / C5

def scaled_score(raw_score, irregularity_flag):
    base = rhu(Decimal(raw_score) * SCALED_SCORE_FACTOR, 0)
    penalised = int(base) - (IRREGULARITY_PENALTY if irregularity_flag else 0)
    return min(1000, max(0, penalised))


def waiting_days(ordinal):
    if ordinal == 1:
        return 14
    if ordinal == 2:
        return 30
    return 180


def attempt_pool(student_id, subject_area):
    pool = [
        a for a in db.attempts.values()
        if a["student_id"] == student_id
        and a["subject_area"] == subject_area
        and a["state"] != "VOIDED"
    ]
    return sort_rows(pool)


def renumber_attempts(student_id, subject_area):
    """C5 STEP 1-3: ordinal renumbering plus next_eligible_at recomputation."""
    pool = attempt_pool(student_id, subject_area)
    for index, attempt in enumerate(pool, start=1):
        changed = False
        if attempt["attempt_ordinal"] != index:
            attempt["attempt_ordinal"] = index
            changed = True
        if attempt["state"] == "SCORED" and attempt["scored_at"] is not None:
            expected = attempt["scored_at"] + timedelta(days=waiting_days(index))
        else:
            expected = None
        if attempt["next_eligible_at"] != expected:
            attempt["next_eligible_at"] = expected
            changed = True
        if changed:
            touch(attempt)


def booking_gate(student_id, subject_area):
    gates = [
        a["next_eligible_at"] for a in attempt_pool(student_id, subject_area)
        if a["state"] == "SCORED" and a["next_eligible_at"] is not None
    ]
    return max(gates) if gates else None


def best_scaled_score(student_id, subject_area):
    """Returns (best_scaled_score, cited_attempt) or (None, None)."""
    pool = [
        a for a in db.attempts.values()
        if a["student_id"] == student_id
        and a["subject_area"] == subject_area
        and a["state"] == "SCORED"
        and a["scaled_score"] is not None
    ]
    if not pool:
        return None, None
    pool.sort(key=lambda a: (-a["scaled_score"], order_key(a)))
    return pool[0]["scaled_score"], pool[0]


# ------------------------------------------------------------------------- C1

def select_rule(student, subject_area):
    clock = db.clock
    best, cited = best_scaled_score(student["id"], subject_area)
    candidates = []
    for rule in db.rules.values():
        if rule["status"] != "ACTIVE":
            continue
        if rule["subject_area"] != subject_area:
            continue
        if not (rule["effective_from"] <= clock):
            continue
        if rule["effective_to"] is not None and not (clock < rule["effective_to"]):
            continue
        if rule["required_el_status"] is not None and rule["required_el_status"] != student["el_status"]:
            continue
        if not _measure_satisfied(rule, student, best):
            continue
        candidates.append(rule)
    if not candidates:
        return None, None
    candidates.sort(key=lambda r: (
        -_level_rank(r["target_course_id"]),
        MEASURE_PRECEDENCE[r["measure_type"]],
        r["priority_rank"],
        order_key(r),
    ))
    winner = candidates[0]
    return winner, (cited if winner["measure_type"] == "TEST_SCORE" else None)


def _level_rank(course_id):
    course = db.courses.get(course_id)
    return course["level_rank"] if course else 0


def _measure_satisfied(rule, student, best):
    kind = rule["measure_type"]
    if kind == "TRANSCRIPT_GPA":
        if student["hs_transcript_status"] not in ("SELF_REPORTED", "VERIFIED"):
            return False
        if student["hs_gpa"] is None:
            return False
        gpa = student["hs_gpa"]
        if rule["min_hs_gpa"] is not None and not (gpa >= rule["min_hs_gpa"]):
            return False
        if rule["max_hs_gpa"] is not None and not (gpa < rule["max_hs_gpa"]):
            return False
        return True
    if kind == "TEST_SCORE":
        if best is None:
            return False
        if rule["min_score"] is not None and not (best >= rule["min_score"]):
            return False
        if rule["max_score"] is not None and not (best <= rule["max_score"]):
            return False
        return True
    if kind == "SELF_GUIDED":
        if student["self_guided_pathway"] is None:
            return False
        return rule["required_self_guided_pathway"] == student["self_guided_pathway"]
    return False


# -------------------------------------------------------------------- C2 / C3

def confidence_bundle(student, subject_area):
    best, _cited = best_scaled_score(student["id"], subject_area)

    if student["hs_transcript_status"] in ("SELF_REPORTED", "VERIFIED") and student["hs_gpa"] is not None:
        t = rhu(min(Decimal("100.00"), student["hs_gpa"] / GPA_SCALE_MAX * Decimal(100)), 2)
    else:
        t = Decimal("0.00")

    if best is not None:
        s = rhu(min(Decimal("100.00"), Decimal(best) / MAX_SCALED_SCORE * Decimal(100)), 2)
    else:
        s = Decimal("0.00")

    g = SELF_GUIDED_COMPONENT_VALUE if student["self_guided_pathway"] is not None else Decimal("0.00")

    wt = rhu(t * W_TRANSCRIPT, 2)
    ws = rhu(s * W_TEST, 2)
    wg = rhu(g * W_SELF_GUIDED, 2)
    base = rhu(wt + ws + wg, 1)

    if base >= VALIDITY_TIER_HIGH_MIN:
        validity_days = 730
    elif base >= VALIDITY_TIER_MID_MIN:
        validity_days = 365
    else:
        validity_days = 180

    determined_at = db.clock
    expires_at = determined_at + timedelta(days=validity_days)

    if student["transcript_recorded_at"] is None:
        penalty = Decimal("0.0")
    else:
        d = floor_days(expires_at, student["transcript_recorded_at"])
        raw = (Decimal(d) - Decimal(STALENESS_FREE_DAYS)) / STALENESS_DIVISOR
        penalty = rhu(min(STALENESS_MAX, max(Decimal("0.0"), raw)), 1)

    confidence = rhu(max(Decimal("0.0"), base - penalty), 1)
    verified = confidence >= CONFIDENCE_VERIFY_MIN and student["hs_transcript_status"] == "VERIFIED"

    return {
        "base_confidence_score": base,
        "staleness_penalty": penalty,
        "confidence_score": confidence,
        "validity_days": validity_days,
        "determined_at": determined_at,
        "expires_at": expires_at,
        "evidence_state": "VERIFIED" if verified else "UNVERIFIED",
    }


def appeal_override_bundle():
    determined_at = db.clock
    return {
        "base_confidence_score": APPEAL_OVERRIDE_CONFIDENCE,
        "staleness_penalty": Decimal("0.0"),
        "confidence_score": APPEAL_OVERRIDE_CONFIDENCE,
        "validity_days": 365,
        "determined_at": determined_at,
        "expires_at": determined_at + timedelta(days=365),
        "evidence_state": "VERIFIED",
    }


# ------------------------------------------------------------------------- C6

def section_counts(section):
    taken = 0
    held = 0
    waitlisted = 0
    for reg in db.registrations.values():
        if reg["section_id"] != section["id"]:
            continue
        if reg["state"] in ("ENROLLED", "COMPLETED"):
            taken += 1
        elif reg["state"] == "PENDING":
            held += 1
        elif reg["state"] == "WAITLISTED":
            waitlisted += 1
    return taken, held, waitlisted


def available_seats(section, exclude_registration_id=None):
    taken, held, _waitlisted = section_counts(section)
    if exclude_registration_id is not None:
        reg = db.registrations.get(exclude_registration_id)
        if reg is not None and reg["section_id"] == section["id"] and reg["state"] == "PENDING":
            held -= 1
    if section["pairing_state"] == "PAIRED" and section["linked_section_id"]:
        linked = db.sections.get(section["linked_section_id"])
        if linked is not None:
            l_taken, l_held, _lw = section_counts(linked)
            return max(
                0,
                min(
                    section["seat_capacity"] - taken - held,
                    linked["seat_capacity"] - l_taken - l_held,
                ),
            )
    return max(0, section["seat_capacity"] - taken)


def section_computed(section):
    taken, held, waitlisted = section_counts(section)
    return {
        "seats_taken": taken,
        "seats_held": held,
        "waitlist_count": waitlisted,
        "available_seats": available_seats(section),
    }


# ------------------------------------------------------------------------- C7

def blocking_prerequisites(course_id):
    return [
        q for q in db.requisites.values()
        if q["course_id"] == course_id
        and q["status"] == "ACTIVE"
        and q["requisite_type"] == "PREREQUISITE"
        and q["enforcement"] == "BLOCKING"
    ]


def _grade_ok(grade, min_grade):
    if grade is None or grade in ("NP", "W"):
        return False
    return GRADE_RANK.get(grade, 0) >= GRADE_RANK.get(min_grade, 0)


def prerequisite_status(student_id, course_id, override_id):
    reqs = blocking_prerequisites(course_id)
    if not reqs:
        return "SATISFIED"
    override = db.overrides.get(override_id) if override_id else None
    unmet = False
    overridden = False
    for req in reqs:
        by_grade = any(
            r["student_id"] == student_id
            and r["state"] == "COMPLETED"
            and section_course_id(r["section_id"]) == req["requisite_course_id"]
            and _grade_ok(r["final_grade"], req["min_grade"])
            for r in db.registrations.values()
        )
        if by_grade:
            continue
        by_override = (
            override is not None
            and override["student_id"] == student_id
            and override["course_id"] == course_id
            and override["requisite_id"] == req["id"]
            and override["state"] in ("ISSUED", "CONSUMED")
            and db.clock < override["expires_at"]
        )
        if by_override:
            overridden = True
        else:
            unmet = True
    if unmet:
        return "UNMET"
    if overridden:
        return "OVERRIDDEN"
    return "SATISFIED"


def recompute_registration_prerequisite(reg):
    course_id = section_course_id(reg["section_id"])
    status = prerequisite_status(reg["student_id"], course_id, reg["override_id"])
    if reg["prerequisite_status"] != status:
        reg["prerequisite_status"] = status
        touch(reg)
        return True
    return False


def creates_cycle(course_id, requisite_course_id):
    """Transitive reachability over ACTIVE PREREQUISITE edges (C7 note)."""
    if course_id == requisite_course_id:
        return True
    seen = set()
    stack = [requisite_course_id]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if node == course_id:
            return True
        for edge in db.requisites.values():
            if (
                edge["course_id"] == node
                and edge["status"] == "ACTIVE"
                and edge["requisite_type"] == "PREREQUISITE"
            ):
                stack.append(edge["requisite_course_id"])
    return False


# ------------------------------------------------------------------------- C8

def term_unit_load(registration, section):
    term = section["term_code"]
    total = Decimal("0")
    for reg in db.registrations.values():
        if reg["student_id"] != registration["student_id"]:
            continue
        if reg["id"] == registration["id"]:
            continue
        if reg["state"] not in ("ENROLLED", "WAITLISTED", "COMPLETED"):
            continue
        other = db.sections.get(reg["section_id"])
        if other is None or other["term_code"] != term:
            continue
        course = db.courses.get(other["course_id"])
        if course is not None:
            total += course["units"]
    course = db.courses.get(section["course_id"])
    if course is not None:
        total += course["units"]
    if section["pairing_state"] == "PAIRED" and section["role_in_pair"] == "PRIMARY":
        linked = db.sections.get(section["linked_section_id"])
        if linked is not None:
            linked_course = db.courses.get(linked["course_id"])
            if linked_course is not None:
                total += linked_course["units"]
    return rhu(total, 1)


# ------------------------------------------------------------------- C9 / C10

def _governing_determination_for_study(student_id, subject_area, target_course_id):
    candidates = [
        d for d in db.determinations.values()
        if d["student_id"] == student_id
        and d["subject_area"] == subject_area
        and d["placed_course_id"] == target_course_id
        and d["placement_state"] in ("PROVISIONAL", "FINAL", "SUPERSEDED", "APPEALED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: (d["determined_at"], d["created_at"], d["_seq"]))
    return candidates[-1]


def study_metrics(study):
    rule = db.rules.get(study["candidate_rule_id"])
    target = rule["target_course_id"] if rule else None
    strict = []
    inclusive = []
    for reg in db.registrations.values():
        if reg["state"] != "COMPLETED":
            continue
        if reg["graded_at"] is None:
            continue
        if not (study["window_start_at"] <= reg["graded_at"] < study["window_end_at"]):
            continue
        if section_course_id(reg["section_id"]) != target:
            continue
        det = _governing_determination_for_study(
            reg["student_id"], study["subject_area"], target
        )
        if det is None:
            continue
        inclusive.append(reg)
        if reg["final_grade"] == "W":
            continue
        if det["measure_type_used"] != "TEST_SCORE":
            continue
        strict.append(reg)

    def rate(num, den):
        if den == 0:
            return None
        return rhu(Decimal(num) / Decimal(den), 4)

    strict_success = len([r for r in strict if r["final_grade"] in SUCCESS_GRADES])
    inclusive_success = len([r for r in inclusive if r["final_grade"] in SUCCESS_GRADES])

    di_index, reference = disproportionate_impact(strict)

    return {
        "strict_cohort_size": len(strict),
        "strict_success_count": strict_success,
        "strict_success_rate": rate(strict_success, len(strict)),
        "inclusive_cohort_size": len(inclusive),
        "inclusive_success_count": inclusive_success,
        "inclusive_success_rate": rate(inclusive_success, len(inclusive)),
        "disproportionate_impact_index": di_index,
        "reference_group_key": reference,
    }


def disproportionate_impact(strict_cohort):
    counts = {}
    successes = {}
    for reg in strict_cohort:
        student = db.students.get(reg["student_id"])
        if student is None:
            continue
        key = student["race_ethnicity_code"]
        counts[key] = counts.get(key, 0) + 1
        if reg["final_grade"] in SUCCESS_GRADES:
            successes[key] = successes.get(key, 0) + 1
    rates = dict(
        (k, rhu(Decimal(successes.get(k, 0)) / Decimal(counts[k]), 4)) for k in counts
    )
    eligible = [k for k in counts if counts[k] >= MIN_SUBGROUP_N]
    if not eligible:
        return Decimal("1.0000"), None
    eligible.sort(key=lambda k: (-rates[k], -counts[k], k))
    reference = eligible[0]
    rr = rates[reference]
    if rr == 0:
        return Decimal("1.0000"), reference
    index = min(rhu(rates[k] / rr, 4) for k in eligible)
    return rhu(index, 4), reference


# ------------------------------------------------------------------------ C11

def _group_key(student, disaggregation_key):
    if disaggregation_key == "RACE_ETHNICITY":
        return student["race_ethnicity_code"]
    if disaggregation_key == "EL_STATUS":
        return student["el_status"]
    if disaggregation_key == "FIRST_GENERATION":
        return "TRUE" if student["first_generation"] else "FALSE"
    if disaggregation_key == "PELL":
        return "TRUE" if student["pell_eligible"] else "FALSE"
    return None


def equity_summary(course_id, disaggregation_key, window_start_at, window_end_at):
    throughput_deadline = window_end_at + timedelta(days=THROUGHPUT_TERMS * TERM_LENGTH_DAYS)

    buckets = {}
    for student in db.students.values():
        key = _group_key(student, disaggregation_key)
        buckets.setdefault(key, []).append(student)

    groups = []
    for key in sorted(buckets.keys()):
        placed_students = []
        for student in buckets[key]:
            placed = any(
                d["student_id"] == student["id"]
                and d["placed_course_id"] == course_id
                and window_start_at <= d["determined_at"] < window_end_at
                for d in db.determinations.values()
            )
            if placed:
                placed_students.append(student)
        through = 0
        for student in placed_students:
            ok = any(
                r["student_id"] == student["id"]
                and r["state"] == "COMPLETED"
                and section_course_id(r["section_id"]) == course_id
                and r["final_grade"] in SUCCESS_GRADES
                and r["graded_at"] is not None
                and r["graded_at"] < throughput_deadline
                for r in db.registrations.values()
            )
            if ok:
                through += 1
        placed = len(placed_students)
        rate = None if placed == 0 else rhu(Decimal(through) / Decimal(placed), 4)
        groups.append({
            "group_key": key,
            "placed": placed,
            "through": through,
            "rate": rate,
        })

    scored = [g for g in groups if g["placed"] >= 1]
    if len(scored) < 2:
        gap = None
        min_key = None
        max_key = None
    else:
        min_rate = min(g["rate"] for g in scored)
        max_rate = max(g["rate"] for g in scored)
        gap = rhu(max_rate - min_rate, 4)
        min_key = sorted([g["group_key"] for g in scored if g["rate"] == min_rate])[0]
        max_key = sorted([g["group_key"] for g in scored if g["rate"] == max_rate])[0]

    return {
        "course_id": course_id,
        "disaggregation_key": disaggregation_key,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "group_count": len(groups),
        "groups": groups,
        "throughput_gap": gap,
        "min_group_key": min_key,
        "max_group_key": max_key,
    }
