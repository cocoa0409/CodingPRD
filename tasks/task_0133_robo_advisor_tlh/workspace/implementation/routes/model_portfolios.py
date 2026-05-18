"""Model portfolio endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

from config import ASSET_CLASSES, HORIZON_BANDS, RISK_BANDS
from db import store
from errors import err_allocation_invalid, err_invalid_state
from middleware import require_auth
from response import list_success, success
from routes._helpers import get_json, paginate, parse_pagination, sort_by_created_at
from services.engine import stamp_create
from services.serializers import serialize_model_portfolio

bp = Blueprint("model_portfolios", __name__)


def _validate_allocation(alloc):
    if not isinstance(alloc, dict):
        raise err_allocation_invalid("target_allocation must be an object.")
    total = Decimal(0)
    for c in ASSET_CLASSES:
        v = alloc.get(c)
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err_allocation_invalid(f"target_allocation[{c}] must be a number.")
        if v < 0 or v > 1:
            raise err_allocation_invalid(f"target_allocation[{c}] must be in [0,1].")
        total += Decimal(str(v))
    # Sum must equal exactly 1.000 to three decimal places.
    if total.quantize(Decimal("0.001")) != Decimal("1.000"):
        raise err_allocation_invalid("target_allocation values must sum to exactly 1.000.")


@bp.post("/model-portfolios")
@require_auth(["Advisor"])
def create_model_portfolio():
    body = get_json()
    risk_band = body.get("risk_band")
    horizon_band = body.get("horizon_band")
    if risk_band not in RISK_BANDS:
        raise err_invalid_state(f"risk_band must be one of {RISK_BANDS}.")
    if horizon_band not in HORIZON_BANDS:
        raise err_invalid_state(f"horizon_band must be one of {HORIZON_BANDS}.")
    alloc = body.get("target_allocation")
    _validate_allocation(alloc)
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise err_invalid_state("is_active must be a boolean.")

    with store.lock:
        m = {
            "risk_band": risk_band,
            "horizon_band": horizon_band,
            "target_allocation": dict(alloc),
            "is_active": is_active,
        }
        stamp_create(m, common=False)
        store.model_portfolios[m["id"]] = m
    return success(serialize_model_portfolio(m), 201)


@bp.get("/model-portfolios")
@require_auth(["Advisor", "ComplianceOfficer"])
def list_model_portfolios():
    limit, offset = parse_pagination()
    risk_band = request.args.get("risk_band")
    horizon_band = request.args.get("horizon_band")
    items = list(store.model_portfolios.values())
    if risk_band:
        items = [m for m in items if m["risk_band"] == risk_band]
    if horizon_band:
        items = [m for m in items if m["horizon_band"] == horizon_band]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success(
        [serialize_model_portfolio(m) for m in page], limit, offset, total
    )
