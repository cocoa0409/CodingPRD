"""ServiceItem and Customer business logic."""
from db import store
from errors import ERR_VALIDATION_ERROR, raise_error
from services.utils import stamp_create, stamp_update, check_occ


VALID_SKILL_TAGS = {"CLEANING", "COOKING", "CHILDCARE", "ELDERCARE"}


def create_service_item(body: dict) -> dict:
    required = ["name", "required_skill_tag", "base_price_cents", "service_areas"]
    for f in required:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION_ERROR, f"Missing required field: {f}")
    if body["required_skill_tag"] not in VALID_SKILL_TAGS:
        raise_error(ERR_VALIDATION_ERROR, "Invalid required_skill_tag")
    try:
        bp = int(body["base_price_cents"])
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION_ERROR, "base_price_cents must be an integer")
    if not isinstance(body["service_areas"], list):
        raise_error(ERR_VALIDATION_ERROR, "service_areas must be an array")
    record = {
        "name": body["name"],
        "required_skill_tag": body["required_skill_tag"],
        "base_price_cents": bp,
        "min_duration_hours": float(body.get("min_duration_hours", 1)),
        "service_areas": list(body["service_areas"]),
        "active": bool(body.get("active", True)),
    }
    stamp_create(record)
    store.service_items[record["id"]] = record
    return record


def update_service_item(item_id: str, body: dict) -> dict:
    item = store.service_items[item_id]
    check_occ(item, body)
    if "base_price_cents" in body and body["base_price_cents"] is not None:
        try:
            item["base_price_cents"] = int(body["base_price_cents"])
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION_ERROR, "base_price_cents must be an integer")
    if "service_areas" in body and body["service_areas"] is not None:
        if not isinstance(body["service_areas"], list):
            raise_error(ERR_VALIDATION_ERROR, "service_areas must be an array")
        item["service_areas"] = list(body["service_areas"])
    if "active" in body and body["active"] is not None:
        item["active"] = bool(body["active"])
    stamp_update(item)
    return item


def create_customer(body: dict) -> dict:
    required = ["full_name", "area_code", "address_lat", "address_lng"]
    for f in required:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION_ERROR, f"Missing required field: {f}")
    record = {
        "full_name": body["full_name"],
        "area_code": body["area_code"],
        "address_lat": float(body["address_lat"]),
        "address_lng": float(body["address_lng"]),
        "pref_gender": body.get("pref_gender"),
        "pref_min_age": body.get("pref_min_age"),
        "pref_max_age": body.get("pref_max_age"),
        "pref_language": body.get("pref_language"),
        "wallet_credit_cents": 0,
    }
    if record["pref_gender"] is not None and record["pref_gender"] not in {"MALE", "FEMALE"}:
        raise_error(ERR_VALIDATION_ERROR, "pref_gender must be MALE, FEMALE, or null")
    stamp_create(record)
    store.customers[record["id"]] = record
    return record
