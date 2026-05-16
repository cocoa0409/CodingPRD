"""Authorization-specific business logic: revoke + downstream cascade."""

from db import db, now_iso_virtual
from errors import APIError
from services.enrollments import cascade_auth_revoke_on_child
from services.projection import project_child_auth_statuses


def revoke_authorization(authorization):
    """Per state machine: ACTIVE→REVOKED. Then re-project child status and cascade enrollment
    cancellations on confirmed future-week enrollments if a kind dropped below ACTIVE.
    """
    if authorization["status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE")
    authorization["status"] = "REVOKED"
    authorization["revoked_at"] = now_iso_virtual()
    child = db.children[authorization["child_id"]]
    # Re-project (this persists changes if any).
    old_med = child["medical_authorization_status"]
    old_pick = child["pickup_authorization_status"]
    project_child_auth_statuses(child, persist=True)
    dropped = (
        (old_med == "ACTIVE" and child["medical_authorization_status"] != "ACTIVE")
        or (old_pick == "ACTIVE" and child["pickup_authorization_status"] != "ACTIVE")
    )
    if dropped:
        cascade_auth_revoke_on_child(child)
    return authorization


def revoke_scholarship(scholarship):
    """Per ScholarshipAward state machine: ACTIVE/EXHAUSTED → REVOKED."""
    if scholarship["status"] not in {"ACTIVE", "EXHAUSTED"}:
        raise APIError("ERR_INVALID_STATE")
    scholarship["status"] = "REVOKED"
    scholarship["revoked_at"] = now_iso_virtual()
    from db import touch  # local import to avoid cycle at module load
    touch(scholarship)
    return scholarship
