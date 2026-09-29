"""Lookups, conserved counters and cascade helpers (PRD 2.8, 2.10)."""

import calc
from db import (add_days, apply_changes, by_created, db, new_record, set_and_touch,
                today_str, touch)
from errors import fail

OPEN_LIFECYCLE = ("PROPOSED", "ACTIVE")
OPEN_COMPLIANCE = ("PENDING_REVIEW", "CLEARED")
LIVE_SAFETY = ("APPROVED", "CONDITIONAL")
PLAN_LIVE = ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED")


# --------------------------------------------------------------------------
# path / foreign-key resolution
# --------------------------------------------------------------------------

def _find(collection, rid, error_id):
    if not isinstance(rid, str) or rid == "":
        fail(error_id, "Referenced resource does not exist.")
    rec = collection.get(rid)
    if rec is None:
        fail(error_id, "Referenced resource does not exist.")
    return rec


def get_partner(rid):
    return _find(db.employer_partners, rid, "ERR_EMPLOYER_NOT_FOUND")


def get_worksite(rid):
    return _find(db.worksites, rid, "ERR_WORKSITE_NOT_FOUND")


def get_review(rid):
    return _find(db.safety_reviews, rid, "ERR_REVIEW_NOT_FOUND")


def get_supervisor(rid):
    return _find(db.supervisors, rid, "ERR_SUPERVISOR_NOT_FOUND")


def get_agreement(rid):
    return _find(db.agreements, rid, "ERR_AGREEMENT_NOT_FOUND")


def get_student(rid):
    return _find(db.students, rid, "ERR_STUDENT_NOT_FOUND")


def get_permit(rid):
    return _find(db.work_permits, rid, "ERR_PERMIT_NOT_FOUND")


def get_placement(rid):
    return _find(db.placements, rid, "ERR_PLACEMENT_NOT_FOUND")


def get_plan(rid):
    return _find(db.training_plans, rid, "ERR_PLAN_NOT_FOUND")


def get_entry(rid):
    return _find(db.timesheet_entries, rid, "ERR_ENTRY_NOT_FOUND")


def get_cycle(rid):
    return _find(db.evaluation_cycles, rid, "ERR_CYCLE_NOT_FOUND")


def get_incident(rid):
    return _find(db.incident_reports, rid, "ERR_INCIDENT_NOT_FOUND")


def get_outcome(rid):
    return _find(db.placement_outcomes, rid, "ERR_OUTCOME_NOT_FOUND")


def partner_of_worksite(worksite):
    return db.employer_partners.get(worksite["employer_partner_id"])


def partner_of_placement(placement):
    worksite = db.worksites.get(placement["worksite_id"])
    if worksite is None:
        return None
    return partner_of_worksite(worksite)


# --------------------------------------------------------------------------
# collection views
# --------------------------------------------------------------------------

def placements_of_worksite(worksite_id):
    return by_created([p for p in db.placements.values()
                       if p["worksite_id"] == worksite_id])


def placements_of_agreement(agreement_id):
    return by_created([p for p in db.placements.values()
                       if p["agreement_id"] == agreement_id])


def placements_of_student(student_id):
    return by_created([p for p in db.placements.values()
                       if p["student_id"] == student_id])


def cycles_of(placement_id):
    cycles = [c for c in db.evaluation_cycles.values()
              if c["placement_id"] == placement_id]
    return sorted(cycles, key=lambda c: c["cycle_index"])


def plans_of(placement_id):
    return by_created([p for p in db.training_plans.values()
                       if p["placement_id"] == placement_id])


def objectives_of(plan_id):
    return by_created([o for o in db.learning_objectives.values()
                       if o["training_plan_id"] == plan_id])


def entries_of(placement_id):
    return by_created([e for e in db.timesheet_entries.values()
                       if e["placement_id"] == placement_id])


def operative_plan(placement_id):
    """The plan that has not been superseded; at most one exists."""
    live = [p for p in plans_of(placement_id) if p["status"] != "SUPERSEDED"]
    if not live:
        return None
    return live[-1]


def student_logged_entries(student_id):
    placement_ids = {p["id"] for p in db.placements.values()
                     if p["student_id"] == student_id}
    return by_created([e for e in db.timesheet_entries.values()
                       if e["placement_id"] in placement_ids
                       and e["status"] == "LOGGED"])


def matching_permits(student_id, permit_class, require_unexpired=False):
    out = []
    for permit in db.work_permits.values():
        if permit["student_id"] != student_id:
            continue
        if permit["status"] != "ISSUED":
            continue
        if permit["permit_class"] != permit_class:
            continue
        if require_unexpired:
            if permit["expires_on"] is None or permit["expires_on"] < today_str():
                continue
        out.append(permit)
    return by_created(out)


# --------------------------------------------------------------------------
# conserved counters
# --------------------------------------------------------------------------

def recompute_worksite_counters(worksite):
    committed = sum(1 for p in db.placements.values()
                    if p["worksite_id"] == worksite["id"]
                    and p["lifecycle_status"] in OPEN_LIFECYCLE)
    return set_and_touch(worksite, slots_committed=committed)


def recompute_supervisor(supervisor):
    load = sum(1 for p in db.placements.values()
               if p["supervisor_id"] == supervisor["id"]
               and p["lifecycle_status"] in OPEN_LIFECYCLE)
    return set_and_touch(supervisor, active_student_load=load)


def recompute_student(student):
    active = 0
    credits = calc.ZERO
    for placement in db.placements.values():
        if placement["student_id"] != student["id"]:
            continue
        if placement["lifecycle_status"] in OPEN_LIFECYCLE:
            active += 1
        credits += calc.dec(placement["credits_awarded"])
    hours = sum((calc.dec(e["hours_worked"])
                 for e in student_logged_entries(student["id"])), calc.ZERO)
    return set_and_touch(student,
                         active_placement_count=active,
                         ytd_wbl_hours=calc.rh(hours, 2),
                         credits_earned_wbl=calc.rh(credits, 2))


def recompute_partner_safety(partner):
    counts, score, posture = calc.employer_safety_score_posture(partner["id"])
    return set_and_touch(partner,
                         substantiated_minor_count=counts["MINOR"],
                         substantiated_moderate_count=counts["MODERATE"],
                         substantiated_critical_count=counts["CRITICAL"],
                         safety_score=score,
                         posture=posture)


def recompute_partner_liability(partner):
    total = 0
    for placement in db.placements.values():
        if placement["wage_settlement_mode"] != "FINAL":
            continue
        worksite = db.worksites.get(placement["worksite_id"])
        if worksite is None or worksite["employer_partner_id"] != partner["id"]:
            continue
        total += int(placement["settled_wage_cents"])
    return set_and_touch(partner, wage_liability_cents=total)


def recompute_plan_counts(plan):
    objectives = objectives_of(plan["id"])
    aligned = sum(1 for o in objectives
                  if o["aligned_course_code"] == plan["course_code"])
    return set_and_touch(plan,
                         objective_count=len(objectives),
                         aligned_objective_count=aligned)


def recompute_placement_hours(placement):
    hours = calc.total_logged_hours(placement["id"])
    provisional, final = calc.wage_variants(placement)
    return set_and_touch(placement,
                         total_verified_hours=hours,
                         provisional_wage_cents=provisional,
                         final_wage_cents=final)


def credit_eligible_value(placement, closed_count=None):
    if closed_count is None:
        closed_count = placement["closed_cycle_count"]
    plan = operative_plan(placement["id"])
    return bool(closed_count >= placement["required_evaluation_cycles"]
                and plan is not None and plan["status"] == "APPROVED")


def recompute_placement_cycles(placement):
    closed = sum(1 for c in db.evaluation_cycles.values()
                 if c["placement_id"] == placement["id"]
                 and c["cycle_status"] == "CLOSED")
    return set_and_touch(placement,
                         closed_cycle_count=closed,
                         credit_eligible=credit_eligible_value(placement, closed))


def release_placement_capacity(placement):
    """Restate the three conserved counters after a lifecycle exit."""
    worksite = db.worksites.get(placement["worksite_id"])
    if worksite is not None:
        recompute_worksite_counters(worksite)
    supervisor = db.supervisors.get(placement["supervisor_id"])
    if supervisor is not None:
        recompute_supervisor(supervisor)
    student = db.students.get(placement["student_id"])
    if student is not None:
        recompute_student(student)


# --------------------------------------------------------------------------
# evaluation cycles
# --------------------------------------------------------------------------

def derive_cycle_status(cycle):
    supervisor_done = cycle["supervisor_eval_status"] == "SUBMITTED"
    reflection_done = cycle["reflection_status"] == "ACCEPTED"
    if supervisor_done and reflection_done:
        return "CLOSED"
    if cycle["supervisor_eval_status"] == "PENDING" and cycle["reflection_status"] == "PENDING":
        return "OPEN"
    return "PARTIAL"


def create_cycle(placement, cycle_index, window_start):
    cycle = new_record()
    cycle.update({
        "placement_id": placement["id"],
        "cycle_index": cycle_index,
        "window_start": window_start,
        "window_end": add_days(window_start, 27),
        "supervisor_eval_status": "PENDING",
        "reflection_status": "PENDING",
        "cycle_status": "OPEN",
        "rating_technical": None,
        "rating_communication": None,
        "rating_reliability": None,
        "rating_safety": None,
        "rating_initiative": None,
        "competency_score": None,
        "reflection_text": None,
        "reflection_returned_count": 0,
        "closed_on": None,
    })
    db.evaluation_cycles[cycle["id"]] = cycle
    return cycle


def spawn_successor(placement, closing_cycle):
    if placement["closed_cycle_count"] >= placement["required_evaluation_cycles"]:
        return None
    return create_cycle(placement,
                        closing_cycle["cycle_index"] + 1,
                        add_days(closing_cycle["window_end"], 1))


def close_cycle(cycle, placement):
    """Both dimensions terminal: close, restate the ledger, spawn the successor."""
    cycle["cycle_status"] = "CLOSED"
    cycle["closed_on"] = today_str()
    recompute_placement_cycles(placement)
    spawn_successor(placement, cycle)


def suspend_cycles(placement_id):
    for cycle in cycles_of(placement_id):
        if cycle["cycle_status"] in ("OPEN", "PARTIAL"):
            set_and_touch(cycle, cycle_status="SUSPENDED")


def cancel_cycles(placement_id, statuses):
    for cycle in cycles_of(placement_id):
        if cycle["cycle_status"] in statuses:
            set_and_touch(cycle, cycle_status="CANCELLED")


def restore_cycles(placement_id):
    for cycle in cycles_of(placement_id):
        if cycle["cycle_status"] == "SUSPENDED":
            set_and_touch(cycle, cycle_status=derive_cycle_status(cycle))


# --------------------------------------------------------------------------
# compliance cascades
# --------------------------------------------------------------------------

def block_placements_of_worksite(worksite_id):
    for placement in placements_of_worksite(worksite_id):
        if placement["lifecycle_status"] not in OPEN_LIFECYCLE:
            continue
        set_and_touch(placement, compliance_status="BLOCKED")
        suspend_cycles(placement["id"])


def flag_placements_of_worksite(worksite_id):
    for placement in placements_of_worksite(worksite_id):
        if (placement["lifecycle_status"] in OPEN_LIFECYCLE
                and placement["compliance_status"] in OPEN_COMPLIANCE):
            set_and_touch(placement, compliance_status="FLAGGED")


def flag_placements_of_student(student_id):
    for placement in placements_of_student(student_id):
        if (placement["lifecycle_status"] in OPEN_LIFECYCLE
                and placement["compliance_status"] in OPEN_COMPLIANCE):
            set_and_touch(placement, compliance_status="FLAGGED")


def fail_worksite(worksite):
    changed = apply_changes(worksite, safety_status="FAILED",
                            safety_review_expires_on=None)
    if changed:
        touch(worksite)
    return changed


# --------------------------------------------------------------------------
# shared gates
# --------------------------------------------------------------------------

def worksite_clearance_current(worksite):
    return (worksite["safety_status"] in LIVE_SAFETY
            and worksite["safety_review_expires_on"] is not None
            and worksite["safety_review_expires_on"] >= today_str())


def require_worksite_clearance(worksite):
    if not worksite_clearance_current(worksite):
        fail("ERR_WORKSITE_SAFETY_NOT_CURRENT",
             "The worksite does not hold a current safety clearance.")


def require_posture(partner):
    if partner is not None and partner["posture"] == "SUSPENDED":
        fail("ERR_EMPLOYER_POSTURE_SUSPENDED",
             "The employer partner's posture is SUSPENDED.")


def require_workers_comp(partner):
    if partner is None or partner["workers_comp_expires_on"] < today_str():
        fail("ERR_WORKERS_COMP_LAPSED",
             "The employer partner's workers compensation policy has lapsed.")


def supervisor_training_current(supervisor):
    from db import days_between
    return days_between(supervisor["training_completed_on"], today_str()) <= 365


def require_supervisor_training(supervisor):
    if not supervisor_training_current(supervisor):
        fail("ERR_SUPERVISOR_TRAINING_EXPIRED",
             "The supervisor's mentor training is no longer current.")
