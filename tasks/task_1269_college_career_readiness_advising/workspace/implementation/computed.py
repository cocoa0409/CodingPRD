"""Derived-field calculations (SCAFFOLD §1.3) and entity serializers.

All advisor/teacher/site counters and plan derived fields are computed live at
read time; audit computed fields are live while the audit is not CERTIFIED and
frozen (stored) while CERTIFIED (PRD §3.7). Pure recomputation never bumps any
entity version (PRD §2.4).
"""

from decimal import Decimal

from store import stores, fmt_ts
from util import d, round_half_up, num2, D2, D4

GROUPS = ("GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D")

PROVISIONAL_SET = {"PLANNED", "ENROLLED", "COMPLETED"}
OFFICIAL_SET = {"COMPLETED"}

GRADUATION_CREDITS_REQUIRED = 24


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def students_of_advisor(advisor_id, enrolled_only=False):
    out = [s for s in stores["students"].values() if s["assigned_advisor_id"] == advisor_id]
    if enrolled_only:
        out = [s for s in out if s["status"] == "ENROLLED"]
    return out


def active_caseload_count(advisor_id):
    return len(students_of_advisor(advisor_id, enrolled_only=True))


def teacher_open_request_count(teacher_id):
    return sum(1 for r in stores["rec_requests"].values()
               if r["teacher_id"] == teacher_id and r["status"] in ("REQUESTED", "ACCEPTED"))


def site_confirmed_active_count(site_id):
    return sum(1 for p in stores["placements"].values()
               if p["site_id"] == site_id and p["status"] in ("CONFIRMED", "ACTIVE"))


def student_active_plan(student_id):
    for p in stores["plans"].values():
        if p["student_id"] == student_id and p["status"] == "ACTIVE":
            return p
    return None


# ---------------------------------------------------------------------------
# caseload_load (SIMPLE / WEIGHTED)
# ---------------------------------------------------------------------------

def caseload_load_weighted(advisor_id):
    advisees = students_of_advisor(advisor_id, enrolled_only=True)
    if not advisees:
        return 0
    total = Decimal("0")
    for s in advisees:
        if s["grade_level"] == 12:
            w = Decimal("2.0")
        elif s["grade_level"] == 11:
            w = Decimal("1.5")
        else:
            w = Decimal("1.0")
        if student_active_plan(s["id"]) is None:
            w += Decimal("0.5")
        total += w
    return num2(total)


# ---------------------------------------------------------------------------
# caseload_equity_gap_index — pinned two-step rounding (PRD §3.1)
# ---------------------------------------------------------------------------

def equity_gap_index(advisor_id):
    district = [s for s in stores["students"].values() if s["status"] == "ENROLLED"]
    advisees = students_of_advisor(advisor_id, enrolled_only=True)
    if len(district) == 0 or len(advisees) == 0:
        return 0
    gap_sum = Decimal("0")
    for g in GROUPS:
        district_share = d(sum(1 for s in district if s["demographic_group"] == g)) / d(len(district))
        advisor_share = d(sum(1 for s in advisees if s["demographic_group"] == g)) / d(len(advisees))
        gap_sum += round_half_up(abs(advisor_share - district_share), D4)
    return num2(round_half_up(gap_sum * 100, D2))


# ---------------------------------------------------------------------------
# district_target_caseload — snapshot ACTIVE pool, ratio * own max
# ---------------------------------------------------------------------------

def district_totals():
    pool = [a for a in stores["advisors"].values() if a["status"] == "ACTIVE"]
    total_students = sum(1 for s in stores["students"].values() if s["status"] == "ENROLLED")
    total_capacity = sum(a["max_caseload"] for a in pool)
    return total_students, total_capacity


def target_caseload(advisor):
    if advisor["status"] != "ACTIVE":
        return 0
    total_students, total_capacity = district_totals()
    if total_capacity == 0:
        ratio = Decimal("0")
    else:
        ratio = d(total_students) / d(total_capacity)
    return num2(round_half_up(ratio * d(advisor["max_caseload"]), D2))


# ---------------------------------------------------------------------------
# plan_alignment / milestone_completion_pct / wbl / certification_points
# ---------------------------------------------------------------------------

def _student_enrollments(student_id):
    return [e for e in stores["enrollments"].values() if e["student_id"] == student_id]


def _covered_codes(required_codes, enrollments, inclusion):
    covered = 0
    for code in required_codes:
        if any(e["course_code"] == code and e["status"] in inclusion for e in enrollments):
            covered += 1
    return covered


def alignment_pct(pathway, enrollments, inclusion):
    required = pathway["required_course_codes"]
    if not required:
        return 100
    covered = _covered_codes(required, enrollments, inclusion)
    from util import pct2
    return pct2(covered, len(required))


def milestone_pcts(student_id):
    """Returns (strict, lenient) milestone completion percentages."""
    pool = []
    for app in stores["applications"].values():
        if app["student_id"] != student_id:
            continue
        if app["submission_status"] == "WITHDRAWN":
            continue
        for m in stores["milestones"].values():
            if m["application_id"] == app["id"]:
                pool.append(m)
    completed = sum(1 for m in pool if m["status"] == "COMPLETED")
    waived = sum(1 for m in pool if m["status"] == "WAIVED")
    from util import pct2
    strict_den = len(pool) - waived
    strict = pct2(completed, strict_den) if strict_den else 100
    lenient = pct2(completed + waived, len(pool)) if pool else 100
    return strict, lenient


def wbl_hours_pct(student_id, pathway):
    required = pathway["required_work_hours"]
    if required == 0:
        return 100
    earned = sum((p["hours_logged"] for p in stores["placements"].values()
                  if p["student_id"] == student_id and p["status"] == "COMPLETED"), Decimal("0"))
    val = round_half_up((earned * 100) / d(required), D2)
    if val > 100:
        val = Decimal("100")
    return float(val)


def certification_points(student_id, pathway):
    req = pathway["required_certification_code"]
    certs = [c for c in stores["certifications"].values() if c["student_id"] == student_id]
    if req is None:
        return 100
    if any(c["cert_code"] == req and c["status"] == "PASSED" for c in certs):
        return 100
    if any(c["status"] == "PASSED" for c in certs):
        return 50
    return 0


def readiness_scores(student, align_prov, align_off, milestone_pct, wbl_pct, cert_points):
    if student["grade_level"] == 12:
        w_align, w_mile, w_wbl, w_cert = Decimal("0.30"), Decimal("0.40"), Decimal("0.20"), Decimal("0.10")
    else:
        w_align, w_mile, w_wbl, w_cert = Decimal("0.50"), Decimal("0.20"), Decimal("0.20"), Decimal("0.10")
    m = d(milestone_pct)
    w_ = d(wbl_pct)
    c = d(cert_points)

    def _score(align):
        weighted = d(align) * w_align + m * w_mile + w_ * w_wbl + c * w_cert
        rounded = round_half_up(weighted, D2)
        if rounded > 100:
            rounded = Decimal("100")
        return float(rounded)

    return _score(align_prov), _score(align_off)


def plan_derived(plan):
    student = stores["students"][plan["student_id"]]
    pathway = stores["pathways"][plan["pathway_id"]]
    enrollments = _student_enrollments(plan["student_id"])
    align_prov = alignment_pct(pathway, enrollments, PROVISIONAL_SET)
    align_off = alignment_pct(pathway, enrollments, OFFICIAL_SET)
    m_strict, m_lenient = milestone_pcts(plan["student_id"])
    wbl = wbl_hours_pct(plan["student_id"], pathway)
    cert = certification_points(plan["student_id"], pathway)
    r_prov, r_off = readiness_scores(student, align_prov, align_off, m_strict, wbl, cert)
    return {
        "alignment_provisional_pct": align_prov,
        "alignment_official_pct": align_off,
        "milestone_pct": m_strict,
        "milestone_pct_lenient": m_lenient,
        "wbl_hours_pct": wbl,
        "certification_points": cert,
        "readiness_provisional": r_prov,
        "readiness_official": r_off,
    }


# ---------------------------------------------------------------------------
# audit computed fields (audit_credits + requirement flags)
# ---------------------------------------------------------------------------

def audit_live_values(audit):
    student_id = audit["student_id"]
    enrollments = _student_enrollments(student_id)
    credits = sum((d(e["credits"]) for e in enrollments if e["status"] == "COMPLETED"), Decimal("0"))
    plan = student_active_plan(student_id)
    if plan is not None:
        pathway = stores["pathways"][plan["pathway_id"]]
        required = pathway["required_course_codes"]
        pathway_met = all(
            any(e["course_code"] == code and e["status"] == "COMPLETED" for e in enrollments)
            for code in required
        )
        req_cert = pathway["required_certification_code"]
        if req_cert is None:
            cert_met = True
        else:
            cert_met = any(c["student_id"] == student_id and c["cert_code"] == req_cert
                           and c["status"] == "PASSED"
                           for c in stores["certifications"].values())
        earned_hours = sum((p["hours_logged"] for p in stores["placements"].values()
                            if p["student_id"] == student_id and p["status"] == "COMPLETED"),
                           Decimal("0"))
        work_met = earned_hours >= d(pathway["required_work_hours"])
    else:
        pathway_met = True
        cert_met = True
        work_met = True
    return {
        "credits_earned": float(credits),
        "pathway_requirements_met": pathway_met,
        "certification_requirement_met": cert_met,
        "work_hours_met": work_met,
    }


# ---------------------------------------------------------------------------
# site_overlap_max (interval_merge; half-open intervals)
# ---------------------------------------------------------------------------

def site_overlap_max(site_id, candidate_start=None, candidate_end=None, exclude_id=None):
    """Max concurrent CONFIRMED/ACTIVE overlap at the site. When a candidate
    interval is given, evaluation points are the candidate start plus existing
    term_starts inside the candidate window (SCAFFOLD calculations.site_overlap_max).
    Without a candidate, all existing term_starts are evaluation points."""
    existing = [p for p in stores["placements"].values()
                if p["site_id"] == site_id and p["status"] in ("CONFIRMED", "ACTIVE")
                and p["id"] != exclude_id]
    if candidate_start is not None:
        points = {candidate_start}
        for p in existing:
            if candidate_start <= p["term_start"] < candidate_end:
                points.add(p["term_start"])
    else:
        points = {p["term_start"] for p in existing}
    best = 0
    for t in points:
        cnt = sum(1 for p in existing if p["term_start"] <= t < p["term_end"])
        if cnt > best:
            best = cnt
    return best


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_student(s):
    out = _common(s)
    out.update({
        "student_ref": s["student_ref"],
        "full_name": s["full_name"],
        "grade_level": s["grade_level"],
        "demographic_group": s["demographic_group"],
        "first_generation": s["first_generation"],
        "status": s["status"],
        "assigned_advisor_id": s["assigned_advisor_id"],
        "graduated_at": fmt_ts(s["graduated_at"]),
    })
    return out


def ser_advisor(a):
    out = _common(a)
    cnt = active_caseload_count(a["id"])
    out.update({
        "full_name": a["full_name"],
        "email": a["email"],
        "max_caseload": a["max_caseload"],
        "status": a["status"],
        "active_caseload_count": cnt,
        "caseload_load_simple": cnt,
        "caseload_load_weighted": caseload_load_weighted(a["id"]),
        "equity_gap_index": equity_gap_index(a["id"]),
        "target_caseload": target_caseload(a),
    })
    return out


def ser_teacher(t):
    out = _common(t)
    out.update({
        "full_name": t["full_name"],
        "department": t["department"],
        "max_active_letters": t["max_active_letters"],
        "open_request_count": teacher_open_request_count(t["id"]),
        "status": t["status"],
    })
    return out


def ser_pathway(p):
    out = _common(p)
    out.update({
        "pathway_code": p["pathway_code"],
        "name": p["name"],
        "required_course_codes": list(p["required_course_codes"]),
        "required_certification_code": p["required_certification_code"],
        "required_work_hours": p["required_work_hours"],
        "status": p["status"],
    })
    return out


def ser_plan(p, include_lenient=False):
    out = _common(p)
    out.update({
        "student_id": p["student_id"],
        "pathway_id": p["pathway_id"],
        "interest_inventory": p["interest_inventory"],
        "status": p["status"],
    })
    derived = plan_derived(p)
    if not include_lenient:
        derived.pop("milestone_pct_lenient", None)
    out.update(derived)
    return out


def ser_enrollment(e):
    out = _common(e)
    plan = stores["plans"].get(e["plan_id"])
    counts = False
    if plan is not None:
        pathway = stores["pathways"].get(plan["pathway_id"])
        if pathway is not None:
            counts = e["course_code"] in pathway["required_course_codes"]
    out.update({
        "student_id": e["student_id"],
        "plan_id": e["plan_id"],
        "course_code": e["course_code"],
        "term": e["term"],
        "credits": e["credits"],
        "grade": e["grade"],
        "status": e["status"],
        "counts_toward_pathway": counts,
    })
    return out


def ser_application(a):
    out = _common(a)
    out.update({
        "student_id": a["student_id"],
        "college_name": a["college_name"],
        "program_type": a["program_type"],
        "deadline_at": fmt_ts(a["deadline_at"]),
        "submission_status": a["submission_status"],
        "decision_status": a["decision_status"],
        "submitted_at": fmt_ts(a["submitted_at"]),
        "decided_at": fmt_ts(a["decided_at"]),
    })
    return out


def ser_milestone(m):
    out = _common(m)
    out.update({
        "application_id": m["application_id"],
        "kind": m["kind"],
        "required": m["required"],
        "due_at": fmt_ts(m["due_at"]),
        "depends_on_milestone_id": m["depends_on_milestone_id"],
        "status": m["status"],
        "completed_at": fmt_ts(m["completed_at"]),
        "last_reminder_sent_at": fmt_ts(m["last_reminder_sent_at"]),
    })
    return out


def ser_rec_request(r):
    out = _common(r)
    out.update({
        "student_id": r["student_id"],
        "teacher_id": r["teacher_id"],
        "application_id": r["application_id"],
        "due_at": fmt_ts(r["due_at"]),
        "status": r["status"],
        "reroute_count": r["reroute_count"],
        "submitted_at": fmt_ts(r["submitted_at"]),
        "verified_at": fmt_ts(r["verified_at"]),
    })
    return out


def ser_certification(c):
    out = _common(c)
    out.update({
        "student_id": c["student_id"],
        "cert_code": c["cert_code"],
        "status": c["status"],
        "exam_at": fmt_ts(c["exam_at"]),
        "earned_at": fmt_ts(c["earned_at"]),
        "retake_count": c["retake_count"],
    })
    return out


def ser_site(s):
    out = _common(s)
    out.update({
        "site_code": s["site_code"],
        "name": s["name"],
        "max_concurrent_placements": s["max_concurrent_placements"],
        "status": s["status"],
        "confirmed_active_count": site_confirmed_active_count(s["id"]),
    })
    return out


def ser_placement(p):
    out = _common(p)
    out.update({
        "student_id": p["student_id"],
        "site_id": p["site_id"],
        "term_start": fmt_ts(p["term_start"]),
        "term_end": fmt_ts(p["term_end"]),
        "hours_per_week": p["hours_per_week"],
        "status": p["status"],
        "hours_logged": p["hours_logged"],
        "terminated_reason": p["terminated_reason"],
    })
    return out


def ser_audit(a):
    out = _common(a)
    if a["status"] == "CERTIFIED" and a.get("frozen") is not None:
        vals = a["frozen"]
    else:
        vals = audit_live_values(a)
    out.update({
        "student_id": a["student_id"],
        "auditor_advisor_id": a["auditor_advisor_id"],
        "status": a["status"],
        "flag_reason": a["flag_reason"],
        "required_credits": a["required_credits"],
        "credits_earned": vals["credits_earned"],
        "pathway_requirements_met": vals["pathway_requirements_met"],
        "certification_requirement_met": vals["certification_requirement_met"],
        "work_hours_met": vals["work_hours_met"],
        "certified_at": fmt_ts(a["certified_at"]),
    })
    return out


def ser_outcome(o):
    out = _common(o)
    out.update({
        "student_id": o["student_id"],
        "outcome_type": o["outcome_type"],
        "institution_name": o["institution_name"],
        "reported_at": fmt_ts(o["reported_at"]),
        "verification_status": o["verification_status"],
        "verified_at": fmt_ts(o["verified_at"]),
    })
    return out


def ser_ops_run(r):
    out = _common(r)
    out.update({
        "run_index": r["run_index"],
        "executed_at": fmt_ts(r["executed_at"]),
        "milestones_marked_missed": r["milestones_marked_missed"],
        "applications_regressed": r["applications_regressed"],
        "reminders_queued": r["reminders_queued"],
        "plans_recomputed": r["plans_recomputed"],
    })
    return out
