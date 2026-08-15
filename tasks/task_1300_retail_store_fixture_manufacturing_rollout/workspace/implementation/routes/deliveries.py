"""InstallDelivery endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_KIT_CONFIG_NOT_FOUND,
    ERR_DELIVERY_NOT_FOUND,
    ERR_DELIVERY_INVALID_STATE,
    ERR_KIT_INVALID_STATE,
    ERR_CREW_CAPACITY_EXCEEDED,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import crew_committed_hours, DAILY_CAPACITY_HOURS
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_date,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("deliveries", __name__)


def _get_delivery_or_404(delivery_id: str) -> dict:
    delivery = db.deliveries.get(delivery_id)
    if delivery is None:
        raise_err(ERR_DELIVERY_NOT_FOUND, "InstallDelivery id does not exist")
    return delivery


@bp.route("/install-deliveries", methods=["POST"])
@require_roles("InstallCrewLead")
def create_delivery(_user_id: str, _role: str):
    body = get_json_body()
    kit_id = require_string(body, "kit_id")
    crew_code = require_string(body, "crew_code")
    delivery_date = require_date(body, "delivery_date")
    estimated_install_hours = require_int(body, "estimated_install_hours", minimum=1)

    kit = db.kits.get(kit_id)
    if kit is None:
        raise_err(ERR_KIT_CONFIG_NOT_FOUND, "StoreKitConfig id does not exist")
    if kit["status"] != "RELEASED":
        raise_err(ERR_KIT_INVALID_STATE, "delivery creation requires kit RELEASED")

    committed = crew_committed_hours(crew_code, delivery_date)
    if committed + estimated_install_hours > DAILY_CAPACITY_HOURS:
        raise_err(ERR_CREW_CAPACITY_EXCEEDED, "Crew-day committed hours + estimated_install_hours exceeds 8")

    delivery = {
        "kit_id": kit_id,
        "crew_code": crew_code,
        "delivery_date": delivery_date,
        "estimated_install_hours": estimated_install_hours,
        "status": "SCHEDULED",
    }
    db.stamp_new(delivery)
    db.deliveries[delivery["id"]] = delivery

    # Consume the kit's earliest HELD reservation (start_ts ASC, tie created_at ASC)
    held = [
        r for r in db.reservations.values()
        if r["kit_id"] == kit_id and r["status"] == "HELD"
    ]
    if held:
        held.sort(key=lambda r: (r["_start_dt"], r["created_at"]))
        earliest = held[0]
        earliest["status"] = "CONSUMED"
        db.touch(earliest)

    return success_object(serialize(delivery), 201)


@bp.route("/install-deliveries", methods=["GET"])
@require_roles("Any")
def list_deliveries(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.deliveries.values()))
    items = apply_filters(items, ["kit_id", "crew_code", "delivery_date", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/install-deliveries/<delivery_id>", methods=["GET"])
@require_roles("Any")
def get_delivery(delivery_id: str, _user_id: str, _role: str):
    delivery = _get_delivery_or_404(delivery_id)
    return success_object(serialize(delivery))


@bp.route("/install-deliveries/<delivery_id>/dispatch", methods=["POST"])
@require_roles("InstallCrewLead")
def dispatch_delivery(delivery_id: str, _user_id: str, _role: str):
    delivery = _get_delivery_or_404(delivery_id)
    if delivery["status"] != "SCHEDULED":
        raise_err(ERR_DELIVERY_INVALID_STATE, "dispatch requires delivery SCHEDULED")
    delivery["status"] = "DISPATCHED"
    db.touch(delivery)
    return success_object(serialize(delivery))


@bp.route("/install-deliveries/<delivery_id>/confirm-delivery", methods=["POST"])
@require_roles("InstallCrewLead")
def confirm_delivery(delivery_id: str, _user_id: str, _role: str):
    delivery = _get_delivery_or_404(delivery_id)
    if delivery["status"] != "DISPATCHED":
        raise_err(ERR_DELIVERY_INVALID_STATE, "confirm-delivery requires delivery DISPATCHED")
    delivery["status"] = "DELIVERED"
    db.touch(delivery)
    return success_object(serialize(delivery))


@bp.route("/install-deliveries/<delivery_id>/fail", methods=["POST"])
@require_roles("InstallCrewLead")
def fail_delivery(delivery_id: str, _user_id: str, _role: str):
    delivery = _get_delivery_or_404(delivery_id)
    if delivery["status"] not in ("SCHEDULED", "DISPATCHED"):
        raise_err(ERR_DELIVERY_INVALID_STATE, "fail requires delivery SCHEDULED or DISPATCHED")
    delivery["status"] = "FAILED"
    db.touch(delivery)
    return success_object(serialize(delivery))
