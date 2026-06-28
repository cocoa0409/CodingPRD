"""TreatmentCase workflow logic (PRD §3.1-§3.3, §3.8, §3.10)."""
from db import db
from errors import err
from models import touch
from services.store import (steps_for_case, checkins_for_case, financing_for_case)

OPEN_LOAD_STATUSES = {"UNDER_REVIEW", "PLAN_APPROVED", "ACTIVE", "REFINEMENT"}


def clinician_open_load(clinician_id):
    """Count of non-terminal cases assigned to this clinician (PRD §3.1)."""
    return sum(
        1 for c in db.cases.values()
        if c["assigned_clinician_id"] == clinician_id
        and c["status"] in OPEN_LOAD_STATUSES
    )


def select_clinician(patient):
    """Assignment selector (PRD §3.1, SCAFFOLD clinician_assignment).

    Candidates: active clinicians licensed in the patient's state. Rank by open
    load ascending; tie-break earliest created_at. Returns the chosen clinician
    or None when no candidate exists.
    """
    state = patient["state_code"]
    candidates = [
        cl for cl in db.clinicians.values()
        if cl["active"] and state in cl["license_state_codes"]
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda cl: (clinician_open_load(cl["id"]), cl["created_at"], cl["_seq"]),
    )


def void_step(step, case):
    """Move a PLANNED/IN_PRODUCTION step to VOID and decrement planned_step_count."""
    if step["status"] in ("PLANNED", "IN_PRODUCTION"):
        step["status"] = "VOID"
        touch(step)
        if case["planned_step_count"] > 0:
            case["planned_step_count"] -= 1


def first_run_steps(case_id):
    return [s for s in steps_for_case(case_id) if s["supersedes_step_id"] is None]


def refinement_steps(case_id):
    return [s for s in steps_for_case(case_id) if s["supersedes_step_id"] is not None]
