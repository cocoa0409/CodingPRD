"""Recurring series routes: create (with occurrence generation), list, get, end."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from errors import err
from db import db, parse_iso, iso_millis
from middleware import get_caller, require_roles
from response import object_response, array_response
from services import core, reqs
from services import booking_svc as bsvc

bp = Blueprint("series", __name__)


@bp.route("/recurring-series", methods=["POST"])
def create_series():
    caller = get_caller()
    require_roles(caller, {"Client", "Dispatcher"})
    data = reqs.body()
    client_id = reqs.require_str(data, "client_id")
    category_id = reqs.require_str(data, "category_id")
    tasker_id = reqs.require_str(data, "tasker_id")
    # existence left-to-right: client, category, tasker
    core.get_client_or_404(client_id)
    category = core.get_category_or_404(category_id)
    core.get_tasker_or_404(tasker_id)
    if caller.role == "Client" and caller.user_id != client_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Client may only create own series")
    if category["status"] == "RETIRED":
        raise err(errors.ERR_CATEGORY_RETIRED, "Category is retired")

    frequency = reqs.require_enum(data, "frequency", {"WEEKLY", "BIWEEKLY"})
    first_raw = reqs.require(data, "first_start")
    try:
        first_dt = parse_iso(first_raw)
    except (ValueError, TypeError):
        reqs.invalid("first_start must be an ISO 8601 instant")
    occurrence_count = reqs.require_int(data, "occurrence_count", minimum=2, maximum=12)

    estimated_hours = None
    if category["pricing_model"] == "HOURLY":
        estimated_hours = reqs.require_number(data, "estimated_hours", minimum=0.25)

    series = {
        "client_id": client_id,
        "category_id": category_id,
        "tasker_id": tasker_id,
        "frequency": frequency,
        "first_start": iso_millis(first_dt),
        "occurrence_count": occurrence_count,
        "estimated_hours": estimated_hours,
        "status": "ACTIVE",
        "generated_count": 0,
    }
    core.stamp_create(series)
    db.recurring_series[series["id"]] = series

    step_days = 7 if frequency == "WEEKLY" else 14
    for i in range(occurrence_count):
        occ_start = first_dt + timedelta(days=step_days * i)
        booking = bsvc.build_booking(
            client_id=client_id, category_id=category_id, dispatch_mode="SCHEDULED",
            scheduled_start_dt=occ_start, estimated_hours=estimated_hours,
            tip_cents=0, series_id=series["id"], status="OFFERED",
        )
        # publish directly into OFFERED: pin quote + window like a one-off offer
        bsvc.apply_offer(booking, category)
        db.bookings[booking["id"]] = booking
    series["generated_count"] = occurrence_count

    return object_response(core.serialize(series), status=201)


@bp.route("/recurring-series", methods=["GET"])
def list_series():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client"})
    limit, offset = core.parse_pagination(request.args)
    items = list(db.recurring_series.values())
    for key in ("client_id", "category_id", "tasker_id"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    window, meta = core.paginate(items, limit, offset)
    return array_response([core.serialize(s) for s in window], pagination=meta)


@bp.route("/recurring-series/<sid>", methods=["GET"])
def get_series(sid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client"})
    s = core.get_series_or_404(sid)
    return object_response(core.serialize(s))


@bp.route("/recurring-series/<sid>/end", methods=["POST"])
def end_series(sid):
    caller = get_caller()
    require_roles(caller, {"Client", "Dispatcher"})
    s = core.get_series_or_404(sid)
    if caller.role == "Client" and caller.user_id != s["client_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Client may only end own series")
    if s["status"] != "ACTIVE":
        raise err(errors.ERR_SERIES_INVALID_STATE, "Series is not ACTIVE")
    s["status"] = "ENDED"
    core.touch(s)
    # cascade: cancel future not-yet-started occurrences (DRAFT/OFFERED) as SYSTEM, no fee
    for b in db.bookings.values():
        if b.get("series_id") == sid and b["status"] in ("DRAFT", "OFFERED"):
            b["status"] = "CANCELLED"
            b["cancelled_by"] = "SYSTEM"
            core.touch(b)
    return object_response(core.serialize(s))
