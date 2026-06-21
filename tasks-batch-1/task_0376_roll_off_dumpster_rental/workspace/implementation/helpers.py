"""Lookup, pagination, ownership, and clock helpers."""
from db import db
from errors import err
from response import list_response


# ---- existence lookups (priority 3) ----

def get_container_type(type_id):
    rec = db.container_types.get(type_id)
    if rec is None:
        raise err("ERR_CONTAINER_TYPE_NOT_FOUND", "Container type not found")
    return rec


def get_account(account_id):
    rec = db.contractor_accounts.get(account_id)
    if rec is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", "Contractor account not found")
    return rec


def get_container(container_id):
    rec = db.containers.get(container_id)
    if rec is None:
        raise err("ERR_CONTAINER_NOT_FOUND", "Container not found")
    return rec


def get_order(order_id):
    rec = db.rental_orders.get(order_id)
    if rec is None:
        raise err("ERR_ORDER_NOT_FOUND", "Rental order not found")
    return rec


def get_route(route_id):
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_ROUTE_NOT_FOUND", "Route not found")
    return rec


def get_stop(stop_id):
    rec = db.service_stops.get(stop_id)
    if rec is None:
        raise err("ERR_STOP_NOT_FOUND", "Service stop not found")
    return rec


def get_weigh_ticket(ticket_id):
    rec = db.weigh_tickets.get(ticket_id)
    if rec is None:
        raise err("ERR_WEIGH_TICKET_NOT_FOUND", "Weigh ticket not found")
    return rec


def get_permit(permit_id):
    rec = db.street_permits.get(permit_id)
    if rec is None:
        raise err("ERR_PERMIT_NOT_FOUND", "Street permit not found")
    return rec


def get_invoice(invoice_id):
    rec = db.invoices.get(invoice_id)
    if rec is None:
        raise err("ERR_INVOICE_NOT_FOUND", "Invoice not found")
    return rec


# ---- ownership (priority 4) ----

def check_order_owner(order, role, user_id):
    """Contractor may only act on its own order (order.account_id == X-User-ID)."""
    if role == "Contractor" and order["account_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Contractor does not own this order")


def check_account_owner(account, role, user_id):
    if role == "Contractor" and account["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Contractor does not own this account")


def check_stop_owner(stop, role, user_id):
    if role == "Contractor":
        order = db.rental_orders.get(stop["order_id"])
        if order is None or order["account_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Contractor does not own this stop")


def check_invoice_owner(invoice, role, user_id):
    if role == "Contractor" and invoice["account_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Contractor does not own this invoice")


# ---- pagination + sorting ----

def paginate(records, serializer, limit, offset):
    """Sort by created_at ascending (ties broken by id for determinism),
    then page and serialize."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    items = [serializer(r) for r in page]
    return list_response(items, limit, offset, total)


# ---- clock ----

def current_date():
    """The business current_date, or None if the clock was never set."""
    if db.clock is None:
        return None
    return db.clock["current_date"]
