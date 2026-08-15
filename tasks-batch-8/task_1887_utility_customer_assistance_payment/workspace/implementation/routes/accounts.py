"""CustomerAccount endpoints: create, get, list, charges, reconnect."""

from flask import Blueprint

import db
from errors import (not_found, ApiError, ERR_ACCOUNT_NOT_DISCONNECTED,
                    ERR_RECONNECTION_FEE_UNPAID)
from middleware import authenticate, check_ownership
from response import success_object, success_list
from serializers import account as ser_account
from services.common import touch_account, delinquency_tier
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("accounts", __name__)

SERVICE_CLASSES = {"RESIDENTIAL", "COMMERCIAL"}
HEATING_FUELS = {"ELECTRIC", "GAS", "DUAL"}
CHARGE_TYPES = {"ARREARAGE", "CURRENT"}
ALL_ROLES = ["Customer", "CustomerServiceRep", "EligibilitySpecialist",
             "ProgramAdmin", "FieldCrew"]


def get_account_or_404(account_id):
    a = db.accounts.get(account_id)
    if a is None:
        raise not_found("Account not found")
    return a


@bp.route("/assistance/accounts", methods=["POST"])
def create_account():
    authenticate(["ProgramAdmin"])
    body = validate_shape(get_body(allow_empty=False), [
        ("service_address", "string", True, None),
        ("service_class", "enum", False, SERVICE_CLASSES),
        ("heating_fuel_type", "enum", False, HEATING_FUELS),
        ("deposit_held_cents", "int", False, (0, None)),
    ])
    a = {
        "id": db.new_id(),
        "service_address": body["service_address"],
        "service_class": body.get("service_class") or "RESIDENTIAL",
        "heating_fuel_type": body.get("heating_fuel_type") or "ELECTRIC",
        "deposit_held_cents": body.get("deposit_held_cents") or 0,
        "arrearage_balance_cents": 0,
        "current_charges_balance_cents": 0,
        "credit_balance_cents": 0,
        "arrearage_since": None,
        "reconnection_fee_due_cents": 0,
        "reconnection_fee_base_cents": 0,
        "reconnection_fee_surcharge_cents": 0,
        "reconnection_deposit_topup_cents": 0,
        "reconnection_surcharge_applied": False,
        "service_status": "CONNECTED",
        "protection_status": "UNPROTECTED",
        "last_activity_at": db.CLOCK.now(),
    }
    db.stamp_common(a)
    db.accounts[a["id"]] = a
    return success_object(ser_account(a), status=201)


@bp.route("/assistance/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    actor = authenticate(ALL_ROLES)
    check_ownership(actor, account_id)
    a = get_account_or_404(account_id)
    return success_object(ser_account(a))


@bp.route("/assistance/accounts", methods=["GET"])
def list_accounts():
    authenticate(["CustomerServiceRep", "EligibilitySpecialist", "ProgramAdmin",
                  "FieldCrew"])
    limit, offset = parse_pagination()
    filters = parse_filters({
        "service_status": {"CONNECTED", "DISCONNECT_PENDING", "DISCONNECTED"},
        "protection_status": {"UNPROTECTED", "WEATHER_MORATORIUM", "MEDICAL_MORATORIUM"},
        "delinquency_tier": {"CURRENT", "DELINQUENT", "SEVERELY_DELINQUENT"},
    })
    items = sort_by_creation(db.accounts.values())
    if "service_status" in filters:
        items = [a for a in items if a["service_status"] == filters["service_status"]]
    if "protection_status" in filters:
        items = [a for a in items if a["protection_status"] == filters["protection_status"]]
    if "delinquency_tier" in filters:
        items = [a for a in items if delinquency_tier(a) == filters["delinquency_tier"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_account(a) for a in page], limit, offset, total)


@bp.route("/assistance/accounts/<account_id>/charges", methods=["POST"])
def post_charge(account_id):
    authenticate(["ProgramAdmin"])
    body = validate_shape(get_body(allow_empty=False), [
        ("charge_type", "enum", True, CHARGE_TYPES),
        ("amount_cents", "int", True, (1, None)),
        ("effective_on", "datetime", False, None),
    ])
    a = get_account_or_404(account_id)
    if body["charge_type"] == "ARREARAGE":
        from services.common import adjust_arrearage
        adjust_arrearage(a, body["amount_cents"])
    else:
        a["current_charges_balance_cents"] += body["amount_cents"]
    touch_account(a)
    return success_object(ser_account(a), status=201)


@bp.route("/assistance/accounts/<account_id>/reconnect", methods=["POST"])
def reconnect(account_id):
    authenticate(["FieldCrew"])
    body = validate_shape(get_body(), [("after_hours", "bool", False, None)])
    a = get_account_or_404(account_id)
    if a["service_status"] != "DISCONNECTED":
        raise ApiError(ERR_ACCOUNT_NOT_DISCONNECTED, 409,
                       "Reconnect requires service_status DISCONNECTED")
    # after-hours surcharge folds in exactly once (PRD §3.7)
    if body.get("after_hours") and not a["reconnection_surcharge_applied"]:
        a["reconnection_fee_due_cents"] += a["reconnection_fee_surcharge_cents"]
        a["reconnection_surcharge_applied"] = True
        touch_account(a)
    if a["reconnection_fee_due_cents"] != 0:
        raise ApiError(ERR_RECONNECTION_FEE_UNPAID, 422,
                       "reconnection_fee_due_cents must be 0 to reconnect")
    a["service_status"] = "CONNECTED"
    touch_account(a)
    return success_object(ser_account(a))
