"""DeliveryTicket endpoints (§3.7)."""

from flask import Blueprint, request

from db import db
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    stamp_new,
    touch,
    public,
    sort_key,
    get_stop_or_404,
    get_contract_or_404,
    get_ticket_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import (
    compute_net_bushels,
    compute_hauling_add_on_cents,
)

bp = Blueprint("delivery_tickets", __name__)


@bp.route("/harvest/route-stops/<stopId>/delivery-tickets", methods=["POST"])
def create_ticket(stopId):
    require_roles("CrewBoss")
    stop = get_stop_or_404(stopId)
    body = get_json_body()
    require_fields(
        body, ["delivered_at", "gross_bushels", "moisture_pct", "used_our_trucks"]
    )
    delivered_at = require_type(body, "delivered_at", "string")
    gross_bushels = require_type(body, "gross_bushels", "number")
    moisture_pct = require_type(body, "moisture_pct", "number")
    used_our_trucks = require_type(body, "used_our_trucks", "bool")

    net_bushels = compute_net_bushels(gross_bushels, moisture_pct)
    hauling_add_on_cents = compute_hauling_add_on_cents(gross_bushels, used_our_trucks)

    record = stamp_new(
        {
            "route_stop_id": stop["id"],
            "contract_id": stop["contract_id"],
            "delivered_at": delivered_at,
            "gross_bushels": gross_bushels,
            "moisture_pct": moisture_pct,
            "net_bushels": net_bushels,
            "hauling_add_on_cents": hauling_add_on_cents,
            "used_our_trucks": used_our_trucks,
        }
    )
    db.delivery_tickets[record["id"]] = record
    # Posting a ticket increments the parent contract's version by 1 — the
    # serialization point with settlement issuance (§2.4, §3.7).
    contract = get_contract_or_404(stop["contract_id"])
    touch(contract)
    return success_object(public(record), status=201)


@bp.route("/harvest/route-stops/<stopId>/delivery-tickets", methods=["GET"])
def list_tickets_for_stop(stopId):
    require_roles(*ALL_ROLES)
    stop = get_stop_or_404(stopId)
    pagination = parse_pagination(request.args)
    items = [t for t in db.delivery_tickets.values() if t["route_stop_id"] == stop["id"]]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/delivery-tickets", methods=["GET"])
def list_tickets():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    route_stop_id = request.args.get("route_stop_id")
    contract_id = request.args.get("contract_id")
    items = list(db.delivery_tickets.values())
    if route_stop_id is not None:
        items = [t for t in items if t["route_stop_id"] == route_stop_id]
    if contract_id is not None:
        items = [t for t in items if t["contract_id"] == contract_id]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/delivery-tickets/<ticketId>", methods=["GET"])
def get_ticket(ticketId):
    require_roles(*ALL_ROLES)
    ticket = get_ticket_or_404(ticketId)
    return success_object(public(ticket))
