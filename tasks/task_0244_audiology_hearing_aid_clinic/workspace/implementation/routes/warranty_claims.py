"""Warranty claim lifecycle endpoints: fetch, approve, deny, appeal, replace."""

from flask import Blueprint

from db import db
import serialize
import validate
import errors
from clock import clock
from timeutil import parse_iso, parse_date, clock_date, add_months
from middleware import require_auth, require_role, require_ownership, get_json_body
from response import object_response
from services.domain import get_or_404, append_ledger
from services import calculations as calc

bp = Blueprint("warranty_claims", __name__)


@bp.get("/clinic/warranty-claims/<cid>")
def get_claim(cid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin", "Patient"})
    claim = get_or_404(db.warranty_claims, cid)
    _require_claim_ownership(auth, claim)
    return object_response(serialize.warranty_claim(claim))


@bp.post("/clinic/warranty-claims/<cid>/approve")
def approve_claim(cid):
    auth = require_auth()
    require_role(auth, {"BillingClerk"})
    with db.lock:
        claim = get_or_404(db.warranty_claims, cid)
        if claim["status"] not in ("SUBMITTED", "APPEALED"):
            raise errors.invalid_state("Claim cannot be approved from its current state.")

        order = db.orders.get(claim["fitting_order_id"])
        if order is None:
            raise errors.not_found()
        # Underlying order must still be WARRANTY_ACTIVE.
        if order["status"] != "WARRANTY_ACTIVE":
            raise errors.ApiError(errors.ERR_OUTSIDE_WARRANTY_WINDOW, 422,
                                  "Order is no longer warranty-active.")

        # Incident within the warranty window: clock date <= purchase_date + warranty_months.
        if not _within_warranty_window(order):
            raise errors.ApiError(errors.ERR_OUTSIDE_WARRANTY_WINDOW, 422,
                                  "Incident falls outside the warranty window.")

        deductible, clinic_cost = calc.warranty_settlement(
            claim["claim_type"], claim["assessed_value_cents"])
        claim["deductible_cents"] = deductible
        claim["clinic_cost_cents"] = clinic_cost
        claim["status"] = "APPROVED"
        db.touch(claim)
    return object_response(serialize.warranty_claim(claim))


@bp.post("/clinic/warranty-claims/<cid>/deny")
def deny_claim(cid):
    auth = require_auth()
    require_role(auth, {"BillingClerk"})
    with db.lock:
        claim = get_or_404(db.warranty_claims, cid)
        if claim["status"] not in ("SUBMITTED", "APPEALED"):
            raise errors.invalid_state("Claim cannot be denied from its current state.")
        claim["status"] = "DENIED"
        db.touch(claim)
    return object_response(serialize.warranty_claim(claim))


@bp.post("/clinic/warranty-claims/<cid>/appeal")
def appeal_claim(cid):
    auth = require_auth()
    require_role(auth, {"Patient"})
    with db.lock:
        claim = get_or_404(db.warranty_claims, cid)
        # Ownership: a Patient may only appeal a claim on their own order.
        _require_claim_ownership(auth, claim)
        if claim["status"] != "DENIED":
            raise errors.invalid_state("Only a DENIED claim may be appealed.")
        claim["status"] = "APPEALED"
        db.touch(claim)
    return object_response(serialize.warranty_claim(claim))


@bp.post("/clinic/warranty-claims/<cid>/replace")
def replace_claim(cid):
    auth = require_auth()
    require_role(auth, {"BillingClerk"})
    body = get_json_body()

    with db.lock:
        # Existence (404) and state (409) precede business rules per the PRD
        # validation chain; the OCC body field is checked after them.
        claim = get_or_404(db.warranty_claims, cid)
        if claim["status"] != "APPROVED":
            raise errors.invalid_state("Only an APPROVED claim may be replaced.")
        # OCC field is non-optional (missing/wrong-type -> ERR_INVALID_REQUEST).
        expected = validate.require_int(body, "expected_warranty_claim_version")
        # OCC value check (priority 19).
        if expected != claim["version"]:
            raise errors.stale_version("expected_warranty_claim_version is stale.")

        order = db.orders.get(claim["fitting_order_id"])
        if order is None:
            raise errors.not_found()

        # Ledger: WARRANTY_DEDUCTIBLE amount = +deductible.
        append_ledger(order["patient_id"], "WARRANTY_DEDUCTIBLE", claim["id"],
                      claim["deductible_cents"], "Warranty deductible")

        # LOSS replacement ships current firmware -> refresh fitted firmware.
        if claim["claim_type"] == "LOSS":
            device = db.device_models.get(order["device_model_id"])
            if device is not None:
                order["fitted_firmware_version"] = device["firmware_version"]
                db.touch(order)

        claim["status"] = "REPLACED"
        db.touch(claim)
    return object_response(serialize.warranty_claim(claim))


# --- helpers ----------------------------------------------------------------
def _require_claim_ownership(auth, claim):
    """Resolve the claim's order -> patient_id and enforce Patient ownership."""
    if auth.role != "Patient":
        return
    order = db.orders.get(claim["fitting_order_id"])
    owner = order["patient_id"] if order else None
    require_ownership(auth, owner)


def _within_warranty_window(order):
    """clock date <= purchase_date + warranty_months months.

    Purchase date is derived from the order's trial_started_at + trial window
    is NOT the purchase moment; instead we use the order's updated_at at the
    time of purchase. To keep this deterministic we record purchase via the
    ledger's ORDER_PURCHASE created_at, which is the canonical purchase instant.
    """
    device = db.device_models.get(order["device_model_id"])
    if device is None:
        return False
    purchase_dt = _purchase_instant(order)
    if purchase_dt is None:
        return False
    window_end = add_months(clock_date(purchase_dt), device["warranty_months"])
    return clock_date(clock.now()) <= window_end


def _purchase_instant(order):
    """The instant the order was purchased, taken from its ORDER_PURCHASE
    ledger entry's created_at (canonical money-movement record)."""
    best = None
    for entry in db.ledger.values():
        if entry["source_kind"] == "ORDER_PURCHASE" and entry["source_ref_id"] == order["id"]:
            dt = parse_iso(entry["created_at"])
            if dt is not None and (best is None or dt < best):
                best = dt
    return best
