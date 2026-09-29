"""Storage in transit: request, authorization, extension and release (PRD §3.7)."""

from datetime import timedelta

from flask import Blueprint

from db import base_record, by_seq, db, mark_fresh, touch
from errors import ApiError
from middleware import (
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SERVICE_MEMBER,
    ROLE_TSP_COORDINATOR,
    endpoint,
    require_ownership,
)
from paging import list_response
from response import created, ok
from serializers import serialize
from services import calculations as calc
from services import ledger
from validation import get_body, req_dt, req_enum, req_int, req_str

bp = Blueprint("sit", __name__)

_ONE_DAY = timedelta(days=1)


def _period(authorization):
    start = authorization["entry_date"]
    return start, start + timedelta(days=authorization["requested_days"])


@bp.post("/shipments/<shipment_id>/sit-authorizations")
@endpoint([ROLE_TSP_COORDINATOR, ROLE_MOVE_COUNSELOR])
def request_sit(shipment_id):
    body = get_body()
    sit_type = req_enum(body, "sit_type", calc.SIT_TYPES)
    entry_date = req_dt(body, "entry_date")
    requested_days = req_int(body, "requested_days", minimum=1, maximum=calc.SIT_MAX_TOTAL_DAYS)

    shipment = ledger.get_shipment(shipment_id)

    pickup = shipment["actual_pickup_date"]
    if pickup is None or entry_date < pickup:
        raise ApiError("ERR_SIT_ENTRY_BEFORE_PICKUP", "Storage cannot begin before pickup.")

    new_start = entry_date
    new_end = entry_date + timedelta(days=requested_days)
    for existing in db.sit_authorizations.values():
        if existing["shipment_id"] != shipment["id"] or existing["status"] == "RELEASED":
            continue
        old_start, old_end = _period(existing)
        # A mandatory one-day gap: the inclusive ranges may neither overlap nor touch,
        # so widening each range by a day and intersecting catches adjacency too.
        if new_start <= old_end + _ONE_DAY and old_start <= new_end + _ONE_DAY:
            raise ApiError(
                "ERR_SIT_PERIOD_OVERLAP",
                "Storage periods of one shipment must stay a day apart.",
            )

    record = base_record()
    record.update(
        {
            "shipment_id": shipment["id"],
            "sit_type": sit_type,
            "entry_date": entry_date,
            "requested_days": requested_days,
            "authorized_days": 0,
            "extension_days": 0,
            "total_authorized_days": 0,
            "release_date": None,
            "days_used": 0,
            "excess_days": 0,
            "sit_base_cost_usd": calc.ZERO,
            "fuel_surcharge_pct": 0,
            "fuel_surcharge_usd": calc.ZERO,
            "sit_total_cost_usd": calc.ZERO,
            "member_liability_usd": calc.ZERO,
            "status": "REQUESTED",
        }
    )
    mark_fresh(record)
    db.sit_authorizations[record["id"]] = record
    return created(serialize(record))


@bp.get("/shipments/<shipment_id>/sit-authorizations")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_shipment_sit(shipment_id):
    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))
    records = by_seq(
        [s for s in db.sit_authorizations.values() if s["shipment_id"] == shipment["id"]]
    )
    return list_response(records)


@bp.get("/sit-authorizations/<sit_id>")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def read_sit(sit_id):
    authorization = ledger.get_sit(sit_id)
    shipment = db.shipments[authorization["shipment_id"]]
    require_ownership(ledger.member_of_shipment(shipment))
    return ok(serialize(authorization))


@bp.post("/sit-authorizations/<sit_id>/authorize")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def authorize_sit(sit_id):
    body = get_body()
    authorized_days = req_int(body, "authorized_days", minimum=1, maximum=calc.SIT_MAX_TOTAL_DAYS)

    authorization = ledger.get_sit(sit_id)

    if authorization["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_SIT_STATE", "Only a requested storage period may be authorized.")
    shipment = db.shipments[authorization["shipment_id"]]
    if shipment["movement_status"] != "PICKED_UP":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE",
            "Only a picked-up shipment may enter storage.",
        )
    if authorized_days + authorization["extension_days"] > calc.SIT_MAX_TOTAL_DAYS:
        raise ApiError("ERR_SIT_MAX_DAYS_EXCEEDED", "Storage may not exceed 90 days in total.")

    authorization["authorized_days"] = authorized_days
    authorization["total_authorized_days"] = authorized_days + authorization["extension_days"]
    authorization["status"] = "AUTHORIZED"
    touch(authorization)

    shipment["movement_status"] = "IN_SIT"
    touch(shipment)
    ledger.create_notification(shipment["id"], "SIT_ENTRY")
    return ok(serialize(authorization))


@bp.post("/sit-authorizations/<sit_id>/extend")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def extend_sit(sit_id):
    body = get_body()
    extension_days = req_int(body, "extension_days", minimum=1, maximum=calc.SIT_MAX_TOTAL_DAYS)
    req_str(body, "extension_reason")

    authorization = ledger.get_sit(sit_id)

    if authorization["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_SIT_STATE", "Only an authorized storage period may be extended.")
    accumulated = authorization["extension_days"] + extension_days
    if authorization["authorized_days"] + accumulated > calc.SIT_MAX_TOTAL_DAYS:
        raise ApiError("ERR_SIT_MAX_DAYS_EXCEEDED", "Storage may not exceed 90 days in total.")

    authorization["extension_days"] = accumulated
    authorization["total_authorized_days"] = authorization["authorized_days"] + accumulated
    touch(authorization)
    return ok(serialize(authorization))


@bp.post("/sit-authorizations/<sit_id>/release")
@endpoint([ROLE_TSP_COORDINATOR])
def release_sit(sit_id):
    body = get_body()
    release_date = req_dt(body, "release_date")

    authorization = ledger.get_sit(sit_id)

    if authorization["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_SIT_STATE", "Only an authorized storage period may be released.")
    if release_date < authorization["entry_date"]:
        raise ApiError("ERR_RELEASE_BEFORE_ENTRY", "Release cannot precede entry.")

    shipment = db.shipments[authorization["shipment_id"]]
    costs = calc.sit_costs(
        authorization["entry_date"],
        release_date,
        authorization["total_authorized_days"],
        shipment["billable_weight_lbs"],
    )
    authorization["release_date"] = release_date
    authorization["days_used"] = costs["days_used"]
    authorization["excess_days"] = costs["excess_days"]
    authorization["sit_base_cost_usd"] = costs["sit_base_cost_usd"]
    authorization["fuel_surcharge_pct"] = costs["fuel_surcharge_pct"]
    authorization["fuel_surcharge_usd"] = costs["fuel_surcharge_usd"]
    authorization["sit_total_cost_usd"] = costs["sit_total_cost_usd"]
    authorization["member_liability_usd"] = costs["member_liability_usd"]
    authorization["status"] = "RELEASED"
    touch(authorization)

    still_stored = any(
        other["shipment_id"] == shipment["id"] and other["status"] == "AUTHORIZED"
        for other in db.sit_authorizations.values()
    )
    if not still_stored and shipment["movement_status"] == "IN_SIT":
        shipment["movement_status"] = "PICKED_UP"
        touch(shipment)
    return ok(serialize(authorization))
