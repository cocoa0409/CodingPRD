"""Degree audit engine: requirement_group_satisfaction (waterfall) and
degree_audit_progress (totals + overall_satisfied).

Implements SCAFFOLD §1.3 rows `requirement_group_satisfaction` and
`degree_audit_progress`, and PRD §3.4.
"""

import db

from .academic import GRADE_VALUE, PASSING_GRADES


def _effective_required(group, approved_waivers):
    """required_credits reduced by APPROVED WAIVER amounts on the group,
    floored at 0."""
    waived = sum(
        w["credit_waiver_amount"]
        for w in approved_waivers
        if w["kind"] == "WAIVER" and w["requirement_group_id"] == group["id"]
    )
    return max(0, group["required_credits"] - waived)


def _approved_substitution_targets(approved_waivers):
    """Map enrollment_id -> set of group_id it is substituted into."""
    m = {}
    for w in approved_waivers:
        if w["kind"] == "SUBSTITUTION" and w["enrollment_id"]:
            m.setdefault(w["enrollment_id"], set()).add(w["requirement_group_id"])
    return m


def compute_audit(student, student_program, target_program, audit_kind):
    """Compute audit outcome fields (does not persist).

    Returns dict with:
      total_credits_applied, in_progress_credits_counted, outstanding_credits,
      gpa_at_audit, overall_satisfied, groups_result
    """
    enrolls = [e for e in db.enrollments.values() if e["student_id"] == student["id"]]
    groups = [
        g for g in db.requirement_groups.values() if g["program_id"] == target_program["id"]
    ]
    # deterministic group ordering for stable output
    groups.sort(key=lambda g: (g["created_at"], g["id"]))

    approved_waivers = [
        w
        for w in db.substitution_waivers.values()
        if w["student_program_id"] == student_program["id"] and w["status"] == "APPROVED"
    ]
    sub_map = _approved_substitution_targets(approved_waivers)

    # Per-group effective requirement
    eff_required = {g["id"]: _effective_required(g, approved_waivers) for g in groups}

    # Credits applied to each group via waterfall
    allocated = {g["id"]: 0 for g in groups}

    # Total credits applied (completed only, plus in-progress for CONDITIONAL)
    total_credits_applied = sum(
        e["credits_earned"] for e in enrolls if e["status"] == "COMPLETED"
    )
    in_progress_counted = 0
    if audit_kind == "CONDITIONAL":
        for e in enrolls:
            if e["status"] == "IN_PROGRESS":
                course = db.courses[e["course_id"]]
                in_progress_counted += course["credits"]
        total_credits_applied += in_progress_counted

    # Build waterfall input: enrollments eligible to be allocated into groups.
    # Order: created_at ASC, tie-break course_code ASC, then term ASC.
    def sort_key(e):
        course = db.courses[e["course_id"]]
        return (e["created_at"], course["course_code"], e["term"], e["id"])

    candidates = []
    for e in enrolls:
        if e["status"] == "COMPLETED" and e["grade"] in PASSING_GRADES:
            candidates.append((e, e["credits_earned"], False))
        elif audit_kind == "CONDITIONAL" and e["status"] == "IN_PROGRESS":
            course = db.courses[e["course_id"]]
            candidates.append((e, course["credits"], True))
        # W / F / non-qualifying completed never count toward groups
    candidates.sort(key=lambda t: sort_key(t[0]))

    for e, credits, is_projected in candidates:
        course = db.courses[e["course_id"]]
        # Determine groups this enrollment is eligible for
        eligible_groups = []
        for g in groups:
            if is_projected:
                # CONDITIONAL: min_grade bypassed for in-progress
                grade_ok = True
            else:
                grade_ok = GRADE_VALUE[e["grade"]] >= GRADE_VALUE[g["min_grade"]]
            if not grade_ok:
                continue
            code_ok = course["course_code"] in g["eligible_course_codes"]
            sub_ok = e["id"] in sub_map and g["id"] in sub_map[e["id"]]
            if not (code_ok or sub_ok):
                continue
            eligible_groups.append(g)
        if not eligible_groups:
            continue
        # Pick group with largest remaining deficit; tie-break group_code ASC.
        def deficit(g):
            return eff_required[g["id"]] - allocated[g["id"]]

        best = None
        best_deficit = 0
        # deterministic tie-break by group_code ascending: iterate sorted
        for g in sorted(eligible_groups, key=lambda x: x["group_code"]):
            d = deficit(g)
            if d > best_deficit:
                best_deficit = d
                best = g
        if best is None:
            # no group has remaining deficit — counts only toward total_credits_applied
            continue
        allocated[best["id"]] += credits

    groups_result = []
    all_satisfied = True
    for g in groups:
        sat = allocated[g["id"]] >= eff_required[g["id"]]
        if not sat:
            all_satisfied = False
        groups_result.append(
            {
                "requirement_group_id": g["id"],
                "group_code": g["group_code"],
                "credits_applied": allocated[g["id"]],
                "effective_required_credits": eff_required[g["id"]],
                "satisfied": sat,
            }
        )

    outstanding = max(0, target_program["min_total_credits"] - total_credits_applied)
    gpa_at_audit = student["institutional_gpa"]

    overall_satisfied = (
        all_satisfied
        and total_credits_applied >= target_program["min_total_credits"]
        and gpa_at_audit >= target_program["min_gpa"]
    )

    return {
        "total_credits_applied": total_credits_applied,
        "in_progress_credits_counted": in_progress_counted,
        "outstanding_credits": outstanding,
        "gpa_at_audit": gpa_at_audit,
        "overall_satisfied": overall_satisfied,
        "groups_result": groups_result,
    }
