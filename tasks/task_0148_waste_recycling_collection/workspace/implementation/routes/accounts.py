"""ServiceAccount endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import serializers as ser
from services.common import (
    check_enum,
    get_json_body,
    paginate,
    parse_pagination,
    require_fields,
)

bp = Blueprint("accounts", __name__)

RATE_CLASSES = {"RESIDENTIAL", "COMMERCIAL_SMALL", "COMMERCIAL_LARGE"}
ACCOUNT_STATUSES = {"PENDING_SETUP", "ACTIVE", "SUSPENDED", "CLOSED"}


@bp.route("/accounts", methods=["POST"])
def create_account():
    # Anonymous self-registration is allowed; if auth headers are present they
    # must be valid and the role must be permitted.
    from flask import request

    if request.headers.get("X-User-ID") or request.headers.get("X-User-Role"):
        _, role = authenticate()
        require_roles(role, {"ResidentAccount", "Dispatcher"})

    body = get_json_body()
    require_fields(body, ["service_address", "rate_class"])
    check_enum(body["rate_class"], RATE_CLASSES, "rate_class")

    floor = body.get("diversion_floor_pct")
    if floor is None:
        floor = 0

    rec = base_record()
    rec.update(
        {
            "service_address": body["service_address"],
            "rate_class": body["rate_class"],
            "status": "PENDING_SETUP",
            "diversion_floor_pct": floor,
        }
    )
    db.accounts[rec["id"]] = rec
    return success(ser.account(rec), status=201)


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    _, role = authenticate()
    require_roles(role, {"ResidentAccount", "Dispatcher", "Billing", "Driver"})
    rec = db.accounts.get(account_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Account not found.")
    return success(ser.account(rec), status=200)


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Billing"})
    parse_pagination()  # validate pagination before filtering
    status = None
    from flask import request

    status = request.args.get("status")
    items = list(db.accounts.values())
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, pagination = paginate(items)
    return success([ser.account(a) for a in page], status=200, pagination=pagination)


@bp.route("/accounts/<account_id>/activate", methods=["POST"])
def activate_account(account_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.accounts.get(account_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Account not found.")
    if rec["status"] not in ("PENDING_SETUP", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Account cannot be activated from its current state.")
    if rec["status"] == "PENDING_SETUP":
        has_cart = any(
            c["account_id"] == account_id and c["status"] in ("ASSIGNED", "ACTIVE")
            for c in db.carts.values()
        )
        has_plan = any(
            p["account_id"] == account_id and p["status"] == "ACTIVE"
            for p in db.service_plans.values()
        )
        if not has_cart or not has_plan:
            raise err(
                "ERR_INVALID_STATE",
                "Account requires an assigned/active cart and an active plan to activate.",
            )
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(ser.account(rec), status=200)


@bp.route("/accounts/<account_id>/suspend", methods=["POST"])
def suspend_account(account_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    rec = db.accounts.get(account_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Account not found.")
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE account can be suspended.")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(ser.account(rec), status=200)


@bp.route("/accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    rec = db.accounts.get(account_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Account not found.")
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Account cannot be closed from its current state.")
    # ERR_OPEN_BALANCE: no Invoice in ISSUED or DISPUTED.
    open_invoice = any(
        inv["account_id"] == account_id and inv["status"] in ("ISSUED", "DISPUTED")
        for inv in db.invoices.values()
    )
    if open_invoice:
        raise err("ERR_OPEN_BALANCE", "Account has an open invoice balance.")

    rec["status"] = "CLOSED"
    touch(rec)
    # Cascade: carts -> RETIRED
    for cart in db.carts.values():
        if cart["account_id"] == account_id and cart["status"] in (
            "ASSIGNED",
            "ACTIVE",
            "ON_HOLD",
        ):
            cart["status"] = "RETIRED"
            touch(cart)
    # Cascade: plans -> TERMINATED
    for plan in db.service_plans.values():
        if plan["account_id"] == account_id and plan["status"] in (
            "DRAFT",
            "ACTIVE",
            "PAUSED",
        ):
            plan["status"] = "TERMINATED"
            touch(plan)
    return success(ser.account(rec), status=200)
