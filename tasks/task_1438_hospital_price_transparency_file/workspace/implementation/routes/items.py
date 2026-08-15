"""ServiceItem catalog: create, facility-scoped list, OCC-guarded PATCH
(price maintenance + retirement), per PRD 3.2/3.8 and scaffold OCC rules."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE_ITEM_CODE,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ITEM_IN_CERTIFIED_LIST,
    ERR_ITEM_RETIRED,
    ERR_SERVICE_ITEM_NOT_FOUND,
    ERR_STALE_VERSION,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import cascade_item_prices
from util import (
    apply_filters,
    get_json_body,
    optional_bool,
    optional_enum,
    optional_int,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    sort_created,
)

bp = Blueprint("items", __name__)

CODE_TYPES = {"CPT", "HCPCS", "MS_DRG", "REVENUE_CODE"}
SERVICE_CLASSES = {"SHOPPABLE", "ANCILLARY", "SUPPLY", "DRUG", "FACILITY_FEE"}
ANCILLARY_INCLUSIONS = {"ALWAYS_BUNDLED", "CONDITIONALLY_INCLUDED", "SEPARATELY_PRICED"}


def get_item_or_404(iid: str) -> dict:
    item = db.service_items.get(iid)
    if item is None:
        raise_err(ERR_SERVICE_ITEM_NOT_FOUND, "Service item not found")
    return item


@bp.post("/transparency/service-items")
@require_roles("TransparencyOfficer")
def create_item(_user_id: str, _role: str):
    body = get_json_body()
    facility_id = require_string(body, "facility_id")
    code = require_string(body, "code")
    code_type_raw = require_string(body, "code_type")
    description = require_string(body, "description")
    service_class_raw = require_string(body, "service_class")
    gross = require_int(body, "gross_charge_cents", minimum=0)
    medicare_base = optional_int(body, "medicare_base_cents", minimum=0)
    ancillary_inclusion = optional_enum(body, "ancillary_inclusion", ANCILLARY_INCLUSIONS, default="SEPARATELY_PRICED")
    mandated = optional_bool(body, "cms_shoppable_mandated", default=False)

    # Existence (P3).
    if facility_id not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")

    # Enum membership after FK existence.
    if code_type_raw not in CODE_TYPES:
        raise_err(ERR_INVALID_REQUEST, f"code_type must be one of {sorted(CODE_TYPES)}")
    if service_class_raw not in SERVICE_CLASSES:
        raise_err(ERR_INVALID_REQUEST, f"service_class must be one of {sorted(SERVICE_CLASSES)}")

    # Structural (P6): code unique within the facility.
    for it in db.service_items.values():
        if it["facility_id"] == facility_id and it["code"] == code:
            raise_err(ERR_DUPLICATE_ITEM_CODE, "code already used within this facility")

    item = db.stamp_new({
        "facility_id": facility_id,
        "code": code,
        "code_type": code_type_raw,
        "description": description,
        "service_class": service_class_raw,
        "gross_charge_cents": gross,
        "medicare_base_cents": medicare_base,
        "ancillary_inclusion": ancillary_inclusion,
        "cms_shoppable_mandated": mandated,
        "status": "ACTIVE",
    })
    db.service_items[item["id"]] = item
    return success_object(db.public(item), 201)


@bp.get("/transparency/facilities/<fid>/service-items")
@require_roles(*ALL_ROLES)
def list_facility_items(fid: str, _user_id: str, _role: str):
    if fid not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")
    limit, offset = parse_pagination()
    items = [i for i in db.service_items.values() if i["facility_id"] == fid]
    items = apply_filters(items, ["service_class", "status"])
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(i) for i in page], limit, offset, total)


@bp.patch("/transparency/service-items/<iid>")
@require_roles("TransparencyOfficer")
def patch_item(iid: str, _user_id: str, _role: str):
    # Existence (P3) before everything payload-related.
    item = get_item_or_404(iid)
    body = get_json_body()

    # Payload shape: the OCC field is mandatory; status accepts only RETIRED.
    expected = require_int(body, "expected_service_item_version")
    status_raw = None
    if "status" in body and body["status"] is not None:
        status_raw = require_string(body, "status")
        if status_raw != "RETIRED":
            raise_err(ERR_INVALID_REQUEST, "status may only be patched to RETIRED")
    gross = optional_int(body, "gross_charge_cents", minimum=0)
    medicare_base = optional_int(body, "medicare_base_cents", minimum=0)
    if status_raw is None and gross is None and medicare_base is None:
        raise_err(ERR_INVALID_REQUEST, "No-op payload: provide gross_charge_cents, medicare_base_cents, or status")

    # OCC: the client's observed version must still be current (412).
    if expected != item["version"]:
        raise_err(ERR_STALE_VERSION, "ServiceItem version is stale")

    # State (P4): only ACTIVE items may be patched; retirement is guarded by
    # CERTIFIED/PUBLISHED shoppable lists of the same facility.
    if item["status"] != "ACTIVE":
        raise_err(ERR_ITEM_RETIRED, "Service item is RETIRED")
    if status_raw == "RETIRED":
        for lst in db.shoppable_service_lists.values():
            if lst["facility_id"] != item["facility_id"] or lst["status"] not in ("CERTIFIED", "PUBLISHED"):
                continue
            if any(e.get("service_item_id") == iid for e in lst.get("entries", [])):
                raise_err(ERR_ITEM_IN_CERTIFIED_LIST, "Item is referenced by a CERTIFIED or PUBLISHED shoppable list")

    price_changed = gross is not None or medicare_base is not None
    if gross is not None:
        item["gross_charge_cents"] = gross
    if medicare_base is not None:
        item["medicare_base_cents"] = medicare_base
    if status_raw == "RETIRED":
        item["status"] = "RETIRED"
    db.bump(item)

    # Cascade A: price maintenance ripples item -> rates -> records -> cycles.
    if price_changed:
        cascade_item_prices(item)

    return success_object(db.public(item), 200)
