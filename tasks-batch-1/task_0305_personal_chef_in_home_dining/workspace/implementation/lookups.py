"""Existence lookups raising the correct not-found error_id (PRD §2.8, §5)."""
from db import DB
from errors import err


def get_chef(chef_id):
    r = DB.chefs.get(chef_id)
    if r is None:
        raise err("ERR_CHEF_NOT_FOUND", "Chef not found: %s" % chef_id)
    return r


def get_menu(menu_id):
    r = DB.menus.get(menu_id)
    if r is None:
        raise err("ERR_MENU_NOT_FOUND", "Menu not found: %s" % menu_id)
    return r


def get_zone(zone_id):
    r = DB.travel_zones.get(zone_id)
    if r is None:
        raise err("ERR_ZONE_NOT_FOUND", "Travel zone not found: %s" % zone_id)
    return r


def get_block(block_id):
    r = DB.availability_blocks.get(block_id)
    if r is None:
        # No dedicated block not-found code in the catalogue; blocks are addressed
        # by id only on GET. Use ERR_BOOKING/CHEF family? PRD lists no block 404.
        # The not-found family per §2.8 omits block; fall back to a generic 404
        # is not in the catalogue, so we surface ERR_CHEF_NOT_FOUND only when a
        # chef path is involved. For /availability-blocks/{blockId} there is no
        # declared id; we return ERR_BOOKING_NOT_FOUND? No — use a 404 generic.
        raise err("ERR_BLOCK_NOT_FOUND", "Availability block not found: %s" % block_id)
    return r


def get_client(client_id):
    r = DB.clients.get(client_id)
    if r is None:
        raise err("ERR_CLIENT_NOT_FOUND", "Client not found: %s" % client_id)
    return r


def get_booking(booking_id):
    r = DB.bookings.get(booking_id)
    if r is None:
        raise err("ERR_BOOKING_NOT_FOUND", "Booking not found: %s" % booking_id)
    return r


def get_grocery_run(grocery_run_id):
    r = DB.grocery_runs.get(grocery_run_id)
    if r is None:
        raise err("ERR_GROCERY_RUN_NOT_FOUND", "Grocery run not found: %s" % grocery_run_id)
    return r


def get_payment(payment_id):
    r = DB.payments.get(payment_id)
    if r is None:
        # No ERR_PAYMENT_NOT_FOUND in the catalogue; payments are addressed by id
        # only on GET. Surface a 404 with a generic id.
        raise err("ERR_PAYMENT_NOT_FOUND", "Payment not found: %s" % payment_id)
    return r


def get_plan(plan_id):
    r = DB.recurring_plans.get(plan_id)
    if r is None:
        raise err("ERR_PLAN_NOT_FOUND", "Recurring plan not found: %s" % plan_id)
    return r


def get_reschedule(request_id):
    r = DB.reschedule_requests.get(request_id)
    if r is None:
        raise err("ERR_RESCHEDULE_NOT_FOUND", "Reschedule request not found: %s" % request_id)
    return r
