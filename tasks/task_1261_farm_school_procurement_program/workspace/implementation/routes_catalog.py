"""Offerings, forecast lines, kitchens, receiving windows."""
import uuid

from flask import Blueprint

from db import clock_date, new_record, next_seq, now_iso, store, touch
from errors import ApiError
from routes_core import DPA, FM, KM, get_or_404
from services import (find_forecast_line, line_coverage, posture, preference,
                      ser_forecast_line, ser_kitchen, ser_offering, ser_window,
                      window_inside)
from util import (body, ctx, list_response, ok_object, req_enum, req_int, req_str,
                  require_role)

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# FarmProductOffering
# ---------------------------------------------------------------------------

@bp.route("/f2s/offerings", methods=["POST"])
def create_offering():
    uid, role = ctx()
    b = body()
    farm_id = req_str(b, "farm_id")
    year_id = req_str(b, "program_year_id")
    product_id = req_str(b, "product_id")
    price = req_int(b, "price_cents_per_unit", mn=1)
    max_q = req_int(b, "max_weekly_quantity", mn=1)
    hs = req_int(b, "harvest_start_week", mn=1, mx=52)
    he = req_int(b, "harvest_end_week", mn=1, mx=52)
    require_role(role, FM)
    farm = store["farms"].get(farm_id)
    if farm is None:
        raise ApiError("ERR_FARM_NOT_FOUND", "Farm %s not found" % farm_id, 404)
    year = store["program_years"].get(year_id)
    if year is None:
        raise ApiError("ERR_PROGRAM_YEAR_NOT_FOUND", "ProgramYear %s not found" % year_id, 404)
    product = store["products"].get(product_id)
    if product is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product %s not found" % product_id, 404)
    if farm_id != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "FarmManager may only act on its own farm", 403)
    if year["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_YEAR_NOT_OPEN",
                       "Offering creation requires an OPEN program year", 409)
    if farm["status"] != "APPROVED":
        raise ApiError("ERR_FARM_NOT_APPROVED",
                       "Offering creation requires farm APPROVED", 409)
    if product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_NOT_ACTIVE",
                       "Offering creation requires an ACTIVE product", 409)
    if not window_inside(hs, he, product["season_start_week"], product["season_end_week"]):
        raise ApiError("ERR_HARVEST_WINDOW_OUTSIDE_SEASON",
                       "Offering harvest window is not contained in the product season", 409)
    is_local, points = preference(farm["distance_miles_to_hub"],
                                  year["local_radius_miles"],
                                  year["preference_model"])
    rec = new_record()
    rec.update({
        "farm_id": farm_id,
        "program_year_id": year_id,
        "product_id": product_id,
        "price_cents_per_unit": price,
        "max_weekly_quantity": max_q,
        "harvest_start_week": hs,
        "harvest_end_week": he,
        "is_local_eligible": is_local,
        "preference_points": points,
        "status": "DRAFT",
    })
    store["offerings"][rec["id"]] = rec
    return ok_object(ser_offering(rec), 201)


@bp.route("/f2s/offerings", methods=["GET"])
def list_offerings():
    ctx()
    return list_response(store["offerings"].values(), ser_offering, {
        "farm_id": "farm_id", "product_id": "product_id",
        "program_year_id": "program_year_id", "status": "status",
    })


@bp.route("/f2s/offerings/<rid>", methods=["GET"])
def get_offering(rid):
    ctx()
    rec = get_or_404("offerings", rid, "ERR_OFFERING_NOT_FOUND")
    return ok_object(ser_offering(rec))


def _owned_offering(rid, uid):
    rec = get_or_404("offerings", rid, "ERR_OFFERING_NOT_FOUND")
    if rec["farm_id"] != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "FarmManager may only act on its own farm's offerings", 403)
    return rec


@bp.route("/f2s/offerings/<rid>/submit", methods=["POST"])
def submit_offering(rid):
    uid, role = ctx()
    require_role(role, FM)
    rec = _owned_offering(rid, uid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_OFFERING_NOT_SUBMITTABLE", "submit requires status DRAFT", 409)
    farm = store["farms"][rec["farm_id"]]
    if farm["status"] != "APPROVED":
        raise ApiError("ERR_FARM_NOT_APPROVED", "submit requires farm APPROVED", 409)
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok_object(ser_offering(rec))


@bp.route("/f2s/offerings/<rid>/verify", methods=["POST"])
def verify_offering(rid):
    uid, role = ctx()
    require_role(role, DPA)
    rec = get_or_404("offerings", rid, "ERR_OFFERING_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_OFFERING_NOT_VERIFIABLE", "verify requires status SUBMITTED", 409)
    farm = store["farms"][rec["farm_id"]]
    if farm["status"] != "APPROVED":
        raise ApiError("ERR_FARM_NOT_APPROVED", "verify requires farm APPROVED", 409)
    if posture(farm, clock_date()) != "COMPLIANT":
        raise ApiError("ERR_FARM_NOT_COMPLIANT",
                       "Farm compliance posture at the current date is NON_COMPLIANT", 422)
    rec["status"] = "VERIFIED"
    touch(rec)
    return ok_object(ser_offering(rec))


@bp.route("/f2s/offerings/<rid>/reject", methods=["POST"])
def reject_offering(rid):
    uid, role = ctx()
    body()  # optional reason; parsed for shape only
    require_role(role, DPA)
    rec = get_or_404("offerings", rid, "ERR_OFFERING_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_OFFERING_NOT_VERIFIABLE", "reject requires status SUBMITTED", 409)
    rec["status"] = "REJECTED"
    touch(rec)
    return ok_object(ser_offering(rec))


@bp.route("/f2s/offerings/<rid>/withdraw", methods=["POST"])
def withdraw_offering(rid):
    uid, role = ctx()
    require_role(role, FM)
    rec = _owned_offering(rid, uid)
    if rec["status"] not in ("DRAFT", "SUBMITTED", "VERIFIED"):
        raise ApiError("ERR_OFFERING_NOT_WITHDRAWABLE",
                       "withdraw requires status DRAFT, SUBMITTED, or VERIFIED", 409)
    if rec["status"] == "VERIFIED":
        for ag in store["agreements"].values():
            if ag["offering_id"] == rid and ag["status"] in (
                    "PROPOSED", "SIGNED", "AMENDMENT_PROPOSED", "FULFILLING"):
                raise ApiError("ERR_OFFERING_HAS_ACTIVE_AGREEMENTS",
                               "withdraw blocked by active planting agreements", 409)
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return ok_object(ser_offering(rec))


# ---------------------------------------------------------------------------
# MenuForecastLine
# ---------------------------------------------------------------------------

@bp.route("/f2s/forecast-lines", methods=["POST"])
def create_forecast_line():
    uid, role = ctx()
    b = body()
    year_id = req_str(b, "program_year_id")
    product_id = req_str(b, "product_id")
    week = req_int(b, "week_number", mn=1, mx=52)
    planned = req_int(b, "planned_quantity", mn=1)
    require_role(role, DPA)
    year = store["program_years"].get(year_id)
    if year is None:
        raise ApiError("ERR_PROGRAM_YEAR_NOT_FOUND", "ProgramYear %s not found" % year_id, 404)
    product = store["products"].get(product_id)
    if product is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product %s not found" % product_id, 404)
    if year["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_YEAR_NOT_OPEN",
                       "Forecast line creation requires an OPEN program year", 409)
    if find_forecast_line(year_id, product_id, week) is not None:
        raise ApiError("ERR_FORECAST_LINE_EXISTS",
                       "A forecast line already exists for this (year, product, week)", 409)
    rec = new_record()
    rec.update({
        "program_year_id": year_id,
        "product_id": product_id,
        "week_number": week,
        "planned_quantity": planned,
    })
    store["forecast_lines"][rec["id"]] = rec
    return ok_object(ser_forecast_line(rec), 201)


@bp.route("/f2s/forecast-lines", methods=["GET"])
def list_forecast_lines():
    ctx()
    return list_response(store["forecast_lines"].values(), ser_forecast_line, {
        "program_year_id": "program_year_id", "product_id": "product_id",
        "week_number": "week_number",
    })


@bp.route("/f2s/forecast-lines/<rid>", methods=["GET"])
def get_forecast_line(rid):
    ctx()
    rec = get_or_404("forecast_lines", rid, "ERR_FORECAST_LINE_NOT_FOUND")
    return ok_object(ser_forecast_line(rec))


# ---------------------------------------------------------------------------
# Kitchen
# ---------------------------------------------------------------------------

@bp.route("/f2s/kitchens", methods=["POST"])
def create_kitchen():
    uid, role = ctx()
    b = body()
    name = req_str(b, "name")
    require_role(role, DPA)
    rec = new_record()
    rec.update({"name": name})
    store["kitchens"][rec["id"]] = rec
    return ok_object(ser_kitchen(rec), 201)


@bp.route("/f2s/kitchens", methods=["GET"])
def list_kitchens():
    ctx()
    return list_response(store["kitchens"].values(), ser_kitchen, {})


@bp.route("/f2s/kitchens/<rid>", methods=["GET"])
def get_kitchen(rid):
    ctx()
    rec = get_or_404("kitchens", rid, "ERR_KITCHEN_NOT_FOUND")
    return ok_object(ser_kitchen(rec))


# ---------------------------------------------------------------------------
# ReceivingWindow (immutable: id + created_at only)
# ---------------------------------------------------------------------------

@bp.route("/f2s/receiving-windows", methods=["POST"])
def create_window():
    uid, role = ctx()
    b = body()
    kitchen_id = req_str(b, "kitchen_id")
    weekday = req_enum(b, "weekday", {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"})
    start = req_int(b, "start_minute", mn=0, mx=1439)
    end = req_int(b, "end_minute", mn=1, mx=1440)
    capacity = req_int(b, "capacity_deliveries", mn=1)
    require_role(role, KM)
    kitchen = store["kitchens"].get(kitchen_id)
    if kitchen is None:
        raise ApiError("ERR_KITCHEN_NOT_FOUND", "Kitchen %s not found" % kitchen_id, 404)
    if kitchen_id != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "KitchenManager may only act on its own kitchen", 403)
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_minute must be after start_minute", 400)
    for w in store["windows"].values():
        if w["kitchen_id"] == kitchen_id and w["weekday"] == weekday:
            # half-open interval overlap; adjacency (start == other end) is lawful
            if start < w["end_minute"] and w["start_minute"] < end:
                raise ApiError("ERR_WINDOW_OVERLAP",
                               "Window overlaps an existing window on this kitchen/weekday", 409)
    rec = {"id": str(uuid.uuid4()), "created_at": now_iso(), "_seq": next_seq()}
    rec.update({
        "kitchen_id": kitchen_id,
        "weekday": weekday,
        "start_minute": start,
        "end_minute": end,
        "capacity_deliveries": capacity,
    })
    store["windows"][rec["id"]] = rec
    return ok_object(ser_window(rec), 201)


@bp.route("/f2s/receiving-windows", methods=["GET"])
def list_windows():
    ctx()
    return list_response(store["windows"].values(), ser_window,
                         {"kitchen_id": "kitchen_id", "weekday": "weekday"})


@bp.route("/f2s/receiving-windows/<rid>", methods=["GET"])
def get_window(rid):
    ctx()
    rec = get_or_404("windows", rid, "ERR_WINDOW_NOT_FOUND")
    return ok_object(ser_window(rec))


@bp.route("/f2s/receiving-windows/<rid>", methods=["DELETE"])
def delete_window(rid):
    uid, role = ctx()
    require_role(role, KM)
    rec = get_or_404("windows", rid, "ERR_WINDOW_NOT_FOUND")
    if rec["kitchen_id"] != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "KitchenManager may only act on its own kitchen", 403)
    for d in store["deliveries"].values():
        if d["window_id"] == rid and d["status"] in ("SCHEDULED", "CHECKED_IN"):
            raise ApiError("ERR_WINDOW_IN_USE",
                           "Delete blocked by SCHEDULED/CHECKED_IN deliveries in the window", 409)
    del store["windows"][rid]
    return "", 204
