"""Cross-aggregate state transitions and cascades (PRD §3.3-3.6, §3.9-3.10)."""
import db
from services import calc, notify


def survey_for_request(request_id):
    for s in db.surveys.values():
        if s["request_id"] == request_id:
            return s
    return None


def work_order_for_request(request_id):
    for wo in db.work_orders.values():
        if wo["request_id"] == request_id:
            return wo
    return None


def open_escalations_for_request(request_id):
    return [e for e in db.escalations.values()
            if e["request_id"] == request_id and e["status"] == "OPEN"]


# ---- Request lifecycle cascades ----

def request_to_in_progress(request):
    """Bubble-up: request ROUTED->IN_PROGRESS (PRD §3.4). Caller guarantees ROUTED."""
    from_status = request["status"]
    request["status"] = "IN_PROGRESS"
    notify.synthesize(request, from_status, "IN_PROGRESS")
    db.touch(request)


def request_to_resolved(request):
    """Bubble-up cascade: request IN_PROGRESS->RESOLVED (PRD §3.4).

    Stamps resolved_at, notifies, creates a SENT survey if none exists, resolves
    any OPEN escalation (resolved_by_role='system'), bumps version.
    """
    from_status = request["status"]
    request["status"] = "RESOLVED"
    request["resolved_at"] = db.CLOCK.now_iso()
    notify.synthesize(request, from_status, "RESOLVED")

    # Create a SatisfactionSurvey (SENT) if none exists yet.
    if survey_for_request(request["id"]) is None:
        survey = {
            "request_id": request["id"],
            "status": "SENT",
            "score": None,
            "comment": None,
        }
        db.stamp_common(survey)
        db.surveys[survey["id"]] = survey

    # Compensating side effect: resolve any still-open escalation on the request.
    for esc in open_escalations_for_request(request["id"]):
        esc["status"] = "RESOLVED"
        esc["resolved_by_role"] = "system"

    db.touch(request)


def request_reopen_cascade(request):
    """RESOLVED->REOPENED cascade (PRD §3.5). Caller has validated preconditions.

    Increments reopen_count, clears resolved_at, drives the work order
    COMPLETED->REOPENED then REOPENED->IN_PROGRESS (which bubbles the request back
    to IN_PROGRESS), expires a still-SENT survey, and synthesizes notifications.
    """
    # Request RESOLVED -> REOPENED
    from_status = request["status"]
    request["reopen_count"] = request.get("reopen_count", 0) + 1
    request["resolved_at"] = None
    request["status"] = "REOPENED"

    # Expire a still-SENT survey.
    survey = survey_for_request(request["id"])
    if survey is not None and survey["status"] == "SENT":
        survey["status"] = "EXPIRED"
        db.touch(survey)

    notify.synthesize(request, from_status, "REOPENED")
    db.touch(request)

    # Work order COMPLETED -> REOPENED (raises backlog), then REOPENED -> IN_PROGRESS.
    wo = work_order_for_request(request["id"])
    if wo is not None and wo["status"] == "COMPLETED":
        wo["status"] = "REOPENED"
        db.touch(wo)
        dept = db.departments.get(wo["department_id"])
        if dept is not None:
            calc.department_backlog(dept)

        # Immediately re-activate: REOPENED -> IN_PROGRESS (bubbles request).
        wo["status"] = "IN_PROGRESS"
        db.touch(wo)
        # Request REOPENED -> IN_PROGRESS bubble-up.
        req_from = request["status"]
        request["status"] = "IN_PROGRESS"
        notify.synthesize(request, req_from, "IN_PROGRESS")
        db.touch(request)


def request_close_cascade(request):
    """RESOLVED->CLOSED (PRD §3.6). Caller validated preconditions.

    Expires a still-SENT survey, notifies, bumps version.
    """
    from_status = request["status"]
    survey = survey_for_request(request["id"])
    if survey is not None and survey["status"] == "SENT":
        survey["status"] = "EXPIRED"
        db.touch(survey)
    request["status"] = "CLOSED"
    notify.synthesize(request, from_status, "CLOSED")
    db.touch(request)
