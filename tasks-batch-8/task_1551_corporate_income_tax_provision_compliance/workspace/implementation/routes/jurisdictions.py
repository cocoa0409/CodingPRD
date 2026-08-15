"""Jurisdiction endpoints: create reference data, get one."""
from flask import Blueprint

from db import db, new_record
from errors import raise_error, ERR_DUPLICATE_JURISDICTION_CODE, ERR_INVALID_REQUEST
from middleware import authorized, READER_ROLES
from response import success_object
from routes.common import get_or_404
from serializers import serialize
from services.calc import recompute_open_year_stack_and_etrs
from validate import body_json, req_str, req_int, opt_int, req_enum

bp = Blueprint("jurisdictions", __name__)

LEVELS = ("FEDERAL", "STATE", "FOREIGN")


@bp.route("/tax/jurisdictions", methods=["POST"])
def create_jurisdiction():
    authorized(("TaxManager", "TaxDirector"))
    data = body_json()

    # Priority 7 (uniqueness): code is globally unique.
    code_probe = data.get("code")
    if isinstance(code_probe, str):
        if any(j["code"] == code_probe for j in db.jurisdictions.values()):
            raise_error(ERR_DUPLICATE_JURISDICTION_CODE,
                        f"jurisdiction code '{code_probe}' already exists")

    # Priority 11 (structural): required fields, types, enums, declared ranges.
    code = req_str(data, "code")
    name = req_str(data, "name")
    level = req_enum(data, "level", LEVELS)
    statutory_rate_bp = req_int(data, "statutory_rate_bp")
    apportionment_pct_bp = req_int(data, "apportionment_pct_bp")
    return_due_month = req_int(data, "return_due_month")
    return_due_day = req_int(data, "return_due_day")
    extension_months = opt_int(data, "extension_months", 6)
    if not (0 <= statutory_rate_bp <= 10000):
        raise_error(ERR_INVALID_REQUEST, "statutory_rate_bp must be within 0..10000")
    if not (0 <= apportionment_pct_bp <= 10000):
        raise_error(ERR_INVALID_REQUEST, "apportionment_pct_bp must be within 0..10000")
    if not (1 <= return_due_month <= 12):
        raise_error(ERR_INVALID_REQUEST, "return_due_month must be within 1..12")
    if not (1 <= return_due_day <= 31):
        raise_error(ERR_INVALID_REQUEST, "return_due_day must be within 1..31")

    jur = new_record({
        "code": code,
        "name": name,
        "level": level,
        "statutory_rate_bp": statutory_rate_bp,
        "apportionment_pct_bp": apportionment_pct_bp,
        "return_due_month": return_due_month,
        "return_due_day": return_due_day,
        "extension_months": extension_months,
    })
    db.jurisdictions[jur["id"]] = jur

    # Jurisdiction creation is a declared current_tax_stack trigger; refresh
    # every OPEN year (a brand-new jurisdiction has no filings, so this is a
    # no-op in practice, but the maintenance rule is honored literally).
    for year in db.tax_years.values():
        if year["status"] == "OPEN":
            recompute_open_year_stack_and_etrs(year)

    return success_object(serialize(jur), status=201)


@bp.route("/tax/jurisdictions/<jurisdictionId>", methods=["GET"])
def get_jurisdiction(jurisdictionId):
    authorized(READER_ROLES)
    return success_object(serialize(get_or_404(db.jurisdictions, jurisdictionId, "Jurisdiction")))
