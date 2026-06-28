"""VinReport compilation (PRD §3.6) and RecallRecord endpoints."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from helpers import (check_enum, get_json_body, paginate, parse_pagination,
                     require_fields, serialize, sort_by_created)
from middleware import require_roles
from response import success
from services import calculations as calc
from services.lookups import get_order, get_recall_record, get_vin_report

bp = Blueprint("vin_reports", __name__)

SEVERITIES = {"LOW", "MEDIUM", "HIGH"}


def serialize_vin_report(vr):
    return serialize(vr)


def serialize_recall(rr):
    return serialize(rr)


# ---------------------------------------------------------------------------
# VinReport
# ---------------------------------------------------------------------------
@bp.route("/vin-reports", methods=["POST"])
@require_roles("OpsAdmin")
def compile_vin_report():
    body = get_json_body()
    require_fields(body, ["order_id"])
    order = get_order(body["order_id"])
    vehicle_id = order["vehicle_id"]
    vehicle = db.vehicles[vehicle_id]

    history = [r for r in db.vin_history_records.values() if r["vehicle_id"] == vehicle_id]
    title_records = [r for r in history if r["record_type"] == "TITLE"]
    odo_records = [r for r in history if r["record_type"] == "ODOMETER"]
    brand_records = [r for r in history if r["record_type"] == "BRANDING"]

    title_count = len(title_records)
    worst = calc.worst_branding(brand_records)
    rollback = calc.odometer_rollback(odo_records)

    open_recalls = sum(
        1 for rr in db.recall_records.values()
        if rr["status"] == "OPEN"
        and rr["year"] == vehicle["year"]
        and rr["make"] == vehicle["make"]
        and rr["model"] == vehicle["model"]
    )

    risk = calc.vin_risk_score(worst, title_count, rollback, open_recalls)

    vr = {
        "order_id": order["id"],
        "vehicle_id": vehicle_id,
        "odometer_rollback": rollback,
        "worst_branding": worst,
        "title_count": title_count,
        "open_recall_count": open_recalls,
        "risk_score": risk,
        "status": "COMPILED",
    }
    stamp_create(vr)
    db.vin_reports[vr["id"]] = vr
    return success(serialize_vin_report(vr), status=201)


@bp.route("/vin-reports/<vin_report_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def get_vin_report_ep(vin_report_id):
    vr = get_vin_report(vin_report_id)
    return success(serialize_vin_report(vr), status=200)


@bp.route("/vin-reports", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def list_vin_reports():
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    vehicle_id = request.args.get("vehicle_id")
    items = list(db.vin_reports.values())
    if order_id is not None:
        items = [v for v in items if v["order_id"] == order_id]
    if vehicle_id is not None:
        items = [v for v in items if v["vehicle_id"] == vehicle_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_vin_report(v) for v in page], status=200, pagination=meta)


# ---------------------------------------------------------------------------
# RecallRecord
# ---------------------------------------------------------------------------
@bp.route("/recall-records", methods=["POST"])
@require_roles("OpsAdmin")
def create_recall():
    body = get_json_body()
    require_fields(body, ["campaign_id", "year", "make", "model", "severity"])
    year = body["year"]
    if not isinstance(year, int) or isinstance(year, bool):
        raise err("ERR_INVALID_REQUEST", "year must be an integer")
    check_enum(body["severity"], SEVERITIES, "severity")

    rr = {
        "campaign_id": body["campaign_id"],
        "year": year,
        "make": body["make"],
        "model": body["model"],
        "severity": body["severity"],
        "status": "OPEN",
    }
    stamp_create(rr)
    db.recall_records[rr["id"]] = rr
    return success(serialize_recall(rr), status=201)


@bp.route("/recall-records/<recall_record_id>/close", methods=["POST"])
@require_roles("OpsAdmin")
def close_recall(recall_record_id):
    rr = get_recall_record(recall_record_id)
    rr["status"] = "CLOSED"
    touch(rr)
    return success(serialize_recall(rr), status=200)


@bp.route("/recall-records", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def list_recalls():
    limit, offset = parse_pagination()
    year = request.args.get("year")
    make = request.args.get("make")
    model = request.args.get("model")
    items = list(db.recall_records.values())
    if year is not None:
        try:
            year_int = int(year)
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "year filter must be an integer")
        items = [r for r in items if r["year"] == year_int]
    if make is not None:
        items = [r for r in items if r["make"] == make]
    if model is not None:
        items = [r for r in items if r["model"] == model]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_recall(r) for r in page], status=200, pagination=meta)
