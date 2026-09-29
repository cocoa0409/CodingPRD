"""Identifier resolution (PRD 2.6): each store has its own 404 code."""
import db
from errors import ApiError

_STORES = {
    "tower": (db.towers, "ERR_TOWER_NOT_FOUND"),
    "circuit": (db.backhaul_circuits, "ERR_CIRCUIT_NOT_FOUND"),
    "license": (db.spectrum_licenses, "ERR_LICENSE_NOT_FOUND"),
    "sector": (db.sectors, "ERR_SECTOR_NOT_FOUND"),
    "coordination": (db.interference_coordinations, "ERR_COORDINATION_NOT_FOUND"),
    "plan": (db.service_plans, "ERR_PLAN_NOT_FOUND"),
    "request": (db.serviceability_requests, "ERR_REQUEST_NOT_FOUND"),
    "hold": (db.capacity_holds, "ERR_HOLD_NOT_FOUND"),
    "subscriber": (db.subscribers, "ERR_SUBSCRIBER_NOT_FOUND"),
    "work_order": (db.install_work_orders, "ERR_WORK_ORDER_NOT_FOUND"),
    "assignment": (db.equipment_assignments, "ERR_ASSIGNMENT_NOT_FOUND"),
    "outage": (db.outage_events, "ERR_OUTAGE_NOT_FOUND"),
    "credit": (db.outage_credits, "ERR_CREDIT_NOT_FOUND"),
}


def find(kind, identifier):
    store, error_id = _STORES[kind]
    record = store.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def tower(identifier):
    return find("tower", identifier)


def circuit(identifier):
    return find("circuit", identifier)


def license_(identifier):
    return find("license", identifier)


def sector(identifier):
    return find("sector", identifier)


def coordination(identifier):
    return find("coordination", identifier)


def plan(identifier):
    return find("plan", identifier)


def request_(identifier):
    return find("request", identifier)


def hold(identifier):
    return find("hold", identifier)


def subscriber(identifier):
    return find("subscriber", identifier)


def work_order(identifier):
    return find("work_order", identifier)


def assignment(identifier):
    return find("assignment", identifier)


def outage(identifier):
    return find("outage", identifier)


def credit(identifier):
    return find("credit", identifier)
