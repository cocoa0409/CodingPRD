"""CoolerRental endpoints."""
from flask import Blueprint

import errors
import services
from db import db
from middleware import (body_json, check_transition, f_enum, f_int, f_str,
                        require_owner, require_roles)
from response import ok_object
from services import base_record, bump, ser_rental

bp = Blueprint("rentals", __name__)

COOLER_MODELS = {"COUNTERTOP", "FREESTANDING", "BOTTOM_LOAD", "FILTRATION_POE"}
RENTAL_TERMINAL = ("RETURNED", "CLOSED")


def _get_rental(rid):
    r = db.rentals.get(rid)
    if r is None:
        raise errors.not_found("cooler rental not found")
    return r


def _linked_wo(rental_id, kind=None):
    matches = [w for w in db.work_orders.values()
               if w.get("linked_rental_id") == rental_id
               and (kind is None or w["order_kind"] == kind)]
    matches.sort(key=lambda w: (w["created_at"], w["seq"]))
    return matches[-1] if matches else None


def _create_linked_wo(customer_id, kind, rental_id):
    rec = base_record()
    rec.update({
        "customer_id": customer_id,
        "order_kind": kind,
        "requested_date": services.today().isoformat(),
        "quantity_bottles": 0,
        "order_status": "PENDING",
        "linked_stop_id": None,
        "linked_rental_id": rental_id,
    })
    db.work_orders[rec["id"]] = rec
    return rec


@bp.post("/cooler-rentals")
@require_roles("OpsAdmin", "CustomerSelf")
def create_rental():
    d = body_json()
    customer_id = f_str(d, "customer_id")
    cooler_model = f_enum(d, "cooler_model", COOLER_MODELS)
    monthly_rent_cents = f_int(d, "monthly_rent_cents", min_value=0)
    deposit_cents = f_int(d, "deposit_cents", min_value=0)
    if db.customers.get(customer_id) is None:
        raise errors.invalid_reference("customer_id does not resolve")
    require_owner(customer_id)
    with db.lock:
        rec = base_record()
        rec.update({
            "customer_id": customer_id,
            "cooler_model": cooler_model,
            "monthly_rent_cents": monthly_rent_cents,
            "deposit_cents": deposit_cents,
            "rental_status": "PENDING_INSTALL",
            "installed_at": None,
            "returned_at": None,
            "accrued_rent_cents": 0,
            "deposit_consumed": False,
            "status_history": [(services.now(), "PENDING_INSTALL")],
        })
        db.rentals[rec["id"]] = rec
        _create_linked_wo(customer_id, "COOLER_INSTALL", rec["id"])
    return ok_object(ser_rental(rec), 201)


@bp.get("/cooler-rentals/<rid>")
@require_roles("OpsAdmin", "Dispatcher", "Driver", "CustomerSelf",
               "BillingAdmin")
def get_rental(rid):
    r = _get_rental(rid)
    require_owner(r["customer_id"])
    return ok_object(ser_rental(r))


@bp.post("/cooler-rentals/<rid>/install")
@require_roles("Driver")
def install_rental(rid):
    r = _get_rental(rid)
    check_transition(r, "rental_status", ("PENDING_INSTALL",),
                     RENTAL_TERMINAL, "CoolerRental")
    customer = db.customers.get(r["customer_id"])
    if customer is None or customer["account_status"] != "ACTIVE":
        raise errors.invalid_state("customer is not ACTIVE")
    wo = _linked_wo(rid, "COOLER_INSTALL")
    # The driver starting the install is what moves the linked order to
    # IN_PROGRESS, so accept it from SCHEDULED as well as IN_PROGRESS.
    if wo is None or wo["order_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise errors.invalid_state(
            "linked install work order is not IN_PROGRESS")
    with db.lock:
        r["rental_status"] = "INSTALLED"
        r["installed_at"] = services.now()
        r["status_history"].append((services.now(), "INSTALLED"))
        bump(r)
        wo["order_status"] = "COMPLETED"
        bump(wo)
    return ok_object(ser_rental(r))


@bp.post("/cooler-rentals/<rid>/suspend")
@require_roles("OpsAdmin")
def suspend_rental(rid):
    r = _get_rental(rid)
    check_transition(r, "rental_status", ("INSTALLED",), RENTAL_TERMINAL,
                     "CoolerRental")
    with db.lock:
        r["rental_status"] = "SUSPENDED"
        r["status_history"].append((services.now(), "SUSPENDED"))
        bump(r)
    return ok_object(ser_rental(r))


@bp.post("/cooler-rentals/<rid>/resume")
@require_roles("OpsAdmin")
def resume_rental(rid):
    r = _get_rental(rid)
    check_transition(r, "rental_status", ("SUSPENDED",), RENTAL_TERMINAL,
                     "CoolerRental")
    with db.lock:
        r["rental_status"] = "INSTALLED"
        r["status_history"].append((services.now(), "INSTALLED"))
        bump(r)
    return ok_object(ser_rental(r))


@bp.post("/cooler-rentals/<rid>/request-return")
@require_roles("CustomerSelf")
def request_return(rid):
    r = _get_rental(rid)
    check_transition(r, "rental_status", ("INSTALLED",), RENTAL_TERMINAL,
                     "CoolerRental")
    require_owner(r["customer_id"])
    with db.lock:
        r["rental_status"] = "RETURN_REQUESTED"
        r["status_history"].append((services.now(), "RETURN_REQUESTED"))
        bump(r)
        _create_linked_wo(r["customer_id"], "COOLER_RETURN", r["id"])
    return ok_object(ser_rental(r))


@bp.post("/cooler-rentals/<rid>/confirm-return")
@require_roles("Driver")
def confirm_return(rid):
    r = _get_rental(rid)
    check_transition(r, "rental_status", ("RETURN_REQUESTED",),
                     RENTAL_TERMINAL, "CoolerRental")
    with db.lock:
        r["rental_status"] = "RETURNED"
        r["returned_at"] = services.now()
        r["status_history"].append((services.now(), "RETURNED"))
        # Final prorated rent up to the return instant (return day counts).
        services.refresh_accrued_rent(r)
        bump(r)
        wo = _linked_wo(rid, "COOLER_RETURN")
        if wo is not None and wo["order_status"] in ("SCHEDULED",
                                                     "IN_PROGRESS"):
            wo["order_status"] = "COMPLETED"
            bump(wo)
    return ok_object(ser_rental(r))


@bp.post("/cooler-rentals/<rid>/close")
@require_roles("OpsAdmin")
def close_rental(rid):
    r = _get_rental(rid)
    if r["rental_status"] == "CLOSED":
        raise errors.already_terminal("CoolerRental is already CLOSED")
    if r["rental_status"] != "RETURNED":
        raise errors.invalid_state(
            "only a RETURNED rental can be closed")
    with db.lock:
        r["rental_status"] = "CLOSED"
        r["status_history"].append((services.now(), "CLOSED"))
        bump(r)
    return ok_object(ser_rental(r))
