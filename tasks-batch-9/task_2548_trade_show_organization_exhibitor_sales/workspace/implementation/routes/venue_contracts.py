"""Venue contract endpoints (PRD 3.1)."""
import copy

from flask import Blueprint, request

import calc
import guards
import services
import validate
import views
from db import base_row, db, fmt_dt, now, touch
from middleware import (FLOOR_MANAGER, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, list_response, object_response, pagination
from validate import CODE_RE

bp = Blueprint("venue_contracts", __name__)


@bp.route("/venue-contracts", methods=["POST"])
def create_venue_contract():
    body = validate.body()
    venue_code = validate.text(body, "venue_code", 1, 32, pattern=CODE_RE)
    hall_code = validate.text(body, "hall_code", 1, 32, pattern=CODE_RE)
    hall_gross_sqft = validate.integer(body, "hall_gross_sqft", minimum=1)
    min_aisle_ratio_pct = validate.integer(body, "min_aisle_ratio_pct", minimum=0, maximum=90)
    max_booth_height_ft = validate.integer(body, "max_booth_height_ft", minimum=1)
    contract_year_start = validate.integer(body, "contract_year_start", minimum=2026)
    contract_year_count = validate.integer(body, "contract_year_count", minimum=1, maximum=10)
    committed = validate.integer(body, "committed_net_sqft_per_year", minimum=1)
    attrition_allowance_pct = validate.integer(body, "attrition_allowance_pct",
                                               minimum=0, maximum=100)
    advance_order_discount_pct = validate.integer(body, "advance_order_discount_pct",
                                                  minimum=0, maximum=60)
    labor_rate = validate.integer(body, "labor_rate_cents_per_hour", minimum=1)
    electrical_rate = validate.integer(body, "electrical_rate_cents_per_amp", minimum=1)
    material_rate = validate.integer(body, "material_handling_rate_cents_per_cwt", minimum=1)
    schedule = validate.fee_schedule(body, "cancellation_fee_schedule", required=False,
                                     default=None)
    if schedule is None:
        schedule = copy.deepcopy(calc.DEFAULT_CANCELLATION_FEE_SCHEDULE)

    authenticate((SHOW_DIRECTOR,))

    row = base_row()
    row.update({
        "venue_code": venue_code,
        "hall_code": hall_code,
        "hall_gross_sqft": hall_gross_sqft,
        "min_aisle_ratio_pct": min_aisle_ratio_pct,
        "max_booth_height_ft": max_booth_height_ft,
        "contract_year_start": contract_year_start,
        "contract_year_count": contract_year_count,
        "committed_net_sqft_per_year": committed,
        "attrition_allowance_pct": attrition_allowance_pct,
        "advance_order_discount_pct": advance_order_discount_pct,
        "labor_rate_cents_per_hour": labor_rate,
        "electrical_rate_cents_per_amp": electrical_rate,
        "material_handling_rate_cents_per_cwt": material_rate,
        "cancellation_fee_schedule": schedule,
        "status": "DRAFT",
        "executed_at": None,
        "terminated_effective_date": None,
    })
    db.venue_contracts[row["id"]] = row
    return created(views.venue_contract_view(row))


@bp.route("/venue-contracts/<contract_id>", methods=["GET"])
def read_venue_contract(contract_id):
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER))
    row = guards.get_venue_contract(contract_id)
    return object_response(views.venue_contract_view(row))


@bp.route("/venue-contracts/<contract_id>/execute", methods=["POST"])
def execute_venue_contract(contract_id):
    authenticate((SHOW_DIRECTOR,))
    row = guards.get_venue_contract(contract_id)
    guards.require_venue_draft(row)
    zero_buckets = [b for b in row["cancellation_fee_schedule"] if b["min_days_out"] == 0]
    if len(zero_buckets) != 1:
        validate.bad("cancellation_fee_schedule must hold exactly one zero-day bucket")
    row["status"] = "EXECUTED"
    row["executed_at"] = fmt_dt(now())
    touch(row)
    return object_response(views.venue_contract_view(row))


@bp.route("/venue-contracts/<contract_id>/terminate", methods=["POST"])
def terminate_venue_contract(contract_id):
    body = validate.body()
    expected_version = validate.integer(body, "expected_venue_contract_version", minimum=0)
    effective_date = validate.date_field(body, "terminated_effective_date")
    reason = validate.text(body, "reason", 1, 500, required=False, default=None)

    authenticate((SHOW_DIRECTOR,))
    row = guards.get_venue_contract(contract_id)
    guards.require_venue_executed(row)
    guards.check_venue_version(row, expected_version)
    services.terminate_venue_contract(row, effective_date, reason)
    return object_response(views.venue_contract_view(row))


@bp.route("/venue-contracts/<contract_id>/shows", methods=["GET"])
def list_venue_contract_shows(contract_id):
    limit, offset = pagination()
    status = request.args.get("status")
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER))
    row = guards.get_venue_contract(contract_id)
    from db import by_created
    shows = by_created(calc.venue_shows(row["id"]))
    if status:
        shows = [s for s in shows if s["status"] == status]
    return list_response([views.show_view(s) for s in shows], limit, offset)
