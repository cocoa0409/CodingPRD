"""Anniversary outreach touchpoints (§3.8)."""

from flask import Blueprint

from core.auth import authenticate, own_outreach_volunteer
from core.envelope import ok
from core.errors import ApiError
from core.shape import body
from core.store import public, store
from services.state import must_exist, require_participant_active, transition

bp = Blueprint("outreach", __name__)

ACTOR_ROLES = ["IntakeCoordinator", "VolunteerCompanion"]


@bp.route("/bereavement/anniversary-outreaches/<oid>/send", methods=["POST"])
def send_outreach(oid):
    ctx = authenticate(ACTOR_ROLES)
    row = must_exist("AnniversaryOutreach", oid)
    own_outreach_volunteer(ctx, row)
    body()
    if row["status"] != "DUE":
        raise ApiError("ERR_OUTREACH_NOT_DUE", "The touchpoint is not DUE.")
    participant = store.get("Participant", row["participant_id"])
    if participant is not None:
        require_participant_active(participant)
    row["status"] = "SENT"
    row["sent_at"] = store.now_iso()
    store.touch(row)
    return ok(public(row))


@bp.route("/bereavement/anniversary-outreaches/<oid>/acknowledge", methods=["POST"])
def acknowledge_outreach(oid):
    ctx = authenticate(ACTOR_ROLES)
    row = must_exist("AnniversaryOutreach", oid)
    own_outreach_volunteer(ctx, row)
    body()
    transition(row, {"SENT", "NO_RESPONSE"})
    row["status"] = "ACKNOWLEDGED"
    row["acknowledged_at"] = store.now_iso()
    store.touch(row)
    participant = store.get("Participant", row["participant_id"])
    if participant is not None and participant["outreach_status"] == "LAPSED":
        participant["outreach_status"] = "SCHEDULED"
        store.touch(participant)
    return ok(public(row))
