"""/drivers/{id}/daily-logs endpoints."""

from __future__ import annotations

from datetime import datetime
from flask import Blueprint, request as flask_request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_LOG_NOT_YET_CERTIFIABLE,
    ERR_NOT_FOUND,
)
from ..serializers import serialize_daily_log
from ..services.daily_logs import recompute_log_full
from ..store import store
from ..timeutil import clock, iso_now, local_date_str
from ..util import get_pagination, paginate


daily_logs_bp = Blueprint("daily_logs", __name__)


@daily_logs_bp.get("/drivers/<driver_id>/daily-logs")
@require_auth({"Driver", "CarrierSafetyOfficer", "FMCSAAuditor"})
def list_logs(driver_id: str):
    driver = store.drivers.get(driver_id)
    if driver is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
    limit, offset = get_pagination()
    status_filter = flask_request.args.get("status")
    from_date = flask_request.args.get("from_date")
    to_date = flask_request.args.get("to_date")

    items = [l for l in store.daily_logs.values() if l.get("driver_id") == driver_id]
    if status_filter:
        items = [l for l in items if l.get("status") == status_filter]
    if from_date:
        items = [l for l in items if l["log_date"] >= from_date]
    if to_date:
        items = [l for l in items if l["log_date"] <= to_date]
    items.sort(key=lambda l: l["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_daily_log(l) for l in page],
        limit=limit,
        offset=offset,
        total_count=total,
        has_more=has_more,
    )


@daily_logs_bp.get("/drivers/<driver_id>/daily-logs/<log_id>")
@require_auth({"Driver", "CarrierSafetyOfficer", "FMCSAAuditor"})
def get_log(driver_id: str, log_id: str):
    driver = store.drivers.get(driver_id)
    if driver is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
    log = store.daily_logs.get(log_id)
    if log is None or log.get("driver_id") != driver_id:
        raise ApiError(ERR_NOT_FOUND, 404, "Daily log not found.")
    return ok_object(serialize_daily_log(log))


@daily_logs_bp.post("/drivers/<driver_id>/daily-logs/<log_id>/certify")
@require_auth({"Driver"})
def certify_log(driver_id: str, log_id: str):
    with store.lock:
        driver = store.drivers.get(driver_id)
        if driver is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
        log = store.daily_logs.get(log_id)
        if log is None or log.get("driver_id") != driver_id:
            raise ApiError(ERR_NOT_FOUND, 404, "Daily log not found.")

        # Priority 19: log_date < today in driver's home_terminal_timezone.
        tz = driver.get("home_terminal_timezone") or "America/New_York"
        today_str = local_date_str(clock.now(), tz)
        if log["log_date"] >= today_str:
            raise ApiError(
                ERR_LOG_NOT_YET_CERTIFIABLE,
                422,
                "Log can only be certified after its log_date has passed.",
            )

        # Recertify path is handled by the duty-event edit endpoint.
        # Direct certify only transitions UNCERTIFIED → CERTIFIED.
        if log.get("status") in ("CERTIFIED", "RECERTIFIED"):
            from ..errors import ERR_LOG_ALREADY_CERTIFIED
            raise ApiError(
                ERR_LOG_ALREADY_CERTIFIED, 409, "Daily log is already certified.",
            )

        log["status"] = "CERTIFIED"
        log["certified_at"] = iso_now(clock.now())
        log["certification_count"] = 1
        recompute_log_full(log)
    return ok_object(serialize_daily_log(log))
