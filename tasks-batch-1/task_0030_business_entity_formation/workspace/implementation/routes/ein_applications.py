"""EINApplication routes."""
from __future__ import annotations

import re

from flask import Blueprint, request

import db
import errors
import middleware
import response
from routes._helpers import parse_json_body_required, parse_json_body_optional, parse_pagination, sort_by_created
from services import access, core, serialize

bp = Blueprint("ein_applications", __name__)

_SSN_LAST4_RE = re.compile(r"^\d{4}$")


@bp.route("/business-entities/<be_id>/ein-applications", methods=["POST"])
def create_ein_application(be_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    be = access.get_business_entity_or_404(be_id)
    access.require_filer_owns(role, user_id, be["id"])

    if be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    body = parse_json_body_required()
    name = body.get("responsible_party_name")
    ssn4 = body.get("responsible_party_ssn_last4")
    if not isinstance(name, str) or len(name) < 1 or len(name) > 120:
        raise errors.err_invalid_request("responsible_party_name must be 1..120 chars.")
    if not isinstance(ssn4, str) or not _SSN_LAST4_RE.match(ssn4):
        raise errors.err_invalid_request("responsible_party_ssn_last4 must be exactly 4 digits.")

    ea = {
        "business_entity_id": be["id"],
        "responsible_party_name": name,
        "responsible_party_ssn_last4": ssn4,
        "ein": None,
        "status": "PENDING",
        "issued_at": None,
    }
    core.stamp_create_common(ea)
    db.ein_applications[ea["id"]] = ea
    return response.success_object(serialize.ein_application(ea), status=201)


@bp.route("/business-entities/<be_id>/ein-applications", methods=["GET"])
def list_ein_applications(be_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    be = access.get_business_entity_or_404(be_id)

    limit, offset = parse_pagination()
    st = request.args.get("status")
    items = core.children_ein_applications(be["id"])
    if st is not None:
        items = [x for x in items if x["status"] == st]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([serialize.ein_application(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)


@bp.route("/ein-applications/<ea_id>/issue", methods=["POST"])
def issue_ein_application(ea_id: str):
    role, user_id = middleware.require_auth(["StateAdmin"])
    ea = access.get_ein_application_or_404(ea_id)
    be = db.business_entities.get(ea["business_entity_id"])

    if ea["status"] != "PENDING":
        raise errors.err_invalid_state(f"EINApplication is in {ea['status']}, not PENDING.")

    body = parse_json_body_optional()
    reject = bool(body.get("reject", False))

    if reject:
        ea["status"] = "REJECTED"
        core.stamp_update_common(ea)
        return response.success_object(serialize.ein_application(ea))

    # ISSUED path: requires BusinessEntity.status != DISSOLVED
    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    ea["ein"] = db.next_ein()
    ea["status"] = "ISSUED"
    ea["issued_at"] = db.iso_format(db.now_utc())
    ea["_issued_at_dt"] = db.now_utc()
    core.stamp_update_common(ea)

    if be is not None:
        core.cascade_after_child_change(be)

    return response.success_object(serialize.ein_application(ea))
