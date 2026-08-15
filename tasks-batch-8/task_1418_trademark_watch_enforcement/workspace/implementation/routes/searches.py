"""ClearanceSearch endpoints (PRD 3.9)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_VALIDATION,
    ERR_UNRESOLVED_HITS,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services.domain import ser_clearance_search
from util import (
    get_payload, reject_unknown_fields, require_string, require_enum,
    require_int, require_nice_classes, stamp_new, touch,
)
from routes.common import do_list

bp = Blueprint("clearance_searches", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "IDENTICAL")
DISPOSITIONS = ("WAIVED", "BLOCKING")


def _get_search(search_id):
    search = db.clearance_searches.get(search_id)
    if search is None:
        raise_error(ERR_NOT_FOUND, "ClearanceSearch not found")
    return search


def _validate_hit(hit):
    if not isinstance(hit, dict):
        raise_error(ERR_VALIDATION, "conflict_hits entries must be objects")
    for key in hit:
        if key not in ("conflicting_mark", "severity"):
            raise_error(ERR_VALIDATION, "Unknown conflict hit field: %s" % key)
    if "conflicting_mark" not in hit or not isinstance(hit["conflicting_mark"], str):
        raise_error(ERR_VALIDATION, "conflict hit requires conflicting_mark (string)")
    if hit.get("severity") not in SEVERITIES:
        raise_error(ERR_VALIDATION, "conflict hit severity must be LOW/MEDIUM/HIGH/IDENTICAL")
    return {"conflicting_mark": hit["conflicting_mark"],
            "severity": hit["severity"],
            "disposition": "OPEN"}


@bp.route("/brand/clearance-searches", methods=["POST"])
def create_search():
    user_id, role = require_roles("ClientContact", "Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"client_id", "proposed_mark", "proposed_classes",
                                 "conflict_hits"})
    client_id = require_string(body, "client_id")
    proposed_mark = require_string(body, "proposed_mark")
    proposed_classes = require_nice_classes(body, "proposed_classes", require_nonempty=False)
    hits_raw = body.get("conflict_hits", None)
    hits = []
    if hits_raw is not None:
        if not isinstance(hits_raw, list):
            raise_error(ERR_VALIDATION, "conflict_hits must be an array")
        hits = [_validate_hit(h) for h in hits_raw]
    # ClientContact may only open a search for its own client_id.
    enforce_client_scope(user_id, role, client_id)
    if client_id not in db.clients:
        raise_error(ERR_NOT_FOUND, "Client not found")
    search = {
        "client_id": client_id,
        "proposed_mark": proposed_mark,
        "proposed_classes": list(proposed_classes),
        "conflict_hits": hits,
        "status": "OPEN",
    }
    stamp_new(search)
    db.clearance_searches[search["id"]] = search
    return success(ser_clearance_search(search), 201)


@bp.route("/brand/clearance-searches", methods=["GET"])
def list_searches():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.clearance_searches.values(), ser_clearance_search,
                   [("client_id", "client_id", None), ("status", "status", None)],
                   user_id, role, "clearance_search")


@bp.route("/brand/clearance-searches/<search_id>", methods=["GET"])
def get_search(search_id):
    user_id, role = require_roles(*READ_ROLES)
    search = _get_search(search_id)
    enforce_client_scope(user_id, role, search["client_id"])
    return success(ser_clearance_search(search), 200)


@bp.route("/brand/clearance-searches/<search_id>/conflict-hits", methods=["POST"])
def append_hit(search_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"conflicting_mark", "severity"})
    hit = _validate_hit(body)
    search = _get_search(search_id)
    if search["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "conflict hits may be appended only to an OPEN search")
    search["conflict_hits"].append(hit)
    touch(search)
    return success(ser_clearance_search(search), 201)


@bp.route("/brand/clearance-searches/<search_id>/dispose-hit", methods=["POST"])
def dispose_hit(search_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"hit_index", "disposition"})
    hit_index = require_int(body, "hit_index")
    disposition = require_enum(body, "disposition", DISPOSITIONS)
    search = _get_search(search_id)
    # hit_index is the 0-based position; an out-of-range index is ERR_VALIDATION.
    if hit_index < 0 or hit_index >= len(search["conflict_hits"]):
        raise_error(ERR_VALIDATION, "hit_index out of range")
    if search["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "hits may be disposed only on an OPEN search")
    search["conflict_hits"][hit_index]["disposition"] = disposition
    touch(search)
    return success(ser_clearance_search(search), 200)


@bp.route("/brand/clearance-searches/<search_id>/finalize", methods=["POST"])
def finalize_search(search_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    search = _get_search(search_id)
    if search["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "finalize is declared only from OPEN")
    # Finalize requires every hit resolved (none still OPEN).
    if any(h["disposition"] == "OPEN" for h in search["conflict_hits"]):
        raise_error(ERR_UNRESOLVED_HITS, "Finalize requires unresolved_hit_count == 0")
    # Any BLOCKING hit lands the search in BLOCKED; otherwise CLEARED.
    search["status"] = ("BLOCKED" if any(h["disposition"] == "BLOCKING"
                                         for h in search["conflict_hits"])
                        else "CLEARED")
    touch(search)
    return success(ser_clearance_search(search), 200)
