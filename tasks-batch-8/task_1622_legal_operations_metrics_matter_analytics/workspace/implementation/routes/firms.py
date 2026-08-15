from flask import Blueprint, request

from db import store, new_entity, touch
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from middleware import require_roles
from response import object_response
from serializers import firm_view
from validation import Payload, require_exists, list_page

bp = Blueprint("firms", __name__, url_prefix="/legal-ops/firms")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")
TIERS = ("TIER_1", "TIER_2", "TIER_3")


@bp.post("")
@require_roles("LegalOpsManager")
def create_firm(user_id, role):
    p = Payload()
    name = p.req_str("name")
    tier = p.req_enum("tier", TIERS)
    rate = p.req_int("blended_hourly_rate_cents")
    if name is not None:
        for f in store.firms.values():
            if f["name"] == name:
                raise ApiError(ERR_DUPLICATE, 409, "Firm name already exists")
    p.finish()
    if rate < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "blended_hourly_rate_cents must be >= 0")
    firm = new_entity({
        "name": name,
        "tier": tier,
        "blended_hourly_rate_cents": rate,
        "status": "ACTIVE",
    })
    store.firms[firm["id"]] = firm
    return object_response(firm_view(firm), 201)


@bp.get("")
@require_roles(*ALL)
def list_firms(user_id, role):
    items = list(store.firms.values())
    tier = request.args.get("tier")
    if tier is not None:
        items = [f for f in items if f["tier"] == tier]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return list_page(items, firm_view)


@bp.get("/<firm_id>")
@require_roles(*ALL)
def get_firm(user_id, role, firm_id):
    return object_response(firm_view(require_exists(store.firms, firm_id, "firm")))


@bp.post("/<firm_id>/suspend")
@require_roles("LegalOpsManager")
def suspend_firm(user_id, role, firm_id):
    firm = require_exists(store.firms, firm_id, "firm")
    if firm["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Firm is not ACTIVE")
    firm["status"] = "SUSPENDED"
    touch(firm)
    return object_response(firm_view(firm))
