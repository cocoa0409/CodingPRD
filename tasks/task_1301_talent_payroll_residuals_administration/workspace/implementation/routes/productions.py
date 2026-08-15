"""Production endpoints."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_PRODUCTION_HAS_OPEN_ENGAGEMENTS
from helpers import (
    new_id, now_timestamp, parse_date, require_enum, require_field,
    require_string, err_validation,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("productions", __name__)

PRODUCTION_TYPES = {"FILM", "TV_SERIES", "COMMERCIAL", "NEW_MEDIA"}
NEXT_STATUS = {
    "PRE_PRODUCTION": "SHOOTING",
    "SHOOTING": "WRAPPED",
    "WRAPPED": "ARCHIVED",
}


def _validate_jurisdictions(value):
    if not isinstance(value, list):
        raise err_validation("Field 'jurisdictions' must be an array")
    seen = set()
    for element in value:
        if not isinstance(element, dict):
            raise err_validation("Each jurisdiction must be an object")
        code = element.get("jurisdiction_code")
        if not isinstance(code, str) or code == "":
            raise err_validation("Each jurisdiction requires a non-empty 'jurisdiction_code'")
        if code in seen:
            raise err_validation(f"Duplicate jurisdiction_code '{code}'")
        seen.add(code)
        tax_pct = element.get("tax_pct")
        if isinstance(tax_pct, bool) or not isinstance(tax_pct, (int, float)) or tax_pct < 0:
            raise err_validation("Jurisdiction 'tax_pct' must be a number >= 0")
        parse_date(element.get("valid_from"), "valid_from")
        parse_date(element.get("valid_to"), "valid_to")
    return value


@bp.post("/payroll/productions")
def create_production():
    require_roles({"PayrollAdmin"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    title = require_string(body, "title")
    production_company = require_string(body, "production_company")
    union_agreement_id = require_string(body, "union_agreement_id")
    production_type = require_enum(body, "production_type", PRODUCTION_TYPES)
    jurisdictions = _validate_jurisdictions(require_field(body, "jurisdictions"))

    # FK existence (priority 3)
    get_or_404(db.union_agreements, union_agreement_id, "UnionAgreement")

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "title": title,
        "production_company": production_company,
        "union_agreement_id": union_agreement_id,
        "production_type": production_type,
        "jurisdictions": jurisdictions,
        "status": "PRE_PRODUCTION",
    }
    db.productions[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/productions")
def list_productions():
    require_roles(ALL_ROLES)
    items = list(db.productions.values())
    union_agreement_id = request.args.get("union_agreement_id")
    if union_agreement_id is not None:
        items = [p for p in items if p["union_agreement_id"] == union_agreement_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response([serialize(p) for p in items], request.args)


@bp.get("/payroll/productions/<production_id>")
def get_production(production_id):
    require_roles(ALL_ROLES)
    production = get_or_404(db.productions, production_id, "Production")
    return success_object(serialize(production), 200)


@bp.post("/payroll/productions/<production_id>/advance")
def advance_production(production_id):
    require_roles({"PayrollAdmin"})
    production = get_or_404(db.productions, production_id, "Production")

    current = production["status"]
    if current == "ARCHIVED":
        # Already terminal; advancing further is a generic validation failure.
        raise err_validation("Production is already ARCHIVED")

    target = NEXT_STATUS[current]
    if current == "SHOOTING" and target == "WRAPPED":
        # Gate: blocked while any engagement is PENDING_APPROVAL or AMENDMENT_PENDING.
        for engagement in db.engagements.values():
            if engagement["production_id"] != production_id:
                continue
            if engagement["status"] in {"PENDING_APPROVAL", "AMENDMENT_PENDING"}:
                raise ApiError(
                    ERR_PRODUCTION_HAS_OPEN_ENGAGEMENTS,
                    "Advance SHOOTING -> WRAPPED is blocked while engagements remain "
                    "PENDING_APPROVAL or AMENDMENT_PENDING",
                    409,
                )
        # Cascade: every ACTIVE or AMENDMENT_PENDING engagement -> WRAPPED.
        for engagement in db.engagements.values():
            if engagement["production_id"] != production_id:
                continue
            if engagement["status"] in {"ACTIVE", "AMENDMENT_PENDING"}:
                engagement["status"] = "WRAPPED"
                bump_version(engagement)

    production["status"] = target
    bump_version(production)
    return success_object(serialize(production), 200)
