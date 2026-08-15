"""Signup attribution endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success_object, paginate

bp = Blueprint("signup_attributions", __name__)


@bp.route("/v1/signup-attributions", methods=["GET"])
def list_attributions():
    require_roles("PlatformAdmin", "SupportAgent")
    items = list(db.signup_attributions.values())
    for f in ["cohort_month", "channel", "content_id", "account_id", "subscription_id"]:
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if str(a.get(f)) == v]
    return paginate(items, request.args)


@bp.route("/v1/signup-attributions/<aid>", methods=["GET"])
def get_attribution(aid):
    require_roles("PlatformAdmin", "SupportAgent")
    a = db.signup_attributions.get(aid)
    if not a:
        raise ApiError("ERR_NOT_FOUND", 404, "attribution not found")
    return success_object(a)
