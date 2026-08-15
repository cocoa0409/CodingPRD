"""PackagingComponent endpoints: creation with initial stock, read (with the
derived available_units), and OCC-guarded stock adjustment with the
on_hand >= reserved floor."""
from flask import Blueprint

from db import STORE
from errors import (
    err,
    ERR_COMPONENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_STOCK_BELOW_RESERVED,
)
from middleware import require_roles
from response import success
from services.core import find_or_404, new_record, serialize, touch
from util import as_int, as_str, body_json, check_enum, req

bp = Blueprint("components", __name__)

COMPONENT_TYPES = ("BOTTLE", "CAP", "LABEL", "CASE")


def component_view(rec):
    """available_units = on_hand_units - reserved_units (derived, §3.4)."""
    out = serialize(rec)
    out["available_units"] = rec["on_hand_units"] - rec["reserved_units"]
    return out


@bp.post("/copack/packaging-components")
def create_component():
    require_roles("OpsAdmin")
    body = body_json()
    component_name = as_str(req(body, "component_name"), "component_name")
    component_type = check_enum(
        as_str(req(body, "component_type"), "component_type"),
        COMPONENT_TYPES, "component_type",
    )
    unit_cost_cents = as_int(req(body, "unit_cost_cents"), "unit_cost_cents")
    if unit_cost_cents < 0:
        raise err(ERR_INVALID_REQUEST, 400, "unit_cost_cents must be >= 0")
    initial_on_hand_units = as_int(req(body, "initial_on_hand_units"), "initial_on_hand_units")
    if initial_on_hand_units < 0:
        raise err(ERR_INVALID_REQUEST, 400, "initial_on_hand_units must be >= 0")
    rec = new_record({
        "component_name": component_name,
        "component_type": component_type,
        "unit_cost_cents": unit_cost_cents,
        "on_hand_units": initial_on_hand_units,
        "reserved_units": 0,
    })
    STORE.components[rec["id"]] = rec
    return success(component_view(rec), 201)


@bp.get("/copack/packaging-components/<cid>")
def get_component(cid):
    require_roles("OpsAdmin", "QAReviewer")
    rec = find_or_404(STORE.components, cid, ERR_COMPONENT_NOT_FOUND, "packaging component")
    return success(component_view(rec))


@bp.put("/copack/packaging-components/<cid>")
def adjust_component(cid):
    require_roles("OpsAdmin")
    rec = find_or_404(STORE.components, cid, ERR_COMPONENT_NOT_FOUND, "packaging component")
    body = body_json()
    on_hand_units = as_int(req(body, "on_hand_units"), "on_hand_units")
    if on_hand_units < 0:
        raise err(ERR_INVALID_REQUEST, 400, "on_hand_units must be >= 0")
    expected = as_int(req(body, "expected_component_version"), "expected_component_version")
    # Optimistic concurrency (§2.5).
    if rec["version"] != expected:
        raise err(ERR_STALE_VERSION, 412, "expected_component_version does not match the current version")
    # The stock floor: on_hand_units never drops below reserved_units (§3.4).
    if on_hand_units < rec["reserved_units"]:
        raise err(ERR_STOCK_BELOW_RESERVED, 409, "on_hand_units may not fall below reserved_units")
    rec["on_hand_units"] = on_hand_units
    touch(rec)
    return success(component_view(rec))
