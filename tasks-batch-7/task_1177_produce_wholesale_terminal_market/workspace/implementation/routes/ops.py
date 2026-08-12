"""LaborTicket routes, logical-clock endpoint, and the day-close ops run."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint

from db import store
from errors import raise_error, ERR_VALIDATION
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    get_json_body,
    require_fields,
    req_date,
    req_enum,
    req_number,
    req_positive_number,
    is_str,
    is_int,
    is_number,
    lookup,
    stamp_new,
    touch,
    paginate,
    sorted_by_created,
    labor_charge_cents,
    recompute_lot_available,
    recompute_customer_credit_exposure,
    clock_now,
    add_days_str,
    TRUST_CLAIM_GRACE_DAYS,
    DATE_FMT,
    Decimal,
    parse_datetime,
)

bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# Labor tickets
# ---------------------------------------------------------------------------

@bp.post("/market/labor-tickets")
def create_labor_ticket():
    require_roles(["Receiver"])
    body = get_json_body()
    require_fields(body, ["purchase_lot_id", "ticket_type", "work_date", "hours"])
    purchase_lot_id = body.get("purchase_lot_id")
    if not is_str(purchase_lot_id):
        raise_error(ERR_VALIDATION, "purchase_lot_id must be a string")
    ticket_type = req_enum(body, "ticket_type", {"HOURLY", "PIECE"})
    work_date = req_date(body, "work_date")
    hours = req_positive_number(body, "hours")

    pieces = None
    hourly_rate = None
    piece_rate = None
    if ticket_type == "HOURLY":
        if "hourly_rate" not in body or body["hourly_rate"] is None:
            raise_error(ERR_VALIDATION, "hourly_rate is required for HOURLY tickets")
        hourly_rate = req_positive_number(body, "hourly_rate")
        if "pieces" in body and body["pieces"] is not None:
            if not is_int(body["pieces"]):
                raise_error(ERR_VALIDATION, "pieces must be an integer")
            pieces = body["pieces"]  # ignored for HOURLY charge
    else:  # PIECE
        if "pieces" not in body or body["pieces"] is None:
            raise_error(ERR_VALIDATION, "pieces is required for PIECE tickets")
        if not is_int(body["pieces"]) or body["pieces"] < 0:
            raise_error(ERR_VALIDATION, "pieces must be a non-negative integer")
        pieces = body["pieces"]
        if "piece_rate" not in body or body["piece_rate"] is None:
            raise_error(ERR_VALIDATION, "piece_rate is required for PIECE tickets")
        piece_rate = req_positive_number(body, "piece_rate")
        if "hourly_rate" in body and body["hourly_rate"] is not None:
            if not is_number(body["hourly_rate"]):
                raise_error(ERR_VALIDATION, "hourly_rate must be a number")
            hourly_rate = Decimal(str(body["hourly_rate"]))

    lot = lookup(store.purchase_lots, purchase_lot_id, "PurchaseLot")

    charge = labor_charge_cents(ticket_type, hours, pieces, hourly_rate, piece_rate)
    ticket = stamp_new(
        {
            "purchase_lot_id": purchase_lot_id,
            "ticket_type": ticket_type,
            "work_date": work_date.strftime(DATE_FMT),
            "hours": float(hours),
            "pieces": pieces,
            "hourly_rate": float(hourly_rate) if hourly_rate is not None else None,
            "piece_rate": float(piece_rate) if piece_rate is not None else None,
            "charge_cents": charge,
        }
    )
    store.labor_tickets[ticket["id"]] = ticket
    return success_object(ticket, 201)


@bp.get("/market/purchase-lots/<lot_id>/labor-tickets")
def list_lot_labor_tickets(lot_id):
    require_roles(ALL_ROLES)
    lookup(store.purchase_lots, lot_id, "PurchaseLot")
    items = [
        t for t in store.labor_tickets.values() if t["purchase_lot_id"] == lot_id
    ]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(["MarketAdmin"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    target = parse_datetime(body.get("to_iso8601"), "to_iso8601")
    store.clock = target
    return success_object({"current_utc": _fmt(store.clock)}, 200)


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Day-close ops run
# ---------------------------------------------------------------------------

@bp.post("/market/ops/run-day-close")
def run_day_close():
    require_roles(["MarketAdmin"])
    clock = clock_now()
    clock_date = clock.date()

    invoices_marked_past_due = 0
    invoices_trust_claimed = 0
    bookings_expired = 0

    # Sweep 1: OPEN -> PAST_DUE when clock date strictly > due_date and
    # balance still positive. Boundary: on due_date exactly, remains OPEN.
    for inv in sorted_by_created(list(store.invoices.values())):
        if inv["status"] != "OPEN" or inv["balance_cents"] <= 0:
            continue
        due = datetime.strptime(inv["due_date"], DATE_FMT).date()
        if clock_date > due:
            inv["status"] = "PAST_DUE"
            touch(inv)
            invoices_marked_past_due += 1

    # Sweep 2: PAST_DUE -> TRUST_CLAIMED when clock date > due_date + 30 days
    # and balance still positive. Cascade: suspend customer, CREDIT-hold
    # their CONFIRMED orders, release those orders' reservations.
    for inv in sorted_by_created(list(store.invoices.values())):
        if inv["status"] != "PAST_DUE" or inv["balance_cents"] <= 0:
            continue
        due = datetime.strptime(inv["due_date"], DATE_FMT).date()
        if clock_date > due + timedelta(days=TRUST_CLAIM_GRACE_DAYS):
            inv["status"] = "TRUST_CLAIMED"
            touch(inv)
            invoices_trust_claimed += 1
            customer = store.customers.get(inv["customer_id"])
            if customer is not None:
                customer["status"] = "SUSPENDED"
                touch(customer)
                for order in list(store.sales_orders.values()):
                    if (
                        order["customer_id"] == customer["id"]
                        and order["status"] == "CONFIRMED"
                    ):
                        for line in order["lines"]:
                            lot = store.purchase_lots.get(line["lot_id"])
                            if lot is not None:
                                lot["reserved_units"] = max(
                                    0, lot["reserved_units"] - line["quantity"]
                                )
                                recompute_lot_available(lot)
                                touch(lot)
                        order["status"] = "ON_HOLD"
                        order["hold_reason"] = "CREDIT"
                        touch(order)
                recompute_customer_credit_exposure(customer["id"])

    # Sweep 3: stale SCHEDULED bookings whose end_time passed -> EXPIRED.
    for booking in sorted_by_created(list(store.ripening_bookings.values())):
        if booking["status"] != "SCHEDULED":
            continue
        end_time = parse_datetime(booking["end_time"], "end_time")
        if end_time < clock:
            booking["status"] = "EXPIRED"
            touch(booking)
            bookings_expired += 1

    return success_object(
        {
            "invoices_marked_past_due": invoices_marked_past_due,
            "invoices_trust_claimed": invoices_trust_claimed,
            "bookings_expired": bookings_expired,
        },
        200,
    )
