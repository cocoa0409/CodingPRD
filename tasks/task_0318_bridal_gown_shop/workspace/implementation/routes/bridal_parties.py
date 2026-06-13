"""BridalParty endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import common
import errors
import services
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")

bp = Blueprint("bridal_parties", __name__)


@bp.route("/bridal-parties", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def create_party():
    body = common.get_body()
    party_name = common.as_str(body, "party_name")
    event_date = common.parse_datetime_str(body, "event_date")
    lead_gown_order_id = body.get("lead_gown_order_id")
    if lead_gown_order_id is not None:
        services.get_order(lead_gown_order_id)  # FK existence (ERR_ORDER_NOT_FOUND)
    obj = {
        "id": db.new_id(),
        "party_name": party_name,
        "event_date": event_date,
        "lead_gown_order_id": lead_gown_order_id,
        "coordination_status": "FORMING",
        "member_order_count": 0,
    }
    db.stamp_create(obj)
    db.bridal_parties[obj["id"]] = obj
    return success(common.serialize(obj), status=201)


@bp.route("/bridal-parties", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_parties():
    limit, offset = common.paginate(request.args)
    rows = list(db.bridal_parties.values())
    lead = request.args.get("lead_gown_order_id")
    if lead is not None:
        rows = [p for p in rows if p.get("lead_gown_order_id") == lead]
    # member_order_count is recomputed on read (PRD §3.1).
    for p in rows:
        services.recompute_member_order_count(p["id"])
    window, meta = common.page_slice(rows, limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/bridal-parties/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_party(pid):
    obj = services.get_party(pid)
    services.recompute_member_order_count(pid)  # recomputed on fetch (PRD §3.1)
    return success(common.serialize(obj))


@bp.route("/bridal-parties/<pid>", methods=["PATCH"])
@require_roles("BridalConsultant", "ShopManager")
def update_party(pid):
    obj = services.get_party(pid)
    body = common.get_body()
    common.require_fields(body, "lead_gown_order_id")
    lead_gown_order_id = body["lead_gown_order_id"]
    if lead_gown_order_id is not None:
        services.get_order(lead_gown_order_id)  # FK existence
    obj["lead_gown_order_id"] = lead_gown_order_id
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/bridal-parties/<pid>/lock", methods=["POST"])
@require_roles("ShopManager")
def lock_party(pid):
    obj = services.get_party(pid)
    if obj["coordination_status"] != "FORMING":
        errors.raise_error(errors.ERR_PARTY_NOT_FORMING, "Party is not FORMING")
    obj["coordination_status"] = "LOCKED"
    db.touch(obj)
    return success(common.serialize(obj))
