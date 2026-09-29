"""Synchronous cascade discipline (PRD 2.9).

Every function here both recomputes derived state and performs the §2.5
mutation bookkeeping (updated_at + version) on each record it touches.
"""

import db
import util
from services import derive
from services import screening


# ------------------------------------------------------------ recompute hops

def recompute_investigator(investigator):
    if investigator is None:
        return None
    derive.compute_investigator(investigator)
    db.touch(investigator)
    return investigator


def recompute_investigator_by_id(investigator_id):
    return recompute_investigator(db.investigators.get(investigator_id))


def recompute_disclosure(disclosure):
    if disclosure is None:
        return None
    derive.compute_disclosure(disclosure)
    db.touch(disclosure)
    return disclosure


def recompute_project(project):
    if project is None:
        return None
    derive.compute_project(project)
    db.touch(project)
    return project


def recompute_project_by_id(project_id):
    return recompute_project(db.projects.get(project_id))


def recompute_projects_for_investigator(investigator_id):
    """Every project on which the investigator holds an ACTIVE personnel row."""
    seen = set()
    for row in db.ordered(db.personnel.values()):
        if row["investigator_id"] != investigator_id or row["status"] != "ACTIVE":
            continue
        if row["project_id"] in seen:
            continue
        seen.add(row["project_id"])
        recompute_project_by_id(row["project_id"])


# ------------------------------------------------------------------- grants

def _suspend_grant(grant, reason):
    grant["status"] = "SUSPENDED"
    grant["status_reason"] = reason
    db.touch(grant)


def _revoke_grant(grant, reason):
    stamp_revoked = grant["status"] in ("ACTIVE", "SUSPENDED")
    grant["status"] = "REVOKED"
    grant["status_reason"] = reason
    if stamp_revoked:
        grant["revoked_at"] = db.clock_str()
    db.touch(grant)


def suspend_project_grants(project, reason="PROJECT_SUSPENDED"):
    changed = False
    for grant in derive.project_grants(project["id"]):
        if grant["status"] in ("REQUESTED", "ACTIVE"):
            _suspend_grant(grant, reason)
            changed = True
    if changed:
        recompute_project(project)
    return changed


def revoke_project_grants(project, reason):
    changed = False
    for grant in derive.project_grants(project["id"]):
        if grant["status"] in ("REQUESTED", "ACTIVE", "SUSPENDED"):
            _revoke_grant(grant, reason)
            changed = True
    if changed:
        recompute_project(project)
    return changed


def revoke_personnel_grants(project_id, investigator_id):
    changed = False
    for grant in derive.project_grants(project_id):
        if grant["investigator_id"] != investigator_id:
            continue
        if grant["status"] in ("REQUESTED", "ACTIVE", "SUSPENDED"):
            _revoke_grant(grant, "PERSONNEL_REMOVED")
            changed = True
    return changed


def suspend_investigator_grants(investigator_id):
    """Posture left CLEAR/REVIEW_REQUIRED: pull the investigator's access."""
    touched_projects = []
    for grant in db.ordered(db.grants.values()):
        if grant["investigator_id"] != investigator_id:
            continue
        if grant["status"] not in ("REQUESTED", "ACTIVE"):
            continue
        _suspend_grant(grant, "INVESTIGATOR_RESTRICTED")
        if grant["project_id"] not in touched_projects:
            touched_projects.append(grant["project_id"])
    for project_id in touched_projects:
        recompute_project_by_id(project_id)
    return touched_projects


def restore_project_grants(project):
    """Conditional restore on SUSPENDED -> CLEARED (PRD 3.6)."""
    candidates = [g for g in derive.project_grants(project["id"])
                  if g["status"] == "SUSPENDED"
                  and g["status_reason"] == "PROJECT_SUSPENDED"]
    capacity = int(project["controlled_area_capacity"])
    for grant in candidates:
        peak = derive.peak_concurrency(project["id"], grant["valid_from"],
                                       grant["valid_until"], grant["id"])
        if peak <= capacity:
            grant["status"] = "ACTIVE"
            grant["status_reason"] = "NONE"
        else:
            grant["status"] = "REVOKED"
            grant["status_reason"] = "CAPACITY_UNAVAILABLE"
            grant["revoked_at"] = db.clock_str()
        db.touch(grant)
    if candidates:
        recompute_project(project)


# ------------------------------------------------------------------ projects

def suspend_project_security(project, reason):
    """CLEARED -> SUSPENDED system cascade with its grant fan-out."""
    if project["security_status"] != "CLEARED":
        return False
    project["security_status"] = "SUSPENDED"
    project["security_status_reason"] = reason
    db.touch(project)
    suspend_project_grants(project, "PROJECT_SUSPENDED")
    recompute_project(project)
    return True


def terminate_project_subawards(project, statuses=None):
    changed = False
    for subaward in derive.project_subawards(project["id"]):
        if subaward["status"] == "TERMINATED":
            continue
        if statuses is not None and subaward["status"] not in statuses:
            continue
        if subaward["status"] == "EXECUTED":
            subaward["terminated_at"] = db.clock_str()
        else:
            subaward["terminated_at"] = db.clock_str()
        subaward["status"] = "TERMINATED"
        db.touch(subaward)
        changed = True
    if changed:
        recompute_project(project)
    return changed


# --------------------------------------------------- designation / ownership

def designation_cascade(organization):
    """Re-resolve descendants, re-screen subawards, suspend affected projects."""
    affected = [organization] + derive.controlled_descendants(organization["id"])
    for descendant in affected[1:]:
        derive.effective_designation(descendant)
        db.touch(descendant)

    affected_ids = {org["id"] for org in affected}
    for subaward in db.ordered(db.subawards.values()):
        if subaward["organization_id"] not in affected_ids:
            continue
        if subaward["status"] not in ("CLEARED", "FLAGGED"):
            continue
        variant = subaward.get("applied_screening_variant")
        if not variant:
            continue
        outcome = screening.apply_screening(subaward, variant)
        if outcome != "BLOCKED":
            continue
        subaward["status"] = "BLOCKED"
        db.touch(subaward)
        project = db.projects.get(subaward["project_id"])
        if project is None:
            continue
        recompute_project(project)
        suspend_project_security(project, "SUBAWARD_BLOCKED")


# ------------------------------------------------------- posture fan-out hop

def apply_posture_cascade(investigator):
    """Recompute posture, then pull access if it left CLEAR/REVIEW_REQUIRED."""
    recompute_investigator(investigator)
    if investigator["disclosure_posture"] in ("RESTRICTED", "SUSPENDED"):
        suspend_investigator_grants(investigator["id"])
    return investigator["disclosure_posture"]
