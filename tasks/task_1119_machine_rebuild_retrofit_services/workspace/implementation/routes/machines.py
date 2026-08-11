"""Machine endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import new_record, sorted_records, store
from errors import bad_request
from middleware import forbidden, require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from util import get_body, pagination_params, paginate, req_enum, req_int, req_str
from routes.common import check_customer_ownership, customer_owns, get_or_404

bp = Blueprint("machines", __name__)

MACHINE_TYPES = ("LATHE", "MILL", "GRINDER")
CONTROL_GENERATIONS = ("LEGACY", "MODERN")


@bp.post("/api/machines")
@require_roles("Customer", "PlatformAdmin")
def create_machine(user_id, role):
    body = get_body()
    # Ownership (gate 2): a Customer caller registers only own machines.
    if role == "Customer" and isinstance(body.get("customer_id"), str):
        if body["customer_id"] != user_id:
            raise forbidden("customer cannot register a machine for another customer")
    customer_id = req_str(body, "customer_id")
    serial_number = req_str(body, "serial_number")
    machine_type = req_enum(body, "machine_type", MACHINE_TYPES)
    year = req_int(body, "year_of_manufacture", minimum=1950, maximum=2026)
    control_generation = req_enum(body, "control_generation", CONTROL_GENERATIONS)
    spindle_hours = req_int(body, "spindle_hours", minimum=0)
    # Unique serial_number across all machines (gate 3: ERR_INVALID_REQUEST).
    for m in store.machines.values():
        if m["serial_number"] == serial_number:
            raise bad_request("serial_number must be unique across all machines")
    # Existence (gate 4): body-referenced customer_id.
    get_or_404(store.customers, customer_id, "customer")
    rec = new_record(
        {
            "customer_id": customer_id,
            "serial_number": serial_number,
            "machine_type": machine_type,
            "year_of_manufacture": year,
            "control_generation": control_generation,
            "spindle_hours": spindle_hours,
            "status": "REGISTERED",
        }
    )
    store.machines[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/api/machines/<mid>")
@require_roles("Customer", "PlatformAdmin", "ProjectManager", "Assessor")
def get_machine(user_id, role, mid):
    rec = get_or_404(store.machines, mid, "machine")
    check_customer_ownership(user_id, role, "machine", rec)
    return success(serialize(rec))


@bp.get("/api/machines")
@require_roles("Customer", "PlatformAdmin", "ProjectManager", "Assessor")
def list_machines(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.machines)
    customer_filter = request.args.get("customer_id")
    if customer_filter is not None:
        items = [m for m in items if m["customer_id"] == customer_filter]
    if role == "Customer":
        items = [m for m in items if customer_owns(user_id, "machine", m)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)
