"""ACCRequest endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    ERR_ACC_REVISION_LIMIT,
    ERR_INVALID_STATE,
    ERR_PROPERTY_SUSPENDED,
    ERR_UNAUTHORIZED,
    raise_err,
)
from middleware import auth_required
from response import list_success, success
from .helpers import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_str,
)


bp = Blueprint("acc_requests", __name__)

SCOPES = {"APPEARANCE", "LANDSCAPING"}


def _serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "property_id": r["property_id"],
        "scope": r["scope"],
        "description": r["description"],
        "status": r["status"],
        "revision_count": int(r.get("revision_count", 0)),
        "decided_at": r.get("decided_at"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _require_owner_of_property(prop: dict):
    if g.user_id != prop["owner_id"]:
        raise_err(ERR_UNAUTHORIZED,
                  "Caller does not own the target property")


@bp.route("/hoa/acc-requests", methods=["POST"])
@auth_required({"HomeOwner"})
def create_acc_request():
    body = get_json_body()
    property_id = require_str(body, "property_id")
    scope = require_enum(body, "scope", SCOPES)
    description = require_str(body, "description")

    prop = fetch_or_404(db.properties, property_id, "Property")
    _require_owner_of_property(prop)

    record = {
        **db.make_common_fields(),
        "property_id": property_id,
        "scope": scope,
        "description": description,
        "status": "SUBMITTED",
        "revision_count": 0,
        "decided_at": None,
    }
    db.acc_requests[record["id"]] = record
    return success(_serialize(record), status=201)


@bp.route("/hoa/acc-requests/<rid>", methods=["GET"])
@auth_required({"PlatformAdmin", "ACCMember", "BoardPresident",
                "BoardSecretary", "HomeOwner"})
def fetch_acc_request(rid):
    r = fetch_or_404(db.acc_requests, rid, "ACCRequest")
    return success(_serialize(r))


@bp.route("/hoa/acc-requests", methods=["GET"])
@auth_required({"PlatformAdmin", "ACCMember", "BoardPresident",
                "BoardSecretary", "HomeOwner"})
def list_acc_requests():
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    scope = request.args.get("scope")
    rows = list(db.acc_requests.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if scope is not None:
        rows = [r for r in rows if r["scope"] == scope]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize(r) for r in page], total, limit, offset)


@bp.route("/hoa/acc-requests/<rid>/approve", methods=["POST"])
@auth_required({"ACCMember"})
def approve_acc_request(rid):
    r = fetch_or_404(db.acc_requests, rid, "ACCRequest")
    if r["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE,
                  f"ACCRequest must be SUBMITTED to approve "
                  f"(currently {r['status']})")
    prop = fetch_or_404(db.properties, r["property_id"], "Property")
    # business_safety (priority 6): block if SUSPENDED
    if prop.get("compliance_posture") == "SUSPENDED":
        raise_err(ERR_PROPERTY_SUSPENDED,
                  "Property is SUSPENDED; ACC approval refused")
    r["status"] = "APPROVED"
    r["decided_at"] = db.iso_now()
    db.bump(r)
    return success(_serialize(r))


@bp.route("/hoa/acc-requests/<rid>/reject", methods=["POST"])
@auth_required({"ACCMember"})
def reject_acc_request(rid):
    r = fetch_or_404(db.acc_requests, rid, "ACCRequest")
    if r["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE,
                  f"ACCRequest must be SUBMITTED to reject "
                  f"(currently {r['status']})")
    r["status"] = "REJECTED"
    r["decided_at"] = db.iso_now()
    db.bump(r)
    return success(_serialize(r))


@bp.route("/hoa/acc-requests/<rid>/request-revision", methods=["POST"])
@auth_required({"ACCMember"})
def request_revision(rid):
    r = fetch_or_404(db.acc_requests, rid, "ACCRequest")
    if r["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE,
                  f"ACCRequest must be SUBMITTED to request revision "
                  f"(currently {r['status']})")
    # business_temporal (priority 8): cap at 3
    if int(r.get("revision_count", 0)) >= 3:
        raise_err(ERR_ACC_REVISION_LIMIT,
                  "ACCRequest has reached the 3-revision limit")
    r["status"] = "REVISION_REQUESTED"
    r["revision_count"] = int(r.get("revision_count", 0)) + 1
    db.bump(r)
    return success(_serialize(r))


@bp.route("/hoa/acc-requests/<rid>/resubmit", methods=["POST"])
@auth_required({"HomeOwner"})
def resubmit_acc_request(rid):
    r = fetch_or_404(db.acc_requests, rid, "ACCRequest")
    if r["status"] != "REVISION_REQUESTED":
        raise_err(ERR_INVALID_STATE,
                  f"ACCRequest must be REVISION_REQUESTED to resubmit "
                  f"(currently {r['status']})")
    prop = fetch_or_404(db.properties, r["property_id"], "Property")
    _require_owner_of_property(prop)
    r["status"] = "SUBMITTED"
    db.bump(r)
    return success(_serialize(r))


@bp.route("/hoa/acc-requests/<rid>/withdraw", methods=["POST"])
@auth_required({"HomeOwner"})
def withdraw_acc_request(rid):
    r = fetch_or_404(db.acc_requests, rid, "ACCRequest")
    if r["status"] not in {"SUBMITTED", "REVISION_REQUESTED"}:
        raise_err(ERR_INVALID_STATE,
                  f"ACCRequest must be SUBMITTED or REVISION_REQUESTED to "
                  f"withdraw (currently {r['status']})")
    prop = fetch_or_404(db.properties, r["property_id"], "Property")
    _require_owner_of_property(prop)
    r["status"] = "WITHDRAWN"
    db.bump(r)
    return success(_serialize(r))
