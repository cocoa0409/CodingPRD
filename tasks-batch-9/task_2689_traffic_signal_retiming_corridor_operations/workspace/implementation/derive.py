"""Derived (computed) surfaces.

Anything the PRD describes as a pure function of other rows is computed here on
demand rather than cached, which is what makes the conserved invariants of PRD
section 2.12 true "at every observable moment".
"""

import calc
import clock
from db import db

ELIGIBLE_POSTURES = ("READY", "RESTRICTED")

OPEN_STATUSES = ("OPEN", "TRIAGED")
LINKED_STATUSES = ("LINKED",)
TERMINAL_STATUSES = ("RESOLVED", "CLOSED_NO_ACTION")
REQUESTER_OPEN_STATUSES = ("OPEN", "TRIAGED", "LINKED")

LIVE_PROJECT_STATUSES = (
    "DATA_COLLECTION",
    "PLAN_DEVELOPMENT",
    "IMPLEMENTED",
    "FIELD_TUNING",
    "EVALUATION",
)


# ---- intersection ---------------------------------------------------------

def posture(intersection):
    return calc.operational_posture(
        intersection["comm_status"], intersection["detection_status"]
    )


def posture_of(intersection_id):
    intersection = db.intersections.get(intersection_id)
    if intersection is None:
        return None
    return posture(intersection)


def plan_age_days(intersection):
    return calc.timing_plan_age_days(intersection.get("last_retimed_at"), clock.now())


def deployed_plans_of(intersection_id):
    return [
        p
        for p in db.plans.values()
        if p["intersection_id"] == intersection_id and p["status"] == "DEPLOYED"
    ]


def deployed_coordinated_cycle_sec(intersection_id):
    plans = deployed_plans_of(intersection_id)
    if not plans:
        return None
    plans.sort(key=lambda p: (p["tod_start_min"], p["_seq"]))
    return plans[0]["cycle_length_sec"]


def configs_of(intersection_id):
    return [c for c in db.priority_configs.values() if c["intersection_id"] == intersection_id]


def priority_grants(intersection_id):
    """{config_id: granted_extension_sec} over the intersection's DEPLOYED pool."""
    budget = calc.priority_budget_sec(deployed_coordinated_cycle_sec(intersection_id))
    deployed = [c for c in configs_of(intersection_id) if c["deployment_status"] == "DEPLOYED"]
    return budget, calc.allocate_priority(budget, deployed)


def granted_extension_sec(config):
    if config["deployment_status"] != "DEPLOYED":
        return 0
    _budget, grants = priority_grants(config["intersection_id"])
    return grants.get(config["id"], 0)


def budget_fields(intersection_id):
    budget, grants = priority_grants(intersection_id)
    granted_total = sum(grants.values())
    return {
        "priority_budget_sec": budget,
        "granted_priority_extension_total_sec": granted_total,
        "unallocated_priority_budget_sec": budget - granted_total,
    }


# ---- corridor -------------------------------------------------------------

def members_of(corridor_id):
    """Membership rows in sequence_index ascending order."""
    rows = [m for m in db.corridor_members.values() if m["corridor_id"] == corridor_id]
    rows.sort(key=lambda m: (m["sequence_index"], m["_seq"]))
    return rows


def memberships_of_intersection(intersection_id):
    rows = [
        m for m in db.corridor_members.values() if m["intersection_id"] == intersection_id
    ]
    rows.sort(key=lambda m: m["_seq"])
    return rows


def member_count(corridor_id):
    return len(members_of(corridor_id))


def complaints_of_corridor(corridor_id):
    return [c for c in db.complaints.values() if c["corridor_id"] == corridor_id]


def complaint_counters(corridor_id):
    rows = complaints_of_corridor(corridor_id)
    return {
        "complaint_total_count": len(rows),
        "complaint_open_count": len([c for c in rows if c["status"] in OPEN_STATUSES]),
        "complaint_linked_count": len([c for c in rows if c["status"] in LINKED_STATUSES]),
        "complaint_terminal_count": len([c for c in rows if c["status"] in TERMINAL_STATUSES]),
    }


def complaint_count_12mo(corridor_id):
    now = clock.now()
    lower = clock.plus_days(now, -calc.COMPLAINT_WINDOW_DAYS)
    total = 0
    for row in complaints_of_corridor(corridor_id):
        if row["status"] == "CLOSED_NO_ACTION":
            continue
        received = row["received_at"]
        if received >= lower and received <= now:
            total += 1
    return total


def member_ages(corridor_id, screening):
    """Per-member timing_plan_age_days under the active variant, sequence order."""
    ages = []
    for member in members_of(corridor_id):
        intersection = db.intersections.get(member["intersection_id"])
        if intersection is None:
            continue
        if screening and posture(intersection) not in ELIGIBLE_POSTURES:
            continue
        ages.append(plan_age_days(intersection))
    return ages


def recompute_corridor_score(corridor, screening):
    """Writes avg_plan_age_days, priority_score and priority_score_variant."""
    ages = member_ages(corridor["id"], screening)
    corridor["avg_plan_age_days"] = calc.avg_plan_age_days(ages)
    corridor["priority_score"] = calc.priority_score(
        corridor["avg_plan_age_days"],
        corridor["annual_volume_change_pct"],
        corridor["complaint_count_12mo"],
        corridor["jurisdiction_class"],
    )
    corridor["priority_score_variant"] = "SCREENING" if screening else "PROGRAMMING"
    return corridor


def eligible_members(corridor_id):
    out = []
    for member in members_of(corridor_id):
        intersection = db.intersections.get(member["intersection_id"])
        if intersection is not None and posture(intersection) in ELIGIBLE_POSTURES:
            out.append(member)
    return out


def eligible_member_count(corridor_id):
    return len(eligible_members(corridor_id))


def requester_open_complaint_count(requester_id):
    return len(
        [
            c
            for c in db.complaints.values()
            if c["requester_id"] == requester_id and c["status"] in REQUESTER_OPEN_STATUSES
        ]
    )


# ---- projects / plans ----------------------------------------------------

def projects_of_corridor(corridor_id):
    rows = [p for p in db.projects.values() if p["corridor_id"] == corridor_id]
    rows.sort(key=lambda p: p["_seq"])
    return rows


def has_live_project(corridor_id):
    return any(p["status"] in LIVE_PROJECT_STATUSES for p in projects_of_corridor(corridor_id))


def plans_of_project(project_id):
    rows = [p for p in db.plans.values() if p["project_id"] == project_id]
    rows.sort(key=lambda p: p["_seq"])
    return rows


def splits_of_plan(plan_id):
    rows = [s for s in db.phase_splits.values() if s["timing_plan_id"] == plan_id]
    rows.sort(key=lambda s: (s["phase_number"], s["_seq"]))
    return rows


def checks_of_plan(plan_id):
    rows = [c for c in db.ped_checks.values() if c["timing_plan_id"] == plan_id]
    rows.sort(key=lambda c: (c["phase_number"], c["_seq"]))
    return rows


def counts_of_project(project_id):
    rows = [c for c in db.counts.values() if c["project_id"] == project_id]
    rows.sort(key=lambda c: c["_seq"])
    return rows


def runs_of_project(project_id):
    rows = [r for r in db.runs.values() if r["project_id"] == project_id]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def observations_of_project(project_id):
    rows = [o for o in db.observations.values() if o["project_id"] == project_id]
    rows.sort(key=lambda o: o["_seq"])
    return rows


def evaluations_of_project(project_id):
    rows = [e for e in db.evaluations.values() if e["project_id"] == project_id]
    rows.sort(key=lambda e: e["_seq"])
    return rows


def refresh_plan_totals(plan):
    splits = splits_of_plan(plan["id"])
    plan["drafted_split_total_sec"] = sum(s["split_sec"] for s in splits)
    plan["effective_split_total_sec"] = sum(s["effective_split_sec"] for s in splits)
    return plan


def sequence_index_of(corridor_id, intersection_id):
    for member in members_of(corridor_id):
        if member["intersection_id"] == intersection_id:
            return member["sequence_index"]
    return None
