"""Shared route helpers: pagination parsing, lookups, serialization."""

from flask import request

import db
import errors


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3. Defaults 10/0; 1<=limit<=100; offset>=0."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def get_or_404(table, entity_id, what="Resource"):
    rec = table.get(entity_id)
    if rec is None:
        raise errors.not_found(f"{what} not found")
    return rec


def sorted_page(records, limit, offset):
    """Sort by created_at ascending (stable result set) then paginate."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def landlord_of_unit(unit):
    prop = db.properties.get(unit["property_id"])
    if not prop:
        return None
    return db.landlords.get(prop["landlord_id"])


def landlord_of_contract(contract):
    unit = db.units.get(contract["unit_id"])
    if not unit:
        return None
    return landlord_of_unit(unit)


def landlord_of_inspection(insp):
    contract = db.hap_contracts.get(insp["contract_id"])
    if not contract:
        return None
    return landlord_of_contract(contract)


def landlord_of_repair_item(item):
    insp = db.inspections.get(item["inspection_id"])
    if not insp:
        return None
    return landlord_of_inspection(insp)


def assert_landlord_owns(acting_landlord_id, owner_landlord):
    if owner_landlord is None or acting_landlord_id != owner_landlord["id"]:
        raise errors.not_owner()
