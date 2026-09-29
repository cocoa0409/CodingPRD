"""Shared cascade helpers (PRD 2.10 chains A and B, plus the smaller ones)."""
from __future__ import annotations

from calc import (core_active_count, credential_of, hnum, module_of,
                  recompute_activation_counts, recompute_cohort_delivered_hours,
                  recompute_cohort_seats, recompute_exercise_counter,
                  recompute_program_counters, recompute_readiness,
                  recompute_session_counter, recompute_trainee_tallies,
                  add_refresher_hours)
from store import store, touch, sorted_rows
from util import D


def program_of_cohort(cohort):
    return store.programs.get(cohort["program_id"])


def cohort_of_trainee(trainee):
    return store.cohorts.get(trainee.get("cohort_id"))


def _snapshot(row, keys):
    return tuple(row.get(k) for k in keys)


def _apply(row, keys, fn):
    """Recompute derived counters and touch the row only when a value moved."""
    if row is None:
        return
    before = _snapshot(row, keys)
    fn(row)
    if _snapshot(row, keys) != before:
        touch(row)


PROGRAM_KEYS = ("equipment_committed_cents", "active_member_count",
                "pending_graduation_count")
COHORT_KEYS = ("seats_confirmed", "seats_waitlisted", "delivered_contact_hours")


def refresh_program(program):
    _apply(program, PROGRAM_KEYS, recompute_program_counters)


def refresh_cohort(cohort):
    def _fn(row):
        recompute_cohort_seats(row)
        recompute_cohort_delivered_hours(row)
    _apply(cohort, COHORT_KEYS, _fn)


def refresh_session(session):
    _apply(session, ("recorded_completion_count",), recompute_session_counter)


def refresh_activation(activation):
    _apply(activation, ("rostered_count", "accepted_count", "deployed_count",
                        "fill_status"), recompute_activation_counts)


def refresh_exercise(exercise):
    _apply(exercise, ("accepted_participant_count",), recompute_exercise_counter)


# --------------------------------------------------------------------------
def withdraw_roster_commitments(trainee, restrict_activation=True):
    """Withdraw the trainee's live call-out assignments and let each affected
    activation recompute its counts and fill_status."""
    affected = {}
    for r in sorted_rows(list(store.roster_assignments.values())):
        if r["trainee_id"] != trainee["id"]:
            continue
        if r["status"] not in ("NOTIFIED", "ACCEPTED"):
            continue
        act = store.activations.get(r["activation_id"])
        if restrict_activation:
            if act is None or act["status"] not in ("REQUESTED", "ROSTERED", "ACTIVATED"):
                continue
        r["status"] = "WITHDRAWN"
        touch(r)
        if act is not None:
            affected[act["id"]] = act
    for act in affected.values():
        refresh_activation(act)


def suspend_credential(credential, trainee, actor_is_system=True):
    """Credential ACTIVE -> SUSPENDED with its three consequences."""
    credential["status"] = "SUSPENDED"
    touch(credential)
    if trainee["currency_status"] == "CURRENT":
        trainee["currency_status"] = "LAPSED"
    touch(trainee)
    withdraw_roster_commitments(trainee, restrict_activation=True)


def revoke_credential(credential, trainee):
    credential["status"] = "REVOKED"
    touch(credential)
    trainee["currency_status"] = "REVOKED"
    touch(trainee)
    withdraw_roster_commitments(trainee, restrict_activation=False)


# --------------------------------------------------------------------------
def demote_trainee_if_short(trainee):
    """GRADUATED -> ENROLLED when passed_core_count falls below the core
    requirement (link 2 of chain A).  Returns True when the demotion fired."""
    if trainee["enrollment_status"] != "GRADUATED":
        return False
    if trainee["passed_core_count"] >= core_active_count():
        return False
    trainee["enrollment_status"] = "ENROLLED"
    touch(trainee)
    return True


def after_demotion(trainee):
    """Links 3-5 of chain A: suspend the credential, which withdraws the
    trainee's live roster commitments."""
    cred = credential_of(trainee["id"])
    if cred is not None and cred["status"] == "ACTIVE":
        suspend_credential(cred, trainee)


def revert_cohort_from_review(cohort):
    """GRADUATION_REVIEW -> IN_SESSION (the reverse edge no user requests)."""
    if cohort is None or cohort["status"] != "GRADUATION_REVIEW":
        return False
    cohort["status"] = "IN_SESSION"
    cohort["graduation_reviewer_user_id"] = None
    touch(cohort)
    program = program_of_cohort(cohort)
    refresh_program(program)
    return True


def cohort_missing_core_delivery(cohort):
    """True when some core ACTIVE module has no DELIVERED session on the cohort."""
    from calc import core_active_modules, cohort_sessions
    sessions = cohort_sessions(cohort["id"])
    for mod in core_active_modules():
        if not any(s["module_id"] == mod["id"] and s["status"] == "DELIVERED"
                   for s in sessions):
            return True
    return False


# --------------------------------------------------------------------------
def apply_pass_ledger(completion, trainee, module, touch_completion=True):
    """The full passing ledger (PRD 3.4), shared by the automatic
    RECORDED -> PASSED edge and the evaluator-signed SKILLS_PENDING -> PASSED."""
    completion["status"] = "PASSED"
    completion["credited_contact_hours"] = hnum(D(module["contact_hours"]))
    if touch_completion:
        touch(completion)
    recompute_trainee_tallies(trainee)
    recompute_readiness(trainee)
    touch(trainee)
    if module["refresher_eligible"]:
        cred = credential_of(trainee["id"])
        if cred is not None and cred["status"] in ("ACTIVE", "GRACE", "EXPIRED", "SUSPENDED"):
            add_refresher_hours(cred, D(completion["credited_contact_hours"]))
            touch(cred)


def void_completion(completion, cohort_hint=None):
    """Move one completion to VOIDED and run chain A from link 1 onward.

    Returns True when the owning trainee was demoted as a consequence.
    """
    was_passed = completion["status"] == "PASSED"
    completion["status"] = "VOIDED"
    completion["credited_contact_hours"] = 0
    touch(completion)
    session = store.class_sessions.get(completion["class_session_id"])
    refresh_session(session)
    trainee = store.trainees.get(completion["trainee_id"])
    if trainee is None:
        return False
    recompute_trainee_tallies(trainee)
    recompute_readiness(trainee)
    touch(trainee)
    demoted = False
    if was_passed:
        demoted = demote_trainee_if_short(trainee)
        if demoted:
            after_demotion(trainee)
    return demoted
