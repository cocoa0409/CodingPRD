"""Shared service helpers: mutation bookkeeping and lazy expiry evaluation."""
from clock import CLOCK
from db import STORE
from errors import err

# PRD 2.5: fields that may appear in a response view for common entities.
OCCUPYING_STATUSES = ("SCHEDULED", "ARRIVED", "IN_PROGRESS", "SUSPENDED")
MODE_TO_RESOURCE_TYPE = {"VESSEL": "DOCK", "RAIL": "RAIL_RACK", "TRUCK": "TRUCK_BAY"}


def touch(entity):
    """Refresh updated_at and bump version (PRD 2.5)."""
    entity["updated_at"] = CLOCK.now()
    entity["version"] = entity.get("version", 1) + 1


def lazy_lease(lease):
    """PRD 2.4: ACTIVE/SUSPENDED lease expires lazily once clock date > end_date."""
    if lease["status"] in ("ACTIVE", "SUSPENDED"):
        if CLOCK.now().date() > lease["_end_date"]:
            lease["status"] = "EXPIRED"
            touch(lease)


def lazy_permit(permit):
    """PRD 2.4: REQUESTED/APPROVED permit expires lazily once clock > valid_until."""
    if permit["status"] in ("REQUESTED", "APPROVED"):
        if CLOCK.now() > permit["valid_until"]:
            permit["status"] = "EXPIRED"
            touch(permit)


def get_lease_or_404(lease_id):
    lease = STORE.leases.get(lease_id)
    if lease is None:
        raise err("ERR_LEASE_NOT_FOUND", "Lease %s not found" % lease_id)
    lazy_lease(lease)
    return lease


def get_tank_or_404(tank_id):
    tank = STORE.tanks.get(tank_id)
    if tank is None:
        raise err("ERR_TANK_NOT_FOUND", "Tank %s not found" % tank_id)
    return tank


def get_resource_or_404(resource_id):
    resource = STORE.resources.get(resource_id)
    if resource is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Resource %s not found" % resource_id)
    return resource


def get_movement_or_404(movement_id):
    movement = STORE.movements.get(movement_id)
    if movement is None:
        raise err("ERR_MOVEMENT_NOT_FOUND", "Movement %s not found" % movement_id)
    return movement


def active_allocation_for(lease_id, tank_id):
    """The ACTIVE TankAllocation covering (lease, tank), or None."""
    for alloc in STORE.allocations.values():
        if (alloc["lease_id"] == lease_id and alloc["tank_id"] == tank_id
                and alloc["status"] == "ACTIVE"):
            return alloc
    return None
