"""Indemnitor + IndemnityAgreement + Collateral endpoints."""
from flask import Blueprint, request

import db
from errors import err
from helpers import paginate, require_enum, require_fields, require_int, require_str
from lookup import (get_bond, get_bond_for_defendant, get_indemnitor,
                    get_indemnity_agreement)
from middleware import (authenticate, get_json_body, parse_pagination,
                        require_role)
from response import array_response, object_response
from services import domain
from views import view, view_list

bp = Blueprint("indemnitors", __name__)

COLLATERAL_KINDS = {"CASH", "PROPERTY_LIEN", "VEHICLE_TITLE"}


@bp.route("/indemnitors", methods=["POST"])
def create_indemnitor():
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    body = get_json_body()
    require_fields(body, ["full_name", "phone_e164", "credit_limit_cents"])
    full_name = require_str(body, "full_name")
    phone = require_str(body, "phone_e164")
    credit_limit = require_int(body, "credit_limit_cents", gt=0)

    rec = db.make_record({
        "full_name": full_name,
        "phone_e164": phone,
        "credit_limit_cents": credit_limit,
        "total_exposure_cents": 0,
    })
    db.indemnitors[rec["id"]] = rec
    return object_response(view(rec), 201)


@bp.route("/indemnitors/<indemnitor_id>", methods=["GET"])
def fetch_indemnitor(indemnitor_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer"})
    i = get_indemnitor(indemnitor_id)
    return object_response(view(i), 200)


@bp.route("/defendants/<defendant_id>/bonds/<bond_id>/indemnity-agreements", methods=["POST"])
def attach_agreement(defendant_id, bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    bond = get_bond_for_defendant(defendant_id, bond_id)
    body = get_json_body()
    require_fields(body, ["indemnitor_id", "liability_share_cents"])
    indemnitor_id = require_str(body, "indemnitor_id")
    liability_share = require_int(body, "liability_share_cents", gt=0)

    # Body FK existence (priority 4) before business rules.
    indemnitor = db.indemnitors.get(indemnitor_id)
    if indemnitor is None:
        raise err("ERR_FK_NOT_FOUND", "indemnitor_id does not reference an existing indemnitor.")

    # Bond must be DRAFT to attach (agreement created PENDING). State check.
    if bond["coverage_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Indemnity agreements can only attach to DRAFT bonds.")

    # Credit-limit: new share + existing BINDING+PENDING exposure must not exceed limit.
    existing = sum(a["liability_share_cents"] for a in domain.agreements_for_indemnitor(indemnitor_id)
                   if a["status"] in ("BINDING", "PENDING"))
    if existing + liability_share > indemnitor["credit_limit_cents"]:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED", "Agreement would exceed indemnitor credit limit.")

    rec = db.make_record({
        "bond_id": bond_id,
        "indemnitor_id": indemnitor_id,
        "liability_share_cents": liability_share,
        "status": "PENDING",
    })
    db.indemnity_agreements[rec["id"]] = rec
    return object_response(view(rec), 201)


@bp.route("/bonds/<bond_id>/indemnity-agreements", methods=["GET"])
def list_bond_agreements(bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer"})
    get_bond(bond_id)
    limit, offset = parse_pagination()
    records = [a for a in db.indemnity_agreements.values() if a["bond_id"] == bond_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/indemnity-agreements/<agreement_id>", methods=["GET"])
def fetch_agreement(agreement_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer"})
    a = get_indemnity_agreement(agreement_id)
    return object_response(view(a), 200)


@bp.route("/indemnity-agreements", methods=["GET"])
def list_agreements():
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer"})
    limit, offset = parse_pagination()
    records = list(db.indemnity_agreements.values())
    indemnitor_id = request.args.get("indemnitor_id")
    if indemnitor_id is not None:
        records = [a for a in records if a["indemnitor_id"] == indemnitor_id]
    bond_id = request.args.get("bond_id")
    if bond_id is not None:
        records = [a for a in records if a["bond_id"] == bond_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


# ---- Collateral ----

@bp.route("/defendants/<defendant_id>/bonds/<bond_id>/collateral", methods=["POST"])
def pledge_collateral(defendant_id, bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    bond = get_bond_for_defendant(defendant_id, bond_id)
    body = get_json_body()
    require_fields(body, ["kind", "pledged_value_cents"])
    kind = require_enum(body, "kind", COLLATERAL_KINDS)
    pledged = require_int(body, "pledged_value_cents", gt=0)

    if bond["coverage_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Collateral can only be pledged to a DRAFT bond.")

    rec = db.make_record({
        "bond_id": bond_id,
        "kind": kind,
        "pledged_value_cents": pledged,
        "status": "HELD",
    })
    db.collateral_items[rec["id"]] = rec
    domain.recompute_collateral_held(bond)
    return object_response(view(rec), 201)


@bp.route("/bonds/<bond_id>/collateral", methods=["GET"])
def list_collateral(bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "ComplianceOfficer"})
    get_bond(bond_id)
    limit, offset = parse_pagination()
    records = [c for c in db.collateral_items.values() if c["bond_id"] == bond_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)
