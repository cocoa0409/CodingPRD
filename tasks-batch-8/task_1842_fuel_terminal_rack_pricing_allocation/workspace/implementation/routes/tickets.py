from flask import Blueprint, request

from clock import clock, today_str
from db import db
from errors import (
    ApiError, ERR_ALLOCATION_EXCEEDED, ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_CUSTOMER_ON_CREDIT_HOLD, ERR_INSUFFICIENT_INVENTORY,
    ERR_INVALID_ADDITIVE_PACKAGE, ERR_NO_PUBLISHED_PRICE,
    ERR_REVERSAL_WINDOW_EXPIRED, ERR_TERMINAL_FROZEN,
    ERR_TICKET_NOT_BOL_ISSUED, ERR_TICKET_NOT_RESERVED, not_found,
)
from helpers import (
    get_body, list_query, new_entity, ser_ticket, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import (
    ADDITIVE_RECIPES, REVERSAL_WINDOW, add_bol_event, adjust_exposure,
    compute_additive_cost, compute_tax, compute_unit_price,
    find_published_schedule, latest_posted_event, next_bol_seq, place_hold,
    price_components, published_notice_exists,
)

bp = Blueprint("tickets", __name__)

_ROLES = [
    "PlatformAdmin", "TerminalOperator", "BillingClerk",
    "AllocationManager", "CreditAnalyst",
]


def _get_ticket(ticket_id):
    t = db.lifting_tickets.get(ticket_id)
    if t is None:
        raise not_found("LiftingTicket {} does not exist".format(ticket_id))
    return t


def _ctx(ticket):
    """Resolve the denormalized aggregate context of a ticket."""
    right = db.lifting_rights.get(ticket["lifting_right_id"])
    customer = db.customers.get(ticket["customer_id"])
    terminal = db.terminals.get(ticket["terminal_id"])
    product = db.products.get(ticket["product_id"])
    contract = db.supply_contracts.get(right["contract_id"]) if right else None
    return right, customer, terminal, product, contract


@bp.post("/rack/lifting-tickets")
def create_ticket():
    require_roles(["TerminalOperator"])
    body = get_body()
    right = db.lifting_rights.get(body.get("lifting_right_id"))
    if right is None:
        raise not_found(
            "LiftingRight {} does not exist".format(body.get("lifting_right_id"))
        )
    requested = body.get("requested_gallons")
    try:
        requested = int(requested) if requested is not None else 0
    except (TypeError, ValueError):
        requested = 0
    branded = bool(body.get("branded", False))
    package = body.get("additive_package_code")

    customer = db.customers[right["customer_id"]]
    terminal = db.terminals[right["terminal_id"]]
    product = db.products[right["product_id"]]
    contract = db.supply_contracts[right["contract_id"]]

    # Reservation gates run in order (PRD §3.6):
    # 1) customer credit GOOD, 2) allocation fit, 3) additive validity,
    # 4) credit-limit gate.
    if customer["credit_status"] != "GOOD":
        raise ApiError(
            ERR_CUSTOMER_ON_CREDIT_HOLD, 402,
            "Customer is on credit hold; reservation refused",
        )

    if terminal["rack_status"] == "SHORTAGE" and published_notice_exists(
        terminal["id"], today_str()
    ):
        basis = right["allocated_gallons"]
    else:
        basis = right["daily_ratable_gallons"]
    remaining = basis - right["lifted_today_gallons"] - right["reserved_gallons"]
    if requested > remaining:
        raise ApiError(
            ERR_ALLOCATION_EXCEEDED, 422,
            "Requested gallons exceed the right's remaining entitlement",
        )

    if branded:
        if not product.get("is_brandable"):
            raise ApiError(
                ERR_INVALID_ADDITIVE_PACKAGE, 422,
                "branded=true requires a brandable product",
            )
        if package not in ADDITIVE_RECIPES:
            raise ApiError(
                ERR_INVALID_ADDITIVE_PACKAGE, 422,
                "additive_package_code does not name a known recipe",
            )

    # Provisional pricing against the schedule in effect on the
    # reservation's logical date (discarded if the schedule changes
    # before the BOL posts).
    unit, additive, tax, gross = price_components(
        terminal, product, contract, branded, package, requested, today_str()
    )

    if (
        customer["open_lifting_exposure_cents"] + gross
        > customer["credit_limit_cents"]
    ):
        raise ApiError(
            ERR_CREDIT_LIMIT_EXCEEDED, 402,
            "Reservation would push open exposure over the credit limit",
        )

    t = new_entity({
        "lifting_right_id": right["id"],
        "customer_id": customer["id"],
        "terminal_id": terminal["id"],
        "product_id": product["id"],
        "requested_gallons": requested,
        "branded": branded,
        "additive_package_code": package,
        "unit_price_cents_per_gal": unit,
        "additive_cost_cents": additive,
        "tax_cents": tax,
        "gross_cents": gross,
        "bol_number": None,
        "status": "RESERVED",
        "_posted_at": None,
    })
    db.lifting_tickets[t["id"]] = t

    right["reserved_gallons"] += requested
    touch(right)
    adjust_exposure(customer, gross)
    add_bol_event(t, "RESERVED", {
        "requested_gallons": requested,
        "unit_price_cents_per_gal": unit,
        "additive_cost_cents": additive,
        "tax_cents": tax,
        "gross_cents": gross,
        "provisional": True,
        "inventory_delta_gallons": 0,
    })
    return success_object(ser_ticket(t), 201)


@bp.get("/rack/lifting-tickets/<ticketId>")
def get_ticket(ticketId):
    require_roles(_ROLES)
    return success_object(ser_ticket(_get_ticket(ticketId)))


@bp.get("/rack/lifting-tickets")
def list_tickets():
    require_roles(_ROLES)
    page, total, limit, offset = list_query(
        db.lifting_tickets.values(), request.args,
        ["lifting_right_id", "customer_id", "terminal_id", "product_id", "status"],
    )
    return success_list([ser_ticket(t) for t in page], total, limit, offset)


@bp.post("/rack/lifting-tickets/<ticketId>/post-bol")
def post_bol(ticketId):
    require_roles(["TerminalOperator"])
    t = _get_ticket(ticketId)
    right, customer, terminal, product, contract = _ctx(t)

    # Five checks, in order (PRD §3.6): RESERVED -> not FROZEN ->
    # credit GOOD -> inventory -> published price.
    if t["status"] != "RESERVED":
        raise ApiError(
            ERR_TICKET_NOT_RESERVED, 409,
            "LiftingTicket must be RESERVED to post a BOL",
        )
    if terminal["rack_status"] == "FROZEN":
        raise ApiError(
            ERR_TERMINAL_FROZEN, 409,
            "Terminal is FROZEN; bill-of-lading capture is blocked",
        )
    if customer["credit_status"] != "GOOD":
        raise ApiError(
            ERR_CUSTOMER_ON_CREDIT_HOLD, 402,
            "Customer is on credit hold; posting refused",
        )
    gallons = t["requested_gallons"]
    if terminal["inventory_gallons"] < gallons:
        raise ApiError(
            ERR_INSUFFICIENT_INVENTORY, 422,
            "Terminal inventory is below the requested gallons",
        )
    today = today_str()
    schedule = find_published_schedule(t["terminal_id"], t["product_id"], today)
    if schedule is None:
        raise ApiError(
            ERR_NO_PUBLISHED_PRICE, 422,
            "No PUBLISHED RackPriceSchedule covers this terminal/product/date",
        )

    # Final pricing re-reads the schedule in effect on the posting date;
    # the provisional figure is discarded.
    unit = compute_unit_price(schedule, t["branded"], contract["pricing_tier"])
    additive = compute_additive_cost(
        t["branded"], t.get("additive_package_code"), gallons
    )
    tax = compute_tax(terminal, product, t["branded"], gallons, today)
    gross = gallons * unit + additive + tax
    exposure_delta = gross - t["gross_cents"]

    yyyymmdd = today.replace("-", "")
    seq = next_bol_seq(terminal["id"], yyyymmdd)
    t["bol_number"] = "BOL-{}-{}-{}".format(terminal["terminal_code"], yyyymmdd, seq)
    t["unit_price_cents_per_gal"] = unit
    t["additive_cost_cents"] = additive
    t["tax_cents"] = tax
    t["gross_cents"] = gross
    t["status"] = "BOL_ISSUED"
    t["_posted_at"] = clock.now()
    touch(t)

    if exposure_delta:
        adjust_exposure(customer, exposure_delta)

    terminal["inventory_gallons"] -= gallons
    touch(terminal)

    right["lifted_today_gallons"] += gallons
    right["reserved_gallons"] -= gallons
    touch(right)

    contract["lifted_to_date_gallons"] += gallons
    touch(contract)

    agreements = [
        a for a in db.exchange_agreements.values()
        if a["delivering_terminal_id"] == terminal["id"]
        and a["product_id"] == product["id"]
        and a["status"] == "ACTIVE"
    ]
    for a in agreements:
        a["delivered_this_month_gallons"] += gallons
        touch(a)

    add_bol_event(t, "POSTED", {
        "requested_gallons": gallons,
        "unit_price_cents_per_gal": unit,
        "additive_cost_cents": additive,
        "tax_cents": tax,
        "gross_cents": gross,
        "provisional": False,
        "bol_number": t["bol_number"],
        "inventory_delta_gallons": -gallons,
        "exchange_agreement_ids": [a["id"] for a in agreements],
    })

    # Contagion (PRD §2.9): the load posts regardless; if the final gross
    # leaves exposure over the ceiling the customer flips to HOLD.
    if (
        customer["open_lifting_exposure_cents"] > customer["credit_limit_cents"]
        and customer["credit_status"] == "GOOD"
    ):
        place_hold(customer, "OVER_LIMIT", "OVER_LIMIT")

    return success_object(ser_ticket(t))


@bp.post("/rack/lifting-tickets/<ticketId>/reverse-bol")
def reverse_bol(ticketId):
    require_roles(["TerminalOperator"])
    t = _get_ticket(ticketId)
    if t["status"] != "BOL_ISSUED":
        raise ApiError(
            ERR_TICKET_NOT_BOL_ISSUED, 409,
            "LiftingTicket must be BOL_ISSUED to reverse",
        )
    posted_at = t.get("_posted_at")
    if posted_at is None or clock.now() - posted_at > REVERSAL_WINDOW:
        raise ApiError(
            ERR_REVERSAL_WINDOW_EXPIRED, 422,
            "Reverse-bol invoked more than 24 logical hours after post-bol",
        )

    right, customer, terminal, product, contract = _ctx(t)
    gallons = t["requested_gallons"]

    # Symmetric unwind of the posting; exposure is deliberately untouched
    # (the ticket returns to RESERVED, so its gross stays in the exposure).
    terminal["inventory_gallons"] += gallons
    touch(terminal)

    right["lifted_today_gallons"] -= gallons
    right["reserved_gallons"] += gallons
    touch(right)

    contract["lifted_to_date_gallons"] -= gallons
    touch(contract)

    posted = latest_posted_event(t["id"])
    original_payload = dict(posted["event_payload"]) if posted else {}
    for aid in original_payload.get("exchange_agreement_ids", []):
        a = db.exchange_agreements.get(aid)
        if a is not None:
            a["delivered_this_month_gallons"] -= gallons
            touch(a)

    t["status"] = "RESERVED"
    t["_posted_at"] = None
    touch(t)

    add_bol_event(t, "REVERSED", original_payload)
    return success_object(ser_ticket(t))


@bp.post("/rack/lifting-tickets/<ticketId>/cancel")
def cancel_ticket(ticketId):
    require_roles(["TerminalOperator"])
    t = _get_ticket(ticketId)
    if t["status"] != "RESERVED":
        raise ApiError(
            ERR_TICKET_NOT_RESERVED, 409,
            "LiftingTicket must be RESERVED to cancel",
        )
    right, customer, terminal, product, contract = _ctx(t)

    right["reserved_gallons"] -= t["requested_gallons"]
    touch(right)
    adjust_exposure(customer, -t["gross_cents"])
    t["status"] = "CANCELLED"
    touch(t)
    add_bol_event(t, "CANCELLED", {
        "requested_gallons": t["requested_gallons"],
        "gross_cents": t["gross_cents"],
        "inventory_delta_gallons": 0,
    })
    return success_object(ser_ticket(t))


@bp.post("/rack/lifting-tickets/<ticketId>/invoice")
def invoice_ticket(ticketId):
    require_roles(["BillingClerk"])
    t = _get_ticket(ticketId)
    if t["status"] != "BOL_ISSUED":
        raise ApiError(
            ERR_TICKET_NOT_BOL_ISSUED, 409,
            "LiftingTicket must be BOL_ISSUED to invoice",
        )
    customer = db.customers.get(t["customer_id"])
    t["status"] = "INVOICED"
    touch(t)
    if customer is not None:
        adjust_exposure(customer, -t["gross_cents"])
    return success_object(ser_ticket(t))
