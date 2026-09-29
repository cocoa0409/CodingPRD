"""Authentication, role authorization (PRD §2.1), path resolution (§2.8) and the
downtime freeze (§2.11)."""
from flask import g

import const
from common import now, touch
from db import db
from errors import ApiError

# ------------------------------------------------------------------ auth


def authenticate(allowed_roles):
    """Steps 1 and 2 of PRD §2.7 — both precede path resolution."""
    from flask import request

    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")

    allowed = tuple(allowed_roles)

    if role == const.SYSTEM_ADMIN:
        # SystemAdmin's X-User-ID is an opaque operator identifier (PRD §2.1).
        if const.SYSTEM_ADMIN not in allowed:
            raise ApiError("ERR_UNAUTHORIZED", "Role SystemAdmin may not perform this operation")
        g.user_id = user_id
        g.role = role
        g.actor = None
        return None

    clinician = db.clinicians.get(user_id)
    if clinician is None:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID does not name a registered clinician")
    if role not in const.CLINICIAN_ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Unknown role %s" % role)
    if role not in (clinician.get("authorized_roles") or []):
        raise ApiError("ERR_UNAUTHORIZED", "Clinician is not authorized to act as %s" % role)
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    g.user_id = user_id
    g.role = role
    g.actor = clinician
    return clinician


def caller_id():
    return g.get("user_id")


def caller_role():
    return g.get("role")


# ------------------------------------------------------------------ path resolution
def _get(table, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    record = table.get(key)
    if record is None:
        raise ApiError(error_id)
    return record


def get_clinician(cid):
    return _get(db.clinicians, cid, "ERR_CLINICIAN_NOT_FOUND")


def get_content_request(cid):
    return _get(db.content_requests, cid, "ERR_CONTENT_REQUEST_NOT_FOUND")


def get_order_set(cid):
    return _get(db.order_sets, cid, "ERR_ORDER_SET_NOT_FOUND")


def get_alert(cid):
    return _get(db.alerts, cid, "ERR_ALERT_NOT_FOUND")


def get_assignment(cid):
    return _get(db.review_assignments, cid, "ERR_REVIEW_ASSIGNMENT_NOT_FOUND")


def get_release(cid):
    return _get(db.vendor_releases, cid, "ERR_VENDOR_RELEASE_NOT_FOUND")


def get_delta(cid):
    return _get(db.vendor_deltas, cid, "ERR_VENDOR_RULE_DELTA_NOT_FOUND")


def get_downtime(cid):
    return _get(db.downtime_events, cid, "ERR_DOWNTIME_EVENT_NOT_FOUND")


def get_measurement(cid):
    return _get(db.adherence_measurements, cid, "ERR_ADHERENCE_MEASUREMENT_NOT_FOUND")


def get_task(cid):
    return _get(db.annual_review_tasks, cid, "ERR_ANNUAL_REVIEW_TASK_NOT_FOUND")


def get_window(alert, window_id):
    """Nested ownership: a window of another alert is not found here (PRD §2.8)."""
    window = db.burden_windows.get(window_id) if isinstance(window_id, str) else None
    if window is None or window["alert_id"] != alert["id"]:
        raise ApiError("ERR_BURDEN_WINDOW_NOT_FOUND")
    return window


# ------------------------------------------------------------------ downtime freeze
# What each scope covers (PRD §2.11).
_SCOPE_CLASSES = {
    "ORDER_SETS_ONLY": ("order_set",),
    "ALERTS_ONLY": ("alert",),
    "SYSTEM_WIDE": ("order_set", "alert", "vendor"),
}


def _active_events(resource_class):
    events = [e for e in db.downtime_events.values() if e["state"] == "ACTIVE"]
    events.sort(key=lambda e: e.get("_seq", 0))
    return [e for e in events if resource_class in _SCOPE_CLASSES.get(e["scope"], ())]


def check_freeze(resource_class):
    """Refuse an in-scope mutation while a downtime event is ACTIVE."""
    for event in _active_events(resource_class):
        error_id = (
            "ERR_CDS_UNAVAILABLE" if event["mode"] == "FULL_UNAVAILABLE" else "ERR_CDS_CONTENT_FROZEN"
        )
        event["blocked_mutation_count"] = event["blocked_mutation_count"] + 1
        touch(event)
        raise ApiError(error_id, "Decision support content is unavailable during downtime")


def check_read_freeze(resource_class):
    """FULL_UNAVAILABLE also refuses reads of in-scope content (PRD §2.11)."""
    for event in _active_events(resource_class):
        if event["mode"] == "FULL_UNAVAILABLE":
            raise ApiError("ERR_CDS_UNAVAILABLE", "Decision support content is unavailable during downtime")
