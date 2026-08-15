"""CustomerClass endpoints (PRD 3.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_CASE_STATE,
    ERR_CLASS_CODE_NOT_UNIQUE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.calculations import annual_revenue, class_cost_allocation
from services.core import new_record, public, touch
from validate import (
    get_body,
    no_unknown_fields,
    req_int,
    req_str,
    req_tiers,
    require_fk,
)

bp = Blueprint("customer_classes", __name__)


@bp.post("/customer-classes")
def create_class():
    body = get_body()
    no_unknown_fields(body, {
        "rate_case_id", "class_code", "customer_count", "monthly_kwh_per_customer",
        "annual_kwh", "coincident_peak_kw", "average_demand_kw",
        "present_customer_charge_cents", "present_tiers",
    })
    rate_case_id = req_str(body, "rate_case_id")
    class_code = req_str(body, "class_code")
    customer_count = req_int(body, "customer_count", positive=True)
    monthly_kwh = req_int(body, "monthly_kwh_per_customer", positive=True)
    annual_kwh = req_int(body, "annual_kwh", positive=True)
    cp_kw = req_int(body, "coincident_peak_kw", positive=True)
    avg_demand = req_int(body, "average_demand_kw", positive=True)
    charge = req_int(body, "present_customer_charge_cents", non_negative=True)
    tiers = req_tiers(body, "present_tiers")
    authorized(["UtilityFiler"])
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    if case["status"] not in ("DRAFT", "DEFICIENT"):
        raise_error(ERR_INVALID_CASE_STATE, "classes may be added only while the case is DRAFT or DEFICIENT")
    for other in db["customer_classes"].values():
        if other["rate_case_id"] == rate_case_id and other["class_code"] == class_code:
            raise_error(ERR_CLASS_CODE_NOT_UNIQUE,
                        f"class_code {class_code} already exists within the case")
    rec = new_record("customer_classes", {
        "rate_case_id": rate_case_id,
        "class_code": class_code,
        "customer_count": customer_count,
        "monthly_kwh_per_customer": monthly_kwh,
        "annual_kwh": annual_kwh,
        "coincident_peak_kw": cp_kw,
        "average_demand_kw": avg_demand,
        "present_customer_charge_cents": charge,
        "present_tiers": tiers,
        "present_revenue_cents": annual_revenue(customer_count, monthly_kwh, charge, tiers),
        "allocated_cost_cents": 0,
        "approved_revenue_cents": None,
    })
    # Refresh allocated_cost_cents for every class of the case under the case's
    # allocation method (immediate consistency).
    alloc = class_cost_allocation(case, case["allocation_method"])
    by_id = {l["class_id"]: l["allocated_cost_cents"] for l in alloc["lines"]}
    for c in db["customer_classes"].values():
        if c["rate_case_id"] == rate_case_id and c["id"] in by_id:
            if c["allocated_cost_cents"] != by_id[c["id"]]:
                c["allocated_cost_cents"] = by_id[c["id"]]
                touch(c)
    return success_object(public(rec), status=201)


@bp.get("/customer-classes")
def list_classes():
    filters = {"rate_case_id": query_arg("rate_case_id")}
    return list_response("customer_classes", filters)


@bp.get("/customer-classes/<class_id>")
def get_class(class_id):
    return get_one("customer_classes", class_id)
