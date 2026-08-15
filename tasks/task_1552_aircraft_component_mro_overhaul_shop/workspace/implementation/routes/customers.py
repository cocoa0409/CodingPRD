from flask import Blueprint

from db import store
from errors import ApiError
from helpers import base_fields, get_customer_or_404, list_response, pub_customer
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("customers", __name__, url_prefix="/mro")

CUSTOMER_SPEC = {
    "name": ("str", True),
    "certificate_number": ("str", True),
    "contract_tat_hours": ("int", True),
    "tat_penalty_rate_cents_per_hour": ("int", True),
    "tat_penalty_cap_pct": ("int", True, None, 0, 100),
    "credit_limit_cents": ("int", True),
    "penalty_delay_rule": ("enum", False, ["ADJUSTED", "CALENDAR"]),
}


@bp.route("/customers", methods=["POST"])
@require_roles("ShopManager")
def create_customer():
    body = validate_body(get_json_body(), CUSTOMER_SPEC)
    if any(c["certificate_number"] == body["certificate_number"] for c in store.customers.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "certificate_number already exists")
    c = dict(base_fields())
    c.update(
        {
            "name": body["name"],
            "certificate_number": body["certificate_number"],
            "contract_tat_hours": body["contract_tat_hours"],
            "tat_penalty_rate_cents_per_hour": body["tat_penalty_rate_cents_per_hour"],
            "tat_penalty_cap_pct": body["tat_penalty_cap_pct"],
            "credit_limit_cents": body["credit_limit_cents"],
            "penalty_delay_rule": body["penalty_delay_rule"] or "ADJUSTED",
            "current_exposure_cents": 0,
            "status": "ACTIVE",
        }
    )
    store.customers[c["id"]] = c
    return ok(pub_customer(c), 201)


@bp.route("/customers/<customerId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_customer(customerId):
    return ok(pub_customer(get_customer_or_404(customerId)))
