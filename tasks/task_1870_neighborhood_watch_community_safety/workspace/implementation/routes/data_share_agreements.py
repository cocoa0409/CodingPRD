"""DataShareAgreement routes."""

from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("data_share_agreements", __name__)

VALID_SCOPES = {"INCIDENT_SUMMARIES", "ROSTER_CONTACTS", "FULL"}


def _serialize_agreement(a):
    return {
        "id": a["id"],
        "watch_group_id": a["watch_group_id"],
        "liaison_officer_id": a["liaison_officer_id"],
        "scope": a["scope"],
        "agreement_status": a["agreement_status"],
        "expires_at": a["expires_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/watch/data-share-agreements", methods=["POST"])
def create_agreement():
    user_id, role = require_roles("ProgramCoordinator")
    body = request.get_json(force=True, silent=True) or {}

    watch_group_id = body.get("watch_group_id")
    liaison_officer_id = body.get("liaison_officer_id")
    scope = body.get("scope")
    expires_at = body.get("expires_at")

    if not scope or scope not in VALID_SCOPES:
        raise errors.invalid_request("Invalid scope")
    if not expires_at:
        raise errors.invalid_request("expires_at is required")
    try:
        db.parse_iso(expires_at)
    except Exception:
        raise errors.invalid_request("expires_at is not valid ISO-8601")

    # Existence
    g = db.watch_groups.get(watch_group_id) if watch_group_id else None
    if not g:
        raise errors.not_found("WatchGroup not found")
    o = db.liaison_officers.get(liaison_officer_id) if liaison_officer_id else None
    if not o:
        raise errors.not_found("LiaisonOfficer not found")

    # Referential integrity: officer precinct must match group precinct
    if o["precinct_code"] != g["precinct_code"]:
        raise errors.referential("Officer precinct does not match group precinct")

    record = {
        "watch_group_id": watch_group_id,
        "liaison_officer_id": liaison_officer_id,
        "scope": scope,
        "agreement_status": "PENDING",
        "expires_at": expires_at,
    }
    svc.stamp_new(record)
    db.data_share_agreements[record["id"]] = record
    return success_object(_serialize_agreement(record), 201)


@bp.route("/watch/data-share-agreements", methods=["GET"])
def list_agreements():
    user_id, role = require_roles("ProgramCoordinator", "LiaisonOfficer")

    # Lazy expiry sweep
    svc.sweep_agreement_expiry()

    items = list(db.data_share_agreements.values())

    wg = request.args.get("watch_group_id")
    if wg:
        items = [a for a in items if a["watch_group_id"] == wg]
    lo = request.args.get("liaison_officer_id")
    if lo:
        items = [a for a in items if a["liaison_officer_id"] == lo]
    st = request.args.get("agreement_status")
    if st:
        items = [a for a in items if a["agreement_status"] == st]

    items.sort(key=lambda a: a["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_agreement(a) for a in items], limit, offset, total)


@bp.route("/watch/data-share-agreements/<id>", methods=["GET"])
def get_agreement(id):
    user_id, role = require_roles("ProgramCoordinator", "LiaisonOfficer")
    a = db.data_share_agreements.get(id)
    if not a:
        raise errors.not_found("DataShareAgreement not found")

    # Lazy expiry
    svc.sweep_agreement_expiry(a["watch_group_id"])
    # Re-fetch in case status changed
    a = db.data_share_agreements[id]
    return success_object(_serialize_agreement(a))


@bp.route("/watch/data-share-agreements/<id>/activate", methods=["POST"])
def activate_agreement(id):
    user_id, role = require_roles("LiaisonOfficer")
    a = db.data_share_agreements.get(id)
    if not a:
        raise errors.not_found("DataShareAgreement not found")

    if a["agreement_status"] != "PENDING":
        raise errors.invalid_state("Agreement is not PENDING")

    # Acting officer must be the agreement's officer
    if user_id != a["liaison_officer_id"]:
        raise errors.unauthorized("Only the designated officer may activate")

    # Precinct match
    o = db.liaison_officers.get(a["liaison_officer_id"])
    g = db.watch_groups.get(a["watch_group_id"])
    if o and g and o["precinct_code"] != g["precinct_code"]:
        raise errors.referential("Officer precinct does not match group precinct")

    # Clock must not have reached expires_at
    exp = db.parse_iso(a["expires_at"])
    if db.get_clock() >= exp:
        raise errors.invalid_state("Agreement has already expired")

    a["agreement_status"] = "ACTIVE"
    svc.touch(a)
    return success_object(_serialize_agreement(a))


@bp.route("/watch/data-share-agreements/<id>/revoke", methods=["POST"])
def revoke_agreement(id):
    user_id, role = require_roles("ProgramCoordinator", "LiaisonOfficer")
    a = svc.revoke_agreement_by_id(id)
    return success_object(_serialize_agreement(a))
