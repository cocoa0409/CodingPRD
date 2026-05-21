"""Rush-hour window endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import err_invalid_input, err_rush_hour_overlap
from ..serializers import serialize_rush_hour_window
from ..services.rush_hour import find_overlapping_rush_hour
from ..store import store
from ..util import new_uuid
from ._helpers import (
    DAY_OF_WEEK_VALUES,
    check_version,
    get_json,
    get_rush_hour_or_404,
    optional_bool,
    optional_number,
    optional_string,
    require_int,
    require_number,
    require_string,
)

bp = Blueprint("rush_hour_windows", __name__)


@bp.route("/rush-hour-windows", methods=["POST"])
@require_roles(["PlatformAdmin"])
def create_window():
    body = get_json()
    label = require_string(body, "label")
    day_of_week = require_string(body, "day_of_week")
    if day_of_week not in DAY_OF_WEEK_VALUES:
        raise err_invalid_input("day_of_week must be one of MON,TUE,WED,THU,FRI,SAT,SUN")
    start_minute = require_int(body, "start_minute", min_value=0, max_value=1439)
    end_minute = require_int(body, "end_minute", min_value=1, max_value=1440)
    if start_minute >= end_minute:
        raise err_invalid_input("start_minute must be < end_minute")
    additive_bonus = require_number(body, "additive_bonus", min_value=0.0, max_value=1.0)

    existing = find_overlapping_rush_hour(day_of_week, start_minute, end_minute)
    if existing is not None:
        raise err_rush_hour_overlap()

    s = store()
    now = s.now()
    wid = new_uuid()
    w = {
        "id": wid,
        "label": label,
        "day_of_week": day_of_week,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "additive_bonus": Decimal(str(additive_bonus)).quantize(Decimal("0.01")),
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("rush_hour_windows", w)
    return jsonify(success_object(serialize_rush_hour_window(w))), 201


@bp.route("/rush-hour-windows", methods=["GET"])
@require_roles(["PlatformAdmin", "Driver", "Rider", "DisputeOps"])
def list_windows():
    limit, offset = parse_pagination()
    items = sorted(store().list_collection("rush_hour_windows"), key=lambda x: x["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_rush_hour_window(x) for x in page], limit=limit, offset=offset, total_count=total
    )), 200


@bp.route("/rush-hour-windows/<window_id>", methods=["PATCH"])
@require_roles(["PlatformAdmin"])
def patch_window(window_id):
    w = get_rush_hour_or_404(window_id)
    body = get_json()
    check_version(w, body)

    new_label = optional_string(body, "label")
    new_bonus = optional_number(body, "additive_bonus", min_value=0.0, max_value=1.0)
    new_active = optional_bool(body, "is_active")

    # Determine the effective is_active for overlap detection.
    effective_active = new_active if new_active is not None else w["is_active"]
    # If reactivating, re-check overlap against existing active windows on the same day.
    if effective_active:
        existing = find_overlapping_rush_hour(
            w["day_of_week"], w["start_minute"], w["end_minute"], exclude_id=window_id
        )
        if existing is not None:
            raise err_rush_hour_overlap()

    if new_label is not None:
        if new_label == "":
            raise err_invalid_input("label must be non-empty")
        w["label"] = new_label
    if new_bonus is not None:
        w["additive_bonus"] = Decimal(str(new_bonus)).quantize(Decimal("0.01"))
    if new_active is not None:
        w["is_active"] = new_active

    s = store()
    w["updated_at"] = s.now()
    w["version"] += 1
    return jsonify(success_object(serialize_rush_hour_window(w))), 200
