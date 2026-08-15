"""Item banks & survey items (PRD §3.1)."""

from flask import Blueprint

from db import db, stamp_new, touch, public
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_DUTY_SEGREGATION, ERR_DUPLICATE,
    ERR_INSUFFICIENT_ITEMS,
)
from middleware import (
    require_roles, parse_pagination, paginate, get_json_body,
    require_fields, optional_fields_present, as_non_empty_string, as_enum,
    as_bool, as_number,
)
from response import success_object, success_list

bp = Blueprint("item_banks", __name__)

FRAMEWORKS = {"EWI", "Q12", "CUSTOM"}
DIMENSIONS = {"PURPOSE", "GROWTH", "MANAGER_SUPPORT", "BELONGING", "WORKLOAD", "RECOGNITION"}


def _get_bank_or_404(bank_id):
    bank = db.item_banks.get(bank_id)
    if bank is None:
        raise err(ERR_NOT_FOUND, "item bank not found", 404)
    return bank


@bp.post("/engagement/item-banks")
def create_item_bank():
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst")
    # Segregation of duties (§2.7): PeopleAnalyst may not create item banks.
    if role == "PeopleAnalyst":
        raise err(ERR_DUTY_SEGREGATION,
                  "PeopleAnalyst may not create item banks", 403)
    body = get_json_body()
    optional_fields_present(body, {"name", "framework"})
    require_fields(body, ["name", "framework"])
    name = as_non_empty_string(body["name"], "name")
    framework = as_enum(body["framework"], "framework", FRAMEWORKS)

    # name unique per tenant
    for b in db.item_banks.values():
        if b["name"] == name:
            raise err(ERR_DUPLICATE, "item bank name must be unique", 409)

    bank = stamp_new({
        "name": name,
        "framework": framework,
        "status": "DRAFT",
    })
    db.item_banks[bank["id"]] = bank
    return success_object(public(bank), 201)


@bp.get("/engagement/item-banks")
def list_item_banks():
    require_roles("HRAdmin", "PeopleAnalyst")
    limit, offset = parse_pagination({"status"})
    status = None
    if "status" in __import__("flask").request.args:
        raw = __import__("flask").request.args.get("status")
        if raw not in ("DRAFT", "ACTIVE", "RETIRED"):
            raise err(ERR_VALIDATION, "invalid status filter", 400)
        status = raw
    items = [b for b in db.item_banks.values() if status is None or b["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(b) for b in page], limit, offset, total)


@bp.get("/engagement/item-banks/<bank_id>")
def get_item_bank(bank_id):
    require_roles("HRAdmin", "PeopleAnalyst")
    bank = _get_bank_or_404(bank_id)
    return success_object(public(bank))


@bp.post("/engagement/item-banks/<bank_id>/items")
def add_survey_item(bank_id):
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst")
    # Segregation of duties: PeopleAnalyst may not add survey items.
    if role == "PeopleAnalyst":
        raise err(ERR_DUTY_SEGREGATION,
                  "PeopleAnalyst may not create survey items", 403)
    bank = _get_bank_or_404(bank_id)
    body = get_json_body()
    optional_fields_present(body, {"item_code", "dimension", "weight", "has_free_text"})
    require_fields(body, ["item_code", "dimension", "weight"])
    item_code = as_non_empty_string(body["item_code"], "item_code")
    dimension = as_enum(body["dimension"], "dimension", DIMENSIONS)
    weight_raw = as_number(body["weight"], "weight")
    # weight: positive decimal with exactly 1 fractional digit, 0.1..5.0
    from decimal import Decimal, InvalidOperation
    try:
        weight = Decimal(str(weight_raw))
    except InvalidOperation:
        raise err(ERR_VALIDATION, "weight must be a decimal", 400)
    if weight < Decimal("0.1") or weight > Decimal("5.0"):
        raise err(ERR_VALIDATION, "weight must be between 0.1 and 5.0", 400)
    if -weight.as_tuple().exponent != 1:
        raise err(ERR_VALIDATION, "weight must have exactly 1 fractional digit", 400)
    has_free_text = False
    if "has_free_text" in body:
        has_free_text = as_bool(body["has_free_text"], "has_free_text")

    # item_code unique within bank
    for it in db.survey_items.values():
        if it["bank_id"] == bank["id"] and it["item_code"] == item_code:
            raise err(ERR_DUPLICATE, "item_code must be unique within bank", 409)

    item = stamp_new({
        "bank_id": bank["id"],
        "item_code": item_code,
        "dimension": dimension,
        "weight": float(weight),
        "has_free_text": has_free_text,
        "status": "ACTIVE",
    })
    db.survey_items[item["id"]] = item
    # Adding an item increments the bank's version (§2.10).
    touch(bank)
    return success_object(public(item), 201)


@bp.get("/engagement/item-banks/<bank_id>/items")
def list_survey_items(bank_id):
    require_roles("HRAdmin", "PeopleAnalyst")
    bank = _get_bank_or_404(bank_id)
    limit, offset = parse_pagination(set())
    items = [it for it in db.survey_items.values() if it["bank_id"] == bank["id"]]
    page, total = paginate(items, limit, offset)
    return success_list([public(it) for it in page], limit, offset, total)


@bp.post("/engagement/item-banks/<bank_id>/activate")
def activate_bank(bank_id):
    require_roles("HRAdmin")
    bank = _get_bank_or_404(bank_id)
    if bank["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  f"cannot activate bank in status {bank['status']}", 409)
    active_items = [it for it in db.survey_items.values()
                    if it["bank_id"] == bank["id"] and it["status"] == "ACTIVE"]
    if len(active_items) < 3:
        raise err(ERR_INSUFFICIENT_ITEMS,
                  "bank requires at least 3 ACTIVE items to activate", 422)
    bank["status"] = "ACTIVE"
    touch(bank)
    return success_object(public(bank))


@bp.post("/engagement/item-banks/<bank_id>/retire")
def retire_bank(bank_id):
    require_roles("HRAdmin")
    bank = _get_bank_or_404(bank_id)
    if bank["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE,
                  f"cannot retire bank in status {bank['status']}", 409)
    # Refused while any cycle on this bank is in CONFIGURED, OPEN, or SCORING.
    for cycle in db.survey_cycles.values():
        if cycle["bank_id"] == bank["id"] and cycle["status"] in ("CONFIGURED", "OPEN", "SCORING"):
            raise err(ERR_INVALID_STATE,
                      "bank has an in-flight survey cycle", 409)
    bank["status"] = "RETIRED"
    for it in db.survey_items.values():
        if it["bank_id"] == bank["id"] and it["status"] == "ACTIVE":
            it["status"] = "RETIRED"
            touch(it)
    touch(bank)
    return success_object(public(bank))
