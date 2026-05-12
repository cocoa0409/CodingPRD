"""Lookup helpers — ERR_NOT_FOUND wrappers."""
import db
from errors import err


def get_building(building_id: str) -> dict:
    b = db.buildings.get(building_id)
    if b is None:
        raise err("ERR_NOT_FOUND", f"Building {building_id} not found")
    return b


def get_unit_in_building(building_id: str, unit_id: str) -> dict:
    get_building(building_id)
    u = db.units.get(unit_id)
    if u is None:
        raise err("ERR_NOT_FOUND", f"Unit {unit_id} not found")
    if u.get("building_id") != building_id:
        raise err("ERR_NOT_FOUND", f"Unit {unit_id} does not belong to building {building_id}")
    return u


def get_unit(unit_id: str) -> dict:
    u = db.units.get(unit_id)
    if u is None:
        raise err("ERR_NOT_FOUND", f"Unit {unit_id} not found")
    return u


def get_tenant(tenant_id: str) -> dict:
    t = db.tenants.get(tenant_id)
    if t is None:
        raise err("ERR_NOT_FOUND", f"Tenant {tenant_id} not found")
    return t


def get_lease(lease_id: str) -> dict:
    le = db.leases.get(lease_id)
    if le is None:
        raise err("ERR_NOT_FOUND", f"Lease {lease_id} not found")
    return le


def get_deposit(deposit_id: str) -> dict:
    d = db.deposits.get(deposit_id)
    if d is None:
        raise err("ERR_NOT_FOUND", f"Deposit {deposit_id} not found")
    return d


def get_deposit_for_lease(lease_id: str):
    for d in db.deposits.values():
        if d["lease_id"] == lease_id:
            return d
    return None


def get_fee_bill(bill_id: str) -> dict:
    b = db.fee_bills.get(bill_id)
    if b is None:
        raise err("ERR_NOT_FOUND", f"FeeBill {bill_id} not found")
    return b


def get_move_out_request(request_id: str) -> dict:
    r = db.move_out_requests.get(request_id)
    if r is None:
        raise err("ERR_NOT_FOUND", f"MoveOutRequest {request_id} not found")
    return r


def get_move_out_for_lease(lease_id: str):
    """Return the latest non-rejected MoveOutRequest for the lease (i.e., active one)."""
    matches = [r for r in db.move_out_requests.values()
               if r["lease_id"] == lease_id and r["status"] != "REJECTED"]
    if not matches:
        return None
    return sorted(matches, key=lambda r: r["_seq"])[-1]
