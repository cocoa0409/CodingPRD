"""Fine list / read / waive endpoints (PRD §3.11)."""
from __future__ import annotations

from flask import Blueprint, g, request

from auth import require_roles
from common import paginate, parse_pagination
from envelope import success
from errors import ApiError
from serializers import serialize_fine
import store
from store import iso_z, lock, now


bp = Blueprint("fines", __name__, url_prefix="/api/fines")


def _find_fine(fid: str) -> dict:
    f = store.fines.get(fid)
    if not f:
        raise ApiError("ERR_NOT_FOUND", "Fine not found.")
    return f


@bp.get("/<fid>")
@require_roles("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
def read_fine(fid: str):
    f = _find_fine(fid)
    # Subject identity guard for non-CS/Admin
    if g.role in ("Rider", "Restaurant", "Customer"):
        if g.user_id != f["subject_id"]:
            raise ApiError("ERR_FORBIDDEN", "Subject identity mismatch.")
    return success(serialize_fine(f))


@bp.get("")
@require_roles("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
def list_fines():
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")
    limit, offset = parse_pagination()

    if g.role in ("Rider", "Restaurant", "Customer"):
        if subject_id is not None and subject_id != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Subject identity mismatch.")
        subject_id = g.user_id
        if g.role == "Rider":
            subject_type = "RIDER"
        elif g.role == "Restaurant":
            subject_type = "RESTAURANT"
        else:
            subject_type = "CUSTOMER"

    items = list(store.fines.values())
    if subject_type:
        items = [f for f in items if f["subject_type"] == subject_type]
    if subject_id:
        items = [f for f in items if f["subject_id"] == subject_id]
    if settlement_status:
        items = [f for f in items if f["settlement_status"] == settlement_status]
    items.sort(key=lambda f: f["created_at"])
    window, meta = paginate(items, limit, offset)
    return success([serialize_fine(f) for f in window], list_meta=meta)


@bp.post("/<fid>/waive")
@require_roles("CustomerService", "PlatformAdmin")
def waive_fine(fid: str):
    f = _find_fine(fid)
    if f["settlement_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only PENDING fines can be waived.")
    with lock():
        f["settlement_status"] = "WAIVED"
        # Reverse ledger effect on subject.
        if f["subject_type"] == "RIDER":
            rider = store.riders.get(f["subject_id"])
            if rider:
                rider["wallet_balance_cents"] += f["amount_cents"]
                rider["updated_at"] = iso_z(now())
                rider["version"] += 1
        elif f["subject_type"] == "CUSTOMER":
            cust = store.customers.get(f["subject_id"])
            if cust:
                # ABUSIVE_RETURN created a fine but did not previously debit the
                # customer's credit balance — the approval already credited it.
                # The PRD says waiving restores a customer's credit balance, so we
                # reverse by adding back the fine amount.
                cust["credit_balance_cents"] += f["amount_cents"]
                cust["updated_at"] = iso_z(now())
                cust["version"] += 1
        elif f["subject_type"] == "RESTAURANT":
            rest = store.restaurants.get(f["subject_id"])
            if rest:
                rest["pending_settlement_cents"] += f["amount_cents"]
                rest["updated_at"] = iso_z(now())
                rest["version"] += 1
    return success(serialize_fine(f))
