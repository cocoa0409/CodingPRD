"""The scoring-run checkpoint of PRD 3.11: six sweeps inside one request."""

from db import base_record, sorted_rows, store, touch
from errors import err
from services import cascade
from services.calc import (COACHING_ESCALATION_DAYS, QUOTA_WINDOW_DAYS,
                           whole_days)

RESCORE_REPORT_STATUSES = ("VALIDATED", "SCORED", "AMENDED")
QUOTA_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
                  "RESOLVED_ACCEPTED", "RESOLVED_REJECTED")


def _previous_snapshot():
    latest = None
    for run in store.runs.values():
        moment = run["snapshot_utc"].dt
        if latest is None or moment > latest:
            latest = moment
    return latest


def create_run(note=None):
    snapshot = store.now_ts()
    previous = _previous_snapshot()
    if previous is not None and snapshot.dt < previous:
        raise err("ERR_SCORING_RUN_SNAPSHOT_REGRESSION")

    run = base_record()
    run["snapshot_utc"] = snapshot
    run["note"] = note
    run["carriers_scored"] = 0
    run["scores_updated"] = 0
    run["challenges_expired"] = 0
    run["coaching_marked_overdue"] = 0
    run["coaching_waived"] = 0
    run["status"] = "COMPLETED"
    store.runs[run["id"]] = run

    _repin_all(snapshot)
    _score_all(run, snapshot)
    _recompute_all_drivers()
    run["challenges_expired"] = _expire_info_requests(run, snapshot)
    marked, waived = _sweep_coaching(run, snapshot)
    run["coaching_marked_overdue"] = marked
    run["coaching_waived"] = waived
    _rederive_quotas(snapshot)
    return run


# ---- sweep 1: re-pin every violation on a live report ----------------------

def _repin_all(snapshot):
    for report in sorted_rows(list(store.reports.values())):
        if report["status"] not in RESCORE_REPORT_STATUSES:
            continue
        changed = False
        for violation in cascade.violations_of_report(report["id"]):
            if violation["status"] not in ("ACTIVE", "RECODED"):
                continue
            if cascade.pin_violation(violation, report, snapshot.dt):
                touch(violation)
                changed = True
        if cascade.rollup_report(report):
            changed = True
        if changed:
            report["severity_basis_utc"] = snapshot
            touch(report)


# ---- sweep 2: rewrite every score row, posture and screening risk ----------

def _score_all(run, snapshot):
    carriers = cascade.all_carriers()
    written = 0
    for carrier in carriers:
        written += _score_one(carrier, run, snapshot)
    run["carriers_scored"] = len(carriers)
    run["scores_updated"] = written


def _score_one(carrier, run, snapshot):
    before = cascade.snap(carrier, cascade.CARRIER_KEYS)
    written = cascade.recompute_basic_scores(carrier, snapshot, run_id=run["id"],
                                            create=True, strict=True)
    cascade.recompute_carrier_counters(carrier)
    cascade.recompute_posture(carrier)
    cascade.recompute_screening(carrier)
    cascade.finish(carrier, before)
    return written


def _recompute_all_drivers():
    for driver in cascade.all_drivers():
        cascade.recompute_driver(driver)


# ---- sweep 3: close out unanswered information requests -------------------

def _expire_info_requests(run, snapshot):
    expired = 0
    touched_carriers = []
    for challenge in sorted_rows(list(store.challenges.values())):
        if challenge["status"] != "INFO_REQUESTED":
            continue
        deadline = challenge.get("info_response_deadline")
        if deadline is None or not deadline.dt < snapshot.dt:
            continue
        challenge["status"] = "RESOLVED_REJECTED"
        challenge["resolution_disposition"] = "EXPIRED_NO_RESPONSE"
        challenge["resolved_at"] = snapshot
        challenge["resolved_by_user_id"] = None
        touch(challenge)
        cascade.set_under_challenge(challenge, False)
        expired += 1
        if challenge.get("carrier_id") not in touched_carriers:
            touched_carriers.append(challenge.get("carrier_id"))
    for carrier_id in touched_carriers:
        carrier = store.carriers.get(carrier_id)
        if carrier is not None:
            _score_one(carrier, run, snapshot)
    return expired


# ---- sweep 4: coaching -----------------------------------------------------

def _sweep_coaching(run, snapshot):
    marked = 0
    waived = 0
    assignments = sorted_rows(list(store.coaching.values()))
    for assignment in assignments:
        if assignment["status"] not in ("ASSIGNED", "IN_PROGRESS"):
            continue
        if assignment["due_at"].dt < snapshot.dt:
            assignment["status"] = "OVERDUE"
            assignment["overdue_marked_run_id"] = run["id"]
            touch(assignment)
            cascade.refresh_open_coaching(assignment["driver_id"],
                                          assignment.get("carrier_id"))
            marked += 1
    for assignment in assignments:
        if assignment["status"] != "OVERDUE":
            continue
        escalation = assignment["due_at"].plus_days(COACHING_ESCALATION_DAYS)
        if escalation.dt < snapshot.dt:
            assignment["status"] = "ESCALATED"
            touch(assignment)
            cascade.refresh_open_coaching(assignment["driver_id"],
                                          assignment.get("carrier_id"))
    for assignment in assignments:
        if assignment["status"] not in cascade.OPEN_COACHING_STATUSES:
            continue
        driver = store.drivers.get(assignment["driver_id"])
        if driver is None or driver.get("coaching_required"):
            continue
        if cascade.waive_assignment(assignment, "SCORE_BELOW_TRIGGER",
                                    statuses=cascade.OPEN_COACHING_STATUSES):
            waived += 1
    return marked, waived


# ---- sweep 5: re-derive the rolling challenge quota ------------------------

def _rederive_quotas(snapshot):
    window_start = snapshot.plus_days(-QUOTA_WINDOW_DAYS).dt
    for carrier in cascade.all_carriers():
        rows = [c for c in store.challenges.values()
                if c.get("carrier_id") == carrier["id"]
                and c["status"] in QUOTA_STATUSES
                and c.get("submitted_at") is not None]
        rows.sort(key=lambda c: (c["submitted_at"].dt, c["created_at"].dt,
                                 c["_seq"]))
        used = 0
        for challenge in rows:
            moment = challenge["submitted_at"].dt
            if moment > window_start and moment <= snapshot.dt:
                used += 1
        before = cascade.snap(carrier, ("challenge_quota_used",))
        carrier["challenge_quota_used"] = used
        cascade.finish(carrier, before)


def days_between(later, earlier):
    return whole_days(later, earlier)
