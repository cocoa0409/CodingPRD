"""Visit endpoints: list, read, add-ons, photos, start, complete,
weather-reschedule, cancel, and nested reclean-request listing."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
from auth import require_roles
from errors import err
from helpers import (
    ADDON_CODES, body, get_or_404, paginate, pagination_params,
    recompute_route_minutes, req_str, req_enum,
)
from response import success, list_success
from serialize import public, public_list
from visit_ops import generate_visit, requires_high_rise, requires_soft_wash

bp = Blueprint("visits", __name__)


@bp.get("/visits")
def list_visits():
    require_roles({"Customer", "Billing", "Dispatcher", "FieldCrew"})
    limit, offset = pagination_params()
    property_id = request.args.get("property_id")
    agreement_id = request.args.get("agreement_id")
    route_id = request.args.get("route_id")
    rows = list(db.visits.values())
    if property_id is not None:
        rows = [v for v in rows if v["property_id"] == property_id]
    if agreement_id is not None:
        rows = [v for v in rows if v["agreement_id"] == agreement_id]
    if route_id is not None:
        rows = [v for v in rows if v.get("route_id") == route_id]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/visits/<rid>")
def read_visit(rid):
    require_roles({"Customer", "Billing", "Dispatcher", "FieldCrew"})
    rec = get_or_404(db.visits, rid)
    return success(public(rec))


@bp.get("/visits/<rid>/add-ons")
def list_visit_addons(rid):
    require_roles({"Customer", "Billing", "Dispatcher", "FieldCrew"})
    get_or_404(db.visits, rid)
    limit, offset = pagination_params()
    rows = [a for a in db.visit_addons.values() if a["visit_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/visits/<rid>/photos")
def list_visit_photos(rid):
    require_roles({"Customer", "Billing", "Dispatcher", "FieldCrew"})
    get_or_404(db.visits, rid)
    limit, offset = pagination_params()
    rows = [p for p in db.visit_photos.values() if p["visit_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.post("/visits/<rid>/add-ons")
def attach_addon(rid):
    require_roles({"Dispatcher", "FieldCrew"})
    visit = get_or_404(db.visits, rid)
    data = body()
    addon_code = req_enum(data, "addon_code", ADDON_CODES)
    prop = db.properties.get(visit["property_id"])
    charge = calc.addon_charge_cents(addon_code, prop)
    rec = db.new_record(db.visit_addons, {
        "visit_id": rid,
        "addon_code": addon_code,
        "charge_cents": charge,
    })
    return success(public(rec), status=201)


@bp.post("/visits/<rid>/photos")
def upload_photo(rid):
    require_roles({"FieldCrew"})
    visit = get_or_404(db.visits, rid)
    data = body()
    phase = req_enum(data, "phase", {"BEFORE", "AFTER"})
    image_uri = req_str(data, "image_uri")
    rec = db.new_record(db.visit_photos, {
        "visit_id": rid,
        "phase": phase,
        "image_uri": image_uri,
    }, leaner=True)
    return success(public(rec), status=201)


@bp.post("/visits/<rid>/start")
def start_visit(rid):
    require_roles({"FieldCrew"})
    visit = get_or_404(db.visits, rid)
    if visit["schedule_status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Visit is not DISPATCHED")
    before = [p for p in db.visit_photos.values()
              if p["visit_id"] == rid and p["phase"] == "BEFORE"]
    if len(before) != 1:
        raise err("ERR_BEFORE_PHOTO_REQUIRED", "Exactly one BEFORE photo required")
    visit["schedule_status"] = "IN_PROGRESS"
    db.touch(visit)
    return success(public(visit))


@bp.post("/visits/<rid>/complete")
def complete_visit(rid):
    require_roles({"FieldCrew"})
    visit = get_or_404(db.visits, rid)
    if visit["schedule_status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Visit is not IN_PROGRESS")
    after = [p for p in db.visit_photos.values()
             if p["visit_id"] == rid and p["phase"] == "AFTER"]
    if len(after) < 1:
        raise err("ERR_AFTER_PHOTO_REQUIRED", "At least one AFTER photo required")

    agreement = db.agreements.get(visit["agreement_id"])
    # If this is a re-clean remedy visit, its charge is waived (stays 0).
    is_remedy = any(
        rc.get("remedy_visit_id") == rid for rc in db.reclean_requests.values()
    )
    if is_remedy:
        visit["charge_amount_cents"] = 0
    else:
        addon_delta = sum(
            a["charge_cents"] for a in db.visit_addons.values() if a["visit_id"] == rid
        )
        visit["charge_amount_cents"] = calc.visit_charge(
            agreement["per_visit_price_cents"], addon_delta, visit["reschedule_count"]
        )
    visit["schedule_status"] = "COMPLETED"
    db.touch(visit)

    # Recurrence: generate the next visit for RECURRING agreements (non-remedy).
    if not is_remedy and agreement["schedule_kind"] == "RECURRING":
        next_date = _add_days(visit["planned_date"], agreement["recurrence_interval_days"])
        prop = db.properties.get(agreement["property_id"])
        quote = db.quotes.get(agreement["quote_id"])
        generate_visit(
            agreement, next_date, visit["window_start_min"], visit["window_end_min"],
            requires_soft_wash(quote), requires_high_rise(prop),
        )
        agreement["visits_generated_count"] += 1
        db.touch(agreement)

    # If this is a remedy visit, resolve its originating re-clean request.
    if is_remedy:
        for rc in db.reclean_requests.values():
            if rc.get("remedy_visit_id") == rid and rc["status"] == "APPROVED":
                rc["status"] = "RESOLVED"
                db.touch(rc)
    return success(public(visit))


@bp.post("/visits/<rid>/weather-reschedule")
def weather_reschedule(rid):
    require_roles({"Dispatcher"})
    visit = get_or_404(db.visits, rid)
    data = body()
    new_planned_date = req_str(data, "new_planned_date")
    if visit["schedule_status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit is not SCHEDULED")
    route = db.routes.get(visit.get("route_id"))
    region = route["region_code"] if route else None
    # Require a SUSPEND advisory covering the visit's planned_date and region.
    has_hold = any(
        w["severity"] == "SUSPEND"
        and w["region_code"] == region
        and w["advisory_date"] == visit["planned_date"]
        for w in db.weather_advisories.values()
    )
    if not has_hold:
        raise err("ERR_NO_WEATHER_HOLD", "No active SUSPEND advisory for this date/region")

    old_route = route
    visit["route_id"] = None
    visit["schedule_status"] = "UNSCHEDULED"
    visit["planned_date"] = new_planned_date
    visit["reschedule_count"] += 1
    db.touch(visit)
    if old_route is not None:
        recompute_route_minutes(old_route)
    return success(public(visit))


@bp.post("/visits/<rid>/cancel")
def cancel_visit(rid):
    require_roles({"Dispatcher"})
    visit = get_or_404(db.visits, rid)
    if visit["schedule_status"] not in ("UNSCHEDULED", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Visit is not UNSCHEDULED or SCHEDULED")
    old_route_id = visit.get("route_id")
    visit["schedule_status"] = "CANCELLED"
    if old_route_id is not None:
        visit["route_id"] = None
    db.touch(visit)
    if old_route_id is not None:
        route = db.routes.get(old_route_id)
        if route is not None:
            recompute_route_minutes(route)
    return success(public(visit))


@bp.get("/visits/<rid>/reclean-requests")
def list_visit_reclean_requests(rid):
    require_roles({"Customer", "Billing"})
    get_or_404(db.visits, rid)
    limit, offset = pagination_params()
    rows = [rc for rc in db.reclean_requests.values() if rc["visit_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


def _add_days(date_str, days):
    """Add days to a YYYY-MM-DD calendar date, returning YYYY-MM-DD."""
    from datetime import date
    y, m, d = (int(x) for x in date_str.split("-"))
    result = date(y, m, d) + timedelta(days=days)
    return result.isoformat()
