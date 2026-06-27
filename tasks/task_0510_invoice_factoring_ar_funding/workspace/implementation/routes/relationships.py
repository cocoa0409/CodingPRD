"""ClientDebtorRelationship endpoints (§3.3)."""

from flask import Blueprint, request

import db
import errors
from common import public, req_str, req_enum, opt_number, stamp_common, touch
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from routes.helpers import get_body, lookup, list_response

bp = Blueprint("relationships", __name__)

RECOURSE_TYPES = {"RECOURSE", "NON_RECOURSE"}


@bp.post("/factoring/relationships")
def create_relationship():
    _, role = authenticate()
    authorize(role, ("FundingOfficer", "UnderwritingOfficer"))
    body = get_body()
    client_id = req_str(body, "client_id")
    debtor_id = req_str(body, "debtor_id")
    # FK existence (priority 4) before structural enum / business uniqueness.
    if client_id not in db.clients:
        raise errors.not_found("client_id does not resolve")
    if debtor_id not in db.debtors:
        raise errors.not_found("debtor_id does not resolve")
    recourse_type = req_enum(body, "recourse_type", RECOURSE_TYPES)
    conc = opt_number(body, "concentration_limit_pct", None)
    if conc is not None and not (0 < conc <= 1):
        raise errors.invalid_request("concentration_limit_pct must be > 0 and <= 1")

    # Uniqueness: only one ACTIVE (client_id, debtor_id) relationship (priority 7).
    for rel in db.relationships.values():
        if (rel["client_id"] == client_id and rel["debtor_id"] == debtor_id
                and rel["status"] == "ACTIVE"):
            raise errors.ApiError(errors.ERR_DUPLICATE_RELATIONSHIP, 409,
                                  "An ACTIVE relationship already exists for this pair")

    rel = {
        "client_id": client_id,
        "debtor_id": debtor_id,
        "recourse_type": recourse_type,
        "concentration_limit_pct": conc,
        "notice_status": "PENDING",
        "status": "ACTIVE",
    }
    stamp_common(rel)
    db.relationships[rel["id"]] = rel
    return success(public(rel), status=201)


@bp.get("/factoring/relationships")
def list_relationships():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    client_id = request.args.get("client_id")
    debtor_id = request.args.get("debtor_id")
    notice_status = request.args.get("notice_status")
    records = []
    for r in db.relationships.values():
        if client_id is not None and r["client_id"] != client_id:
            continue
        if debtor_id is not None and r["debtor_id"] != debtor_id:
            continue
        if notice_status is not None and r["notice_status"] != notice_status:
            continue
        records.append(r)
    return list_response(records)


@bp.get("/factoring/relationships/<relationship_id>")
def read_relationship(relationship_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rel = lookup(db.relationships, relationship_id)
    return success(public(rel), status=200)


@bp.post("/factoring/relationships/<relationship_id>/send-notice")
def send_notice(relationship_id):
    _, role = authenticate()
    authorize(role, ("FundingOfficer",))
    rel = lookup(db.relationships, relationship_id)
    if rel["notice_status"] != "PENDING":
        raise errors.invalid_state("Relationship notice_status is not PENDING")
    client = db.clients.get(rel["client_id"])
    debtor = db.debtors.get(rel["debtor_id"])
    if (client is None or client["status"] != "APPROVED"
            or debtor is None or debtor["status"] != "APPROVED"):
        raise errors.ApiError(errors.ERR_PARTY_NOT_APPROVED, 409,
                              "Both client and debtor must be APPROVED")
    rel["notice_status"] = "NOTICED"
    touch(rel)
    return success(public(rel), status=200)


@bp.post("/factoring/relationships/<relationship_id>/suspend")
def suspend_relationship(relationship_id):
    _, role = authenticate()
    authorize(role, ("FundingOfficer",))
    rel = lookup(db.relationships, relationship_id)
    if rel["notice_status"] != "NOTICED":
        raise errors.invalid_state("Relationship notice_status is not NOTICED")
    rel["notice_status"] = "SUSPENDED"
    touch(rel)
    return success(public(rel), status=200)


@bp.post("/factoring/relationships/<relationship_id>/resume")
def resume_relationship(relationship_id):
    _, role = authenticate()
    authorize(role, ("FundingOfficer",))
    rel = lookup(db.relationships, relationship_id)
    if rel["notice_status"] != "SUSPENDED":
        raise errors.invalid_state("Relationship notice_status is not SUSPENDED")
    debtor = db.debtors.get(rel["debtor_id"])
    if debtor is None or debtor["status"] != "APPROVED":
        raise errors.ApiError(errors.ERR_PARTY_NOT_APPROVED, 409,
                              "Debtor must be APPROVED to resume")
    rel["notice_status"] = "NOTICED"
    touch(rel)
    return success(public(rel), status=200)
