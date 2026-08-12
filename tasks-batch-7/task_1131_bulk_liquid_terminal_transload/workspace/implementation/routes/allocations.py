"""TankAllocation endpoints: create (RESERVED), list per lease/tank, get,
activate, release."""
from flask import Blueprint

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import allocation_view
from services import calc
from services.common import touch, get_lease_or_404, get_tank_or_404
from services.lifecycle import recompute_reserved_capacity
from validation import get_body, req_string, req_number, req_date, sort_and_page

bp = Blueprint("allocations", __name__)


def _check_lease_allocation_state(lease):
    if lease["status"] not in ("DRAFT", "ACTIVE"):
        raise err("ERR_LEASE_NOT_ACTIVE",
                  "Allocation operations require the lease to be DRAFT or ACTIVE")


def _check_tank_available(tank):
    if tank["status"] != "AVAILABLE":
        raise err("ERR_TANK_NOT_AVAILABLE",
                  "Tank %s is %s; operation requires AVAILABLE"
                  % (tank["id"], tank["status"]))


def _check_period(lease, period_start_raw, ps, period_end_raw, pe):
    if pe < ps:
        raise err("ERR_ALLOCATION_PERIOD_INVALID",
                  "period_end must be on or after period_start")
    if ps < lease["_start_date"] or pe > lease["_end_date"]:
        raise err("ERR_ALLOCATION_PERIOD_INVALID",
                  "Allocation period must lie within the lease [start_date, end_date]")


@bp.post("/lease-agreements/<leaseId>/allocations")
def create_allocation(leaseId):
    require_roles("TerminalOperator")
    body = get_body()
    tank_id = req_string(body, "tank_id")
    allocated_bbl = req_number(body, "allocated_bbl", gt=0)
    period_start_raw, ps = req_date(body, "period_start")
    period_end_raw, pe = req_date(body, "period_end")

    lease = get_lease_or_404(leaseId)
    tank = get_tank_or_404(tank_id)

    _check_lease_allocation_state(lease)
    _check_tank_available(tank)
    _check_period(lease, period_start_raw, ps, period_end_raw, pe)

    now = CLOCK.now()
    allocation = {
        "id": new_id(),
        "lease_id": lease["id"],
        "tank_id": tank["id"],
        "allocated_bbl": allocated_bbl,
        "period_start": period_start_raw,
        "period_end": period_end_raw,
        "_period_start": ps,
        "_period_end": pe,
        "status": "RESERVED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    # Capacity sweep over RESERVED/ACTIVE allocations of the same tank.
    if not calc.capacity_sweep_ok(tank, allocation, "RESERVED"):
        raise err("ERR_ALLOCATION_CAPACITY_EXCEEDED",
                  "Overlapping allocation sum would exceed tank working capacity")
    STORE.allocations[allocation["id"]] = allocation
    return success_object(allocation_view(allocation), status=201)


@bp.get("/lease-agreements/<leaseId>/allocations")
def list_lease_allocations(leaseId):
    current_user()
    get_lease_or_404(leaseId)
    rows = [a for a in STORE.allocations.values() if a["lease_id"] == leaseId]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([allocation_view(a) for a in page], total, limit, offset)


@bp.get("/tanks/<tankId>/allocations")
def list_tank_allocations(tankId):
    current_user()
    get_tank_or_404(tankId)
    rows = [a for a in STORE.allocations.values() if a["tank_id"] == tankId]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([allocation_view(a) for a in page], total, limit, offset)


def _get_allocation_or_404(allocation_id):
    allocation = STORE.allocations.get(allocation_id)
    if allocation is None:
        raise err("ERR_ALLOCATION_NOT_FOUND", "Allocation %s not found" % allocation_id)
    return allocation


@bp.get("/tank-allocations/<allocationId>")
def get_allocation(allocationId):
    current_user()
    allocation = _get_allocation_or_404(allocationId)
    return success_object(allocation_view(allocation))


@bp.post("/tank-allocations/<allocationId>/activate")
def activate_allocation(allocationId):
    require_roles("TerminalOperator")
    allocation = _get_allocation_or_404(allocationId)
    if allocation["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE",
                  "Allocation %s is %s; activate requires RESERVED"
                  % (allocationId, allocation["status"]))
    lease = get_lease_or_404(allocation["lease_id"])
    tank = get_tank_or_404(allocation["tank_id"])
    _check_lease_allocation_state(lease)
    _check_tank_available(tank)
    if not calc.capacity_sweep_ok(tank, allocation, "ACTIVE"):
        raise err("ERR_ALLOCATION_CAPACITY_EXCEEDED",
                  "Overlapping allocation sum would exceed tank working capacity")
    allocation["status"] = "ACTIVE"
    touch(allocation)
    recompute_reserved_capacity(lease)
    return success_object(allocation_view(allocation))


@bp.post("/tank-allocations/<allocationId>/release")
def release_allocation(allocationId):
    require_roles("TerminalOperator")
    allocation = _get_allocation_or_404(allocationId)
    if allocation["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  "Allocation %s is %s; release requires ACTIVE"
                  % (allocationId, allocation["status"]))
    for m in STORE.movements.values():
        if (m["lease_id"] == allocation["lease_id"]
                and m["tank_id"] == allocation["tank_id"]
                and m["status"] in ("SCHEDULED", "ARRIVED", "IN_PROGRESS", "SUSPENDED")):
            raise err("ERR_INVALID_STATE",
                      "A movement on this (lease, tank) is in status %s" % m["status"])
    allocation["status"] = "RELEASED"
    touch(allocation)
    lease = get_lease_or_404(allocation["lease_id"])
    recompute_reserved_capacity(lease)
    return success_object(allocation_view(allocation))
