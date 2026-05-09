from decimal import Decimal
from flask import Blueprint, request
from auth import require_role
from db import db, make_common_fields
from envelope import created
from errors import APIError, ERR_INVALID_INPUT
from validation import need_body, require_enum, require_int, require_decimal
from serializers import serialize_pricing_plan
from common import to_money

bp = Blueprint("pricing_plans", __name__)

VALID_CITIES = {"BJ", "SH"}


@bp.post("/pricing-plans")
def create_pricing_plan():
    require_role({"Admin"})
    body = need_body(request.get_json(silent=True))

    city_code = require_enum(body, "city_code", VALID_CITIES)
    hourly_rate = to_money(require_decimal(body, "hourly_rate", strictly_positive=True))
    daily_cap = to_money(require_decimal(body, "daily_cap", strictly_positive=True))
    free_minutes = require_int(body, "free_minutes", min_value=0)
    cross_city_surcharge = to_money(require_decimal(body, "cross_city_surcharge", min_value=Decimal("0")))

    if daily_cap <= hourly_rate:
        raise APIError(ERR_INVALID_INPUT, 400, "daily_cap must be > hourly_rate")

    cf = make_common_fields()
    plan = {
        **cf,
        "city_code": city_code,
        "hourly_rate": hourly_rate,
        "daily_cap": daily_cap,
        "free_minutes": free_minutes,
        "cross_city_surcharge": cross_city_surcharge,
    }
    db.pricing_plans[plan["id"]] = plan
    return created(serialize_pricing_plan(plan))
