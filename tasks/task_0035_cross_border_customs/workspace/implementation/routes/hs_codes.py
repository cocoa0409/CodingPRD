"""HS code library routes."""

from flask import Blueprint

from db import DB, LOCK
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    not_found,
)
from middleware import require_roles
from response import success_object
from services.common import get_body, stamp_create_minimal, parse_pagination
from services.serializers import serialize_hs_code


bp = Blueprint("hs_codes", __name__)


@bp.route("/hs_codes", methods=["POST"])
@require_roles("CustomsOfficer")
def create_hs_code():
    body = get_body()
    code = body.get("code")
    description = body.get("description")
    keywords = body.get("keywords")
    country_code_map = body.get("country_code_map")
    tariff_rate_bps = body.get("tariff_rate_bps")
    vat_rate_bps = body.get("vat_rate_bps")
    consumption_tax_rate_bps = body.get("consumption_tax_rate_bps", 0)
    postal_tax_rate_bps = body.get("postal_tax_rate_bps")

    # Basic validation
    if not isinstance(code, str) or not code.isdigit() or len(code) != 10:
        raise APIError(ERR_INVALID_REQUEST, "code must be a 10-digit string", 400)
    if not isinstance(description, str) or description.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "description required", 400)
    if not isinstance(keywords, list):
        raise APIError(ERR_INVALID_REQUEST, "keywords must be an array", 400)
    if not isinstance(country_code_map, dict):
        raise APIError(ERR_INVALID_REQUEST, "country_code_map must be an object", 400)
    for fld_name, fld_val in (("tariff_rate_bps", tariff_rate_bps),
                              ("vat_rate_bps", vat_rate_bps),
                              ("postal_tax_rate_bps", postal_tax_rate_bps)):
        if not isinstance(fld_val, int) or isinstance(fld_val, bool):
            raise APIError(ERR_INVALID_REQUEST, f"{fld_name} must be integer", 400)
    if not isinstance(consumption_tax_rate_bps, int) or isinstance(consumption_tax_rate_bps, bool):
        raise APIError(ERR_INVALID_REQUEST, "consumption_tax_rate_bps must be integer", 400)

    with LOCK:
        for hs in DB.hs_codes.values():
            if hs["code"] == code:
                raise APIError(ERR_INVALID_REQUEST, "HsCode.code must be unique", 400)
        hs = {
            "code": code,
            "description": description,
            "keywords": list(keywords),
            "country_code_map": dict(country_code_map),
            "tariff_rate_bps": int(tariff_rate_bps),
            "vat_rate_bps": int(vat_rate_bps),
            "consumption_tax_rate_bps": int(consumption_tax_rate_bps),
            "postal_tax_rate_bps": int(postal_tax_rate_bps),
            "status": "ACTIVE",
        }
        stamp_create_minimal(hs)
        DB.hs_codes[hs["id"]] = hs
        return success_object(serialize_hs_code(hs), status=201)


@bp.route("/hs_codes/<hs_code_id>/deprecate", methods=["POST"])
@require_roles("CustomsOfficer")
def deprecate_hs_code(hs_code_id):
    with LOCK:
        hs = DB.hs_codes.get(hs_code_id)
        if hs is None:
            raise not_found("HsCode not found")
        hs["status"] = "DEPRECATED"
        return success_object(serialize_hs_code(hs), status=200)


@bp.route("/hs_codes/<hs_code_id>", methods=["GET"])
@require_roles("CustomsOfficer", "Declarant", "Auditor")
def get_hs_code(hs_code_id):
    hs = DB.hs_codes.get(hs_code_id)
    if hs is None:
        raise not_found("HsCode not found")
    return success_object(serialize_hs_code(hs), status=200)
