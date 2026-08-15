"""WorkOrder endpoints (PRD §3.2): create, quote, confirm, amend (OCC),
start-production, deliver, accept-delivery, cancel."""
from datetime import timedelta
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, now, stamp_new, touch
from errors import (
    ApiError,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_MEDIA_NOT_CLEARED,
    ERR_QUOTE_EXPIRED,
    ERR_STALE_WORK_ORDER_VERSION,
    ERR_TIER_DURATION_INCOMPATIBLE,
    ERR_COMPLAINTS_STILL_OPEN,
    invalid_transition,
    not_found,
    validation,
)
from respond import list_response, ok_object
from serialize import order_active_complaint_count
from services import workflow
from services.pricing import TURNAROUND_TIERS, compute_due_at, program_minutes, quote_price_cents
from util import opt_enum, opt_str, req_enum, req_int, req_str, is_int

bp = Blueprint("work_orders", __name__)

SERVICE_TYPES = {"CAPTIONS", "AUDIO_DESCRIPTION", "BUNDLE"}


def get_order(order_id):
    o = DB.work_orders.get(order_id)
    if o is None:
        raise not_found("Work order not found")
    return o


def _check_same_day_tier(tier, duration_seconds):
    """SAME_DAY is reserved for short programs: media longer than sixty
    minutes is rejected at creation and at amendment."""
    if tier == "SAME_DAY" and program_minutes(duration_seconds) > 60:
        raise ApiError(
            ERR_TIER_DURATION_INCOMPATIBLE,
            422,
            "SAME_DAY tier requested for media longer than 60 minutes",
        )


@bp.post("/caption-ad/work-orders")
@guarded({"IntakeCoordinator"})
def create_work_order(_user_id, _role):
    data = body()
    # Body FKs resolve left to right.
    client_id = data.get("client_id")
    if not isinstance(client_id, str) or client_id not in DB.clients:
        raise not_found("Referenced client_id does not exist")
    media_asset_id = data.get("media_asset_id")
    if not isinstance(media_asset_id, str) or media_asset_id not in DB.media_assets:
        raise not_found("Referenced media_asset_id does not exist")
    service_type = req_enum(data, "service_type", SERVICE_TYPES)
    turnaround_tier = req_enum(data, "turnaround_tier", TURNAROUND_TIERS)
    language = req_str(data, "language")
    media = DB.media_assets[media_asset_id]
    _check_same_day_tier(turnaround_tier, media["duration_seconds"])
    rec = {
        "client_id": client_id,
        "media_asset_id": media_asset_id,
        "service_type": service_type,
        "turnaround_tier": turnaround_tier,
        "language": language,
        "order_status": "DRAFT",
        "quoted_price_cents": None,
        "quote_expires_at": None,
        "due_at": None,
        "sla_breached": False,
        "delivered_at": None,
    }
    stamp_new(rec)
    DB.work_orders[rec["id"]] = rec
    return ok_object(serialize.work_order(rec), status=201)


@bp.get("/caption-ad/work-orders")
@guarded(set(ALL_ROLES))
def list_work_orders(_user_id, _role):
    records = list(DB.work_orders.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        records = [r for r in records if r["client_id"] == client_id]
    media_asset_id = request.args.get("media_asset_id")
    if media_asset_id is not None:
        records = [r for r in records if r["media_asset_id"] == media_asset_id]
    status = request.args.get("order_status")
    if status is not None:
        records = [r for r in records if r["order_status"] == status]
    return list_response(records, serialize.work_order)


@bp.get("/caption-ad/work-orders/<workOrderId>")
@guarded(set(ALL_ROLES))
def get_one_work_order(workOrderId, _user_id, _role):
    return ok_object(serialize.work_order(get_order(workOrderId)))


@bp.post("/caption-ad/work-orders/<workOrderId>/quote")
@guarded({"IntakeCoordinator"})
def quote_work_order(workOrderId, _user_id, _role):
    o = get_order(workOrderId)
    if o["order_status"] not in ("DRAFT", "QUOTE_EXPIRED"):
        raise invalid_transition("Only a DRAFT or QUOTE_EXPIRED order can be quoted")
    media = DB.media_assets[o["media_asset_id"]]
    if media["intake_status"] == "REJECTED_INTAKE":
        raise invalid_transition("A work order referencing a rejected asset can never be quoted")
    client = DB.clients[o["client_id"]]
    o["quoted_price_cents"] = quote_price_cents(
        o["turnaround_tier"], media["duration_seconds"], o["language"], client["ytd_completed_minutes"]
    )
    o["quote_expires_at"] = now() + timedelta(hours=72)
    o["order_status"] = "QUOTED"
    touch(o)
    return ok_object(serialize.work_order(o))


@bp.post("/caption-ad/work-orders/<workOrderId>/confirm")
@guarded({"ClientContact"})
def confirm_work_order(workOrderId, _user_id, _role):
    o = get_order(workOrderId)
    # Ownership: the acting client must own the order.
    if o["client_id"] != _user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "The acting client does not own this order")
    if o["order_status"] != "QUOTED":
        raise invalid_transition("Only a QUOTED order can be confirmed")
    t = now()
    # Temporal window precedes linked-entity state in the validation order.
    if t >= o["quote_expires_at"]:
        raise ApiError(ERR_QUOTE_EXPIRED, 409, "Confirm attempted at or after quote_expires_at")
    client = DB.clients[o["client_id"]]
    if client["client_status"] != "ACTIVE":
        raise ApiError(ERR_CLIENT_NOT_ACTIVE, 409, "Client is not ACTIVE")
    media = DB.media_assets[o["media_asset_id"]]
    if media["intake_status"] != "CLEARED":
        raise ApiError(ERR_MEDIA_NOT_CLEARED, 409, "Media asset is not CLEARED")
    o["due_at"] = compute_due_at(o["turnaround_tier"], media["duration_seconds"], t)
    o["order_status"] = "CONFIRMED"
    touch(o)
    return ok_object(serialize.work_order(o))


@bp.patch("/caption-ad/work-orders/<workOrderId>")
@guarded({"IntakeCoordinator"})
def amend_work_order(workOrderId, _user_id, _role):
    o = get_order(workOrderId)
    data = body()
    expected = data.get("expected_work_order_version")
    new_tier = opt_enum(data, "turnaround_tier", TURNAROUND_TIERS)
    new_language = opt_str(data, "language")
    if not is_int(expected):
        raise validation("Field 'expected_work_order_version' is required and must be an integer")
    if expected != o["version"]:
        raise ApiError(ERR_STALE_WORK_ORDER_VERSION, 412, "Stale work order version")
    if o["order_status"] not in ("DRAFT", "QUOTED"):
        raise invalid_transition("Only a DRAFT or QUOTED order can be amended")
    effective_tier = new_tier if new_tier is not None else o["turnaround_tier"]
    media = DB.media_assets[o["media_asset_id"]]
    _check_same_day_tier(effective_tier, media["duration_seconds"])
    if new_tier is not None:
        o["turnaround_tier"] = new_tier
    if new_language is not None:
        o["language"] = new_language
    if o["order_status"] == "QUOTED":
        # Amendments re-quote and move the expiry window.
        client = DB.clients[o["client_id"]]
        o["quoted_price_cents"] = quote_price_cents(
            o["turnaround_tier"], media["duration_seconds"], o["language"], client["ytd_completed_minutes"]
        )
        o["quote_expires_at"] = now() + timedelta(hours=72)
    touch(o)
    return ok_object(serialize.work_order(o))


@bp.post("/caption-ad/work-orders/<workOrderId>/start-production")
@guarded({"CaptionEditor"})
def start_production(workOrderId, _user_id, _role):
    o = get_order(workOrderId)
    if o["order_status"] != "CONFIRMED":
        raise invalid_transition("Only a CONFIRMED order can start production")
    o["order_status"] = "IN_PRODUCTION"
    touch(o)
    return ok_object(serialize.work_order(o))


@bp.post("/caption-ad/work-orders/<workOrderId>/deliver")
@guarded({"OperationsManager"})
def deliver_work_order(workOrderId, _user_id, _role):
    o = get_order(workOrderId)
    if o["order_status"] != "READY_FOR_DELIVERY":
        raise invalid_transition("Only a READY_FOR_DELIVERY order can be delivered")
    workflow.deliver_order(o)
    return ok_object(serialize.work_order(o))


@bp.post("/caption-ad/work-orders/<workOrderId>/accept-delivery")
@guarded({"ClientContact"})
def accept_delivery(workOrderId, _user_id, _role):
    o = get_order(workOrderId)
    if o["client_id"] != _user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "The acting client does not own this order")
    # The transition's pinned precondition (active_complaint_count == 0, else
    # ERR_COMPLAINTS_STILL_OPEN) outranks the generic from-state check: an open
    # complaint has already pushed the order to REMEDIATION, so a state-first
    # check would mask the catalogue error.
    if order_active_complaint_count(o["id"]) != 0:
        raise ApiError(ERR_COMPLAINTS_STILL_OPEN, 409, "Non-terminal complaints reference this order")
    if o["order_status"] != "DELIVERED":
        raise invalid_transition("Only a DELIVERED order can be accepted")
    o["order_status"] = "CLIENT_ACCEPTED"
    touch(o)
    return ok_object(serialize.work_order(o))


@bp.post("/caption-ad/work-orders/<workOrderId>/cancel")
@guarded({"IntakeCoordinator", "OperationsManager"})
def cancel_work_order(workOrderId, _user_id, _role):
    o = get_order(workOrderId)
    if o["order_status"] not in ("DRAFT", "QUOTED", "CONFIRMED"):
        raise invalid_transition("Only DRAFT, QUOTED, or CONFIRMED orders can be cancelled")
    o["order_status"] = "CANCELLED"
    touch(o)
    return ok_object(serialize.work_order(o))
