"""Training assignment lifecycle and the clock expiry sweep (PRD §3.1, §2.5)."""
import db
from errors import ApiError, ERR_TRAINING_STATE, forbidden_ownership
from services.common import touch, refresh_posture


def complete(assignment, lab, user_id):
    if assignment["status"] != "ASSIGNED":
        raise ApiError(ERR_TRAINING_STATE,
                       "Training assignment must be ASSIGNED to complete", 409)
    if user_id != assignment["worker_id"] and user_id != lab["pi_worker_id"]:
        raise forbidden_ownership(
            "Only the assigned worker or the lab's PI may complete this training")
    assignment["status"] = "COMPLETED"
    assignment["completed_at"] = db.now()
    touch(assignment)
    refresh_posture(lab)
    return assignment


def expiry_sweep():
    """Clock-set sweep: ASSIGNED assignments with due_date < now -> EXPIRED;
    then recompute every lab's posture (covers overstay re-evaluation too)."""
    now = db.now()
    for t in db.training_assignments.values():
        if t["status"] == "ASSIGNED" and t["due_date"] < now:
            t["status"] = "EXPIRED"
            touch(t)
    for lab in db.labs.values():
        refresh_posture(lab)
