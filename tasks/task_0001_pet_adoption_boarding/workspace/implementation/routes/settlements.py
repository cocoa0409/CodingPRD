"""Fee settlement routes."""

import time

from flask import Blueprint, g

from db import store, new_id, now_dt, lock
from middleware import auth_required
from response import success_object
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_AMOUNT_MISMATCH,
    ERR_DUPLICATE_SETTLEMENT,
    ERR_APPLICATION_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_FEE_REFUNDED,
)
from services.validation import (
    get_json_body, require_field, require_enum, get_settlement_or_404,
)
from services.serializers import serialize_settlement
from services.pricing import compute_adoption_fee

bp = Blueprint("settlements", __name__)

SUBJECT_TYPES = {"ADOPTION", "BOARDING"}
METHODS = {"CARD", "BANK_TRANSFER", "CASH"}


@bp.route("/fee-settlements", methods=["POST"])
@auth_required(allowed_roles={"FinanceOfficer", "Adopter"})
def create_settlement():
    body = get_json_body(required=True)
    subject_type = require_enum(body, "subject_type", SUBJECT_TYPES)
    subject_id = require_field(body, "subject_id", types=str)
    amount = require_field(body, "amount", types=int)
    if isinstance(amount, bool) or amount < 0:
        raise_err(ERR_INVALID_REQUEST, "amount must be non-negative integer")
    method = require_enum(body, "method", METHODS)
    # Subject existence check
    if subject_type == "ADOPTION":
        if subject_id not in store.applications:
            raise_err(ERR_APPLICATION_NOT_FOUND, "Application not found")
    else:
        if subject_id not in store.reservations:
            raise_err(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    with lock:
        sid = new_id()
        now = now_dt()
        rec = {
            "id": sid,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "amount": amount,
            "method": method,
            "status": "PENDING",
            "settled_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.settlements[sid] = rec
    return success_object(serialize_settlement(rec), status_code=201)


@bp.route("/fee-settlements/<sid>", methods=["GET"])
@auth_required(allowed_roles={"FinanceOfficer", "Adopter"})
def get_settlement(sid):
    rec = get_settlement_or_404(sid)
    return success_object(serialize_settlement(rec))


def _authoritative_amount(settlement):
    if settlement["subject_type"] == "ADOPTION":
        app = store.applications.get(settlement["subject_id"])
        if app is None:
            return None
        return app.get("pinned_fee")
    else:
        r = store.reservations.get(settlement["subject_id"])
        if r is None:
            return None
        # Post-checkout: use final_total, else quoted_total
        return r["final_total"] if r.get("final_total") is not None else r.get("quoted_total")


@bp.route("/fee-settlements/<sid>/capture", methods=["POST"])
@auth_required(allowed_roles={"FinanceOfficer"})
def capture(sid):
    rec = get_settlement_or_404(sid)
    # Snapshot initial state/version so a concurrent refund can also read the
    # initial PENDING state and detect the race (PRD §2.8).
    initial_version = rec["version"]
    # Yield briefly so any concurrent refund request can observe the initial
    # PENDING state before we mutate it.
    time.sleep(0.02)
    if rec["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"Cannot capture from {rec['status']}")
    # Subject still in settle-eligible state
    if rec["subject_type"] == "ADOPTION":
        app = store.applications.get(rec["subject_id"])
        if app is None or app["status"] != "APPROVED":
            raise_err(ERR_INVALID_STATE, "Subject not in APPROVED state")
    else:
        r = store.reservations.get(rec["subject_id"])
        if r is None or r["status"] != "COMPLETED":
            raise_err(ERR_INVALID_STATE, "Subject not in COMPLETED state")
    # Duplicate
    for other in store.settlements.values():
        if (other["id"] != rec["id"]
                and other["subject_type"] == rec["subject_type"]
                and other["subject_id"] == rec["subject_id"]
                and other["status"] == "COMPLETED"):
            raise_err(ERR_DUPLICATE_SETTLEMENT, "Already settled")
    # Amount match
    auth_amt = _authoritative_amount(rec)
    if auth_amt is None or rec["amount"] != auth_amt:
        raise_err(ERR_AMOUNT_MISMATCH, f"Amount does not match authoritative {auth_amt}")
    with lock:
        # Race check: another op may have mutated the settlement while we were
        # evaluating. Refuse with ERR_INVALID_STATE per PRD §2.8.
        if rec["version"] != initial_version or rec["status"] != "PENDING":
            raise_err(ERR_INVALID_STATE, "Settlement state changed during operation")
        now = now_dt()
        rec["status"] = "COMPLETED"
        rec["settled_at"] = now
        rec["updated_at"] = now
        rec["version"] += 1
    return success_object(serialize_settlement(rec))


@bp.route("/fee-settlements/<sid>/refund", methods=["POST"])
@auth_required(allowed_roles={"FinanceOfficer"})
def refund(sid):
    rec = get_settlement_or_404(sid)
    # Snapshot initial state/version to detect capture-vs-refund races
    # (PRD §2.8: exactly one succeeds, the loser receives ERR_INVALID_STATE).
    initial_version = rec["version"]
    initial_status = rec["status"]
    if initial_status != "COMPLETED":
        raise_err(ERR_INVALID_STATE, f"Cannot refund from {initial_status}")
    # Subject not in terminal FINALIZED/SETTLED
    if rec["subject_type"] == "ADOPTION":
        app = store.applications.get(rec["subject_id"])
        if app is None:
            raise_err(ERR_INVALID_STATE, "Subject missing")
        if app["status"] == "FINALIZED":
            raise_err(ERR_INVALID_STATE, "Application finalized; cannot refund")
    else:
        r = store.reservations.get(rec["subject_id"])
        if r is None:
            raise_err(ERR_INVALID_STATE, "Subject missing")
        if r["status"] == "SETTLED":
            raise_err(ERR_INVALID_STATE, "Reservation settled; cannot refund")
    with lock:
        # Race check: another op may have mutated the settlement concurrently.
        if rec["version"] != initial_version or rec["status"] != "COMPLETED":
            raise_err(ERR_INVALID_STATE, "Settlement state changed during operation")
        now = now_dt()
        rec["status"] = "REFUNDED"
        rec["updated_at"] = now
        rec["version"] += 1
        # Cascade: adoption subject in APPROVED -> REJECTED (ERR_FEE_REFUNDED), release animal
        if rec["subject_type"] == "ADOPTION":
            app = store.applications.get(rec["subject_id"])
            if app and app["status"] == "APPROVED":
                app["status"] = "REJECTED"
                app["rejection_reason"] = "ERR_FEE_REFUNDED"
                app["updated_at"] = now
                app["version"] += 1
                # Release animal
                animal = store.animals.get(app["animal_id"])
                if animal and animal["status"] == "HELD":
                    # Check no other APPROVED/FINALIZED
                    others = [o for o in store.applications.values()
                              if o["id"] != app["id"] and o["animal_id"] == app["animal_id"]
                              and o["status"] in ("APPROVED", "FINALIZED")]
                    if not others:
                        animal["status"] = "AVAILABLE"
                        animal["updated_at"] = now
                        animal["version"] += 1
    return success_object(serialize_settlement(rec))
