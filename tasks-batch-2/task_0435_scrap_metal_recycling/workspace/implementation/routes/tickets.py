"""ScaleTicket + TicketLineItem routes, incl. the theft gate (PRD §3.3-§3.4)."""
from flask import Blueprint

import errors
import response
import serializers
from calc import line_valuation_cents
from db import (db, stamp_create, stamp_create_append_only, touch)
from helpers import (as_number, as_string, get_json_body, parse_pagination,
                     paginate, query_arg, require_fields)
from middleware import authenticate, require_roles
from routes.commodity_prices import find_active_price

bp = Blueprint("tickets", __name__)

READ_ROLES = {"WeighMaster", "PayoutClerk", "ComplianceOfficer",
              "YardManager", "SettlementAccountant"}
TICKET_STATUSES = {"DRAFT", "WEIGHED", "HOLD", "RELEASED", "REPORTED", "PAID"}


def ticket_line_items(ticket_id):
    rows = [li for li in db.line_items.values() if li["ticket_id"] == ticket_id]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    return rows


# --- ScaleTicket CRUD -------------------------------------------------------

@bp.route("/yard/tickets", methods=["POST"])
def create_ticket():
    _uid, role = authenticate()
    require_roles(role, {"WeighMaster"})
    body = get_json_body()
    require_fields(body, ["seller_id", "gross_weight_lb"])
    seller_id = as_string(body["seller_id"], "seller_id")
    gross = as_number(body["gross_weight_lb"], "gross_weight_lb", positive=True)
    # Existence of FK target (priority 3).
    if seller_id not in db.sellers:
        raise errors.not_found("Seller not found.")

    record = {
        "seller_id": seller_id,
        "container_id": None,
        "gross_weight_lb": gross,
        "tare_weight_lb": None,
        "net_weight_lb": None,
        "status": "DRAFT",
        "gross_valuation_cents": 0,
        "theft_hold_released_by": None,
    }
    stamp_create(record)
    db.tickets[record["id"]] = record
    return response.success(serializers.ticket(record), 201)


@bp.route("/yard/tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    authenticate()
    record = db.tickets.get(tid)
    if not record:
        raise errors.not_found("Ticket not found.")
    return response.success(serializers.ticket(record), 200)


@bp.route("/yard/tickets", methods=["GET"])
def list_tickets():
    authenticate()
    limit, offset = parse_pagination()
    seller_id = query_arg("seller_id")
    container_id = query_arg("container_id")
    status = query_arg("status")
    if status is not None and status not in TICKET_STATUSES:
        raise errors.invalid_request("status filter is invalid.")
    rows = list(db.tickets.values())
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if container_id is not None:
        rows = [r for r in rows if r.get("container_id") == container_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.ticket(r) for r in page], limit, offset, total)


# --- TicketLineItem ---------------------------------------------------------

@bp.route("/yard/tickets/<tid>/line-items", methods=["POST"])
def create_line_item(tid):
    _uid, role = authenticate()
    require_roles(role, {"WeighMaster"})
    ticket = db.tickets.get(tid)
    if not ticket:
        raise errors.not_found("Ticket not found.")
    # State gate (priority 4): line items only while DRAFT.
    if ticket["status"] != "DRAFT":
        raise errors.invalid_state("Line items may only be added while ticket is DRAFT.")
    body = get_json_body()
    require_fields(body, ["grade_code", "weight_lb"])
    grade_code = as_string(body["grade_code"], "grade_code")
    weight = as_number(body["weight_lb"], "weight_lb", positive=True)
    # grade must resolve to an ACTIVE CommodityPrice (priority 8).
    price = find_active_price(grade_code)
    if price is None:
        raise errors.grade_not_active("grade_code has no ACTIVE CommodityPrice row.")

    record = {
        "ticket_id": tid,
        "grade_code": grade_code,
        "commodity_price_id": price["id"],
        "weight_lb": weight,
        "line_valuation_cents": line_valuation_cents(
            weight, price["spot_price_cents_per_lb"]),
    }
    stamp_create_append_only(record)
    db.line_items[record["id"]] = record
    return response.success(serializers.line_item(record), 201)


@bp.route("/yard/tickets/<tid>/line-items", methods=["GET"])
def list_ticket_line_items(tid):
    authenticate()
    ticket = db.tickets.get(tid)
    if not ticket:
        raise errors.not_found("Ticket not found.")
    limit, offset = parse_pagination()
    rows = [li for li in db.line_items.values() if li["ticket_id"] == tid]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.line_item(r) for r in page], limit, offset, total)


@bp.route("/yard/line-items/<lid>", methods=["GET"])
def get_line_item(lid):
    authenticate()
    record = db.line_items.get(lid)
    if not record:
        raise errors.not_found("Line item not found.")
    return response.success(serializers.line_item(record), 200)


@bp.route("/yard/line-items", methods=["GET"])
def list_line_items():
    authenticate()
    limit, offset = parse_pagination()
    ticket_id = query_arg("ticket_id")
    commodity_price_id = query_arg("commodity_price_id")
    rows = list(db.line_items.values())
    if ticket_id is not None:
        rows = [r for r in rows if r["ticket_id"] == ticket_id]
    if commodity_price_id is not None:
        rows = [r for r in rows if r["commodity_price_id"] == commodity_price_id]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.line_item(r) for r in page], limit, offset, total)


# --- Weigh-out --------------------------------------------------------------

@bp.route("/yard/tickets/<tid>/weigh-out", methods=["POST"])
def weigh_out(tid):
    _uid, role = authenticate()
    require_roles(role, {"WeighMaster"})
    ticket = db.tickets.get(tid)
    if not ticket:
        raise errors.not_found("Ticket not found.")
    # State gate: only from DRAFT.
    if ticket["status"] != "DRAFT":
        raise errors.invalid_state("weigh-out is only valid from DRAFT.")
    # Must have >= 1 line item (ERR_NO_LINE_ITEMS, 409).
    lines = ticket_line_items(tid)
    if len(lines) == 0:
        raise errors.no_line_items()
    body = get_json_body()
    require_fields(body, ["tare_weight_lb"])
    tare = as_number(body["tare_weight_lb"], "tare_weight_lb")
    # Weight validity (ERR_INVALID_WEIGHT, 422): tare >= 0 and < gross.
    if tare < 0 or not (tare < ticket["gross_weight_lb"]):
        raise errors.invalid_weight()
    # Seller must not be BANNED.
    seller = db.sellers.get(ticket["seller_id"])
    if seller and seller["status"] == "BANNED":
        raise errors.seller_frozen("Seller is BANNED.")

    ticket["tare_weight_lb"] = tare
    ticket["net_weight_lb"] = ticket["gross_weight_lb"] - tare
    ticket["gross_valuation_cents"] = sum(li["line_valuation_cents"] for li in lines)
    ticket["status"] = "WEIGHED"
    touch(ticket)
    return response.success(serializers.ticket(ticket), 200)


# --- Theft gate: hold / clear / release / report ---------------------------

@bp.route("/yard/tickets/<tid>/theft-hold", methods=["POST"])
def theft_hold(tid):
    _uid, role = authenticate()
    require_roles(role, {"WeighMaster"})
    ticket = db.tickets.get(tid)
    if not ticket:
        raise errors.not_found("Ticket not found.")
    if ticket["status"] != "WEIGHED":
        raise errors.invalid_state("theft-hold is only valid from WEIGHED.")
    ticket["status"] = "HOLD"
    touch(ticket)
    return response.success(serializers.ticket(ticket), 200)


@bp.route("/yard/tickets/<tid>/clear-hold", methods=["POST"])
def clear_hold(tid):
    uid, role = authenticate()
    require_roles(role, {"WeighMaster"})
    ticket = db.tickets.get(tid)
    if not ticket:
        raise errors.not_found("Ticket not found.")
    if ticket["status"] != "HOLD":
        raise errors.invalid_state("clear-hold is only valid from HOLD.")
    # Seller must have zero open theft reports (ERR_SELLER_FROZEN, 409).
    seller = db.sellers.get(ticket["seller_id"])
    if seller and seller["open_theft_reports"] > 0:
        raise errors.seller_frozen("Seller still has open theft reports.")
    ticket["status"] = "WEIGHED"
    ticket["theft_hold_released_by"] = uid
    touch(ticket)
    return response.success(serializers.ticket(ticket), 200)


@bp.route("/yard/tickets/<tid>/release", methods=["POST"])
def release_ticket(tid):
    _uid, role = authenticate()
    require_roles(role, {"WeighMaster"})
    ticket = db.tickets.get(tid)
    if not ticket:
        raise errors.not_found("Ticket not found.")
    body = get_json_body()
    require_fields(body, ["container_id"])
    container_id = as_string(body["container_id"], "container_id")
    # Existence of FK target (priority 3) before state? PRD §2.8: existence is
    # priority 3, state priority 4. So validate container existence first.
    container = db.containers.get(container_id)
    if container is None:
        raise errors.not_found("Container not found.")
    # State gate (priority 4): only from WEIGHED.
    if ticket["status"] != "WEIGHED":
        raise errors.invalid_state("release is only valid from WEIGHED.")
    # Seller-frozen (priority 6): must be ACTIVE and no open theft reports.
    seller = db.sellers.get(ticket["seller_id"])
    if seller and (seller["status"] != "ACTIVE" or seller["open_theft_reports"] > 0):
        raise errors.seller_frozen("Seller is frozen.")
    # Container must be STAGED (state precondition on container).
    if container["status"] != "STAGED":
        raise errors.invalid_state("Container is not STAGED.")
    # Category match (priority 7): container.category == every line item category.
    lines = ticket_line_items(tid)
    for li in lines:
        price = db.commodity_prices.get(li["commodity_price_id"])
        line_category = price["category"] if price else None
        if line_category != container["category"]:
            raise errors.category_mismatch()
    # Container capacity (priority 10).
    if container["loaded_weight_lb"] + ticket["net_weight_lb"] > container["capacity_lb"]:
        raise errors.container_capacity_exceeded()

    # Commit: assign ticket to container, bubble up loaded weight, advance both.
    ticket["container_id"] = container_id
    ticket["status"] = "RELEASED"
    touch(ticket)
    container["loaded_weight_lb"] += ticket["net_weight_lb"]
    touch(container)
    return response.success(serializers.ticket(ticket), 200)


@bp.route("/yard/tickets/<tid>/report", methods=["POST"])
def report_ticket(tid):
    _uid, role = authenticate()
    require_roles(role, {"WeighMaster"})
    ticket = db.tickets.get(tid)
    if not ticket:
        raise errors.not_found("Ticket not found.")
    if ticket["status"] != "WEIGHED":
        raise errors.invalid_state("report is only valid from WEIGHED.")
    body = get_json_body()
    require_fields(body, ["reason"])
    reason = as_string(body["reason"], "reason")

    ticket["status"] = "REPORTED"
    touch(ticket)
    # Cross-entity cascade: create TheftReport(OPEN), flag the seller.
    report = {
        "seller_id": ticket["seller_id"],
        "ticket_id": tid,
        "reason": reason,
        "status": "OPEN",
    }
    stamp_create(report)
    db.theft_reports[report["id"]] = report
    seller = db.sellers.get(ticket["seller_id"])
    if seller:
        seller["status"] = "FLAGGED"
        seller["open_theft_reports"] += 1
        touch(seller)
    return response.success(serializers.ticket(ticket), 200)
