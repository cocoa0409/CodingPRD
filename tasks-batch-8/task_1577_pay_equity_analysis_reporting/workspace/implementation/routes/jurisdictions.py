"""JurisdictionRule endpoints (PRD §3.5)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_DUPLICATE_JURISDICTION
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record
from validate import get_body, req_str, opt_bool, opt_int, opt_num

bp = Blueprint("jurisdictions", __name__)


@bp.post("/jurisdiction-rules")
def create_rule():
    authorized(["PeopleOpsAdmin"])
    body = get_body()
    jurisdiction_code = req_str(body, "jurisdiction_code")
    range_disclosure_required = opt_bool(body, "range_disclosure_required", False)
    max_range_spread_pct = opt_num(body, "max_range_spread_pct", None)
    min_posting_duration_days = opt_int(body, "min_posting_duration_days", 0, minimum=0)
    pay_data_report_required = opt_bool(body, "pay_data_report_required", False)
    filing_due_month = opt_int(body, "filing_due_month", None, minimum=1, maximum=12)
    filing_due_day = opt_int(body, "filing_due_day", None, minimum=1, maximum=31)

    # Priority 7: jurisdiction_code unique
    for r in db["jurisdiction_rules"].values():
        if r["jurisdiction_code"] == jurisdiction_code:
            raise_error(ERR_DUPLICATE_JURISDICTION,
                        f"jurisdiction_code already exists: {jurisdiction_code}")

    rec = new_record("jurisdiction_rules", {
        "jurisdiction_code": jurisdiction_code,
        "range_disclosure_required": range_disclosure_required,
        "max_range_spread_pct": max_range_spread_pct,
        "min_posting_duration_days": min_posting_duration_days,
        "pay_data_report_required": pay_data_report_required,
        "filing_due_month": filing_due_month,
        "filing_due_day": filing_due_day,
    })
    return success_object(public(rec), status=201)


@bp.get("/jurisdiction-rules")
def list_rules():
    return list_response("jurisdiction_rules", {})


@bp.get("/jurisdiction-rules/<rid>")
def get_rule(rid):
    return get_one("jurisdiction_rules", rid)
