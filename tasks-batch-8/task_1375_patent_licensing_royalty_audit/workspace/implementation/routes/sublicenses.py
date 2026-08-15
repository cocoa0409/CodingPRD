"""Sublicense grant endpoints."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response

bp = Blueprint("sublicenses", __name__)


@bp.post("/licensing/sublicense-grants")
def create_grant():
    user_id, role = middleware.require_role("Licensee")
    body = common.get_body()
    common.validate_body(body, [
        ("agreement_id", "string", True),
        ("sublicensee_name", "string", True),
        ("territory", "string", True),
    ])
    # Tier 3: body FK existence
    agr = db.agreements.get(body["agreement_id"])
    if agr is None:
        raise errors.err_agreement_not_found()
    # Tier 4: ownership -- licensee may only request grants under own agreements
    if agr["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()
    # Tier 6: licensee standing
    licensee = db.licensees[agr["licensee_id"]]
    if licensee["status"] != "ACTIVE":
        raise errors.err_licensee_not_active()
    # Tier 7: agreement standing
    if agr["status"] != "ACTIVE":
        raise errors.err_agreement_not_active()
    # Tier 10: sublicensing permission
    if not agr["sublicense_allowed"]:
        raise errors.err_sublicensing_not_granted()

    g = common.new_resource({
        "agreement_id": body["agreement_id"],
        "sublicensee_name": body["sublicensee_name"],
        "territory": body["territory"],
        "status": "PENDING",
        "decided_by_user_id": None,
    })
    db.sublicense_grants[g["id"]] = g
    return response.success_object(g, 201)


@bp.get("/licensing/sublicense-grants")
def list_grants():
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "Licensee")
    args = common.request.args
    agreement_id = args.get("agreement_id")
    status = args.get("status")
    items = list(db.sublicense_grants.values())
    if role == "Licensee":
        items = [g for g in items
                 if db.agreements[g["agreement_id"]]["licensee_id"] == user_id]
    if agreement_id is not None:
        items = [g for g in items if g["agreement_id"] == agreement_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/sublicense-grants/<gid>")
def get_grant(gid):
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "Licensee")
    g = db.sublicense_grants.get(gid)
    if g is None:
        raise errors.err_sublicense_not_found()
    if role == "Licensee" and \
            db.agreements[g["agreement_id"]]["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()
    return response.success_object(g)


@bp.post("/licensing/sublicense-grants/<gid>/decision")
def decide_grant(gid):
    user_id, _ = middleware.require_role("LicensingAnalyst")
    g = db.sublicense_grants.get(gid)
    if g is None:
        raise errors.err_sublicense_not_found()
    body = common.get_body()
    common.validate_body(body, [
        ("decision", "enum:APPROVED,REJECTED,REVOKED", True),
    ])
    decision = body["decision"]
    cur = g["status"]
    ok = (
        (decision in ("APPROVED", "REJECTED") and cur == "PENDING")
        or (decision == "REVOKED" and cur == "APPROVED")
    )
    if not ok:
        raise errors.err_sublicense_invalid_state(
            f"Decision {decision} not permitted from status {cur}")
    g["status"] = decision
    g["decided_by_user_id"] = user_id
    common.touch(g)
    return response.success_object(g)
