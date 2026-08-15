"""Customer accounts and the serialized unit registry (PRD 3.1)."""
from flask import Blueprint

from db import store, new_id, new_common
from errors import ApiError
from middleware import get_context, require_roles, check_customer_scope, ALL_ROLES
from response import ok, created, paginate
from validation import parse_body, require_path_entity, schema_field

bp = Blueprint("customers", __name__)


@bp.post("/reman/customers")
def create_customer():
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    body = parse_body({
        "legal_name": schema_field("string"),
        "credit_limit_cents": schema_field("integer"),
    }, allow_empty=False)
    customer = {
        "id": new_id(),
        "legal_name": body["legal_name"],
        "credit_limit_cents": body["credit_limit_cents"],
        "outstanding_approved_cents": 0,
        "credit_hold": False,
    }
    new_common(customer)
    store.customers[customer["id"]] = customer
    return created(customer)


@bp.get("/reman/customers/<customer_id>")
def get_customer(customer_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    check_customer_scope(uid, role, customer_id)
    return ok(require_path_entity(store.customers, customer_id))


@bp.get("/reman/customers/<customer_id>/units")
def list_customer_units(customer_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    check_customer_scope(uid, role, customer_id)
    require_path_entity(store.customers, customer_id)
    rows = [u for u in store.units.values() if u["customer_id"] == customer_id]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/reman/customers/<customer_id>/units")
def create_unit(customer_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    require_path_entity(store.customers, customer_id)
    body = parse_body({
        "serial_number": schema_field("string"),
        "model": schema_field("string"),
        "rated_torque_nm": schema_field("integer"),
    }, allow_empty=False)
    for unit in store.units.values():
        if unit["serial_number"] == body["serial_number"]:
            raise ApiError("ERR_SERIAL_EXISTS", 409,
                           "serial_number already registered in the unit registry")
    unit = {
        "id": new_id(),
        "customer_id": customer_id,
        "serial_number": body["serial_number"],
        "model": body["model"],
        "rated_torque_nm": body["rated_torque_nm"],
        "cumulative_service_hours": 0,
        "physical_status": "IN_SERVICE",
        "commercial_status": "STANDARD",
    }
    new_common(unit)
    store.units[unit["id"]] = unit
    return created(unit)
