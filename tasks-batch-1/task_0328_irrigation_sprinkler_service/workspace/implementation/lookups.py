"""Existence-resolution helpers (priority-3 validation, PRD §2.5).

Each returns the row or raises the entity-specific not-found error.
"""
from db import db
import errors
from errors import fail


def get_customer(cid):
    row = db.customers.get(cid)
    if row is None:
        fail(errors.ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    return row


def get_technician(tid):
    row = db.technicians.get(tid)
    if row is None:
        fail(errors.ERR_TECHNICIAN_NOT_FOUND, "Technician not found")
    return row


def get_property(pid):
    row = db.properties.get(pid)
    if row is None:
        fail(errors.ERR_PROPERTY_NOT_FOUND, "Property not found")
    return row


def get_system(sid):
    row = db.irrigation_systems.get(sid)
    if row is None:
        fail(errors.ERR_SYSTEM_NOT_FOUND, "Irrigation system not found")
    return row


def get_zone(zid):
    row = db.zones.get(zid)
    if row is None:
        fail(errors.ERR_ZONE_NOT_FOUND, "Zone not found")
    return row


def get_program(pid):
    row = db.controller_programs.get(pid)
    if row is None:
        fail(errors.ERR_PROGRAM_NOT_FOUND, "Controller program not found")
    return row


def get_quote(qid):
    row = db.service_quotes.get(qid)
    if row is None:
        fail(errors.ERR_QUOTE_NOT_FOUND, "Service quote not found")
    return row


def get_workorder(wid):
    row = db.work_orders.get(wid)
    if row is None:
        fail(errors.ERR_WORKORDER_NOT_FOUND, "Work order not found")
    return row


def get_plan(pid):
    row = db.maintenance_plans.get(pid)
    if row is None:
        fail(errors.ERR_PLAN_NOT_FOUND, "Maintenance plan not found")
    return row


def get_route(rid):
    row = db.routes.get(rid)
    if row is None:
        fail(errors.ERR_ROUTE_NOT_FOUND, "Route not found")
    return row


def get_route_stop(rid):
    row = db.route_stops.get(rid)
    if row is None:
        fail(errors.ERR_ROUTESTOP_NOT_FOUND, "Route stop not found")
    return row
