"""Existence resolution (gates 5-6) and ownership scoping (gates 7-8)."""

import errors
from db import db, ordered
from errors import fail


def _get(collection, resource_id, error_id):
    record = collection.get(resource_id) if isinstance(resource_id, str) else None
    if record is None:
        fail(error_id, "Resource '%s' was not found." % resource_id)
    return record


def get_property(resource_id):
    return _get(db.properties, resource_id, errors.ERR_PROPERTY_NOT_FOUND)


def get_cleaner(resource_id):
    return _get(db.cleaners, resource_id, errors.ERR_CLEANER_NOT_FOUND)


def get_booking(resource_id):
    return _get(db.bookings, resource_id, errors.ERR_BOOKING_NOT_FOUND)


def get_turnover(resource_id):
    return _get(db.turnovers, resource_id, errors.ERR_TURNOVER_NOT_FOUND)


def get_assignment(resource_id):
    return _get(db.assignments, resource_id, errors.ERR_ASSIGNMENT_NOT_FOUND)


def get_checklist_task(resource_id):
    return _get(db.checklist_tasks, resource_id, errors.ERR_CHECKLIST_TASK_NOT_FOUND)


def get_supply_line(resource_id):
    return _get(db.supply_lines, resource_id, errors.ERR_SUPPLY_LINE_NOT_FOUND)


def get_stock_movement(resource_id):
    return _get(db.stock_movements, resource_id, errors.ERR_STOCK_MOVEMENT_NOT_FOUND)


def get_issue_report(resource_id):
    return _get(db.issue_reports, resource_id, errors.ERR_ISSUE_REPORT_NOT_FOUND)


def get_repair_order(resource_id):
    return _get(db.repair_orders, resource_id, errors.ERR_REPAIR_ORDER_NOT_FOUND)


def get_quality_audit(resource_id):
    return _get(db.quality_audits, resource_id, errors.ERR_QUALITY_AUDIT_NOT_FOUND)


def get_pay_line(resource_id):
    return _get(db.pay_lines, resource_id, errors.ERR_PAY_LINE_NOT_FOUND)


# --------------------------------------------------------------------------
# ownership scoping
# --------------------------------------------------------------------------

def owner_scope_resource(actor, property_id):
    """Gate 7 on a single-resource read: the acting owner IS the property."""
    if actor.is_owner and property_id != actor.user_id:
        fail(errors.ERR_NOT_PROPERTY_OWNER)


def owner_scope_list(actor, property_id_filter):
    """Gate 7 on a list read: the property_id filter is mandatory for owners."""
    if actor.is_owner and property_id_filter != actor.user_id:
        fail(errors.ERR_NOT_PROPERTY_OWNER,
             "A PropertyOwner must pass its own id as the property_id filter.")


# --------------------------------------------------------------------------
# assignment helpers
# --------------------------------------------------------------------------

def turnover_assignments(turnover_id):
    return [a for a in ordered(db.assignments.values())
            if a["turnover_id"] == turnover_id]


def turnover_assignment_in(turnover_id, statuses):
    for assignment in turnover_assignments(turnover_id):
        if assignment["status"] in statuses:
            return assignment
    return None


def working_assignment(turnover_id):
    """The assignment that currently covers the turnover, most advanced first."""
    for statuses in (("ACTIVE",), ("ACCEPTED",), ("COMPLETED",), ("OFFERED",)):
        assignment = turnover_assignment_in(turnover_id, statuses)
        if assignment is not None:
            return assignment
    return None


def cleaner_scope_turnover(actor, turnover, statuses):
    """Gate 8: the acting cleaner must hold the covering assignment."""
    if not actor.is_cleaner:
        return None
    assignment = turnover_assignment_in(turnover["id"], statuses)
    if assignment is None or assignment["cleaner_id"] != actor.user_id:
        fail(errors.ERR_NOT_ASSIGNMENT_OWNER)
    return assignment
