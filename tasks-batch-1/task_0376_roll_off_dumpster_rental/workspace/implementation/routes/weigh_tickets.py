"""WeighTicket endpoints (PRD section 3.9). Append-only, immutable."""
from flask import Blueprint, request

from db import db
from helpers import get_order, get_stop, get_weigh_ticket, paginate
from middleware import require_auth, require_role
from response import success
from serialize import weigh_ticket as ser
import validate

bp = Blueprint("weigh_tickets", __name__)

CONTAMINATION_KINDS = {"NONE", "TIRES", "APPLIANCES", "HAZMAT"}


@bp.post("/weigh-tickets")
def create_weigh_ticket():
    _, role = require_auth()
    require_role(role, ["ScaleOperator"])
    body = validate.get_json_body()
    validate.require_fields(body, [
        "order_id", "service_stop_id", "gross_weight_lbs", "tare_weight_lbs",
    ])
    order_id = validate.require_string(body, "order_id")
    service_stop_id = validate.require_string(body, "service_stop_id")
    gross = validate.require_non_negative_int(body, "gross_weight_lbs")
    tare = validate.require_non_negative_int(body, "tare_weight_lbs")
    contaminated = validate.require_bool(body, "contaminated", default=False)
    contamination_kind = validate.optional_enum(
        body, "contamination_kind", CONTAMINATION_KINDS, default="NONE")

    # existence of FK ids (priority 3, left to right).
    get_order(order_id)
    get_stop(service_stop_id)

    net = max(0, gross - tare)
    rec = db.insert_append_only(db.weigh_tickets, {
        "order_id": order_id,
        "service_stop_id": service_stop_id,
        "gross_weight_lbs": gross,
        "tare_weight_lbs": tare,
        "net_weight_lbs": net,
        "contaminated": contaminated,
        "contamination_kind": contamination_kind,
    })
    return success(ser(rec), status=201)


@bp.get("/weigh-tickets")
def list_weigh_tickets():
    _, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "BillingClerk", "ScaleOperator"])
    limit, offset = validate.get_pagination()
    records = list(db.weigh_tickets.values())
    order_id = request.args.get("order_id")
    stop_id = request.args.get("service_stop_id")
    contaminated = request.args.get("contaminated")
    if order_id is not None:
        records = [r for r in records if r["order_id"] == order_id]
    if stop_id is not None:
        records = [r for r in records if r["service_stop_id"] == stop_id]
    if contaminated is not None:
        want = contaminated.lower() == "true"
        records = [r for r in records if r["contaminated"] == want]
    return paginate(records, ser, limit, offset)


@bp.get("/weigh-tickets/<ticket_id>")
def get_weigh_ticket_ep(ticket_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "BillingClerk", "ScaleOperator"])
    rec = get_weigh_ticket(ticket_id)
    return success(ser(rec), status=200)
