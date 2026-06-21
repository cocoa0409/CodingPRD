"""POST/GET /applicants and GET /applicants/{id}."""

from flask import Blueprint

from db import db, new_id
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.body import (
    get_json_body,
    require_string,
    optional_enum,
    optional_int,
)
from services.calc import micro_eligible
from services.pagination import parse_pagination, slice_sorted
from services.serialize import applicant_to_wire


bp = Blueprint("applicants", __name__)


ENTITY_SIZES = {"LARGE", "SMALL", "MICRO"}


def _validate_micro_year(year):
    if year is None:
        return None
    if not (2000 <= int(year) <= 2100):
        raise_api("ERR_INVALID_REQUEST", "micro_qualifying_year must be in [2000, 2100]")
    return int(year)


def _validate_income(value):
    if value is None:
        return None
    if int(value) < 0:
        raise_api("ERR_INVALID_REQUEST", "gross_income_prior_year_cents must be non-negative")
    return int(value)


def _validate_prior_apps(value):
    if value is None:
        return 0
    if int(value) < 0:
        raise_api("ERR_INVALID_REQUEST", "prior_applications_filed must be non-negative")
    return int(value)


@bp.route("/applicants", methods=["POST"])
@require_roles("Applicant", "USPTOAdmin")
def create_applicant(**_):
    body = get_json_body()
    legal_name = require_string(body, "legal_name", min_len=2, max_len=200)
    entity_size = optional_enum(body, "entity_size", ENTITY_SIZES, default="LARGE")
    micro_year = _validate_micro_year(optional_int(body, "micro_qualifying_year"))
    income = _validate_income(optional_int(body, "gross_income_prior_year_cents"))
    prior_apps = _validate_prior_apps(optional_int(body, "prior_applications_filed"))

    applicant = {
        "id": new_id(),
        "legal_name": legal_name,
        "entity_size": entity_size,
        "micro_qualifying_year": micro_year,
        "gross_income_prior_year_cents": income,
        "prior_applications_filed": prior_apps,
        "created_at": db.current_utc_dt(),
        "updated_at": db.current_utc_dt(),
        "version": 1,
    }

    # MICRO eligibility validation (priority 10, VAL-FEE-MICRO-INCOME)
    if entity_size == "MICRO" and not micro_eligible(applicant):
        raise_api("ERR_MICRO_INELIGIBLE", "MICRO entity eligibility predicate failed")

    db.applicants[applicant["id"]] = applicant
    return success(applicant_to_wire(applicant), http_status=201)


@bp.route("/applicants/<aid>", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin", "USPTOExaminer")
def get_applicant(aid, **_):
    applicant = db.applicants.get(aid)
    if applicant is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", f"Applicant {aid} not found")
    return success(applicant_to_wire(applicant))


@bp.route("/applicants", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin", "USPTOExaminer")
def list_applicants(**_):
    limit, offset = parse_pagination()
    items = list(db.applicants.values())
    page, total = slice_sorted(items, limit, offset)
    return list_success([applicant_to_wire(a) for a in page], limit, offset, total)
