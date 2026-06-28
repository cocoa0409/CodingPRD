"""Existence lookups (PRD §2.6): return the row or raise the matching 404."""
from db import db
from errors import err


def get_pricing_config(cid):
    row = db.pricing_configs.get(cid)
    if row is None:
        raise err("ERR_PRICING_CONFIG_NOT_FOUND", "PricingConfig not found.")
    return row


def get_homeowner(hid):
    row = db.homeowners.get(hid)
    if row is None:
        raise err("ERR_HOMEOWNER_NOT_FOUND", "Homeowner not found.")
    return row


def get_home(hid):
    row = db.homes.get(hid)
    if row is None:
        raise err("ERR_HOME_NOT_FOUND", "Home not found.")
    return row


def get_system(sid):
    row = db.hvac_systems.get(sid)
    if row is None:
        raise err("ERR_SYSTEM_NOT_FOUND", "HvacSystem not found.")
    return row


def get_crew(cid):
    row = db.crew_members.get(cid)
    if row is None:
        raise err("ERR_CREW_NOT_FOUND", "CrewMember not found.")
    return row


def get_route(rid):
    row = db.route_plans.get(rid)
    if row is None:
        raise err("ERR_ROUTE_NOT_FOUND", "RoutePlan not found.")
    return row


def get_work_order(wid):
    row = db.work_orders.get(wid)
    if row is None:
        raise err("ERR_WORK_ORDER_NOT_FOUND", "WorkOrder not found.")
    return row


def get_plan(pid):
    row = db.recurring_plans.get(pid)
    if row is None:
        raise err("ERR_PLAN_NOT_FOUND", "RecurringPlan not found.")
    return row


def get_referral(rid):
    row = db.upsell_referrals.get(rid)
    if row is None:
        raise err("ERR_REFERRAL_NOT_FOUND", "UpsellReferral not found.")
    return row


def get_ticket(tid):
    row = db.callback_tickets.get(tid)
    if row is None:
        raise err("ERR_TICKET_NOT_FOUND", "CallbackTicket not found.")
    return row
