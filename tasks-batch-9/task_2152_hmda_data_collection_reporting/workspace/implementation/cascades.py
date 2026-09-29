"""Cascade integrity across the register (PRD 2.10).

Every write that invalidates something downstream propagates immediately,
inside the same request.  Rows mutated by a cascade have their updated_at
refreshed and their version incremented by 1, exactly as for a directly
requested mutation.
"""

import calc
import store


def exceptions_of_run(run_id):
    return [e for e in store.ordered(store.edit_exceptions.values())
            if e["edit_run_id"] == run_id]


def open_exceptions_for_application(run_id, application_id):
    return [e for e in store.edit_exceptions.values()
            if e["edit_run_id"] == run_id
            and e["application_id"] == application_id
            and e["status"] == "OPEN"]


def decertify_submission(sub, inst):
    """A submission resting on an invalidated run loses its attachment and,
    when it had one, its whole certification (PRD 3.2 hop 4 / hop 5)."""
    if sub["status"] == "CERTIFIED":
        sub["status"] = "DRAFT"
        sub["edit_run_id"] = None
        sub["certified_by_user_id"] = None
        sub["certified_at"] = None
        sub["attestation_text"] = None
        sub["final_record_count"] = None
        sub["_final_application_ids"] = []
        store.bump(sub)
        if inst is not None and inst["filing_posture"] == "LOCKED_FOR_FILING":
            inst["filing_posture"] = "OPEN"
            store.touch(inst)
    elif sub["status"] == "EDITS_ATTACHED":
        sub["status"] = "DRAFT"
        sub["edit_run_id"] = None
        store.bump(sub)


def invalidate_run(run):
    """A run whose snapshot no longer describes the register is terminal."""
    if run["status"] == "INVALIDATED":
        return
    run["status"] = "INVALIDATED"
    store.bump(run)
    inst = store.institutions.get(run["institution_id"])
    for sub in store.ordered(store.filing_submissions.values()):
        if sub["edit_run_id"] == run["id"] and sub["status"] in ("EDITS_ATTACHED", "CERTIFIED"):
            decertify_submission(sub, inst)


def stale_run_exceptions(run):
    """Completing a newer run makes every exception of an earlier run STALE."""
    for exc in exceptions_of_run(run["id"]):
        if exc["status"] == "OPEN":
            run["open_exception_count"] -= 1
        elif exc["status"] == "VERIFIED":
            run["verified_exception_count"] -= 1
        else:
            continue
        exc["status"] = "STALE"
        store.bump(exc)
        run["stale_exception_count"] += 1
    store.touch(run)


def drop_cleared_record(run, application_id):
    if application_id in run["_cleared_ids"]:
        run["_cleared_ids"].discard(application_id)
        run["cleared_record_count"] = len(run["_cleared_ids"])
        store.touch(run)


def add_cleared_record(run, application_id):
    if application_id not in run["_cleared_ids"]:
        run["_cleared_ids"].add(application_id)
        run["cleared_record_count"] = len(run["_cleared_ids"])
        store.touch(run)


def reopen_cascade(app, inst):
    """The five-hop decertification cascade of PRD 3.2."""
    # hop 1 -- the record returns to DECISIONED with its action cleared.
    app["stage"] = "DECISIONED"
    app["action_taken"] = None
    app["action_taken_date"] = None
    calc.application_completeness(app, inst)

    # hop 2 -- VERIFIED exceptions naming this record revert to OPEN.
    touched_runs = []
    for exc in store.ordered(store.edit_exceptions.values()):
        if exc["application_id"] != app["id"] or exc["status"] != "VERIFIED":
            continue
        exc["status"] = "OPEN"
        exc["verified_by_user_id"] = None
        exc["verified_at"] = None
        exc["verification_note"] = None
        store.bump(exc)
        run = store.edit_runs.get(exc["edit_run_id"])
        if run is None:
            continue
        run["verified_exception_count"] -= 1
        run["open_exception_count"] += 1
        store.touch(run)
        if run not in touched_runs:
            touched_runs.append(run)

    # A snapshot record that leaves CLEARED breaks the run that described it,
    # whether it had been cleared by verification or by drawing no exception.
    for run in store.ordered(store.edit_runs.values()):
        if run["institution_id"] != inst["id"] or run["status"] == "INVALIDATED":
            continue
        if app["id"] not in run["_snapshot_ids"]:
            continue
        drop_cleared_record(run, app["id"])
        if run not in touched_runs:
            touched_runs.append(run)

    # hop 3 -- those runs are invalidated; hop 4 and hop 5 follow from there.
    for run in touched_runs:
        invalidate_run(run)

    calc.recompute_institution_counters(inst)
