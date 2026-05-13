"""Test-harness endpoints (admin-only)."""

from __future__ import annotations

from flask import Blueprint, request

from db import STORE
from errors import APIError
from middleware import require_auth
from response import success
from services.validate import (
    require_body, get_int, get_enum, get_str,
)
from utils import CLOCK


bp = Blueprint("test_harness", __name__)


SEGMENT_TYPES = {"FLIGHT", "TRAIN", "HOTEL", "CAR"}
EMPLOYEE_LEVELS = {"STAFF", "MANAGER", "DIRECTOR", "EXECUTIVE"}


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(["Admin"])
def advance_clock():
    body = require_body(request.get_json(silent=True))
    seconds = get_int(body, "seconds")
    CLOCK.advance(seconds)
    return success({"advanced_seconds": seconds, "now": CLOCK.now_iso()})


@bp.route("/_external/invoice-verify-result", methods=["POST"])
@require_auth(["Admin"])
def pin_tax_verdict():
    body = require_body(request.get_json(silent=True))
    invoice_id = get_str(body, "invoice_id")
    verdict = get_enum(body, "verdict", {"VALID", "INVALID"})
    STORE.pinned_tax_verdict[invoice_id] = verdict
    return success({"invoice_id": invoice_id, "verdict": verdict})


@bp.route("/_external/booking-options", methods=["POST"])
@require_auth(["Admin"])
def seed_booking_options():
    body = require_body(request.get_json(silent=True))
    seg_type = get_enum(body, "segment_type", SEGMENT_TYPES)
    level = get_enum(body, "employee_level", EMPLOYEE_LEVELS)
    codes = body.get("option_codes")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise APIError("ERR_VALIDATION", "option_codes must be a list of strings", 422)
    STORE.eligible_options[(seg_type, level)] = set(codes)
    return success({
        "segment_type": seg_type,
        "employee_level": level,
        "option_codes": list(codes),
    })
