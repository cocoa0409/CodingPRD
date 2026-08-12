"""EventRegistration endpoints."""

from flask import Blueprint, request

import db
from errors import (
    err_event_held, err_event_not_open, err_invalid_state, err_not_found,
    err_referential, err_sales_window_closed, err_tier_sold_out, err_unauthorized,
)
from middleware import require_roles
from response import success_list, success_object
from services.calculations import (
    recompute_engagement, rederive_posture, ticket_price,
)
from services.common import (
    apply_pagination, json_body, new_entity, pagination_args, req_str, touch,
)
from services.serializers import REGISTRATION_FIELDS, serialize
from routes.events import get_event_or_404
from routes.ticket_tiers import get_tier_or_404

bp = Blueprint("registrations", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
EVENT_REG_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair")
REG_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "Alumni")


def get_registration_or_404(rid):
    reg = db.registrations.get(rid)
    if reg is None:
        raise err_not_found("EventRegistration not found")
    return reg


@bp.route("/alumni/events/<eid>/registrations", methods=["POST"])
@require_roles("Alumni")
def create_registration(eid, _role, _user_id):
    event = get_event_or_404(eid)
    body = json_body(required=["tier_id", "alumni_id"])
    tier_id = req_str(body["tier_id"], "tier_id")
    alumni_id = req_str(body["alumni_id"], "alumni_id")
    if alumni_id != _user_id:
        raise err_unauthorized("Acting user must be the registrant")

    # referential: tier exists, belongs to event, alumnus exists & not DECEASED
    tier = db.ticket_tiers.get(tier_id)
    if tier is None:
        raise err_referential("TicketTier not found")
    if tier["event_id"] != eid:
        raise err_referential("TicketTier does not belong to this event")
    record = db.records.get(alumni_id)
    if record is None:
        raise err_referential("AlumniRecord not found")
    if record["status"] == "DECEASED":
        raise err_referential("Alumnus is DECEASED")

    # temporal: sales window half-open [sales_start, sales_end)
    now = db.logical_now()
    if not (tier["sales_start_dt"] <= now < tier["sales_end_dt"]):
        raise err_sales_window_closed()

    quoted = ticket_price(tier, event, alumni_id, "ESTIMATE")
    reg = new_entity({
        "event_id": eid,
        "tier_id": tier_id,
        "alumni_id": alumni_id,
        "payment_status": "PENDING_PAYMENT",
        "attendance_status": "NOT_CHECKED_IN",
        "quoted_price_cents": quoted,
        "final_price_cents": None,
        "cancelled_reason": None,
    })
    db.registrations[reg["id"]] = reg
    return success_object(serialize(reg, REGISTRATION_FIELDS), status=201)


@bp.route("/alumni/events/<eid>/registrations", methods=["GET"])
@require_roles(*EVENT_REG_READ)
def list_event_registrations(eid, _role, _user_id):
    get_event_or_404(eid)
    limit, offset = pagination_args()
    rows = [r for r in db.registrations.values() if r["event_id"] == eid]
    ps = request.args.get("payment_status")
    if ps:
        rows = [r for r in rows if r["payment_status"] == ps]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(r, REGISTRATION_FIELDS) for r in page], limit, offset, total)


@bp.route("/alumni/registrations", methods=["GET"])
@require_roles(*REG_READ)
def list_registrations(_role, _user_id):
    limit, offset = pagination_args()
    rows = list(db.registrations.values())
    alumni_id = request.args.get("alumni_id")
    if alumni_id:
        rows = [r for r in rows if r["alumni_id"] == alumni_id]
    tier_id = request.args.get("tier_id")
    if tier_id:
        rows = [r for r in rows if r["tier_id"] == tier_id]
    event_id = request.args.get("event_id")
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    ps = request.args.get("payment_status")
    if ps:
        rows = [r for r in rows if r["payment_status"] == ps]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(r, REGISTRATION_FIELDS) for r in page], limit, offset, total)


@bp.route("/alumni/registrations/<rid>", methods=["GET"])
@require_roles(*REG_READ)
def get_registration(rid, _role, _user_id):
    return success_object(serialize(get_registration_or_404(rid), REGISTRATION_FIELDS))


@bp.route("/alumni/registrations/<rid>/confirm-payment", methods=["POST"])
@require_roles("Alumni")
def confirm_payment(rid, _role, _user_id):
    reg = get_registration_or_404(rid)
    if reg["alumni_id"] != _user_id:
        raise err_unauthorized("Acting user does not own this registration")
    if reg["payment_status"] != "PENDING_PAYMENT":
        raise err_invalid_state("Registration must be PENDING_PAYMENT to confirm")
    event = db.events.get(reg["event_id"])
    if event is None:
        raise err_not_found("ReunionEvent not found")
    if event["status"] != "OPEN_FOR_REGISTRATION":
        raise err_event_not_open()
    tier = db.ticket_tiers.get(reg["tier_id"])
    if tier is None:
        raise err_not_found("TicketTier not found")
    if not (tier["capacity"] == 0 or tier["sold_count"] < tier["capacity"]):
        raise err_tier_sold_out()

    final_price = ticket_price(tier, event, reg["alumni_id"], "FINAL")
    reg["payment_status"] = "CONFIRMED"
    reg["final_price_cents"] = final_price
    touch(reg)
    tier["sold_count"] += 1
    touch(tier)
    event["total_revenue_cents"] += final_price
    rederive_posture(event)
    recompute_engagement(reg["alumni_id"])
    return success_object(serialize(reg, REGISTRATION_FIELDS))


@bp.route("/alumni/registrations/<rid>/refund", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def refund(rid, _role, _user_id):
    reg = get_registration_or_404(rid)
    if reg["payment_status"] != "CONFIRMED":
        raise err_invalid_state("Registration must be CONFIRMED to refund")
    event = db.events.get(reg["event_id"])
    if event is None:
        raise err_not_found("ReunionEvent not found")
    if event["status"] == "HELD":
        raise err_event_held()

    reg["payment_status"] = "REFUNDED"
    touch(reg)
    tier = db.ticket_tiers.get(reg["tier_id"])
    if tier is not None:
        tier["sold_count"] = max(0, tier["sold_count"] - 1)
        touch(tier)
    event["total_revenue_cents"] -= reg.get("final_price_cents") or 0
    rederive_posture(event)
    return success_object(serialize(reg, REGISTRATION_FIELDS))


@bp.route("/alumni/registrations/<rid>/check-in", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def check_in(rid, _role, _user_id):
    reg = get_registration_or_404(rid)
    if reg["attendance_status"] != "NOT_CHECKED_IN":
        raise err_invalid_state("Registration already checked in")
    event = db.events.get(reg["event_id"])
    if event is None:
        raise err_not_found("ReunionEvent not found")
    if event["status"] not in ("OPEN_FOR_REGISTRATION", "HELD"):
        raise err_invalid_state("Parent event must be OPEN_FOR_REGISTRATION or HELD")
    if reg["payment_status"] != "CONFIRMED":
        raise err_invalid_state("Registration payment_status must be CONFIRMED")
    reg["attendance_status"] = "CHECKED_IN"
    touch(reg)
    return success_object(serialize(reg, REGISTRATION_FIELDS))


@bp.route("/alumni/registrations/<rid>/cancel", methods=["POST"])
@require_roles("Alumni")
def cancel_registration(rid, _role, _user_id):
    reg = get_registration_or_404(rid)
    if reg["alumni_id"] != _user_id:
        raise err_unauthorized("Acting user does not own this registration")
    if reg["payment_status"] != "PENDING_PAYMENT":
        raise err_invalid_state("Registration must be PENDING_PAYMENT to cancel")
    reg["payment_status"] = "CANCELLED"
    reg["cancelled_reason"] = "REGISTRANT"
    touch(reg)
    return success_object(serialize(reg, REGISTRATION_FIELDS))
