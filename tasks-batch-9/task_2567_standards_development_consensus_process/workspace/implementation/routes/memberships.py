"""Committee seats: read and edit (PRD 3.1). Seats are edited, never deleted."""

from flask import Blueprint

from core import auth, envelope
from core.enums import MEMBERSHIP_STATUS
from core.errors import bad_request
from core.store import db, public, rows, touch
from core.validation import Body, apply_filters, load_path
from services import balance

bp = Blueprint("memberships", __name__)

FILTERS = ("committee_id", "participant_id", "status")

ALLOWED_EDGES = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "WITHDRAWN"),
    ("SUSPENDED", "WITHDRAWN"),
}


@bp.get("/sdo/memberships")
def list_memberships():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("memberships"), FILTERS))


@bp.get("/sdo/memberships/<membership_id>")
def get_membership(membership_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("memberships", membership_id)))


@bp.patch("/sdo/memberships/<membership_id>")
def edit_membership(membership_id):
    auth.authenticate((auth.STANDARDS_STAFF,))
    seat = load_path("memberships", membership_id)
    body = Body(("status", "voting_rights"))
    new_status = body.enum("status", MEMBERSHIP_STATUS, default=None)
    new_voting = body.boolean("voting_rights", default=None)

    current = seat["status"]
    if new_status is not None and new_status != current:
        if (current, new_status) not in ALLOWED_EDGES:
            bad_request("A seat cannot move from %s to %s." % (current, new_status))

    changed = False
    if new_status is not None and new_status != current:
        seat["status"] = new_status
        if current == "SUSPENDED" and new_status == "ACTIVE":
            seat["missed_ballot_streak"] = 0
        changed = True
    if new_voting is not None and new_voting != seat["voting_rights"]:
        seat["voting_rights"] = new_voting
        changed = True

    if changed:
        touch(seat)
        committee = db.committees.get(seat["committee_id"])
        if committee is not None:
            balance.seat_change_cascade(committee)
    return envelope.object_response(public(seat))
