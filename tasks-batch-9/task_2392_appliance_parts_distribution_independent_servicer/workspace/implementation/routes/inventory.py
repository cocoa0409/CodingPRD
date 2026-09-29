"""Inventory positions and physical-count adjustments."""

from db import db, base_row, fmt, now, touch
from errors import ApiError
from flask import Blueprint
from middleware import authenticate, check_branch_open, check_branch_scope
from response import created, ok, ok_list
from services import flows, serialize
from validation import parse_body, pagination, q_str

bp = Blueprint("inventory", __name__)

ALL_ROLES = ("PlatformAdmin", "BranchCounterRep", "CreditManager", "PricingAdmin",
             "WarrantyAdmin", "Servicer")
BRANCH_WRITERS = ("BranchCounterRep", "PlatformAdmin")


@bp.post("/inventory-records")
def create_inventory_record():
    user_id, role = authenticate(BRANCH_WRITERS)
    body = parse_body([
        ("branch_id", "str", True),
        ("part_id", "str", True),
        ("on_hand_units", "units", False),
        ("reorder_point", "units", False),
    ])
    flows.part_or_404(body["part_id"])
    flows.branch_or_404(body["branch_id"])
    check_branch_scope(user_id, role, body["branch_id"])
    if flows.inventory_for(body["branch_id"], body["part_id"]) is not None:
        raise ApiError("ERR_DUPLICATE_KEY",
                       "An inventory position already exists for this branch and part")
    row = base_row()
    row.update({
        "branch_id": body["branch_id"],
        "part_id": body["part_id"],
        "on_hand_units": body.get("on_hand_units", 0),
        "reserved_units": 0,
        "reorder_point": body.get("reorder_point", 0),
        "last_counted_at": None,
    })
    db.inventory_records[row["id"]] = row
    return created(serialize.inventory_record(row))


@bp.post("/inventory-records/<record_id>/adjustments")
def adjust_inventory(record_id):
    user_id, role = authenticate(BRANCH_WRITERS)
    body = parse_body([
        ("delta_units", "signed", True),
        ("adjustment_reason", "str", True),
    ])
    record = flows.find(db.inventory_records, record_id,
                        "ERR_INVENTORY_RECORD_NOT_FOUND")
    check_branch_scope(user_id, role, record["branch_id"])
    branch = db.branches.get(record["branch_id"])
    check_branch_open(branch)
    new_on_hand = record["on_hand_units"] + body["delta_units"]
    if new_on_hand < 0 or new_on_hand < record["reserved_units"]:
        raise ApiError("ERR_INVENTORY_NEGATIVE",
                       "Adjustment would drive on_hand_units below zero or below "
                       "the reserved quantity")
    record["on_hand_units"] = new_on_hand
    record["last_counted_at"] = fmt(now())
    touch(record)
    return ok(serialize.inventory_record(record))


@bp.get("/inventory-records")
def list_inventory_records():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.inventory_records)
    for field in ("branch_id", "part_id"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.inventory_record(r) for r in page],
                   limit, offset, total)


@bp.get("/inventory-records/<record_id>")
def get_inventory_record(record_id):
    authenticate(ALL_ROLES)
    record = flows.find(db.inventory_records, record_id,
                        "ERR_INVENTORY_RECORD_NOT_FOUND")
    return ok(serialize.inventory_record(record))
