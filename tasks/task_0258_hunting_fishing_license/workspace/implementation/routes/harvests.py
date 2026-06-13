"""HarvestReport endpoints (PRD §3.9)."""
from flask import Blueprint, request

import serialize
from db import store, parse_dt
from errors import (
    err, ERR_INVALID_STATE, ERR_SEASON_NOT_OPEN, ERR_BAG_LIMIT_EXCEEDED,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, as_int, parse_pagination, paginate,
)
from services.core import (
    get_license_or_404, get_harvest_report_or_404, counted_quantity_for_season,
)

bp = Blueprint("harvests", __name__)


@bp.route("/harvest-reports", methods=["POST"])
@require_roles("Applicant", "DrawOfficer")
def create_harvest_report():
    body = get_json_body()
    license_id = as_nonempty_str(body, "license_id", required=True)
    harvest_datetime = as_nonempty_str(body, "harvest_datetime", required=True)
    quantity = as_int(body, "quantity", required=True, minimum=1)

    try:
        hdt = parse_dt(harvest_datetime)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "harvest_datetime is not a valid ISO 8601 datetime")

    # FK existence (PRD §2.5).
    lic = get_license_or_404(license_id)

    # State: referenced license must be ISSUED (PRD §3.9).
    if lic["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "License is not ISSUED")

    product = store.license_products.get(lic["license_product_id"])
    season_id = product["species_season_id"] if product else None
    season = store.species_seasons.get(season_id) if season_id else None

    # Season-window gate (ERR_SEASON_NOT_OPEN) before bag-limit gate (PRD §3.9).
    if season is None or season["status"] != "OPEN":
        raise err(ERR_SEASON_NOT_OPEN, "Season is not OPEN")
    s_open = parse_dt(season["season_open"])
    s_close = parse_dt(season["season_close"])
    if not (s_open <= hdt < s_close):
        raise err(ERR_SEASON_NOT_OPEN, "harvest_datetime outside the season window")

    # Bag-limit gate: counted + new quantity must not exceed bag_limit (PRD §3.9).
    counted = counted_quantity_for_season(lic["applicant_id"], season_id)
    if counted + quantity > season["bag_limit"]:
        raise err(ERR_BAG_LIMIT_EXCEEDED, "Harvest exceeds the season bag limit")

    record = {
        "license_id": license_id,
        "harvest_datetime": harvest_datetime,
        "quantity": quantity,
        "status": "SUBMITTED",
    }
    store.stamp_new(record)
    store.harvest_reports[record["id"]] = record
    return success(serialize.harvest_report(record), status=201, response_type="object")


@bp.route("/harvest-reports/<id>", methods=["GET"])
@require_roles("DrawOfficer", "GameWarden", "Applicant")
def get_harvest_report(id):
    record = get_harvest_report_or_404(id)
    return success(serialize.harvest_report(record), status=200, response_type="object")


@bp.route("/harvest-reports", methods=["GET"])
@require_roles("DrawOfficer", "GameWarden", "Applicant")
def list_harvest_reports():
    limit, offset = parse_pagination()
    items = list(store.harvest_reports.values())
    license_id = request.args.get("license_id")
    if license_id is not None:
        items = [r for r in items if r["license_id"] == license_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.harvest_report(r) for r in page], limit, offset, total
    )


@bp.route("/harvest-reports/<id>/accept", methods=["POST"])
@require_roles("GameWarden")
def accept_harvest_report(id):
    record = get_harvest_report_or_404(id)
    if record["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Report is not SUBMITTED")
    record["status"] = "ACCEPTED"
    store.touch(record)  # quantity remains counted (PRD §3.9).
    return success(serialize.harvest_report(record), status=200, response_type="object")


@bp.route("/harvest-reports/<id>/reject", methods=["POST"])
@require_roles("GameWarden")
def reject_harvest_report(id):
    record = get_harvest_report_or_404(id)
    if record["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Report is not SUBMITTED")
    record["status"] = "REJECTED"
    store.touch(record)  # releases quantity from the budget (PRD §3.9).
    return success(serialize.harvest_report(record), status=200, response_type="object")
