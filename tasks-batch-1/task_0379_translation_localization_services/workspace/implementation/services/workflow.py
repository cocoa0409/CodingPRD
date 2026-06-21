"""Cross-entity state propagation: cascade cancel, payout reversal (PRD §2.11, §3.11)."""
from db import db, touch
from services.helpers import append_ledger_entry
from services.lookups import assignments_of_job, jobs_of_project

ACTIVE_ASSIGNMENT_STATES = {"ACCEPTED", "IN_PROGRESS"}
NON_TERMINAL_ASSIGNMENT = {"OFFERED", "ACCEPTED", "IN_PROGRESS"}


def revert_assignment_commitment(assignment, reason):
    """Append a REVERSAL ledger entry and decrement committed_payout_cents."""
    linguist = db.linguists.get(assignment["linguist_id"])
    if linguist is None:
        return
    append_ledger_entry(linguist, assignment["id"], "REVERSAL",
                        -assignment["payout_cents"], reason)


def cancel_active_assignments_for_job(job, reason):
    """Cancel a job's active (non-terminal) assignments; revert committed payouts."""
    for a in assignments_of_job(job["id"]):
        if a["status"] in NON_TERMINAL_ASSIGNMENT:
            if a["status"] in ACTIVE_ASSIGNMENT_STATES:
                revert_assignment_commitment(a, reason)
            a["status"] = "CANCELLED"
            touch(a)


def cascade_cancel_job(job, reason):
    """Move a non-terminal job to CANCELLED with side effects per PRD §3.11."""
    if job["status"] in ("DELIVERED", "CANCELLED"):
        return
    prev = job["status"]
    if prev in ("TRANSLATING", "REVISION", "IN_QA"):
        cancel_active_assignments_for_job(job, reason)
    elif prev == "PENDING":
        pass
    # QA_PASSED jobs are non-terminal but have no active translator work to revert
    # beyond assignments still active; handle them like TRANSLATING/REVISION too.
    elif prev == "QA_PASSED":
        cancel_active_assignments_for_job(job, reason)
    job["status"] = "CANCELLED"
    touch(job)


def cascade_cancel_project_jobs(project, reason):
    for job in jobs_of_project(project["id"]):
        cascade_cancel_job(job, reason)


def maybe_bubble_project_to_delivered(project):
    """If every non-CANCELLED job is DELIVERED, advance project IN_PRODUCTION -> DELIVERED."""
    if project["status"] != "IN_PRODUCTION":
        return
    jobs = jobs_of_project(project["id"])
    relevant = [j for j in jobs if j["status"] != "CANCELLED"]
    if not relevant:
        return
    if all(j["status"] == "DELIVERED" for j in relevant):
        project["status"] = "DELIVERED"
        touch(project)
