"""DowntimeWindow endpoints (PRD §3.5)."""

from flask import Blueprint, request

from calc import windows_overlap
from db import bump, new_record, sorted_records, store
from errors import ApiError, ERR_INVALID_STATE, ERR_WINDOW_EMPTY, ERR_WINDOW_OVERLAP
from middleware import forbidden, require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from util import get_body, pagination_params, paginate, req_datetime, req_str
from routes.common import check_customer_ownership, customer_owns, get_or_404

bp = Blueprint("windows", __name__)


@bp.post("/api/downtime-windows")
@require_roles("Customer", "LogisticsCoordinator")
def create_window(user_id, role):
    body = get_body()
    # Ownership (gate 2): a Customer books only own windows.
    if role == "Customer" and isinstance(body.get("customer_id"), str):
        if body["customer_id"] != user_id:
            raise forbidden("customer cannot book a window for another customer")
    customer_id = req_str(body, "customer_id")
    starts_dt, starts_raw = req_datetime(body, "starts_at")
    ends_dt, ends_raw = req_datetime(body, "ends_at")
    # Gate 4: body-referenced customer existence.
    get_or_404(store.customers, customer_id, "customer")
    # Gate 8 (temporal): half-open window must be non-empty.
    if ends_dt <= starts_dt:
        raise ApiError(
            ERR_WINDOW_EMPTY,
            "ends_at must be strictly after starts_at",
            409,
        )
    # Gate 9 (structural): no overlap with same-customer OPEN/LOCKED windows.
    for w in store.windows.values():
        if w["customer_id"] != customer_id or w["status"] not in ("OPEN", "LOCKED"):
            continue
        if windows_overlap(starts_dt, ends_dt, w["_starts_dt"], w["_ends_dt"]):
            raise ApiError(
                ERR_WINDOW_OVERLAP,
                "window overlaps an existing OPEN/LOCKED window of this customer",
                409,
            )
    rec = new_record(
        {
            "customer_id": customer_id,
            "starts_at": starts_raw,
            "ends_at": ends_raw,
            "status": "OPEN",
            "_starts_dt": starts_dt,
            "_ends_dt": ends_dt,
        }
    )
    store.windows[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/api/downtime-windows/<wid>")
@require_roles("Customer", "LogisticsCoordinator", "ProjectManager", "PlatformAdmin")
def get_window(user_id, role, wid):
    rec = get_or_404(store.windows, wid, "downtime window")
    check_customer_ownership(user_id, role, "window", rec)
    return success(serialize(rec))


@bp.get("/api/downtime-windows")
@require_roles("Customer", "LogisticsCoordinator", "ProjectManager", "PlatformAdmin")
def list_windows(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.windows)
    customer_filter = request.args.get("customer_id")
    if customer_filter is not None:
        items = [w for w in items if w["customer_id"] == customer_filter]
    if role == "Customer":
        items = [w for w in items if customer_owns(user_id, "window", w)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


@bp.post("/api/downtime-windows/<wid>/cancel")
@require_roles("Customer", "LogisticsCoordinator")
def cancel_window(user_id, role, wid):
    rec = get_or_404(store.windows, wid, "downtime window")
    check_customer_ownership(user_id, role, "window", rec)
    if rec["status"] != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE,
            f"window in status {rec['status']} cannot be cancelled",
            409,
        )
    rec["status"] = "CANCELLED"
    bump(rec)
    return success(serialize(rec))
