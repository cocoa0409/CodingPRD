"""AllowancePolicy endpoints (PRD §3.1).

Half-open effectiveness windows [effective_from, effective_to); same-country
windows must not overlap, adjacency allowed. All policies are ACTIVE in v1.
"""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_POLICY_WINDOW_OVERLAP
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record
from validate import get_body, opt_int, req_date, req_int, req_str

bp = Blueprint("allowance_policies", __name__)


@bp.post("/mobility/allowance-policies")
def create_policy():
    authorized(["MobilityAdmin"])
    body = get_body()
    policy_name = req_str(body, "policy_name")
    host_country_code = req_str(body, "host_country_code")
    effective_from = req_date(body, "effective_from")
    effective_to = req_date(body, "effective_to")
    if effective_to <= effective_from:
        raise_error(ERR_INVALID_REQUEST, "effective_to must be strictly after effective_from")
    per_diem_daily_cents = req_int(body, "per_diem_daily_cents", minimum=0)
    housing_monthly_cap_cents = req_int(body, "housing_monthly_cap_cents", minimum=0)
    cola_pct = opt_int(body, "cola_pct", 0, minimum=0)

    # Date-window rule: half-open overlap against same-country policies.
    for p in db["allowance_policies"].values():
        if p["host_country_code"] != host_country_code:
            continue
        if effective_from.isoformat() < p["effective_to"] and p["effective_from"] < effective_to.isoformat():
            raise_error(
                ERR_POLICY_WINDOW_OVERLAP,
                "policy window overlaps an existing policy for this host country",
            )

    rec = new_record("allowance_policies", {
        "policy_name": policy_name,
        "host_country_code": host_country_code,
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat(),
        "per_diem_daily_cents": per_diem_daily_cents,
        "housing_monthly_cap_cents": housing_monthly_cap_cents,
        "cola_pct": cola_pct,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/allowance-policies/<rid>")
def get_policy(rid):
    return get_one("allowance_policies", rid)


@bp.get("/mobility/allowance-policies")
def list_policies():
    return list_response("allowance_policies", {
        "host_country_code": request.args.get("host_country_code"),
    })
