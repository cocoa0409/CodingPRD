"""Request shaping, validation, time, pagination, and path-resolution helpers."""

from datetime import datetime, timezone

from flask import request

from db import store, public
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
    ERR_PLANT_NOT_FOUND,
    ERR_CYLINDER_NOT_FOUND,
    ERR_PRESERVATIVE_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_CHARGE_NOT_FOUND,
    ERR_PIECE_NOT_FOUND,
    ERR_CYCLE_NOT_FOUND,
    ERR_ASSAY_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_DRIP_LOG_NOT_FOUND,
    ERR_WARRANTY_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
)


# ---------------------------------------------------------------------------
# Body parsing / field validation (request shaping — runs before the ordered
# validation cascade per PRD section 2.9)
# ---------------------------------------------------------------------------

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Malformed request body")
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: " + name)
    return body[name]


def as_str(v, name):
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field {} must be a non-empty string".format(name))
    return v


def as_number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field {} must be a number".format(name))
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field {} must be an integer".format(name))
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field {} must be a boolean".format(name))
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_INVALID_ENUM,
            400,
            "Field {} must be one of {}".format(name, ", ".join(sorted(allowed))),
        )
    return v


def as_list(v, name):
    if not isinstance(v, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field {} must be an array".format(name))
    return v


def parse_ts(v, name):
    """Parse an ISO 8601 timestamp to an aware UTC datetime."""
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field {} must be an ISO 8601 timestamp".format(name))
    t = v.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field {} is not a valid ISO 8601 timestamp".format(name))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_query_ts(raw, name):
    if raw is None:
        return None
    try:
        return parse_ts(raw, name)
    except ApiError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter {} is not a valid ISO 8601 timestamp".format(name))


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3): limit default 10, min 1, max 100; offset 0.
# Sort: created_at ascending (oldest first), insertion order as tiebreaker.
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def sorted_items(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paginate(items):
    """Apply sort + pagination; returns (page_dicts, pagination_meta)."""
    limit, offset = pagination_params()
    ordered = sorted_items(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [public(e) for e in page], meta


def query_filter(name):
    return request.args.get(name)


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter {} must be true or false".format(name))


# ---------------------------------------------------------------------------
# Nested path resolution, validated left-to-right (PRD section 2.8). Each
# resolver returns the entity or raises the resource-specific 404.
# ---------------------------------------------------------------------------

def resolve_plant(plant_id):
    plant = store.plants.get(plant_id)
    if plant is None:
        raise ApiError(ERR_PLANT_NOT_FOUND, 404, "TreatmentPlant not found: " + str(plant_id))
    return plant


def resolve_cylinder(cylinder_id, plant=None):
    cyl = store.cylinders.get(cylinder_id)
    if cyl is None or (plant is not None and cyl["plant_id"] != plant["id"]):
        raise ApiError(ERR_CYLINDER_NOT_FOUND, 404, "TreatmentCylinder not found: " + str(cylinder_id))
    return cyl


def resolve_preservative(preservative_id, plant=None):
    pres = store.preservatives.get(preservative_id)
    if pres is None or (plant is not None and pres["plant_id"] != plant["id"]):
        raise ApiError(ERR_PRESERVATIVE_NOT_FOUND, 404, "PreservativeConcentrate not found: " + str(preservative_id))
    return pres


def resolve_customer(customer_id):
    cust = store.customers.get(customer_id)
    if cust is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, 404, "CustomerAccount not found: " + str(customer_id))
    return cust


def resolve_charge(charge_id, plant=None):
    charge = store.charges.get(charge_id)
    if charge is None or (plant is not None and charge["plant_id"] != plant["id"]):
        raise ApiError(ERR_CHARGE_NOT_FOUND, 404, "Charge not found: " + str(charge_id))
    return charge


def resolve_piece(piece_id, charge=None):
    piece = store.pieces.get(piece_id)
    if piece is None or (charge is not None and piece["charge_id"] != charge["id"]):
        raise ApiError(ERR_PIECE_NOT_FOUND, 404, "ChargePiece not found: " + str(piece_id))
    return piece


def resolve_cycle(cycle_id, cylinder=None, charge=None):
    cycle = store.cycles.get(cycle_id)
    if cycle is None:
        raise ApiError(ERR_CYCLE_NOT_FOUND, 404, "TreatmentCycle not found: " + str(cycle_id))
    if cylinder is not None and cycle["cylinder_id"] != cylinder["id"]:
        raise ApiError(ERR_CYCLE_NOT_FOUND, 404, "TreatmentCycle not found: " + str(cycle_id))
    if charge is not None and cycle["charge_id"] != charge["id"]:
        raise ApiError(ERR_CYCLE_NOT_FOUND, 404, "TreatmentCycle not found: " + str(cycle_id))
    return cycle


def resolve_assay(assay_id, charge=None, cycle=None):
    assay = store.assays.get(assay_id)
    if assay is None:
        raise ApiError(ERR_ASSAY_NOT_FOUND, 404, "RetentionAssay not found: " + str(assay_id))
    if charge is not None and assay["charge_id"] != charge["id"]:
        raise ApiError(ERR_ASSAY_NOT_FOUND, 404, "RetentionAssay not found: " + str(assay_id))
    if cycle is not None and assay["cycle_id"] != cycle["id"]:
        raise ApiError(ERR_ASSAY_NOT_FOUND, 404, "RetentionAssay not found: " + str(assay_id))
    return assay


def resolve_inspection(inspection_id, plant=None):
    insp = store.inspections.get(inspection_id)
    if insp is None or (plant is not None and insp["plant_id"] != plant["id"]):
        raise ApiError(ERR_INSPECTION_NOT_FOUND, 404, "QualityInspection not found: " + str(inspection_id))
    return insp


def resolve_drip_log(log_id, charge=None):
    log = store.drip_logs.get(log_id)
    if log is None or (charge is not None and log["charge_id"] != charge["id"]):
        raise ApiError(ERR_DRIP_LOG_NOT_FOUND, 404, "DripPadLog not found: " + str(log_id))
    return log


def resolve_warranty(warranty_id, charge=None):
    war = store.warranties.get(warranty_id)
    if war is None or (charge is not None and war["charge_id"] != charge["id"]):
        raise ApiError(ERR_WARRANTY_NOT_FOUND, 404, "WarrantyRegistration not found: " + str(warranty_id))
    return war


def resolve_slot(slot_id, cylinder=None):
    slot = store.slots.get(slot_id)
    if slot is None or (cylinder is not None and slot["cylinder_id"] != cylinder["id"]):
        raise ApiError(ERR_SLOT_NOT_FOUND, 404, "CylinderScheduleSlot not found: " + str(slot_id))
    return slot
