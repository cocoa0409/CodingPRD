"""Artist endpoints (PRD §3.1)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain
from util import (body, req_str, opt_bool, opt_enum, opt_int, new_resource, touch,
                  pagination_params, paginate, sort_by_created)

bp = Blueprint("artists", __name__)

TIERS = {"STANDARD", "PREMIUM", "PLATINUM"}


@bp.route("/backline/artists", methods=["POST"])
def create_artist():
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    data = body()
    artist = new_resource()
    artist.update({
        "legal_name": req_str(data, "legal_name"),
        "tier": opt_enum(data, "tier", TIERS, default="STANDARD"),
        "deposit_credit_cents": 0,
        "deposit_waived": opt_bool(data, "deposit_waived", default=False),
        "risk_score": 0,
    })
    store.artists[artist["id"]] = artist
    return success_object(domain.serialize(artist), status=201)


@bp.route("/backline/artists/<artist_id>/deposit-topups", methods=["POST"])
def deposit_topup(artist_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager", "TourManager"})
    artist = domain.get_artist(artist_id)
    data = body()
    amount = opt_int(data, "amount_cents", minimum=None)
    if amount is None:
        raise errors.invalid_request("Missing required field: amount_cents")
    artist["deposit_credit_cents"] = artist.get("deposit_credit_cents", 0) + amount
    touch(artist)
    return success_object(domain.serialize(artist), status=200)


@bp.route("/backline/artists/<artist_id>", methods=["GET"])
def fetch_artist(artist_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager", "TourManager", "LogisticsCoordinator"})
    artist = domain.get_artist(artist_id)
    return success_object(domain.serialize(artist), status=200)


@bp.route("/backline/artists", methods=["GET"])
def list_artists():
    auth = get_auth()
    require_roles(auth, {"OpsManager", "TourManager", "LogisticsCoordinator"})
    limit, offset = pagination_params()
    tier = request.args.get("tier")
    items = list(store.artists.values())
    if tier is not None:
        items = [a for a in items if a.get("tier") == tier]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(a) for a in page], meta, status=200)


@bp.route("/backline/artists/<artist_id>", methods=["PATCH"])
def update_artist(artist_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    artist = domain.get_artist(artist_id)
    data = body()
    changed = False
    if "tier" in data:
        artist["tier"] = opt_enum(data, "tier", TIERS, default=None)
        changed = True
    if "deposit_waived" in data:
        artist["deposit_waived"] = opt_bool(data, "deposit_waived", default=None)
        changed = True
    if changed:
        touch(artist)
    return success_object(domain.serialize(artist), status=200)
