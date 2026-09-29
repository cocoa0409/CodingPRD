"""State machines, cascades and the two conserved ledgers (PRD §2.9, §2.12, §3)."""
import const
from common import add_days, base_record, now, touch
from db import db
from services import calc


# ------------------------------------------------------------------ lookups
def assignments_of_order_set(order_set_id):
    return [a for a in db.review_assignments.values() if a.get("order_set_id") == order_set_id]


def assignments_of_alert(alert_id):
    return [a for a in db.review_assignments.values() if a.get("alert_id") == alert_id]


def windows_of_alert(alert_id):
    return [w for w in db.burden_windows.values() if w["alert_id"] == alert_id]


def items_of_order_set(order_set_id):
    return [i for i in db.order_set_items.values() if i["order_set_id"] == order_set_id]


def events_of_alert(alert_id):
    return [e for e in db.override_events.values() if e["alert_id"] == alert_id]


def alerts_linked_to(order_set_id):
    return [a for a in db.alerts.values() if a.get("linked_order_set_id") == order_set_id]


def deltas_of_release(release_id):
    return [d for d in db.vendor_deltas.values() if d["vendor_release_id"] == release_id]


def governing_task(artifact_kind, artifact_id):
    key = "order_set_id" if artifact_kind == "ORDER_SET" else "alert_id"
    tasks = [
        t for t in db.annual_review_tasks.values()
        if t["artifact_kind"] == artifact_kind and t.get(key) == artifact_id
        and t["state"] in ("PENDING", "OVERDUE")
    ]
    tasks.sort(key=lambda t: (t["cycle_index"], t.get("_seq", 0)))
    return tasks[-1] if tasks else None


# ------------------------------------------------------------------ workload ledger
def _refresh_remaining(clinician):
    clinician["review_workload_remaining_minutes"] = (
        clinician["review_workload_capacity_minutes"] - clinician["review_workload_assigned_minutes"]
    )


def debit_workload(clinician, minutes):
    clinician["review_workload_assigned_minutes"] += minutes
    clinician["open_assignment_count"] += 1
    _refresh_remaining(clinician)
    touch(clinician)


def credit_workload(assignment):
    clinician = db.clinicians.get(assignment["reviewer_id"])
    if clinician is None:
        return
    clinician["review_workload_assigned_minutes"] -= assignment["estimated_minutes"]
    if assignment["state"] == "ASSIGNED":
        clinician["open_assignment_count"] -= 1
    _refresh_remaining(clinician)
    touch(clinician)


# ------------------------------------------------------------------ order set helpers
def order_set_risk_class(order_set):
    request_record = db.content_requests.get(order_set["content_request_id"])
    safety = bool(request_record and request_record.get("patient_safety_flag"))
    if order_set["high_alert_item_count"] >= 1 or safety:
        return "HIGH"
    return "STANDARD"


def alert_risk_class(alert):
    return "HIGH" if alert["severity_tier"] == "TIER_1_HARD_STOP" else "STANDARD"


def recompute_order_set_counters(order_set):
    assignments = assignments_of_order_set(order_set["id"])
    for kind, prefix in (("PEER_REVIEW", "peer"), ("SPECIALTY_APPROVAL", "specialty")):
        cast = [a for a in assignments if a["review_kind"] == kind and a["state"] == "CAST"]
        approve = len([a for a in cast if a["vote"] == "APPROVE"])
        order_set[prefix + "_cast_count"] = len(cast)
        order_set[prefix + "_approve_ratio"] = calc.approve_ratio(approve, len(cast))
    order_set["votes_cast_count"] = len([a for a in assignments if a["state"] == "CAST"])
    order_set["votes_voided_count"] = len([a for a in assignments if a["state"] == "VOIDED"])


def recompute_alert_counters(alert):
    assignments = assignments_of_alert(alert["id"])
    alert["approval_cast_count"] = len([a for a in assignments if a["state"] == "CAST"])


def void_assignment(assignment, reason):
    credit_workload(assignment)
    assignment["state"] = "VOIDED"
    assignment["void_reason"] = reason
    touch(assignment)


def void_other_assignments(assignments, exclude_id, reason):
    for assignment in sorted(assignments, key=lambda a: a.get("_seq", 0)):
        if assignment["id"] == exclude_id:
            continue
        if assignment["state"] in ("ASSIGNED", "CAST"):
            void_assignment(assignment, reason)


def restage_linked_alerts(order_set):
    for alert in sorted(alerts_linked_to(order_set["id"]), key=lambda a: a.get("_seq", 0)):
        if alert["lifecycle_state"] != "UNPUBLISHED":
            continue
        if alert["review_state"] not in ("SPECIALTY_APPROVAL", "APPROVED"):
            continue
        alert["review_state"] = "DRAFT"
        alert["restage_count"] += 1
        touch(alert)


def supersede_unpublished_predecessor(predecessor):
    predecessor["publication_state"] = "SUPERSEDED"
    touch(predecessor)
    for assignment in sorted(assignments_of_order_set(predecessor["id"]), key=lambda a: a.get("_seq", 0)):
        if assignment["state"] in ("ASSIGNED", "CAST"):
            void_assignment(assignment, "ARTIFACT_SUPERSEDED")
    recompute_order_set_counters(predecessor)


# ------------------------------------------------------------------ review schedule
def review_interval_days(risk_class):
    return const.REVIEW_INTERVAL_DAYS[risk_class]


def schedule_from(anchor, risk_class, with_archive=True):
    due = add_days(anchor, review_interval_days(risk_class))
    expiration = add_days(due, const.GRACE_PERIOD_DAYS)
    archive = add_days(expiration, const.ARCHIVE_AFTER_EXPIRY_DAYS) if with_archive else None
    return due, expiration, archive


def create_annual_task(artifact_kind, artifact, due, expiration, archive, cycle_index=1):
    task = base_record()
    task.update({
        "order_set_id": artifact["id"] if artifact_kind == "ORDER_SET" else None,
        "alert_id": artifact["id"] if artifact_kind == "ALERT" else None,
        "attested_by_clinician_id": None,
        "evidence_citations": [],
        "artifact_kind": artifact_kind,
        "state": "PENDING",
        "review_due_date": due,
        "expiration_at": expiration,
        "archive_eligible_at": archive,
        "stale_content_triggered": False,
        "attested_at": None,
        "attestation_note": None,
        "cycle_index": cycle_index,
    })
    db.annual_review_tasks[task["id"]] = task
    return task


# ------------------------------------------------------------------ content request closure
def request_type_satisfied(request_record):
    order_sets = [o for o in db.order_sets.values() if o["content_request_id"] == request_record["id"]]
    alerts = [a for a in db.alerts.values() if a["content_request_id"] == request_record["id"]]
    published = any(o["publication_state"] == "PUBLISHED" for o in order_sets)
    active = any(a["lifecycle_state"] == "ACTIVE" for a in alerts)
    kind = request_record["request_type"]
    if kind == "ORDER_SET":
        return published
    if kind == "ALERT":
        return active
    return published and active


def maybe_close_content_request(request_record):
    if request_record is None:
        return
    if request_record["status"] != "BUILD_IN_PROGRESS":
        return
    if request_type_satisfied(request_record):
        request_record["status"] = "CLOSED_IMPLEMENTED"
        touch(request_record)


def advance_request_to_build(request_record):
    if request_record["status"] == "TRIAGE_ACCEPTED":
        request_record["status"] = "BUILD_IN_PROGRESS"
        touch(request_record)


# ------------------------------------------------------------------ alert firing ledger
def recompute_alert_ledger(alert):
    windows = windows_of_alert(alert["id"])
    windowed = sum(w["fire_count"] for w in windows if w["state"] in ("CLOSED", "FINALIZED"))
    alert["windowed_fire_count"] = windowed
    alert["unwindowed_fire_count"] = alert["lifetime_fire_count"] - windowed
    closed = [w for w in windows if w["state"] in ("CLOSED", "FINALIZED")]
    closed.sort(key=lambda w: (w["window_start"], w["created_at"], w.get("_seq", 0)), reverse=True)
    if closed:
        alert["latest_burden_index"] = closed[0]["burden_index"]
        alert["latest_burden_classification"] = closed[0]["burden_classification"]
    else:
        alert["latest_burden_index"] = None
        alert["latest_burden_classification"] = None
    touch(alert)


def recompute_override_ledger(alert):
    alert["lifetime_override_count"] = len(
        [e for e in events_of_alert(alert["id"]) if e["accepted"] is False]
    )


def close_window(window, alert, closure_reason):
    """Compute the window's measurement and close it (PRD §3.7)."""
    events = [
        e for e in events_of_alert(alert["id"])
        if window["window_start"] <= e["fired_at"] < window["window_end"]
    ]
    fire_count = len(events)
    overrides = [e for e in events if e["accepted"] is False]
    override_count = len(overrides)
    distinct_fired = len({e["firing_clinician_ref"] for e in events})
    distinct_overriding = len({e["firing_clinician_ref"] for e in overrides})

    metrics = calc.burden_metrics(
        fire_count, override_count, distinct_fired, distinct_overriding,
        window["severity_tier_snapshot"],
    )

    window["fire_count"] = fire_count
    window["override_count"] = override_count
    window["accept_count"] = fire_count - override_count
    window["distinct_fired_clinician_count"] = distinct_fired
    window["distinct_overriding_clinician_count"] = distinct_overriding
    window.update(metrics)
    window["state"] = "CLOSED"
    window["closure_reason"] = closure_reason
    window["closed_at"] = now()
    touch(window)

    recompute_alert_ledger(alert)
    return window


def close_open_windows(alert, closure_reason):
    closed = 0
    for window in sorted(windows_of_alert(alert["id"]), key=lambda w: w.get("_seq", 0)):
        if window["state"] == "OPEN":
            close_window(window, alert, closure_reason)
            closed += 1
    return closed


# ------------------------------------------------------------------ alert lifecycle cascades
def suspend_alert(alert, reason):
    """ACTIVE -> SUSPENDED, closing any OPEN burden window."""
    alert["lifecycle_state"] = "SUSPENDED"
    alert["suspension_reason"] = reason
    alert["suspension_count"] += 1
    touch(alert)
    return close_open_windows(alert, "SOURCE_SUSPENDED")


def retire_alert(alert):
    """-> RETIRED, closing OPEN windows and finalizing CLOSED ones."""
    alert["lifecycle_state"] = "RETIRED"
    alert["retired_at"] = now()
    touch(alert)
    closed = close_open_windows(alert, "ALERT_RETIRED")
    for window in sorted(windows_of_alert(alert["id"]), key=lambda w: w.get("_seq", 0)):
        if window["state"] == "CLOSED":
            window["state"] = "FINALIZED"
            touch(window)
    task = governing_task("ALERT", alert["id"])
    expired = 0
    if task is not None:
        task["state"] = "EXPIRED"
        touch(task)
        expired = 1
    return closed, expired


def retirement_gate_satisfied(alert):
    windows = [
        w for w in windows_of_alert(alert["id"]) if w["state"] in ("CLOSED", "FINALIZED")
    ]
    windows.sort(key=lambda w: (w["window_start"], w["created_at"], w.get("_seq", 0)), reverse=True)
    candidates = windows[:const.RETIREMENT_WINDOW_COUNT]
    if len(candidates) != const.RETIREMENT_WINDOW_COUNT:
        return False
    for window in candidates:
        rate = window["override_rate"]
        index = window["burden_index"]
        if rate is None or index is None:
            return False
        if rate < const.MIN_OVERRIDE_RATE:
            return False
        if window["fire_count"] < const.MIN_FIRE_COUNT:
            return False
        if index < const.MIN_BURDEN_INDEX:
            return False
    return True


# ------------------------------------------------------------------ order set publication cascades
def apply_schedule_to_order_set(order_set, due, expiration, archive):
    order_set["review_due_date"] = due
    order_set["expiration_at"] = expiration
    order_set["archive_eligible_at"] = archive


def apply_schedule_to_alert(alert, due, expiration):
    alert["review_due_date"] = due
    alert["expiration_at"] = expiration
