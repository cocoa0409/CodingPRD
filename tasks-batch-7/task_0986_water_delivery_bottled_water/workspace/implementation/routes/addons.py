"""AddOn endpoints."""
from flask import Blueprint

import errors
from db import db
from middleware import (body_json, check_transition, f_enum, f_int, f_str,
                        require_owner, require_roles)
from response import ok_object
from services import base_record, bump, ser_addon

bp = Blueprint("addons", __name__)

ADDON_KINDS = {"COFFEE", "FILTRATION", "CUPS", "SANITIZATION"}
ADDON_TERMINAL = ("CANCELLED",)


def _get_addon(aid):
    a = db.addons.get(aid)
    if a is None:
        raise errors.not_found("addon not found")
    return a


@bp.post("/addons")
@require_roles("OpsAdmin", "CustomerSelf")
def create_addon():
    d = body_json()
    customer_id = f_str(d, "customer_id")
    addon_kind = f_enum(d, "addon_kind", ADDON_KINDS)
    quantity = f_int(d, "quantity", min_value=1)
    unit_price_cents = f_int(d, "unit_price_cents", min_value=0)
    cadence = f_enum(d, "cadence", {"RECURRING", "ONE_TIME"},
                     required=False, default="RECURRING")
    if db.customers.get(customer_id) is None:
        raise errors.invalid_reference("customer_id does not resolve")
    require_owner(customer_id)
    rec = base_record()
    rec.update({
        "customer_id": customer_id,
        "addon_kind": addon_kind,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "cadence": cadence,
        "addon_status": "ACTIVE",
    })
    with db.lock:
        db.addons[rec["id"]] = rec
    return ok_object(ser_addon(rec), 201)


@bp.get("/addons/<aid>")
@require_roles("OpsAdmin", "BillingAdmin", "CustomerSelf")
def get_addon(aid):
    a = _get_addon(aid)
    require_owner(a["customer_id"])
    return ok_object(ser_addon(a))


@bp.post("/addons/<aid>/pause")
@require_roles("CustomerSelf")
def pause_addon(aid):
    a = _get_addon(aid)
    check_transition(a, "addon_status", ("ACTIVE",), ADDON_TERMINAL, "AddOn")
    require_owner(a["customer_id"])
    with db.lock:
        a["addon_status"] = "PAUSED"
        bump(a)
    return ok_object(ser_addon(a))


@bp.post("/addons/<aid>/resume")
@require_roles("CustomerSelf")
def resume_addon(aid):
    a = _get_addon(aid)
    check_transition(a, "addon_status", ("PAUSED",), ADDON_TERMINAL, "AddOn")
    require_owner(a["customer_id"])
    with db.lock:
        a["addon_status"] = "ACTIVE"
        bump(a)
    return ok_object(ser_addon(a))


@bp.post("/addons/<aid>/cancel")
@require_roles("CustomerSelf")
def cancel_addon(aid):
    a = _get_addon(aid)
    check_transition(a, "addon_status", ("ACTIVE", "PAUSED"), ADDON_TERMINAL,
                     "AddOn")
    require_owner(a["customer_id"])
    with db.lock:
        a["addon_status"] = "CANCELLED"
        bump(a)
    return ok_object(ser_addon(a))
