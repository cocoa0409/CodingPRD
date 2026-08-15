from flask import Blueprint, request

from core import (ApiError, body, db, list_response, new_resource, ok,
                  req_enum, req_str, require_roles, touch)
from logic import active_hold_for, suppress_live_invitations
from serializers import ser_hold

bp = Blueprint("holds", __name__)


def get_hold_or_404(hold_id):
    h = db.holds.get(hold_id)
    if h is None:
        raise ApiError("ERR_PRIVACY_HOLD_NOT_FOUND", 404, "Privacy hold not found")
    return h


@bp.post("/feedback-panel/privacy-holds")
@require_roles("PrivacyOfficer")
def create_hold():
    data = body()
    panelist_id = req_str(data, "panelist_id")
    panelist = db.panelists.get(panelist_id)
    if panelist is None:
        raise ApiError("ERR_PANELIST_NOT_FOUND", 404, "Panelist not found")
    scope = req_enum(data, "scope", ("NO_CONTACT", "FULL_SUPPRESS"))
    reason = req_str(data, "reason")
    if active_hold_for(panelist_id) is not None:
        raise ApiError("ERR_PRIVACY_HOLD_EXISTS", 409,
                       "An ACTIVE hold already exists for the panelist")
    h = new_resource()
    h.update({
        "panelist_id": panelist_id,
        "scope": scope,
        "reason": reason,
        "status": "ACTIVE",
    })
    db.holds[h["id"]] = h
    if scope == "FULL_SUPPRESS":
        if panelist["status"] == "ACTIVE":
            panelist["status"] = "SUSPENDED"
            touch(panelist)
        suppress_live_invitations(panelist)
    return ok(ser_hold(h), 201)


@bp.get("/feedback-panel/privacy-holds")
@require_roles("PrivacyOfficer", "PanelManager")
def list_holds():
    items = list(db.holds.values())
    panelist_id = request.args.get("panelist_id")
    if panelist_id is not None:
        items = [h for h in items if h["panelist_id"] == panelist_id]
    status = request.args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    return list_response(items, ser_hold)


@bp.get("/feedback-panel/privacy-holds/<hold_id>")
@require_roles("PrivacyOfficer", "PanelManager")
def get_hold(hold_id):
    return ok(ser_hold(get_hold_or_404(hold_id)))


@bp.post("/feedback-panel/privacy-holds/<hold_id>/release")
@require_roles("PrivacyOfficer")
def release(hold_id):
    h = get_hold_or_404(hold_id)
    if h["status"] != "ACTIVE":
        raise ApiError("ERR_PRIVACY_HOLD_NOT_ACTIVE", 409,
                       "Release requires hold status ACTIVE")
    h["status"] = "RELEASED"
    touch(h)
    if h["scope"] == "FULL_SUPPRESS" and active_hold_for(h["panelist_id"]) is None:
        panelist = db.panelists[h["panelist_id"]]
        if panelist["status"] == "SUSPENDED":
            panelist["status"] = "ACTIVE"
            touch(panelist)
    return ok(ser_hold(h))
