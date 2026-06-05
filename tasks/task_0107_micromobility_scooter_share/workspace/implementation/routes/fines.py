"""Fine endpoints (PRD §3.5, §3.6).

GET  /api/fines/{id}                 — PlatformAdmin, Rider
GET  /api/fines                       — PlatformAdmin, Rider
POST /api/fines/{id}/settle           — Rider
POST /api/fines/{id}/dispute          — Rider
POST /api/fines/{id}/reject-dispute   — PlatformAdmin
POST /api/fines/{id}/waive            — PlatformAdmin
"""
from flask import Blueprint, request

import errors
from db import db, touch
from middleware import authenticate, require_role, require_rider_owner
from response import success
from services.wallet import create_txn
from util import public, parse_pagination, paginate

bp = Blueprint("fines", __name__)


@bp.get("/api/fines/<fine_id>")
def get_fine(fine_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    fine = _require_fine(fine_id)
    require_rider_owner(role, user_id, fine["rider_id"])
    return success(public(fine))


@bp.get("/api/fines")
def list_fines():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    limit, offset = parse_pagination()

    rows = list(db.fines.values())
    if role == "Rider":
        rows = [r for r in rows if r["rider_id"] == user_id]

    rider_id = request.args.get("rider_id")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    trip_id = request.args.get("trip_id")
    if trip_id is not None:
        rows = [r for r in rows if r["trip_id"] == trip_id]
    settlement_status = request.args.get("settlement_status")
    if settlement_status is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)


@bp.post("/api/fines/<fine_id>/settle")
def settle_fine(fine_id):
    role, user_id = authenticate()
    require_role(role, {"Rider"})
    fine = _require_fine(fine_id)
    require_rider_owner(role, user_id, fine["rider_id"])

    # State (priority 6): must be PENDING.
    if fine["settlement_status"] != "PENDING":
        raise errors.invalid_state("Fine is not PENDING")

    rider = db.riders[fine["rider_id"]]
    # Fiscal (priority 14): wallet_balance_cents >= amount_cents.
    if rider["wallet_balance_cents"] < fine["amount_cents"]:
        raise errors.ApiError(
            errors.ERR_INSUFFICIENT_WALLET, 422,
            "Wallet balance is insufficient to settle the fine",
        )

    # Settle clears the outstanding flag only; the debit happened at creation.
    fine["settlement_status"] = "SETTLED"
    touch(fine)
    rider["outstanding_fine_cents"] -= fine["amount_cents"]
    touch(rider)
    return success(public(fine))


@bp.post("/api/fines/<fine_id>/dispute")
def dispute_fine(fine_id):
    role, user_id = authenticate()
    require_role(role, {"Rider"})
    fine = _require_fine(fine_id)
    require_rider_owner(role, user_id, fine["rider_id"])
    if fine["settlement_status"] != "PENDING":
        raise errors.invalid_state("Fine is not PENDING")
    fine["settlement_status"] = "DISPUTED"
    touch(fine)
    return success(public(fine))


@bp.post("/api/fines/<fine_id>/reject-dispute")
def reject_dispute(fine_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    fine = _require_fine(fine_id)
    if fine["settlement_status"] != "DISPUTED":
        raise errors.invalid_state("Fine is not DISPUTED")
    fine["settlement_status"] = "PENDING"
    touch(fine)
    return success(public(fine))


@bp.post("/api/fines/<fine_id>/waive")
def waive_fine(fine_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    fine = _require_fine(fine_id)
    if fine["settlement_status"] != "DISPUTED":
        raise errors.invalid_state("Fine is not DISPUTED")

    fine["settlement_status"] = "WAIVED"
    touch(fine)

    # Compensation: FINE_REFUND wallet credit; clear outstanding (PRD §3.6).
    rider = db.riders[fine["rider_id"]]
    create_txn(rider["id"], "FINE_REFUND", fine["amount_cents"], fine_id=fine["id"])
    rider["wallet_balance_cents"] += fine["amount_cents"]
    rider["outstanding_fine_cents"] -= fine["amount_cents"]
    touch(rider)
    return success(public(fine))


def _require_fine(fine_id):
    fine = db.fines.get(fine_id)
    if fine is None:
        raise errors.not_found("Fine not found")
    return fine
