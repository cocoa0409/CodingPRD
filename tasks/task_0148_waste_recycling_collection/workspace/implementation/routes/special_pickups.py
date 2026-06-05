"""SpecialPickup endpoints (PRD §3.5, §3.7)."""
from flask import request, Blueprint

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_owner, require_roles
from response import success
from services import calculations as calc
from services import serializers as ser
from services.common import check_enum, get_json_body, paginate, parse_pagination, require_fields

bp = Blueprint("special_pickups", __name__)

KINDS = {"BULK", "HAZARDOUS"}
HAZARD_CLASSES = {"FLAMMABLE", "CORROSIVE", "TOXIC", "EWASTE"}


@bp.route("/accounts/<account_id>/special-pickups", methods=["POST"])
def create_special_pickup(account_id):
    user_id, role = authenticate()
    require_roles(role, {"ResidentAccount", "Dispatcher"})
    # Ownership (priority 3) is evaluated before path existence (priority 4):
    # the owning account here IS the path id, so the resident's X-User-ID must
    # equal {id} before the account is even resolved.
    require_owner(role, user_id, account_id)
    account = db.accounts.get(account_id)
    if account is None:
        raise err("ERR_NOT_FOUND", "Account not found.")
    body = get_json_body()
    require_fields(body, ["kind", "requested_date"])
    check_enum(body["kind"], KINDS, "kind")
    hazard_class = body.get("hazard_class")
    if hazard_class is not None:
        check_enum(hazard_class, HAZARD_CLASSES, "hazard_class")
    # HAZARDOUS requires hazard_class -> ERR_HAZARD_CLASS_REQUIRED (422).
    if body["kind"] == "HAZARDOUS" and hazard_class is None:
        raise err("ERR_HAZARD_CLASS_REQUIRED", "A HAZARDOUS special pickup requires a hazard_class.")

    rec = base_record()
    rec.update(
        {
            "account_id": account_id,
            "kind": body["kind"],
            "requested_date": body["requested_date"],
            "hazard_class": hazard_class,
            "status": "REQUESTED",
            "quoted_fee_cents": 0,
        }
    )
    db.special_pickups[rec["id"]] = rec
    return success(ser.special_pickup(rec), status=201)


@bp.route("/special-pickups/<sp_id>", methods=["GET"])
def get_special_pickup(sp_id):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing", "ResidentAccount"})
    rec = db.special_pickups.get(sp_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Special pickup not found.")
    require_owner(role, user_id, rec["account_id"])
    return success(ser.special_pickup(rec), status=200)


@bp.route("/special-pickups", methods=["GET"])
def list_special_pickups():
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing", "ResidentAccount"})
    parse_pagination()
    items = list(db.special_pickups.values())
    if role == "ResidentAccount":
        items = [s for s in items if s["account_id"] == user_id]
    account_id = request.args.get("account_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if kind is not None:
        items = [s for s in items if s["kind"] == kind]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pagination = paginate(items)
    return success([ser.special_pickup(s) for s in page], status=200, pagination=pagination)


@bp.route("/special-pickups/<sp_id>/approve", methods=["POST"])
def approve_special_pickup(sp_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.special_pickups.get(sp_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Special pickup not found.")
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a REQUESTED special pickup can be approved.")
    account = db.accounts.get(rec["account_id"])
    if account is None or account["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Requesting account must be ACTIVE to approve.")
    if rec["kind"] == "HAZARDOUS" and rec["hazard_class"] is None:
        raise err("ERR_HAZARD_CLASS_REQUIRED", "A HAZARDOUS special pickup requires a hazard_class.")
    rec["status"] = "APPROVED"
    rec["quoted_fee_cents"] = calc.special_pickup_fee_cents(rec["kind"], rec["hazard_class"])
    touch(rec)
    return success(ser.special_pickup(rec), status=200)


@bp.route("/special-pickups/<sp_id>/reject", methods=["POST"])
def reject_special_pickup(sp_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.special_pickups.get(sp_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Special pickup not found.")
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a REQUESTED special pickup can be rejected.")
    rec["status"] = "REJECTED"
    touch(rec)
    return success(ser.special_pickup(rec), status=200)


@bp.route("/special-pickups/<sp_id>/schedule", methods=["POST"])
def schedule_special_pickup(sp_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.special_pickups.get(sp_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Special pickup not found.")
    if rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only an APPROVED special pickup can be scheduled.")
    rec["status"] = "SCHEDULED"
    touch(rec)
    return success(ser.special_pickup(rec), status=200)


@bp.route("/special-pickups/<sp_id>/complete", methods=["POST"])
def complete_special_pickup(sp_id):
    _, role = authenticate()
    require_roles(role, {"Driver"})
    rec = db.special_pickups.get(sp_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Special pickup not found.")
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED special pickup can be completed.")
    rec["status"] = "COMPLETED"
    touch(rec)
    return success(ser.special_pickup(rec), status=200)


@bp.route("/special-pickups/<sp_id>/cancel", methods=["POST"])
def cancel_special_pickup(sp_id):
    user_id, role = authenticate()
    require_roles(role, {"ResidentAccount", "Dispatcher"})
    rec = db.special_pickups.get(sp_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Special pickup not found.")
    require_owner(role, user_id, rec["account_id"])
    if rec["status"] not in ("REQUESTED", "APPROVED", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Special pickup cannot be cancelled from its current state.")
    was_scheduled = rec["status"] == "SCHEDULED"
    rec["status"] = "CANCELLED"
    touch(rec)
    # Conditional cascade: a SCHEDULED cancel auto-creates a partial-refund credit.
    if was_scheduled:
        credit = base_record()
        credit.update(
            {
                "account_id": rec["account_id"],
                "source_type": "SPECIAL_PICKUP",
                "source_pickup_id": None,
                "source_special_pickup_id": rec["id"],
                "amount_cents": calc.missed_credit_amount_cents(
                    "SPECIAL_PICKUP", rec["quoted_fee_cents"]
                ),
                "status": "PENDING",
                "applied_invoice_id": None,
            }
        )
        db.credits[credit["id"]] = credit
    return success(ser.special_pickup(rec), status=200)
