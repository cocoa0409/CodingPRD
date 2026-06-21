"""Shared route helpers: existence lookups (404), FK resolution (422),
pagination (with bounds enforcement), and list serialization.
"""

from flask import request

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from db import store
from errors import err
from models import serialize


# ---- path existence lookups (ERR_NOT_FOUND, priority 3) ----
def get_carrier_or_404(cid):
    rec = store.carriers.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Carrier not found")
    return rec


def get_reefer_unit_or_404(uid):
    rec = store.reefer_units.get(uid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Reefer unit not found")
    return rec


def get_temp_lane_or_404(lid):
    rec = store.temp_lanes.get(lid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Temp lane not found")
    return rec


def get_shipment_or_404(sid):
    rec = store.shipments.get(sid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Shipment not found")
    return rec


def get_compartment_or_404(cid):
    rec = store.compartments.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Compartment not found")
    return rec


def get_product_lot_or_404(lid):
    rec = store.product_lots.get(lid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Product lot not found")
    return rec


def get_sensor_reading_or_404(rid):
    rec = store.sensor_readings.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Sensor reading not found")
    return rec


def get_claim_or_404(cid):
    rec = store.spoilage_claims.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Spoilage claim not found")
    return rec


def get_stop_or_404(sid):
    rec = store.stop_events.get(sid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Stop event not found")
    return rec


# ---- pagination (PRD §2.3; out-of-bounds -> ERR_INVALID_REQUEST priority 18) ----
def pagination_params():
    """Parse limit/offset query params with defaults & bounds.

    Out-of-range or non-integer values are rejected with ERR_INVALID_REQUEST
    (PRD §2.3: a limit/offset outside the bounds is a malformed request).
    """
    limit = _parse_int_param(
        "limit", default=PAGE_LIMIT_DEFAULT, minimum=PAGE_LIMIT_MIN, maximum=PAGE_LIMIT_MAX
    )
    offset = _parse_int_param(
        "offset", default=PAGE_OFFSET_DEFAULT, minimum=0, maximum=None
    )
    return limit, offset


def _parse_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Query param %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "Query param %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "Query param %s must be <= %s" % (name, maximum))
    return value


def paginate(records, limit, offset):
    """Sort ascending by created_at (then creation sequence) then slice.

    Returns (page_of_serialized_records, total_count).
    """
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], total
