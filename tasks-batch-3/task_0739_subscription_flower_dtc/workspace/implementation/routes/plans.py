"""POST /plans — PlatformAdmin only."""
from flask import Blueprint, request

from common import new_common
from middleware import auth_required
import db
from response import created
from services import validators as v
from services.views import plan_view

bp = Blueprint("plans", __name__)


@bp.route("/plans", methods=["POST"])
@auth_required("PlatformAdmin")
def create_plan():
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    name = v.require_str(body, "name")
    cadence = v.require_enum(body, "cadence", v.CADENCE_ENUM)
    base_fee_cents = v.require_int(body, "base_fee_cents", min_value=0)
    default_style = v.optional_enum(body, "default_style", v.STYLE_ENUM, default="ROUND")
    is_active = v.optional_bool(body, "is_active", default=True)

    plan = {
        **new_common(),
        "name": name,
        "cadence": cadence,
        "base_fee_cents": base_fee_cents,
        "default_style": default_style,
        "is_active": is_active,
    }
    db.plans[plan["id"]] = plan
    return created(plan_view(plan))
