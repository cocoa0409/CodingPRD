"""FundingCurve endpoints."""

from flask import Blueprint

from db import STORE
from errors import bad_request
from middleware import get_body, paginate, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from utils import req_date, req_list, stamp_new

bp = Blueprint("funding", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@bp.post("/funding-curves")
@require_roles("TreasuryOfficer")
def create_curve():
    data = get_body()
    curve_date = req_date(data, "curve_date")
    points = req_list(data, "points", allow_empty=False)
    prev_tenor = None
    has_zero = False
    for p in points:
        if not isinstance(p, dict):
            raise bad_request("each point must be an object")
        if "tenor_months" not in p or "cost_bp" not in p:
            raise bad_request("each point requires tenor_months and cost_bp")
        if not _is_int(p["tenor_months"]) or not _is_int(p["cost_bp"]):
            raise bad_request("tenor_months and cost_bp must be integers")
        if p["tenor_months"] < 0 or p["cost_bp"] < 0:
            raise bad_request("tenor_months and cost_bp must be >= 0")
        if prev_tenor is not None and p["tenor_months"] <= prev_tenor:
            raise bad_request("points must ascend by tenor_months")
        prev_tenor = p["tenor_months"]
        if p["tenor_months"] == 0:
            has_zero = True
    if not has_zero:
        raise bad_request("points must include a tenor_months of 0")
    row = {"curve_date": curve_date, "points": points}
    stamp_new(row)
    STORE["curves"][row["id"]] = row
    return ok_object(serialize("curves", row), 201)


@bp.get("/funding-curves")
@require_roles("TreasuryOfficer", "PricingAnalyst", "PricingCommittee")
def list_curves():
    rows = list(STORE["curves"].values())
    return paginate(serialize_many("curves", rows))
