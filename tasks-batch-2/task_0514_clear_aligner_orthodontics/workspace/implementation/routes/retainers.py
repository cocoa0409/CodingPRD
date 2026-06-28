"""RetainerSubscription endpoints (PRD §3.10)."""
from flask import Blueprint, request

from clock import clock, format_iso8601_ms
from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize, touch
from response import object_response, array_response
from services.dates import add_months
from services.listing import paginate
from services.store import get_retainer, get_case, fk_case
from validation import get_body, require_str, require_int, require_enum, parse_pagination

bp = Blueprint("retainers", __name__)

CADENCES = {"QUARTERLY", "SEMIANNUAL"}
_CADENCE_MONTHS = {"QUARTERLY": 3, "SEMIANNUAL": 6}


def _advance(cadence):
    return format_iso8601_ms(add_months(clock.now(), _CADENCE_MONTHS[cadence]))


@bp.route("/retainers", methods=["POST"])
def create_retainer():
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    body = get_body()
    case_id = require_str(body, "case_id")
    cadence = require_enum(body, "cadence", CADENCES)
    per_shipment_fee_cents = require_int(body, "per_shipment_fee_cents")
    if per_shipment_fee_cents < 0:
        raise err("ERR_INVALID_REQUEST", "per_shipment_fee_cents must be >= 0.")
    # FK existence
    case = fk_case(case_id)
    # business: case must be COMPLETED (priority 20)
    if case["status"] != "COMPLETED":
        raise err("ERR_CASE_NOT_COMPLETED",
                  "Retainer may only be created for a COMPLETED case.")

    rec = base_record(common_fields=True)
    rec.update({
        "case_id": case_id,
        "cadence": cadence,
        "per_shipment_fee_cents": per_shipment_fee_cents,
        "status": "ACTIVE",
        "next_ship_at": _advance(cadence),
    })
    db.retainers[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/retainers/<rid>", methods=["GET"])
def fetch_retainer(rid):
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    rec = get_retainer(rid)
    return object_response(serialize(rec), status=200)


@bp.route("/retainers", methods=["GET"])
def list_retainers():
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    records = list(db.retainers.values())
    if case_id is not None:
        records = [r for r in records if r["case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/retainers/<rid>/pause", methods=["POST"])
def pause_retainer(rid):
    _, role = get_auth()
    require_roles(role, {"Patient"})
    rec = get_retainer(rid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Retainer must be ACTIVE to pause.")
    rec["status"] = "PAUSED"
    touch(rec)
    return object_response(serialize(rec), status=200)


@bp.route("/retainers/<rid>/resume", methods=["POST"])
def resume_retainer(rid):
    _, role = get_auth()
    require_roles(role, {"Patient"})
    rec = get_retainer(rid)
    if rec["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "Retainer must be PAUSED to resume.")
    rec["status"] = "ACTIVE"
    # advance next_ship_at by one cadence interval from the current clock
    rec["next_ship_at"] = _advance(rec["cadence"])
    touch(rec)
    return object_response(serialize(rec), status=200)


@bp.route("/retainers/<rid>/cancel", methods=["POST"])
def cancel_retainer(rid):
    _, role = get_auth()
    require_roles(role, {"Patient"})
    rec = get_retainer(rid)
    if rec["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Retainer must be ACTIVE or PAUSED to cancel.")
    rec["status"] = "CANCELLED"
    touch(rec)
    return object_response(serialize(rec), status=200)
