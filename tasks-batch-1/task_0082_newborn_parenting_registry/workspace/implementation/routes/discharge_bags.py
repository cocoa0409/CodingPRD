"""DischargeBag resource (PRD §3.6)."""

from flask import Blueprint, request

import db
import services
from errors import (
    APIError,
    ERR_BAG_ALREADY_ISSUED,
    ERR_PHARMACY_SIGNOFF_REQUIRED,
    invalid_request,
    invalid_state,
    not_found,
)
from helpers import (
    get_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("discharge_bags", __name__)

BAG_STATUSES = {"DRAFT", "ASSEMBLED", "ISSUED", "RECALLED"}
LINE_ITEM_CATEGORIES = {"FORMULA", "DIAPERS", "EDUCATION", "CARSEAT_VOUCHER", "MEDICATION"}


def _get_bag(bag_id):
    b = db.discharge_bags.get(bag_id)
    if b is None:
        raise not_found("Discharge bag not found.")
    return b


def _validate_line_items(line_items):
    if not isinstance(line_items, list):
        raise invalid_request("line_items must be an array.")
    for item in line_items:
        if not isinstance(item, dict):
            raise invalid_request("Each line item must be an object.")
        for key in ("sku", "category", "qty", "unit_value_cents"):
            if key not in item or item[key] is None:
                raise invalid_request(f"Line item is missing {key!r}.")
        if not isinstance(item["sku"], str):
            raise invalid_request("Line item sku must be a string.")
        if item["category"] not in LINE_ITEM_CATEGORIES:
            raise invalid_request(
                f"Line item category must be one of {sorted(LINE_ITEM_CATEGORIES)}.")
        if isinstance(item["qty"], bool) or not isinstance(item["qty"], int):
            raise invalid_request("Line item qty must be an integer.")
        if isinstance(item["unit_value_cents"], bool) or not isinstance(item["unit_value_cents"], int):
            raise invalid_request("Line item unit_value_cents must be an integer.")


@bp.post("/discharge-bags")
def create_bag():
    require_roles("AttendingNurse")
    body = get_body()
    newborn_id = require_field(body, "newborn_id", str)
    if db.newborns.get(newborn_id) is None:
        raise not_found("newborn_id does not resolve to a newborn.")
    line_items = require_field(body, "line_items", list)
    _validate_line_items(line_items)
    row = {
        "id": db.new_id(),
        "newborn_id": newborn_id,
        "line_items": line_items,
        "status": "DRAFT",
        "total_value_cents": 0,
        "requires_pharmacy_signoff": False,
    }
    db.stamp_create(row)
    db.discharge_bags[row["id"]] = row
    return ok_object(db.public(row), 201)


@bp.get("/discharge-bags/<bag_id>")
def get_bag(bag_id):
    require_roles("AttendingNurse", "RegistrySupervisor")
    return ok_object(db.public(_get_bag(bag_id)))


@bp.get("/discharge-bags")
def list_bags():
    require_roles("AttendingNurse", "RegistrySupervisor")
    limit, offset = parse_pagination()
    newborn_id = request.args.get("newborn_id")
    status = request.args.get("status")
    rows = list(db.discharge_bags.values())
    if newborn_id is not None:
        rows = [r for r in rows if r["newborn_id"] == newborn_id]
    if status is not None:
        require_enum(status, "status", BAG_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/discharge-bags/<bag_id>/assemble")
def assemble_bag(bag_id):
    require_roles("AttendingNurse")
    b = _get_bag(bag_id)
    if b["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT bag may be assembled.")
    line_items = b["line_items"]
    if not line_items:
        raise invalid_request("line_items must be non-empty to assemble.")
    for item in line_items:
        if int(item["qty"]) < 1:
            raise invalid_request("Every line item qty must be >= 1.")
    b["total_value_cents"] = services.compute_bag_value(line_items)
    b["requires_pharmacy_signoff"] = services.requires_pharmacy_signoff(line_items)
    b["status"] = "ASSEMBLED"
    db.stamp_update(b)
    return ok_object(db.public(b))


@bp.post("/discharge-bags/<bag_id>/issue")
def issue_bag(bag_id):
    require_roles("AttendingNurse")
    b = _get_bag(bag_id)
    body = get_body()
    pharmacy_signoff = optional_field(body, "pharmacy_signoff", bool, default=False)
    if b["status"] != "ASSEMBLED":
        raise invalid_state("Only an ASSEMBLED bag may be issued.")
    # Pharmacy sign-off (priority 8).
    if b["requires_pharmacy_signoff"] and pharmacy_signoff is not True:
        raise APIError(ERR_PHARMACY_SIGNOFF_REQUIRED,
                       "Medication-bearing bag requires pharmacy_signoff == true.", 422)
    # Already-issued bag (priority 20).
    for other in db.discharge_bags.values():
        if (other["id"] != bag_id
                and other["newborn_id"] == b["newborn_id"]
                and other["status"] == "ISSUED"):
            raise APIError(ERR_BAG_ALREADY_ISSUED,
                           "The newborn already has another ISSUED discharge bag.", 409)
    b["status"] = "ISSUED"
    db.stamp_update(b)
    services.append_audit("BAG_ISSUED", request.headers.get("X-User-Role"),
                          b["newborn_id"], {"discharge_bag_id": bag_id})
    return ok_object(db.public(b))


@bp.post("/discharge-bags/<bag_id>/recall")
def recall_bag(bag_id):
    require_roles("AttendingNurse")
    b = _get_bag(bag_id)
    if b["status"] != "ISSUED":
        raise invalid_state("Only an ISSUED bag may be recalled.")
    newborn = db.newborns.get(b["newborn_id"])
    if newborn is not None and newborn["clinical_status"] == "DISCHARGED":
        raise invalid_state("Cannot recall a bag after the newborn is discharged.")
    b["status"] = "RECALLED"
    db.stamp_update(b)
    return ok_object(db.public(b))
