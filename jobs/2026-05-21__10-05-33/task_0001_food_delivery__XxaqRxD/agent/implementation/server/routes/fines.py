"""Fine query + waive endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..envelope import success_list, success_object
from ..errors import ApiError
from ..pagination import page_slice, parse_pagination
from ..serializers import fine_out


bp = Blueprint("fines", __name__, url_prefix="/api")


@bp.get("/fines/<fid>")
def read_fine(fid: str):
    require_role("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
    store = g.store
    f = store.fines.get(fid)
    if not f:
        raise ApiError("ERR_NOT_FOUND")
    if g.user_role in ("Rider", "Restaurant", "Customer"):
        if f["subject_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN")
    return success_object(store.clock, fine_out(f))


@bp.get("/fines")
def list_fines():
    require_role("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
    store = g.store
    limit, offset = parse_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")
    if g.user_role in ("Rider", "Restaurant", "Customer"):
        if subject_id is not None and subject_id != g.user_id:
            raise ApiError("ERR_FORBIDDEN")
        subject_id = g.user_id
    rows = list(store.fines.values())
    if subject_type:
        rows = [f for f in rows if f["subject_type"] == subject_type]
    if subject_id:
        rows = [f for f in rows if f["subject_id"] == subject_id]
    if settlement_status:
        rows = [f for f in rows if f["settlement_status"] == settlement_status]
    page, total = page_slice(rows, limit=limit, offset=offset)
    return success_list(
        store.clock, [fine_out(f) for f in page], limit=limit, offset=offset, total_count=total
    )


@bp.post("/fines/<fid>/waive")
def waive_fine(fid: str):
    require_role("CustomerService", "PlatformAdmin")
    store = g.store
    with store.lock:
        f = store.fines.get(fid)
        if not f:
            raise ApiError("ERR_NOT_FOUND")
        if f["settlement_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE")
        now_iso = store.now_iso()
        f["settlement_status"] = "WAIVED"
        amt = f["amount_cents"]
        if f["subject_type"] == "RIDER":
            rider = store.riders.get(f["subject_id"])
            if rider is not None:
                rider["wallet_balance_cents"] += amt
                rider["version"] += 1
                rider["updated_at"] = now_iso
                from ..bonus import recompute_rider_metrics

                recompute_rider_metrics(rider)
        elif f["subject_type"] == "CUSTOMER":
            cust = store.customers.get(f["subject_id"])
            if cust is not None:
                cust["credit_balance_cents"] += amt
                cust["version"] += 1
                cust["updated_at"] = now_iso
        elif f["subject_type"] == "RESTAURANT":
            rest = store.restaurants.get(f["subject_id"])
            if rest is not None:
                rest["pending_settlement_cents"] += amt
                rest["version"] += 1
                rest["updated_at"] = now_iso
        return success_object(store.clock, fine_out(f))
