"""Distributor acknowledgment routes."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles
from response import success_object
from services import core
from routes.onboarding import _paginate

bp = Blueprint("acks", __name__)


@bp.post("/vfd/feed-mills/<mid>/distributor-acknowledgments")
def create_ack(mid):
    require_roles("FeedMillOperator", "Inspector")
    mill = core.get_feed_mill(mid)
    body = util.get_json_body()
    distributor_name = util.require_field(body, "distributor_name")
    covers_drug_id = util.require_field(body, "covers_drug_id")
    statement_text = util.require_field(body, "statement_text")
    core.get_drug(covers_drug_id)
    ack = util.new_entity({
        "feed_mill_id": mill["id"],
        "distributor_name": distributor_name,
        "acknowledged_at": util.logical_now_iso(),
        "covers_drug_id": covers_drug_id,
        "statement_text": statement_text,
        "status": "ACKNOWLEDGED",
    })
    store.distributor_acknowledgments[ack["id"]] = ack
    return success_object(ack, 201)


@bp.get("/vfd/feed-mills/<mid>/distributor-acknowledgments")
def list_acks_for_mill(mid):
    require_roles("Inspector", "FeedMillOperator")
    core.get_feed_mill(mid)
    items = [a for a in store.distributor_acknowledgments.values() if a.get("feed_mill_id") == mid]
    for param in ("covers_drug_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if a.get(param) == val]
    return _paginate(items)


@bp.get("/vfd/distributor-acknowledgments")
def list_acks():
    require_roles("Inspector", "FeedMillOperator")
    items = list(store.distributor_acknowledgments.values())
    for param in ("covers_drug_id", "feed_mill_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if a.get(param) == val]
    return _paginate(items)


@bp.get("/vfd/distributor-acknowledgments/<aid>")
def get_ack(aid):
    require_roles("Inspector", "FeedMillOperator")
    return success_object(core.get_ack(aid))
