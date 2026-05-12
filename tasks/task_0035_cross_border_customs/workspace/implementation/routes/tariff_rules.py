"""Tariff rule endpoints."""

from flask import Blueprint

from db import DB, LOCK
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_TARIFF_RULE_OVERLAP,
    not_found,
)
from middleware import require_roles
from response import success_object
from services.calculations import tariff_rules_overlap
from services.common import get_body, stamp_create_minimal
from services.serializers import serialize_tariff_rule


bp = Blueprint("tariff_rules", __name__)


@bp.route("/tariff_rules", methods=["POST"])
@require_roles("CustomsOfficer")
def create_tariff_rule():
    body = get_body()
    hs_code_id = body.get("hs_code_id")
    origin_country = body.get("origin_country")
    destination_country = body.get("destination_country")
    tariff_rate_bps = body.get("tariff_rate_bps")
    effective_from = body.get("effective_from")
    effective_to = body.get("effective_to")

    if not isinstance(hs_code_id, str):
        raise APIError(ERR_INVALID_REQUEST, "hs_code_id required", 400)
    if not isinstance(origin_country, str):
        raise APIError(ERR_INVALID_REQUEST, "origin_country required", 400)
    if not isinstance(destination_country, str):
        raise APIError(ERR_INVALID_REQUEST, "destination_country required", 400)
    if not isinstance(tariff_rate_bps, int) or isinstance(tariff_rate_bps, bool):
        raise APIError(ERR_INVALID_REQUEST, "tariff_rate_bps must be integer", 400)
    if not isinstance(effective_from, str):
        raise APIError(ERR_INVALID_REQUEST, "effective_from required", 400)
    if effective_to is not None and not isinstance(effective_to, str):
        raise APIError(ERR_INVALID_REQUEST, "effective_to must be ISO 8601 string", 400)

    with LOCK:
        if hs_code_id not in DB.hs_codes:
            raise not_found("HsCode not found")

        # Overlap check on same triple
        for tr in DB.tariff_rules.values():
            if (tr["hs_code_id"] == hs_code_id
                    and tr["origin_country"] == origin_country
                    and tr["destination_country"] == destination_country):
                if tariff_rules_overlap(effective_from, effective_to,
                                        tr["effective_from"], tr.get("effective_to")):
                    raise APIError(ERR_TARIFF_RULE_OVERLAP,
                                   "Effective interval overlaps an existing rule",
                                   409)

        tr = {
            "hs_code_id": hs_code_id,
            "origin_country": origin_country,
            "destination_country": destination_country,
            "tariff_rate_bps": int(tariff_rate_bps),
            "effective_from": effective_from,
            "effective_to": effective_to,
        }
        stamp_create_minimal(tr)
        DB.tariff_rules[tr["id"]] = tr
        return success_object(serialize_tariff_rule(tr), status=201)
