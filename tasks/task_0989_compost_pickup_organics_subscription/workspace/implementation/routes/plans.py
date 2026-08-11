"""ServicePlan endpoints."""

from flask import Blueprint

import response
from db import new_entity, store
from errors import not_found
from middleware import auth, require_roles
from services import BIN_TYPES, SUBSCRIBER_TYPES, ser_plan
from utils import get_body, require_enum, require_int, require_str

bp = Blueprint("plans", __name__)


@bp.post("/service-plans")
def create_plan():
    _, role = auth()
    require_roles(role, "OperationsManager")
    body = get_body()
    plan = new_entity(common=False)
    plan.update({
        "code": require_str(body, "code"),
        "name": require_str(body, "name"),
        "subscriber_type": require_enum(body, "subscriber_type", SUBSCRIBER_TYPES),
        "bin_type": require_enum(body, "bin_type", BIN_TYPES),
        "included_bins": require_int(body, "included_bins"),
        "weekly_price_cents": require_int(body, "weekly_price_cents"),
        "metered_base_cents": require_int(body, "metered_base_cents"),
        "per_kg_rate_cents": require_int(body, "per_kg_rate_cents"),
        "included_kg_per_week": _kg(body, "included_kg_per_week"),
        "credit_rate_cents_per_kg": require_int(body, "credit_rate_cents_per_kg"),
        "skip_allowance_per_quarter": require_int(body, "skip_allowance_per_quarter"),
    })
    store["service_plans"][plan["id"]] = plan
    return response.ok(ser_plan(plan), code=201)


def _kg(body, field):
    from utils import D, require_num
    require_num(body, field)
    return D(body[field])


@bp.get("/service-plans/<pid>")
def get_plan(pid):
    _, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    plan = store["service_plans"].get(pid)
    if plan is None:
        not_found("Service plan not found")
    return response.ok(ser_plan(plan))
