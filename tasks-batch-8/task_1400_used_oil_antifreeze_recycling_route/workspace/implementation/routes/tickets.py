"""PickupTicket endpoints (PRD §3.4, §3.5, §3.6): metered pickup creation
(idempotent via client_request_id), settlement, dispute, adjustment."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_DUPLICATE_CLIENT_REQUEST,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_PICKUP_TICKET_NOT_FOUND,
    ERR_ROUTE_CAPACITY_EXCEEDED,
    ERR_ROUTE_STOP_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_STOP_NOT_COMPLETED,
    ERR_STOP_NOT_READY_TO_PUMP,
    ERR_TICKET_NOT_DISPUTABLE,
    ERR_TICKET_NOT_DISPUTED,
    ERR_TICKET_NOT_PROVISIONAL,
    ERR_VOLUME_EXCEEDS_TANK_LEVEL,
    ERR_ZERO_VOLUME_PICKUP,
)
from middleware import get_body, opt_int, req_int, req_str, require_roles
from response import success_list, success_object
from services import cascades
from services.calc import market_price_for, settlement_calc

bp = Blueprint("tickets", __name__)

READ_ROLES = ("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator", "Driver")


def get_ticket_or_404(ticket_id):
    ticket = db.get("pickup_tickets", ticket_id)
    if ticket is None:
        raise ApiError(ERR_PICKUP_TICKET_NOT_FOUND, "PickupTicket id not found", 404)
    return ticket


def _post_to_customer(customer, signed_amount):
    """Post a signed net (or delta) according to direction and credit terms."""
    if signed_amount > 0:
        customer["prepaid_balance_cents"] += signed_amount
    elif signed_amount < 0:
        if customer["credit_terms"] == "PREPAY":
            if customer["prepaid_balance_cents"] + signed_amount < 0:
                raise ApiError(
                    "ERR_INSUFFICIENT_PREPAID_BALANCE",
                    "PREPAY customer balance would go negative at settle",
                    402,
                )
            customer["prepaid_balance_cents"] += signed_amount
        else:  # NET30 / CHARGE_ONLY accrue invoiced charges
            customer["outstanding_charge_cents"] += abs(signed_amount)


@bp.post("/route-stops/<routeStopId>/pickup-tickets")
@require_roles("Driver")
def create_pickup_ticket(routeStopId):
    stop = db.get("route_stops", routeStopId)
    if stop is None:
        raise ApiError(ERR_ROUTE_STOP_NOT_FOUND, "RouteStop id not found", 404)
    route = db.get("routes", stop["route_id"])
    if route is not None and route["driver_id"] != request.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Driver may only act on routes assigned to them",
            403,
        )
    body = get_body()
    client_request_id = req_str(body, "client_request_id")
    metered = req_int(body, "metered_volume_gallons")
    if metered < 0:
        raise ApiError("ERR_INVALID_REQUEST", "metered_volume_gallons must be a positive integer", 400)

    # PRD §2.6 pinned check order for the pickup write path.
    if stop["status"] != "READY_TO_PUMP":
        raise ApiError(ERR_STOP_NOT_READY_TO_PUMP, "Pickup requires READY_TO_PUMP", 409)
    tank = db.get("tanks", stop["tank_id"])
    if metered > tank["current_volume_gallons"]:
        raise ApiError(ERR_VOLUME_EXCEEDS_TANK_LEVEL, "metered_volume_gallons > tank.current_volume_gallons", 422)
    if route["loaded_gallons"] + metered > route["vehicle_capacity_gallons"]:
        raise ApiError(ERR_ROUTE_CAPACITY_EXCEEDED, "Pickup would exceed vehicle_capacity_gallons", 422)
    if metered == 0:
        raise ApiError(ERR_ZERO_VOLUME_PICKUP, "metered_volume_gallons == 0; use skip-below-minimum instead", 400)
    site = db.get("tank_sites", stop["tank_site_id"])
    customer = cascades.customer_of_site(site)
    price = market_price_for(
        customer["market_zone"],
        tank["tank_kind"],
        route["scheduled_date"],
        tank.get("_oil_share_pct"),
    )  # raises ERR_PRICE_NOT_PUBLISHED (422)
    for ticket in cascades.tickets_for_stop(stop["id"]):
        if ticket["client_request_id"] == client_request_id:
            raise ApiError(ERR_DUPLICATE_CLIENT_REQUEST, "client_request_id already used for this RouteStop", 409)

    frozen = stop.get("_halogen_count_at_screen")
    if frozen is None:
        frozen = customer["halogen_violation_count"]
    calc = settlement_calc(
        price, metered, frozen, site["density_zone"], site["route_eligibility_override"]
    )

    # Atomic commit: stop completes, tank draws down, route loads up,
    # manifest accrues volume — all in this single request.
    stop["status"] = "COMPLETED"
    db.touch(stop)
    tank["current_volume_gallons"] -= metered
    db.touch(tank)
    route["loaded_gallons"] += metered
    db.touch(route)

    ticket = db.create_entity("pickup_tickets", {
        "route_stop_id": stop["id"],
        "client_request_id": client_request_id,
        "metered_volume_gallons": metered,
        "commodity_price_cents_per_gal": calc["commodity_price_cents_per_gal"],
        "settlement_direction": calc["settlement_direction"],
        "gross_amount_cents": calc["gross_amount_cents"],
        "surcharge_cents": calc["surcharge_cents"],
        "density_fee_cents": calc["density_fee_cents"],
        "net_amount_cents": calc["net_amount_cents"],
        "payment_status": "PROVISIONAL",
        "frozen_halogen_count": frozen,
        "tank_kind": tank["tank_kind"],
        "route_id": route["id"],
        "_was_settled": False,
        "_consumed_by": None,
    })
    # PRD §3.7: the manifest total is recomputed from the route's COMPLETED
    # stops on each stop completion — the ticket created above is part of
    # this completion, so the recompute must observe it.
    manifest = cascades.manifest_for_route(route["id"])
    if manifest is not None:
        cascades.recompute_manifest_totals(manifest)
    return success_object(db.serialize(ticket), 201)


@bp.get("/pickup-tickets/<ticketId>")
@require_roles(*READ_ROLES)
def get_ticket(ticketId):
    return success_object(db.serialize(get_ticket_or_404(ticketId)))


@bp.get("/pickup-tickets")
@require_roles("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator")
def list_tickets():
    items = db.all_entities("pickup_tickets")
    payment_status = request.args.get("payment_status")
    route_stop_id = request.args.get("route_stop_id")
    if payment_status is not None:
        items = [t for t in items if t["payment_status"] == payment_status]
    if route_stop_id is not None:
        items = [t for t in items if t["route_stop_id"] == route_stop_id]
    return success_list([db.serialize(t) for t in db.sorted_created(items)])


@bp.post("/pickup-tickets/<ticketId>/settle")
@require_roles("SettlementClerk")
def settle_ticket(ticketId):
    ticket = get_ticket_or_404(ticketId)
    body = get_body()
    expected_customer_version = req_int(body, "expected_customer_version")
    if ticket["payment_status"] != "PROVISIONAL":
        raise ApiError(ERR_TICKET_NOT_PROVISIONAL, "Settle requires PROVISIONAL", 409)
    stop = db.get("route_stops", ticket["route_stop_id"])
    if stop is None or stop["status"] != "COMPLETED":
        raise ApiError(ERR_STOP_NOT_COMPLETED, "Settle requires RouteStop COMPLETED", 409)
    customer = cascades.customer_of_ticket(ticket)
    # OCC on Customer.version (priority 6).
    if expected_customer_version != customer["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_customer_version does not match the customer's current version",
            412,
        )
    net = ticket["net_amount_cents"]
    if customer["credit_terms"] == "PREPAY" and net < 0:
        if customer["prepaid_balance_cents"] + net < 0:
            raise ApiError(
                "ERR_INSUFFICIENT_PREPAID_BALANCE",
                "PREPAY customer balance would go negative at settle",
                402,
            )
    _post_to_customer(customer, net)
    db.touch(customer)
    ticket["payment_status"] = "SETTLED"
    ticket["_was_settled"] = True
    db.touch(ticket)
    return success_object(db.serialize(ticket))


@bp.post("/pickup-tickets/<ticketId>/dispute")
@require_roles("SettlementClerk")
def dispute_ticket(ticketId):
    ticket = get_ticket_or_404(ticketId)
    if ticket["payment_status"] not in ("PROVISIONAL", "SETTLED"):
        raise ApiError(ERR_TICKET_NOT_DISPUTABLE, "Dispute requires PROVISIONAL or SETTLED", 409)
    # A previously SETTLED ticket keeps its original net posted; the later
    # adjustment posts only the delta.
    ticket["payment_status"] = "DISPUTED"
    db.touch(ticket)
    return success_object(db.serialize(ticket))


@bp.post("/pickup-tickets/<ticketId>/adjust")
@require_roles("SettlementClerk")
def adjust_ticket(ticketId):
    ticket = get_ticket_or_404(ticketId)
    body = get_body()
    corrected_volume = req_int(body, "corrected_metered_volume_gallons", minimum=0)
    override_price = opt_int(body, "override_price_cents_per_gal", None)
    if ticket["payment_status"] != "DISPUTED":
        raise ApiError(ERR_TICKET_NOT_DISPUTED, "Adjust requires DISPUTED", 409)
    stop = db.get("route_stops", ticket["route_stop_id"])
    site = db.get("tank_sites", stop["tank_site_id"]) if stop else None
    price = override_price if override_price is not None else ticket["commodity_price_cents_per_gal"]
    calc = settlement_calc(
        price,
        corrected_volume,
        ticket["frozen_halogen_count"],
        site["density_zone"],
        site["route_eligibility_override"],
    )
    customer = cascades.customer_of_ticket(ticket)
    old_net = ticket["net_amount_cents"]
    new_net = calc["net_amount_cents"]
    delta = new_net - old_net if ticket.get("_was_settled") else new_net
    _post_to_customer(customer, delta)
    db.touch(customer)
    ticket["metered_volume_gallons"] = corrected_volume
    ticket["commodity_price_cents_per_gal"] = calc["commodity_price_cents_per_gal"]
    ticket["gross_amount_cents"] = calc["gross_amount_cents"]
    ticket["surcharge_cents"] = calc["surcharge_cents"]
    ticket["density_fee_cents"] = calc["density_fee_cents"]
    ticket["net_amount_cents"] = calc["net_amount_cents"]
    ticket["settlement_direction"] = calc["settlement_direction"]
    ticket["payment_status"] = "ADJUSTED"
    db.touch(ticket)
    return success_object(db.serialize(ticket))
