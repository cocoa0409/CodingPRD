"""/drivers/{id}/adverse-conditions endpoints."""

from __future__ import annotations

from flask import Blueprint, request as flask_request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import ApiError, ERR_INVALID_INPUT, ERR_NOT_FOUND
from ..serializers import serialize_exemption
from ..services import hos
from ..store import store
from ..timeutil import local_date_str, parse_iso
from ..util import get_pagination, paginate, require_json_body, require_str


adverse_conditions_bp = Blueprint("adverse_conditions", __name__)


@adverse_conditions_bp.post("/drivers/<driver_id>/adverse-conditions")
@require_auth({"Driver"})
def declare_adverse(driver_id: str):
    with store.lock:
        driver = store.drivers.get(driver_id)
        if driver is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
        payload = require_json_body()
        declared_at_iso = require_str(payload, "declared_at", max_len=64)
        try:
            declared_at = parse_iso(declared_at_iso)
        except Exception:
            raise ApiError(ERR_INVALID_INPUT, 400, "declared_at must be a valid ISO 8601 UTC timestamp.")
        reason = require_str(payload, "reason", max_len=2000)
        if len(reason) < 10:
            raise ApiError(ERR_INVALID_INPUT, 400, "reason must be at least 10 characters.")

        tz = driver.get("home_terminal_timezone") or "America/New_York"
        applies_to_log_date = local_date_str(declared_at, tz)

        entity = {
            "driver_id": driver_id,
            "declared_at": declared_at_iso,
            "reason": reason,
            "status": "ACTIVE",
            "extra_minutes_granted": 120,
            "applies_to_log_date": applies_to_log_date,
        }
        store.stamp_create(entity)
        store.adverse_exemptions[entity["id"]] = entity
    return ok_object(serialize_exemption(entity), status=201)


@adverse_conditions_bp.get("/drivers/<driver_id>/adverse-conditions")
@require_auth({"Driver", "CarrierSafetyOfficer", "FMCSAAuditor"})
def list_adverse(driver_id: str):
    driver = store.drivers.get(driver_id)
    if driver is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
    limit, offset = get_pagination()
    status_filter = flask_request.args.get("status")
    items = [e for e in store.adverse_exemptions.values() if e.get("driver_id") == driver_id]
    if status_filter:
        items = [e for e in items if e.get("status") == status_filter]
    items.sort(key=lambda e: e["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_exemption(e) for e in page],
        limit=limit,
        offset=offset,
        total_count=total,
        has_more=has_more,
    )
