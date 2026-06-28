"""Payment endpoints: fetch, settle, refund."""
from flask import Blueprint

import db
import errors
import response
from middleware import authenticate, require_role
from services import models

bp = Blueprint("payments", __name__)


def _get_payment(pid):
    p = db.store.payments.get(pid)
    if p is None:
        raise errors.not_found("Payment not found.")
    return p


@bp.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "FleetManager", "Dispatcher"})
    p = _get_payment(pid)
    if role == "Customer":
        sr = db.store.service_requests.get(p["service_request_id"])
        if sr is None or uid != sr["customer_id"]:
            raise errors.not_owner("Customer may only read its own payments.")
    if role == "FleetManager" and p.get("fleet_account_id") != uid:
        raise errors.not_owner("FleetManager may only read its own fleet payments.")
    return response.success(models.serialize(p), 200)


@bp.route("/payments/<pid>/settle", methods=["POST"])
def settle(pid):
    uid, role = authenticate()
    require_role(role, {"FleetManager", "Customer"})
    p = _get_payment(pid)

    # ownership (priority 4): for FLEET_CREDIT, the acting FleetManager must own the
    # payment's fleet account; for a Customer, must own the underlying request.
    if role == "Customer":
        sr = db.store.service_requests.get(p["service_request_id"])
        if sr is None or uid != sr["customer_id"]:
            raise errors.not_owner("Customer may only settle its own payments.")
    if role == "FleetManager":
        if p.get("fleet_account_id") != uid:
            raise errors.not_owner("FleetManager may only settle its own fleet payments.")

    # state precondition (priority 5)
    if p["status"] != "INVOICED":
        raise errors.invalid_state("Only an INVOICED payment may be settled.")

    # fleet active (priority 13) for fleet-billed settlements
    fleet_id = p.get("fleet_account_id")
    fleet = db.store.fleet_accounts.get(fleet_id) if fleet_id else None
    if p["method"] == "FLEET_CREDIT" and fleet is not None and fleet["status"] != "ACTIVE":
        raise errors.fleet_account_suspended()

    p["status"] = "SETTLED"
    models.touch(p, db.store)
    if fleet is not None:
        fleet["outstanding_balance_cents"] -= p["total_due_cents"]
        models.touch(fleet, db.store)
    return response.success(models.serialize(p), 200)


@bp.route("/payments/<pid>/refund", methods=["POST"])
def refund(pid):
    _uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    p = _get_payment(pid)
    if p["status"] != "INVOICED":
        raise errors.invalid_state("Only an INVOICED payment may be refunded.")
    p["status"] = "REFUNDED"
    models.touch(p, db.store)
    fleet_id = p.get("fleet_account_id")
    fleet = db.store.fleet_accounts.get(fleet_id) if fleet_id else None
    if fleet is not None:
        fleet["outstanding_balance_cents"] -= p["total_due_cents"]
        models.touch(fleet, db.store)
    return response.success(models.serialize(p), 200)
