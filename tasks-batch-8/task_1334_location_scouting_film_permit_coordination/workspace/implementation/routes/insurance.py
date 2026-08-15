"""InsuranceCertificate endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int,
    make_entity, touch, get_production, get_scoped, get_jurisdiction,
    list_filtered, paginate, get_pagination_params, parse_date,
)

bp = Blueprint("insurance", __name__)


@bp.route("/productions/<pid>/insurance-certificates", methods=["POST"])
def create_certificate(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["jurisdiction_id", "insurer_name", "umbrella_limit_cents",
                             "indemnity_clause_ref", "effective_date", "expiry_date"])
    jid = require_str(payload, "jurisdiction_id")
    get_jurisdiction(jid)
    entity = make_entity({
        "production_id": pid,
        "jurisdiction_id": jid,
        "insurer_name": require_str(payload, "insurer_name"),
        "umbrella_limit_cents": require_int(payload, "umbrella_limit_cents"),
        "indemnity_clause_ref": require_str(payload, "indemnity_clause_ref"),
        "effective_date": require_str(payload, "effective_date"),
        "expiry_date": require_str(payload, "expiry_date"),
        "status": "PRESENTED",
    })
    store.insurance_certificates[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/insurance-certificates", methods=["GET"])
def list_certificates(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("jurisdiction_id", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.insurance_certificates, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/insurance-certificates/<rid>/verify", methods=["POST"])
def verify_certificate(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    cert = get_scoped(store.insurance_certificates, rid, pid, "InsuranceCertificate")
    if cert["status"] != "PRESENTED":
        raise ApiError(ERR_INVALID_STATE, "Certificate is not PRESENTED", 409)
    jurisdiction = get_jurisdiction(cert["jurisdiction_id"])
    if cert["umbrella_limit_cents"] < jurisdiction["min_liability_limit_cents"]:
        raise ApiError(ERR_INSURANCE_INSUFFICIENT, "Umbrella limit below jurisdiction minimum", 422)
    if not cert.get("indemnity_clause_ref") or cert["indemnity_clause_ref"].strip() == "":
        raise ApiError(ERR_INDEMNITY_MISSING, "Indemnity clause reference is empty", 422)
    eff = parse_date(cert["effective_date"])
    exp = parse_date(cert["expiry_date"])
    if exp < eff:
        raise ApiError(ERR_INVALID_REQUEST, "expiry_date must be >= effective_date", 400)
    cert["status"] = "VERIFIED"
    touch(cert)
    return success_object(cert)


@bp.route("/productions/<pid>/insurance-certificates/<rid>/reject", methods=["POST"])
def reject_certificate(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    cert = get_scoped(store.insurance_certificates, rid, pid, "InsuranceCertificate")
    if cert["status"] != "PRESENTED":
        raise ApiError(ERR_INVALID_STATE, "Certificate is not PRESENTED", 409)
    cert["status"] = "REJECTED"
    touch(cert)
    return success_object(cert)
