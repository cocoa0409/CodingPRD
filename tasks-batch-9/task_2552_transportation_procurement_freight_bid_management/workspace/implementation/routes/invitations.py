"""Invitation reads, responses and revocation — PRD §3.4."""
from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from routes.events import _recount_invitations
from services import bidding

bp = Blueprint("invitations", __name__)


@bp.get("/freight-procurement/invitations/<invitation_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "CarrierRep")
def get_invitation(invitation_id):
    return responses.ok(helpers.get_invitation(invitation_id))


@bp.get("/freight-procurement/invitations")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "CarrierRep")
def list_invitations():
    rows = store.sorted_rows(store.invitations.values())
    rows = helpers.filter_rows(rows, {"bid_event_id": "bid_event_id",
                                      "carrier_id": "carrier_id",
                                      "status": "status"})
    return responses.listing(rows)


@bp.post("/freight-procurement/invitations/<invitation_id>/response")
@auth.roles_required("CarrierRep")
def respond(invitation_id):
    invitation = helpers.get_invitation(invitation_id)
    payload = v.body()
    accept = v.bool_field(payload, "accept")
    nda_signed = v.bool_field(payload, "nda_signed", required=False, default=False)
    decline_reason = v.string_field(payload, "decline_reason", required=False,
                                    default=None)

    auth.own_carrier_or_raise(invitation["carrier_id"])
    if invitation["status"] != "SENT":
        raise ApiError("ERR_INVITATION_NOT_ACCEPTED",
                       "Only an invitation still SENT may be responded to.")

    carrier = store.carriers.get(invitation["carrier_id"])
    event = helpers.event_of(invitation)

    if accept:
        helpers.check_fitness(carrier, standing=helpers.STANDING_APPROVAL)
        if invitation["nda_required"] and not nda_signed:
            raise ApiError("ERR_NDA_NOT_SIGNED")
        invitation["status"] = "ACCEPTED"
        invitation["nda_signed"] = nda_signed
        invitation["responded_at"] = store.now_iso()
        invitation["snapshot_stale"] = (
            carrier["version"] != invitation["qualification_snapshot_carrier_version"])
        store.touch(invitation)
        if event is not None:
            _recount_invitations(event)
            store.touch(event)
    else:
        invitation["status"] = "DECLINED"
        invitation["decline_reason"] = decline_reason
        invitation["responded_at"] = store.now_iso()
        store.touch(invitation)
    return responses.ok(invitation)


@bp.post("/freight-procurement/invitations/<invitation_id>/revoke")
@auth.roles_required("ProcurementAnalyst")
def revoke(invitation_id):
    invitation = helpers.get_invitation(invitation_id)
    payload = v.body()
    reason = v.string_field(payload, "revoked_reason", min_len=1)

    if invitation["status"] not in ("SENT", "ACCEPTED"):
        raise ApiError("ERR_INVITATION_NOT_ACCEPTED",
                       "Only a SENT or ACCEPTED invitation may be revoked.")

    invitation["status"] = "REVOKED"
    invitation["revoked_reason"] = reason
    store.touch(invitation)

    event = helpers.event_of(invitation)
    if event is not None:
        _recount_invitations(event)
        store.touch(event)

    # The same withdrawal cascade a disqualification triggers.
    bidding.withdrawal_cascade(invitation["carrier_id"])
    return responses.ok(invitation)
