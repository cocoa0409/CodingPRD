"""Global filtered list endpoints and single-record fetches (PRD §4)."""

from flask import Blueprint, request

from db import store
from errors import ERR_NOT_FOUND, fail
from middleware import ALL_ROLES, authorize, pagination, public, sort_created
from response import list_response, object_response

bp = Blueprint("lists", __name__)


def _filter(records, params, allowed):
    items = list(records)
    for key in allowed:
        value = params.get(key)
        if value is not None:
            items = [r for r in items if r.get(key) == value]
    return sort_created(items)


def _paginate(items):
    limit, offset = pagination()
    page = items[offset:offset + limit]
    return list_response([public(r) for r in page], len(items), limit, offset)


@bp.get("/orders")
def list_orders():
    authorize(*ALL_ROLES)
    items = _filter(store.orders.values(), request.args,
                    ("employee_id", "employer_id", "issuing_authority_id",
                     "processing_status"))
    return _paginate(items)


@bp.get("/events")
def list_events():
    authorize(*ALL_ROLES)
    items = _filter(store.events.values(), request.args,
                    ("garnishment_order_id", "employer_id", "payroll_run_id",
                     "pay_statement_id", "event_type"))
    return _paginate(items)


@bp.get("/events/<eventId>")
def get_event(eventId):
    authorize(*ALL_ROLES)
    event = store.events.get(eventId)
    if event is None:
        fail(ERR_NOT_FOUND, 404, "WithholdingEvent '%s' does not exist." % eventId)
    return object_response(public(event))


@bp.get("/statements")
def list_statements():
    authorize(*ALL_ROLES)
    items = _filter(store.statements.values(), request.args,
                    ("payroll_run_id", "employer_id", "employee_id"))
    return _paginate(items)


@bp.get("/employees")
def list_employees():
    authorize(*ALL_ROLES)
    items = _filter(store.employees.values(), request.args, ("employer_id",))
    return _paginate(items)


@bp.get("/payroll-runs")
def list_runs():
    authorize(*ALL_ROLES)
    items = _filter(store.runs.values(), request.args, ("employer_id", "status"))
    return _paginate(items)


@bp.get("/remittances")
def list_remittances():
    authorize(*ALL_ROLES)
    items = _filter(store.remittances.values(), request.args,
                    ("employer_id", "authority_id", "payroll_run_id", "status"))
    return _paginate(items)


@bp.get("/audit-log")
def list_audit_log():
    authorize(*ALL_ROLES)
    items = _filter(store.audit_entries.values(), request.args,
                    ("employer_id", "entity_type", "entity_id"))
    return _paginate(items)


@bp.get("/audit-log/<entryId>")
def get_audit_entry(entryId):
    authorize(*ALL_ROLES)
    entry = store.audit_entries.get(entryId)
    if entry is None:
        fail(ERR_NOT_FOUND, 404, "AuditLogEntry '%s' does not exist." % entryId)
    return object_response(public(entry))
