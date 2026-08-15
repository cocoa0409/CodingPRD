"""RegulatoryAsset endpoints (PRD 3.6): deferred assets and the closed-window
incurrence rule."""
from flask import Blueprint

from errors import (
    raise_error,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_DATE_RANGE,
    ERR_DEFERRAL_OVERLAPS_TEST_YEAR,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import new_record, public
from util import parse_datetime, fmt_datetime
from validate import (
    get_body,
    no_unknown_fields,
    req_datetime,
    req_int,
    req_str,
    require_fk,
)

bp = Blueprint("regulatory_assets", __name__)


@bp.post("/regulatory-assets")
def create_asset():
    body = get_body()
    no_unknown_fields(body, {
        "rate_case_id", "asset_name", "principal_cents", "incurrence_start",
        "incurrence_end", "amortization_months",
    })
    rate_case_id = req_str(body, "rate_case_id")
    asset_name = req_str(body, "asset_name")
    principal = req_int(body, "principal_cents", positive=True)
    inc_start = req_datetime(body, "incurrence_start")
    inc_end = req_datetime(body, "incurrence_end")
    months = req_int(body, "amortization_months", positive=True)
    if parse_datetime(inc_end) < parse_datetime(inc_start):
        raise_error(ERR_INVALID_DATE_RANGE, "incurrence_end must be >= incurrence_start")
    authorized(["UtilityFiler"])
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    if case["status"] not in ("DRAFT", "DEFICIENT"):
        raise_error(ERR_INVALID_CASE_STATE,
                    "assets may be registered only while the case is DRAFT or DEFICIENT")
    # Closed-interval intersection with the test year: a single shared day counts
    ty_start = parse_datetime(case["test_year_start"])
    ty_end = parse_datetime(case["test_year_end"])
    if parse_datetime(inc_start) <= ty_end and parse_datetime(inc_end) >= ty_start:
        raise_error(ERR_DEFERRAL_OVERLAPS_TEST_YEAR,
                    "the incurrence window intersects the case test year")
    monthly_base = principal // months
    final_month = principal - monthly_base * (months - 1)
    rec = new_record("regulatory_assets", {
        "rate_case_id": rate_case_id,
        "asset_name": asset_name,
        "principal_cents": principal,
        "incurrence_start": fmt_datetime(parse_datetime(inc_start)),
        "incurrence_end": fmt_datetime(parse_datetime(inc_end)),
        "amortization_months": months,
        "monthly_base_cents": monthly_base,
        "final_month_cents": final_month,
        "amortized_to_date_cents": 0,
        "status": "DEFERRED",
    })
    return success_object(public(rec), status=201)


@bp.get("/regulatory-assets")
def list_assets():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "status": query_arg("status"),
    }
    return list_response("regulatory_assets", filters)


@bp.get("/regulatory-assets/<asset_id>")
def get_asset(asset_id):
    return get_one("regulatory_assets", asset_id)
