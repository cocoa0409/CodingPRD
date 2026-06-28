from flask import Blueprint, request

from db import db, base_fields, now_iso
from middleware import get_auth, require_role
from validators import get_body, req_str, req_enum, req_int, opt_int
from errors import err
from response import success
from pagination import paginate
import serializers as S
import services as svc

bp = Blueprint("attribution", __name__)

ASSET_TYPES = {"TRACKING_LINK", "PROMO_CODE"}
EVENT_TYPES = {"IMPRESSION", "ENGAGEMENT", "SALE"}


@bp.route("/attribution-assets", methods=["POST"])
def create_asset():
    user_id, role = get_auth()
    require_role(role, {"Brand", "PlatformAdmin"})
    body = get_body()
    contract_id = req_str(body, "contract_id", allow_empty=False)
    asset_type = req_enum(body, "asset_type", ASSET_TYPES)
    code_or_slug = req_str(body, "code_or_slug", allow_empty=False)

    contract = svc.get_contract(contract_id)

    # ownership: a Brand must own the contract's campaign (PlatformAdmin exempt)
    if role == "Brand":
        campaign = db.campaigns.get(contract["campaign_id"])
        if not campaign or campaign["brand_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this contract")

    # state: contract must be ACTIVE or FULFILLED
    if contract["status"] not in {"ACTIVE", "FULFILLED"}:
        raise err("ERR_INVALID_STATE", "Attribution assets require an ACTIVE or FULFILLED contract")

    # uniqueness among ENABLED assets (priority 6)
    for a in db.attribution_assets.values():
        if a["status"] == "ENABLED" and a["code_or_slug"] == code_or_slug:
            raise err("ERR_DUPLICATE_VALUE", "code_or_slug already in use by an ENABLED asset")

    rec = base_fields()
    rec.update({
        "contract_id": contract_id,
        "asset_type": asset_type,
        "code_or_slug": code_or_slug,
        "status": "ENABLED",
    })
    db.attribution_assets[rec["id"]] = rec
    return success(S.attribution_asset_view(rec), status=201)


@bp.route("/attribution-assets/<asset_id>", methods=["GET"])
def get_asset(asset_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer"})
    a = svc.get_attribution_asset(asset_id)
    return success(S.attribution_asset_view(a), status=200)


@bp.route("/attribution-assets/<asset_id>/conversions", methods=["POST"])
def ingest_conversion(asset_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    a = svc.get_attribution_asset(asset_id)
    body = get_body()
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    count = req_int(body, "count", minimum=1)
    revenue_cents = opt_int(body, "revenue_cents", default=0, minimum=0)

    # revenue may only be attached to a sale (priority 16)
    if event_type != "SALE" and revenue_cents > 0:
        raise err("ERR_REVENUE_ON_NON_SALE", "revenue_cents must be 0 unless event_type is SALE")

    rec = base_fields(versioned=False)
    rec.update({
        "attribution_asset_id": asset_id,
        "event_type": event_type,
        "count": count,
        "revenue_cents": revenue_cents,
        "occurred_at": now_iso(),
    })
    db.conversion_events[rec["id"]] = rec
    return success(S.conversion_event_view(rec), status=201)


@bp.route("/attribution-assets/<asset_id>/conversions", methods=["GET"])
def list_conversions(asset_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer"})
    svc.get_attribution_asset(asset_id)
    event_type = request.args.get("event_type")
    rows = [e for e in db.conversion_events.values() if e["attribution_asset_id"] == asset_id]
    if event_type is not None:
        rows = [e for e in rows if e["event_type"] == event_type]
    page, meta = paginate(rows)
    return success([S.conversion_event_view(e) for e in page], status=200, pagination=meta)
