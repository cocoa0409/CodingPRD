"""Service-order scheduling rules: account data, window shape, lead time and
half-open window conflicts."""

from datetime import timedelta

import db
from errors import ApiError
from services import enums


# --------------------------------------------- rung 24: required account data
def check_account_data(provider, account_data):
    for field in provider["required_account_fields"]:
        if field not in account_data:
            raise ApiError(
                "ERR_MISSING_ACCOUNT_DATA",
                "account_data is missing required field '%s'." % field,
            )
        value = account_data[field]
        if value is None:
            raise ApiError(
                "ERR_MISSING_ACCOUNT_DATA",
                "account_data field '%s' must not be empty." % field,
            )
        if isinstance(value, str) and not value.strip():
            raise ApiError(
                "ERR_MISSING_ACCOUNT_DATA",
                "account_data field '%s' must not be empty." % field,
            )


# ------------------------------------------- rung 30: service window validity
def check_service_window(requested_date, window_start, window_end):
    if window_start >= window_end:
        raise ApiError(
            "ERR_INVALID_SERVICE_WINDOW",
            "scheduled_window_start must be strictly before scheduled_window_end.",
        )
    if window_start.date() != requested_date or window_end.date() != requested_date:
        raise ApiError(
            "ERR_INVALID_SERVICE_WINDOW",
            "Both window bounds must fall on the requested_service_date.",
        )
    if window_end - window_start > timedelta(hours=enums.MAX_SERVICE_WINDOW_HOURS):
        raise ApiError(
            "ERR_INVALID_SERVICE_WINDOW",
            "The service window may not span more than %d hours."
            % enums.MAX_SERVICE_WINDOW_HOURS,
        )


# ----------------------------------------------------- rung 31: lead time
def check_lead_time(provider, order, requested_date):
    if order["order_kind"] == "STOP" and provider["same_day_stop_allowed"]:
        return
    earliest = db.clock_date() + timedelta(days=provider["scheduling_lead_days"])
    if requested_date < earliest:
        raise ApiError(
            "ERR_LEAD_TIME_VIOLATION",
            "requested_service_date must be on or after %s." % earliest.isoformat(),
        )


# -------------------------------------------------- rung 32: window conflicts
def check_window_conflict(order, window_start, window_end):
    for other in db.db.orders.values():
        if other["id"] == order["id"]:
            continue
        if other["service_address_id"] != order["service_address_id"]:
            continue
        if other["utility_type"] != order["utility_type"]:
            continue
        if other["provision_status"] not in ("SCHEDULED", "ACTIVE_SERVICE"):
            continue
        other_start = db.parse_ts(other["scheduled_window_start"])
        other_end = db.parse_ts(other["scheduled_window_end"])
        if other_start is None or other_end is None:
            continue
        if window_start < other_end and other_start < window_end:
            raise ApiError(
                "ERR_SERVICE_WINDOW_CONFLICT",
                "The requested window overlaps an existing scheduled window.",
            )
