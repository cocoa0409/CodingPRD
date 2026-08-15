"""Trading partners (PRD §3.1): registration and retrieval."""
from flask import Blueprint

import db
from db import store
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from validation import get_body, req_str, req_enum, req_int, path_entity

bp = Blueprint("partners", __name__)

PARTNER_KINDS = ["CUSTOMER", "SUPPLIER"]


@bp.route("/wholesale/trading-partners", methods=["POST"])
@endpoint(["OrderManager"])
def create_partner():
    body = get_body()
    partner = {
        "id": db.new_id(),
        "partner_name": req_str(body, "partner_name"),
        "partner_kind": req_enum(body, "partner_kind", PARTNER_KINDS),
        "dea_number": req_str(body, "dea_number"),
        "credit_limit_cents": req_int(body, "credit_limit_cents", minimum=0),
        "open_receivable_cents": 0,
        "allocation_watermark_units": 0,
    }
    db.new_common(partner)
    store.trading_partners[partner["id"]] = partner
    return created(partner)


@bp.route("/wholesale/trading-partners", methods=["GET"])
@endpoint(ALL_ROLES)
def list_partners():
    pg = Paginator()
    rows = list(store.trading_partners.values())
    rows = pg.filter(rows, "partner_kind")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/trading-partners/<partnerId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_partner(partnerId):
    partner = path_entity(store.trading_partners, partnerId, "TradingPartner")
    return ok(partner)
