"""Family endpoints (PRD §3.1)."""

from flask import Blueprint, request

import errors
from db import store
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.common import base_record, touch
from services.ledger import recompute_escrow_available
from services.lookup import get_family, sorted_by_created
from services.serialize import family_out

bp = Blueprint("families", __name__)

TIERS = {"BASIC", "STANDARD", "PREMIUM"}


@bp.route("/marketplace/families", methods=["POST"])
def create_family():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    body = get_json()

    display_name = v.req_str(body, "display_name")
    email = v.req_str(body, "email")
    num_children = v.req_int(body, "num_children", minimum=1, maximum=8)
    required_tier = v.opt_enum(body, "required_tier", TIERS, default="BASIC")
    wallet = v.opt_int(body, "wallet_balance_cents", default=0, minimum=0)

    rec = base_record()
    rec.update({
        "display_name": display_name,
        "email": email,
        "num_children": num_children,
        "required_tier": required_tier,
        "wallet_balance_cents": wallet,
        "escrow_reserved_cents": 0,
        "escrow_available_cents": wallet,
        "tax_withheld_ytd_cents": 0,
        "cash_wages_ytd_cents": 0,
        "is_w2_obligated": False,
        "status": "ACTIVE",
    })
    store.families[rec["id"]] = rec
    return ok(family_out(rec), status=201)


@bp.route("/marketplace/families/<fid>", methods=["GET"])
def get_one_family(fid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    f = get_family(fid)
    if auth.is_family and auth.user_id != f["id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only read its own record")
    return ok(family_out(f), status=200)


@bp.route("/marketplace/families", methods=["GET"])
def list_families():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    limit, offset = parse_pagination()
    status = request.args.get("status")

    items = list(store.families.values())
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([family_out(f) for f in page], status=200, pagination=meta)


@bp.route("/marketplace/families/<fid>/deposit", methods=["POST"])
def deposit(fid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    f = get_family(fid)
    if auth.is_family and auth.user_id != f["id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only fund its own wallet")
    body = get_json()
    amount = v.req_int(body, "amount_cents", minimum=1)
    f["wallet_balance_cents"] += amount
    recompute_escrow_available(f)
    touch(f)
    return ok(family_out(f), status=200)
