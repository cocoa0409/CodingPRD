"""Contractor endpoints."""

from flask import Blueprint, request
from db import store, new_id
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import stamp_new, touch, get_contractor_or_404

bp = Blueprint("contractors", __name__)

ENTITY_TYPES = {"INDIVIDUAL", "SOLE_PROPRIETOR", "LLC", "S_CORP", "PARTNERSHIP"}


@bp.route("/api/contractors", methods=["POST"])
def create_contractor():
    require_auth(["EngagementManager"])
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    entity_type = body.get("entity_type")
    ein = body.get("ein")
    insurance = body.get("insurance_coverage_cents")
    if not legal_name or not isinstance(legal_name, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "legal_name is required")
    if entity_type not in ENTITY_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid entity_type")
    if not ein or not isinstance(ein, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "ein is required")
    if insurance is None or not isinstance(insurance, int) or isinstance(insurance, bool) or insurance < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "insurance_coverage_cents must be an integer >= 0")
    for c in store.contractors.values():
        if c["ein"] == ein:
            raise ApiError(ERR_INVALID_REQUEST, 400, "ein must be unique")
    contractor = {
        "id": new_id(),
        "legal_name": legal_name,
        "entity_type": entity_type,
        "ein": ein,
        "insurance_coverage_cents": insurance,
        "verification_status": "UNVERIFIED",
        "standing_status": "GOOD_STANDING",
        "lifetime_reported_cents": 0,
    }
    stamp_new(contractor)
    store.contractors[contractor["id"]] = contractor
    return success(contractor, status=201)


@bp.route("/api/contractors", methods=["GET"])
def list_contractors():
    require_auth(ALL_ROLES)
    items = list(store.contractors.values())
    standing = request.args.get("standing_status")
    verification = request.args.get("verification_status")
    if standing:
        items = [c for c in items if c["standing_status"] == standing]
    if verification:
        items = [c for c in items if c["verification_status"] == verification]
    items.sort(key=lambda c: c["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/contractors/<cid>", methods=["GET"])
def get_contractor(cid):
    require_auth(ALL_ROLES)
    return success(get_contractor_or_404(cid))


@bp.route("/api/contractors/<cid>/verify", methods=["POST"])
def verify_contractor(cid):
    require_auth(["ComplianceOfficer"])
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("VERIFIED", "FAILED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "outcome must be VERIFIED or FAILED")
    contractor = get_contractor_or_404(cid)
    vs = contractor["verification_status"]
    if outcome == "VERIFIED":
        if vs in ("UNVERIFIED", "VERIFICATION_FAILED"):
            contractor["verification_status"] = "VERIFIED"
        elif vs == "VERIFIED":
            pass
    else:  # FAILED
        if vs == "UNVERIFIED":
            contractor["verification_status"] = "VERIFICATION_FAILED"
        elif vs == "VERIFIED":
            raise ApiError(ERR_INVALID_STATE, 409, "Cannot fail a verified contractor")
    touch(contractor)
    return success(contractor)
