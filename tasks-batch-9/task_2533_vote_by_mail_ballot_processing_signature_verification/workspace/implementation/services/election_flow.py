"""Posture advance, shared by the admin endpoint and the two automatic cascades."""
import db
from services import accountability, logbook


def apply_advance(election_rec, target, actor_role, actor_user_id):
    election_rec["posture"] = target
    db.touch(election_rec)
    if target == "MAILING":
        accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "POSTURE_CHANGED",
        actor_role,
        actor_user_id,
        "Election",
        election_rec["id"],
        "Election posture advanced to %s." % target,
    )


def auto_advance(election_rec, expected_current, target):
    """Fires as the third link of a business cascade; actor_role is 'system'."""
    if election_rec["posture"] != expected_current:
        return False
    apply_advance(election_rec, target, "system", None)
    return True
