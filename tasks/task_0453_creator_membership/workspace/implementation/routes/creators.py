"""Creator endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
import response
from db import db
from middleware import require_auth, require_role
from services import serialize
from services.common import (init_common, get_body, require_string, optional_enum,
                             parse_pagination, paginate)
from services.lookups import get_creator

bp = Blueprint("creators", __name__)

PLATFORM_PLANS = {"STARTER", "PRO", "PREMIUM"}
BILLING_MODES = {"MONTHLY", "PER_CREATION"}
CHARGE_TIMINGS = {"UP_FRONT", "END_OF_MONTH"}


@bp.post("/creators")
def create_creator():
    ctx = require_auth()
    require_role(ctx, {"Creator"})
    body = get_body()
    display_name = require_string(body, "display_name")
    email = require_string(body, "email")
    require_string(body, "payout_account_ref")
    payout_account_ref = body["payout_account_ref"]
    platform_plan = optional_enum(body, "platform_plan", PLATFORM_PLANS, "STARTER")
    billing_mode = optional_enum(body, "billing_mode", BILLING_MODES, "MONTHLY")
    charge_timing = optional_enum(body, "charge_timing", CHARGE_TIMINGS, "UP_FRONT")

    rec = init_common({
        "display_name": display_name,
        "email": email,
        "platform_plan": platform_plan,
        "payout_account_ref": payout_account_ref,
        "billing_mode": billing_mode,
        "charge_timing": charge_timing,
        "pending_payout_cents": 0,
        "status": "ACTIVE",
    })
    db.creators[rec["id"]] = rec
    return response.success(serialize.creator(rec), status=201)


@bp.get("/creators")
def list_creators():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    page, total = paginate(list(db.creators.values()), limit, offset)
    return response.list_success([serialize.creator(r) for r in page], limit, offset, total)


@bp.get("/creators/<creator_id>")
def get_one_creator(creator_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_creator(creator_id)
    return response.success(serialize.creator(rec))
