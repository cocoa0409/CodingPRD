"""Payer policy endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized, ROLE_OPS_ADMIN
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public
from util import ceil_div
from validate import get_body, req_str, req_int, opt_int, req_number, req_bool

bp = Blueprint("payer_policies", __name__, url_prefix="/sleep-therapy")


@bp.post("/payer-policies")
def create_payer_policy():
    authorized([ROLE_OPS_ADMIN])
    body = get_body()

    payer_name = req_str(body, "payer_name")
    plan_code = req_str(body, "plan_code")
    threshold = req_int(body, "compliance_threshold_pct", minimum=1, maximum=100)
    min_hours = req_number(body, "compliance_min_hours_per_night")
    if min_hours <= 0:
        raise_error(ERR_INVALID_REQUEST, "compliance_min_hours_per_night must be > 0")
    window_days = req_int(body, "compliance_window_days", minimum=1)
    # Pinned at intake; client-supplied per the endpoint contract, derived when absent.
    min_nights = opt_int(
        body, "compliance_min_nights", default=None, minimum=0, maximum=window_days
    )
    if min_nights is None:
        min_nights = ceil_div(threshold * window_days, 100)
    rental_months_to_own = req_int(body, "rental_months_to_own", minimum=1)
    mask_cadence = req_int(body, "mask_cadence_days", minimum=0)
    cushion_cadence = req_int(body, "cushion_cadence_days", minimum=0)
    filter_cadence = req_int(body, "filter_cadence_days", minimum=0)
    tubing_cadence = req_int(body, "tubing_cadence_days", minimum=0)
    exchange_window = req_int(body, "mask_exchange_window_days", minimum=0)
    max_exchanges = req_int(body, "max_exchanges_per_window", minimum=1)
    requires_prior_auth = req_bool(body, "requires_prior_auth")

    for existing in db["payer_policies"].values():
        if existing["plan_code"] == plan_code:
            raise_error(ERR_INVALID_REQUEST, f"plan_code must be unique: {plan_code}")

    rec = new_record("payer_policies", {
        "payer_name": payer_name,
        "plan_code": plan_code,
        "compliance_threshold_pct": threshold,
        "compliance_min_hours_per_night": min_hours,
        "compliance_window_days": window_days,
        "compliance_min_nights": min_nights,
        "rental_months_to_own": rental_months_to_own,
        "mask_cadence_days": mask_cadence,
        "cushion_cadence_days": cushion_cadence,
        "filter_cadence_days": filter_cadence,
        "tubing_cadence_days": tubing_cadence,
        "mask_exchange_window_days": exchange_window,
        "max_exchanges_per_window": max_exchanges,
        "requires_prior_auth": requires_prior_auth,
    })
    return success_object(public(rec), status=201)


@bp.get("/payer-policies")
def list_payer_policies():
    return list_response("payer_policies", {})


@bp.get("/payer-policies/<rid>")
def get_payer_policy(rid):
    return get_one("payer_policies", rid)
