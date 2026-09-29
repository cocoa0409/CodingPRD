"""Compensation, the safety-hold cycle and the multi-hop cascades.

Every helper here mutates rows in place and bumps the ``version`` of each row it
touches, because PRD section 2.4 makes the bump a property of the row, not of
the request (a cascaded child gets its own timestamp and version increment).
"""

import lookup
from store import ZERO2, db, now_iso, touch

OPEN_OR_DONE_FOR_EXCLUSION = ("SCHEDULED", "MASKING", "INJECTING", "PAUSED",
                              "SEALED", "VERIFIED", "RETEST_REQUIRED")
REPORTS_VOIDABLE = ("DRAFT", "ISSUED", "CORRECTION_REQUIRED")
CLAIMS_WITHDRAWABLE = ("SUBMITTED", "APPROVED", "RETURNED_FOR_CORRECTION")


# --------------------------------------------------------------------------
# the ledger compensation identity (PRD section 2.10)
# --------------------------------------------------------------------------
def compensate_ledger(system):
    """seal_status -> SEAL_PENDING, working leakage -> baseline, reduction -> 0.00.

    ``active_seal_job_id`` needs no explicit clearing: it is derived from the
    runs on the system, and every caller of this helper has just driven the run
    out of the SCHEDULED/MASKING/INJECTING/PAUSED band."""
    system["seal_status"] = "SEAL_PENDING"
    system["working_leakage_cfm25"] = system.get("baseline_leakage_cfm25")
    system["sealed_leakage_reduction_cfm"] = ZERO2


# --------------------------------------------------------------------------
# the project safety hold (PRD sections 2.12 and 3.4)
# --------------------------------------------------------------------------
def pause_injecting_jobs(project):
    """Runs that are INJECTING are driven to PAUSED; SCHEDULED and MASKING runs
    are left where they are.  This transition is not a manual or stall pause, so
    it leaves pause_count and stall_flag alone."""
    for job in lookup.seal_jobs_of_project(project["id"]):
        if job["status"] == "INJECTING":
            job["status"] = "PAUSED"
            touch(job)


def raise_safety_hold(project, reason, pause_jobs=True):
    project["status"] = "SAFETY_HOLD"
    project["safety_hold_reason"] = reason
    # Marker for "created strictly after the hold was raised".  The logical
    # clock can be frozen, so the monotone insertion counter is the only
    # well-defined ordering available.
    project["_hold_seq"] = db._seq
    touch(project)
    if pause_jobs:
        pause_injecting_jobs(project)


def clear_safety_hold(project):
    project["status"] = "ACTIVE"
    project["safety_hold_reason"] = None
    project["_hold_seq"] = None
    touch(project)


def maybe_clear_hold_after_post_pass(project):
    """Measurement-driven release: every POST-phase combustion test created
    strictly after the hold was raised must read PASS."""
    if project["status"] != "SAFETY_HOLD":
        return False
    marker = project.get("_hold_seq") or 0
    for test in lookup.combustion_tests_of_project(project["id"]):
        if test["phase"] != "POST":
            continue
        if test["_seq"] <= marker:
            continue
        if test["verdict"] != "PASS":
            return False
    clear_safety_hold(project)
    return True


def abort_runs_for_post_combustion_fail(project):
    """POST-phase FAIL: every run under the project in MASKING, INJECTING or
    PAUSED is driven to ABORTED_SAFETY and its system's ledger compensated."""
    for job in lookup.seal_jobs_of_project(project["id"]):
        if job["status"] not in ("MASKING", "INJECTING", "PAUSED"):
            continue
        job["status"] = "ABORTED_SAFETY"
        job["abort_reason"] = "combustion spillage failure"
        touch(job)
        system = db.duct_systems.get(job["duct_system_id"])
        if system is not None:
            compensate_ledger(system)
            touch(system)


# --------------------------------------------------------------------------
# the injection-pressure cutoff (PRD section 3.6) - three hops
# --------------------------------------------------------------------------
def injection_pressure_cutoff(job, system, project):
    """Hop 1 on the run, hop 2 on the duct system, hop 3 on the project.

    The run and the duct system are NOT touched here: the caller is already
    bumping both for the sample it just stored, and PRD section 2.4 allows
    exactly one increment per row per mutation."""
    job["status"] = "ABORTED_SAFETY"
    job["abort_reason"] = "injection pressure cutoff"
    compensate_ledger(system)
    if project is not None:
        raise_safety_hold(
            project,
            "injection pressure cutoff on system %s" % system["system_label"],
            pause_jobs=False,
        )


# --------------------------------------------------------------------------
# the retrofit-exclusion cascade (PRD section 3.2) - four hops
# --------------------------------------------------------------------------
def exclusion_cascade(system, exclusion_reason, abort_reason):
    """Hop 1 rewrites the duct system, hop 2 aborts its runs, hop 3 voids their
    reports, hop 4 withdraws the claims on those reports.

    The caller has already stamped whatever screening fields the entry point
    owns; this helper owns the eligibility dimension, the compensation and the
    version bump of the duct system itself."""
    # --- hop 1 ---
    system["eligibility_status"] = "EXCLUDED"
    system["exclusion_reason"] = exclusion_reason
    compensate_ledger(system)
    touch(system)

    # --- hop 2 ---
    aborted = []
    for job in lookup.seal_jobs_of_system(system["id"]):
        if job["status"] not in OPEN_OR_DONE_FOR_EXCLUSION:
            continue
        job["status"] = "ABORTED_EXCLUSION"
        job["abort_reason"] = abort_reason
        touch(job)
        aborted.append(job)

    # --- hop 3 ---
    voided = []
    for job in aborted:
        for report in lookup.reports_of_job(job["id"]):
            if report["status"] not in REPORTS_VOIDABLE:
                continue
            report["status"] = "VOIDED"
            touch(report)
            voided.append(report)

    # --- hop 4 ---
    for report in voided:
        for claim in lookup.claims_of_report(report["id"]):
            if claim["status"] not in CLAIMS_WITHDRAWABLE:
                continue
            claim["status"] = "WITHDRAWN"
            touch(claim)
            # ``committed`` and the program's committed_rebate_cents follow the
            # claim status, so the release happens by construction: the row is
            # no longer counted in the program ledger of PRD section 2.11.


# --------------------------------------------------------------------------
# the inspector-failure cascade (PRD section 3.8) - three hops
# --------------------------------------------------------------------------
def inspector_failure_cascade(report, program):
    """Hop 2 on the report and hop 3 on its run.  Hop 1 (the claim itself) and
    the program version bump are owned by the caller."""
    if report["status"] == "ISSUED":
        report["status"] = "CORRECTION_REQUIRED"
        report["correction_round"] = report["correction_round"] + 1
        touch(report)
    job = db.seal_jobs.get(report["seal_job_id"])
    if job is not None and job["status"] == "VERIFIED":
        job["status"] = "RETEST_REQUIRED"
        job["warranty_suspended"] = True
        touch(job)
    if program is not None:
        touch(program)


# --------------------------------------------------------------------------
# report issuance side effects (PRD section 3.7)
# --------------------------------------------------------------------------
def close_parent_retest(job):
    """When the verified run is itself a follow-up re-test, its parent closes."""
    parent_id = job.get("retest_of_job_id")
    if not parent_id:
        return
    parent = db.seal_jobs.get(parent_id)
    if parent is None or parent["status"] != "RETEST_REQUIRED":
        return
    parent["status"] = "RETEST_CLOSED"
    parent["warranty_suspended"] = False
    touch(parent)


def stamp_issuance(report, user_id, signature_note):
    report["status"] = "ISSUED"
    report["issued_by_user_id"] = user_id
    report["issued_at"] = now_iso()
    report["signature_note"] = signature_note
