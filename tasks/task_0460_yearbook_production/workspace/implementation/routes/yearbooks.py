"""Clock + Yearbook routes."""
from flask import Blueprint

from clock import clock, parse_iso
from db import db, stamp_create, sorted_by_created
from middleware import authenticate, authorize
from validators import (
    get_json_body, require, as_str, as_int, as_datetime, parse_pagination, invalid,
)
from lookups import get_yearbook_path
from response import success_object, success_array
import serializers as ser
from services.derive import recompute_yearbook
from services.calculations import per_copy_cost

bp = Blueprint("yearbooks", __name__)


# ---- logical clock (test-driving) ----
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"Adviser"})
    body = get_json_body()
    raw = require(body, "to_iso8601")
    dt = as_datetime(raw, "to_iso8601")
    clock.set(dt)
    from clock import format_iso_millis
    return success_object({"now_iso": format_iso_millis(clock.now())}, 200)


# ---- Yearbook ----
@bp.route("/yearbooks", methods=["POST"])
def create_yearbook():
    _, role = authenticate()
    authorize(role, {"Adviser"})
    body = get_json_body()

    school_name = as_str(require(body, "school_name"), "school_name")
    academic_year = as_str(require(body, "academic_year"), "academic_year")
    target_page_count = as_int(require(body, "target_page_count"), "target_page_count")
    unit_cost_cents = as_int(require(body, "unit_cost_cents"), "unit_cost_cents")
    presale_open = as_datetime(require(body, "presale_open_iso"), "presale_open_iso")
    presale_close = as_datetime(require(body, "presale_close_iso"), "presale_close_iso")

    if target_page_count <= 0 or target_page_count % 4 != 0:
        invalid("target_page_count must be positive and divisible by 4")
    if unit_cost_cents < 0:
        invalid("unit_cost_cents must be >= 0")

    yb = {
        "school_name": school_name,
        "academic_year": academic_year,
        "target_page_count": target_page_count,
        "unit_cost_cents": unit_cost_cents,
        "presale_open_iso": body["presale_open_iso"],
        "presale_close_iso": body["presale_close_iso"],
        "production_phase": "LADDER_BUILD",
        "ladder_filled_count": 0,
        "ladder_complete": False,
        "ad_revenue_cents": 0,
        "presale_revenue_cents": 0,
        "production_cost_cents": 0,
    }
    stamp_create(yb)
    db.yearbooks[yb["id"]] = yb
    return success_object(ser.yearbook(yb), 201)


@bp.route("/yearbooks/<yearbook_id>", methods=["GET"])
def get_yearbook(yearbook_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff", "SalesRep", "Contributor"})
    yb = get_yearbook_path(yearbook_id)
    return success_object(ser.yearbook(yb), 200)


@bp.route("/yearbooks", methods=["GET"])
def list_yearbooks():
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff", "SalesRep", "Contributor"})
    limit, offset = parse_pagination()
    records = sorted_by_created(list(db.yearbooks.values()))
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.yearbook(r) for r in page], limit, offset, total, 200)


@bp.route("/yearbooks/<yearbook_id>/cost-estimate", methods=["GET"])
def cost_estimate(yearbook_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "SalesRep"})
    yb = get_yearbook_path(yearbook_id)
    estimated_quantity = sum(
        o["quantity"] for o in db.presale_orders.values()
        if o["yearbook_id"] == yearbook_id and o["status"] in ("PLACED", "PAID")
    )
    estimated_cost = per_copy_cost(yb["unit_cost_cents"], yb["target_page_count"]) * estimated_quantity
    return success_object({
        "estimated_quantity": estimated_quantity,
        "estimated_cost_cents": estimated_cost,
    }, 200)
