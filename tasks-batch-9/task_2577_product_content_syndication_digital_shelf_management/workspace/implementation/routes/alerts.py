"""Shelf alert triage (PRD 3.10)."""
from flask import Blueprint, g, request

import calc
import envelope
import recompute
import validate
from auth import ALL_ROLES, endpoint
from entities import alert_out, get_alert
from errors import ApiError
from store import db, in_order, now, touch

bp = Blueprint("alerts", __name__)


def _rollup(alert):
    listing = db.listings.get(alert["retailer_listing_id"])
    if listing is None:
        return
    product = db.products.get(listing["product_id"])
    if product is None:
        return
    recompute.recompute_product_alerts(product)
    touch(product)


@bp.route("/shelf-alerts/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_alert(row_id):
    return envelope.ok(alert_out(get_alert(row_id)))


@bp.route("/shelf-alerts", methods=["GET"])
@endpoint(ALL_ROLES)
def list_alerts():
    limit, offset = envelope.page_params()
    rows = in_order(list(db.alerts.values()))
    for arg in ("retailer_listing_id", "source_observation_id", "alert_type", "state"):
        value = request.args.get(arg)
        if value is not None:
            rows = [r for r in rows if r.get(arg) == value]
    return envelope.paged_with(rows, alert_out, limit, offset)


@bp.route("/shelf-alerts/<row_id>/acknowledge", methods=["POST"])
@endpoint(["AccountTeamLead"])
def acknowledge_alert(row_id):
    alert = get_alert(row_id)
    if alert["state"] != "OPEN":
        raise ApiError("ERR_ALERT_ALREADY_RESOLVED")
    alert["state"] = "ACKNOWLEDGED"
    alert["acknowledged_by_user_id"] = g.user_id
    touch(alert)
    # ACKNOWLEDGED still counts as open follow-up: no product rollup here.
    return envelope.ok(alert_out(alert))


@bp.route("/shelf-alerts/<row_id>/resolve", methods=["POST"])
@endpoint(["AccountTeamLead"])
def resolve_alert(row_id):
    data = validate.body()
    note = validate.req_str(data, "resolution_note", 1, 500)
    alert = get_alert(row_id)
    if alert["state"] not in calc.OPEN_ALERT_STATES:
        raise ApiError("ERR_ALERT_ALREADY_RESOLVED")
    alert["state"] = "RESOLVED"
    alert["resolution_note"] = note
    alert["resolved_at"] = now()
    touch(alert)
    _rollup(alert)
    return envelope.ok(alert_out(alert))
