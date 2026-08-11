"""CommunicationPreference and global suppression-list endpoints."""

from flask import Blueprint

import db
from errors import (
    err_duplicate_child, err_invalid_request, err_not_found, err_unauthorized,
)
from middleware import require_roles
from response import success_list, success_object
from services.calculations import recompute_preference_suppression
from services.common import (
    apply_pagination, json_body, new_entity, pagination_args, req_enum, touch,
)
from services.serializers import PREFERENCE_FIELDS, serialize

bp = Blueprint("preferences", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
PREF_ROLES = ("AlumniRelationsStaff", "AlumniRelationsDirector", "Alumni")
CHANNELS = ("EMAIL", "MAIL", "PHONE")


def _get_record_or_404(rid):
    rec = db.records.get(rid)
    if rec is None:
        raise err_not_found("AlumniRecord not found")
    return rec


def get_preference_or_404(pid):
    p = db.preferences.get(pid)
    if p is None:
        raise err_not_found("CommunicationPreference not found")
    return p


def _find_pref(alumni_id, channel):
    for p in db.preferences.values():
        if p["alumni_id"] == alumni_id and p["channel"] == channel:
            return p
    return None


@bp.route("/alumni/records/<rid>/preferences", methods=["POST"])
@require_roles(*PREF_ROLES)
def upsert_preference(rid, _role, _user_id):
    record = _get_record_or_404(rid)
    if _role == "Alumni" and rid != _user_id:
        raise err_unauthorized("Acting user does not own this record")
    body = json_body(required=["channel"])
    channel = req_enum(body["channel"], "channel", CHANNELS)
    opt_in = body.get("opt_in", True)
    if not isinstance(opt_in, bool):
        raise err_invalid_request("opt_in must be a boolean")

    pref = _find_pref(rid, channel)
    if pref is None:
        pref = new_entity({
            "alumni_id": rid,
            "channel": channel,
            "opt_in": opt_in,
            "suppressed": False,
            "suppression_reason": "NONE",
        })
        db.preferences[pref["id"]] = pref
    else:
        # upsert: creating for an existing (alumnus, channel) updates opt_in
        pref["opt_in"] = opt_in
        touch(pref)
    recompute_preference_suppression(pref)
    return success_object(serialize(pref, PREFERENCE_FIELDS), status=201)


@bp.route("/alumni/records/<rid>/preferences", methods=["GET"])
@require_roles(*PREF_ROLES)
def list_preferences(rid, _role, _user_id):
    _get_record_or_404(rid)
    if _role == "Alumni" and rid != _user_id:
        raise err_unauthorized("Acting user does not own this record")
    limit, offset = pagination_args()
    rows = [p for p in db.preferences.values() if p["alumni_id"] == rid]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(p, PREFERENCE_FIELDS) for p in page], limit, offset, total)


@bp.route("/alumni/preferences/<pid>", methods=["PUT"])
@require_roles(*PREF_ROLES)
def update_preference(pid, _role, _user_id):
    pref = get_preference_or_404(pid)
    if _role == "Alumni" and pref["alumni_id"] != _user_id:
        raise err_unauthorized("Acting user does not own this preference")
    body = json_body(required=["opt_in"])
    opt_in = body["opt_in"]
    if not isinstance(opt_in, bool):
        raise err_invalid_request("opt_in must be a boolean")
    pref["opt_in"] = opt_in
    touch(pref)
    recompute_preference_suppression(pref)
    return success_object(serialize(pref, PREFERENCE_FIELDS))


@bp.route("/alumni/suppression-list", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def add_suppression(_role, _user_id):
    body = json_body(required=["alumni_id", "channel"])
    alumni_id = body["alumni_id"]
    if not isinstance(alumni_id, str):
        raise err_invalid_request("alumni_id must be a string")
    channel = req_enum(body["channel"], "channel", CHANNELS)
    _get_record_or_404(alumni_id)
    db.suppression_list.add((alumni_id, channel))
    pref = _find_pref(alumni_id, channel)
    if pref is not None:
        recompute_preference_suppression(pref)
        return success_object(serialize(pref, PREFERENCE_FIELDS), status=201)
    # No preference row yet: echo the pair as an object payload
    return success_object({"alumni_id": alumni_id, "channel": channel,
                           "suppressed": True, "suppression_reason": "GLOBAL_LIST"},
                          status=201)


@bp.route("/alumni/suppression-list", methods=["DELETE"])
@require_roles(*STAFF_OR_DIRECTOR)
def remove_suppression(_role, _user_id):
    # DELETE clients conventionally pass the pair as query parameters.
    body = json_body(required=["alumni_id", "channel"], allow_query=True)
    alumni_id = body["alumni_id"]
    if not isinstance(alumni_id, str):
        raise err_invalid_request("alumni_id must be a string")
    channel = req_enum(body["channel"], "channel", CHANNELS)
    _get_record_or_404(alumni_id)
    db.suppression_list.discard((alumni_id, channel))
    pref = _find_pref(alumni_id, channel)
    if pref is not None:
        recompute_preference_suppression(pref)
        return success_object(serialize(pref, PREFERENCE_FIELDS))
    return success_object({"alumni_id": alumni_id, "channel": channel,
                           "suppressed": False, "suppression_reason": "NONE"})
