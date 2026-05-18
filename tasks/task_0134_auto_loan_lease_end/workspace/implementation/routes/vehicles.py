"""Vehicle endpoints — PRD §3.2."""
from __future__ import annotations

from flask import Blueprint, request

from config import (
    RESIDUAL_FACTOR_MAX_BPS,
    RESIDUAL_FACTOR_MIN_BPS,
    ROLE_CUSTOMER,
    ROLE_FINANCE_MANAGER,
    ROLE_LOAN_OFFICER,
    ROLE_PLATFORM_ADMIN,
    VIN_LENGTH,
)
from db import store
from errors import err_invalid_request
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    get_json,
    paginate,
    parse_pagination,
    sort_by_created_at,
)
from services.engine import get_vehicle_or_404, stamp_create, stamp_update
from services.serializers import serialize_vehicle

bp = Blueprint("vehicles", __name__)


VEHICLE_STATUSES = {"AVAILABLE", "RESERVED", "SOLD", "LEASED"}


# ── POST /vehicles ──────────────────────────────────────────────────────────


@bp.post("/vehicles")
@require_auth([ROLE_PLATFORM_ADMIN])
def create_vehicle():
    body = get_json()
    vin = body.get("vin")
    if not isinstance(vin, str) or len(vin) != VIN_LENGTH:
        raise err_invalid_request(f"vin must be a string of length {VIN_LENGTH}.")
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise err_invalid_request("model is required (string).")
    msrp_cents = body.get("msrp_cents")
    if msrp_cents is None or isinstance(msrp_cents, bool) or not isinstance(msrp_cents, int):
        raise err_invalid_request("msrp_cents must be an integer.")
    if msrp_cents <= 0:
        raise err_invalid_request("msrp_cents must be > 0.")
    residual = body.get("residual_factor_bps")
    if residual is None or isinstance(residual, bool) or not isinstance(residual, int):
        raise err_invalid_request("residual_factor_bps must be an integer.")
    if residual < RESIDUAL_FACTOR_MIN_BPS or residual > RESIDUAL_FACTOR_MAX_BPS:
        raise err_invalid_request(
            f"residual_factor_bps must be in [{RESIDUAL_FACTOR_MIN_BPS}, {RESIDUAL_FACTOR_MAX_BPS}]."
        )

    with store.lock:
        if vin in store.vins:
            raise err_invalid_request("vin must be unique across vehicles.")
        v = {
            "vin": vin,
            "model": model,
            "msrp_cents": msrp_cents,
            "residual_factor_bps": residual,
            "status": "AVAILABLE",
        }
        stamp_create(v)
        store.vehicles[v["id"]] = v
        store.vins.add(vin)
    return success(serialize_vehicle(v), 201)


# ── GET /vehicles/{vehicleId} ───────────────────────────────────────────────


@bp.get("/vehicles/<vehicle_id>")
@require_auth([ROLE_PLATFORM_ADMIN, ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER, ROLE_CUSTOMER])
def get_vehicle(vehicle_id):
    v = get_vehicle_or_404(vehicle_id)
    return success(serialize_vehicle(v))


# ── GET /vehicles ───────────────────────────────────────────────────────────


@bp.get("/vehicles")
@require_auth([ROLE_PLATFORM_ADMIN, ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER, ROLE_CUSTOMER])
def list_vehicles():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in VEHICLE_STATUSES:
        raise err_invalid_request(
            f"status must be one of {sorted(VEHICLE_STATUSES)}."
        )
    items = list(store.vehicles.values())
    if status_filter is not None:
        items = [v for v in items if v["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize_vehicle(v) for v in page], limit, offset, total)
