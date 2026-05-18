"""Platform endpoints + advance_clock."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_invalid_request
from middleware import require_auth
from response import success
from routes._helpers import get_json, get_platform
from services.engine import advance_clock, stamp_create
from services.serializers import serialize_platform

bp = Blueprint("platforms", __name__)


def _validate_optional_nonneg_int(name: str, value, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"{name} must be a non-negative integer.")
    if value < 0:
        raise err_invalid_request(f"{name} must be a non-negative integer.")
    return value


@bp.post("/platforms")
@require_auth(["PlatformOperator"])
def create_platform():
    body = get_json()
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise err_invalid_request("name is required.")

    currency = body.get("currency", "USD")
    if not isinstance(currency, str) or len(currency) != 3:
        raise err_invalid_request("currency must be a 3-letter ISO-4217 code.")

    origination_fee_bps = _validate_optional_nonneg_int(
        "origination_fee_bps", body.get("origination_fee_bps"), 300
    )
    servicing_fee_bps = _validate_optional_nonneg_int(
        "servicing_fee_bps", body.get("servicing_fee_bps"), 100
    )
    late_fee_cents = _validate_optional_nonneg_int(
        "late_fee_cents", body.get("late_fee_cents"), 2500
    )
    max_borrower_concentration_bps = _validate_optional_nonneg_int(
        "max_borrower_concentration_bps",
        body.get("max_borrower_concentration_bps"),
        1000,
    )

    with store.lock:
        platform = {
            "name": name,
            "currency": currency,
            "clock_day_index": 0,
            "origination_fee_bps": origination_fee_bps,
            "servicing_fee_bps": servicing_fee_bps,
            "late_fee_cents": late_fee_cents,
            "max_borrower_concentration_bps": max_borrower_concentration_bps,
        }
        stamp_create(platform)
        store.platforms[platform["id"]] = platform
    return success(serialize_platform(platform), 201)


@bp.get("/platforms/<platform_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower", "Investor"])
def get_platform_route(platform_id):
    p = get_platform(platform_id)
    return success(serialize_platform(p))


@bp.post("/platforms/<platform_id>/advance_clock")
@require_auth(["PlatformOperator"])
def advance_clock_route(platform_id):
    platform = get_platform(platform_id)
    body = get_json()
    days = body.get("days")
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise err_invalid_request("days must be a positive integer.")

    with store.lock:
        advance_clock(platform, days)
    return success(serialize_platform(platform))
