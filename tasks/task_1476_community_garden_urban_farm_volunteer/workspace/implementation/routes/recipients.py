"""Donation recipients (PRD section 3.8)."""
from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err_invalid_request, err_not_found
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import opt_bool, opt_int, pagination_args, req_int, req_str

bp = Blueprint("recipients", __name__)


@bp.post("/api/donation-recipients")
def create_recipient():
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    data = body()
    org = req_str(data, "org_name")
    email = req_str(data, "contact_email")
    capacity = req_int(data, "weekly_capacity_grams")
    tier = req_int(data, "priority_tier")
    accepts_c = opt_bool(data, "accepts_grade_c", True)
    active = opt_bool(data, "active", True)
    if capacity <= 0:
        raise err_invalid_request("weekly_capacity_grams must be > 0")
    if tier < 1 or tier > 5:
        raise err_invalid_request("priority_tier must be in 1..5")
    rec = services.create_record({
        "org_name": org,
        "contact_email": email,
        "weekly_capacity_grams": capacity,
        "priority_tier": tier,
        "accepts_grade_c": accepts_c,
        "active": active,
    })
    db.recipients[rec["id"]] = rec
    return ok(services.recipient_view(rec), status=201)


@bp.get("/api/donation-recipients")
def list_recipients():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(db.recipients.values(), {"active": "active"},
                               request.args, services.recipient_view)
    total = len(items)
    return ok([services.recipient_view(r) for r in items[offset:offset + limit]],
              pagination=(limit, offset, total))


def _get_recipient(recipient_id):
    rec = db.recipients.get(recipient_id)
    if rec is None:
        raise err_not_found("recipient")
    return rec


@bp.get("/api/donation-recipients/<recipientId>")
def get_recipient(recipientId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.recipient_view(_get_recipient(recipientId)))


@bp.patch("/api/donation-recipients/<recipientId>")
def patch_recipient(recipientId):
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    rec = _get_recipient(recipientId)
    data = body()
    if data.get("weekly_capacity_grams") is not None:
        cap = req_int(data, "weekly_capacity_grams")
        if cap <= 0:
            raise err_invalid_request("weekly_capacity_grams must be > 0")
        rec["weekly_capacity_grams"] = cap
    if data.get("priority_tier") is not None:
        tier = req_int(data, "priority_tier")
        if tier < 1 or tier > 5:
            raise err_invalid_request("priority_tier must be in 1..5")
        rec["priority_tier"] = tier
    if data.get("accepts_grade_c") is not None:
        rec["accepts_grade_c"] = opt_bool(data, "accepts_grade_c")
    if data.get("active") is not None:
        rec["active"] = opt_bool(data, "active")
    if data.get("contact_email") is not None:
        rec["contact_email"] = req_str(data, "contact_email")
    services.bump(rec)
    return ok(services.recipient_view(rec))
