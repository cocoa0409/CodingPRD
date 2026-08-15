from flask import Blueprint, request

import response
from db import store, new_rec, serialize, parse_dt, add_years
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_ASSIGNED_APPRAISER,
    ERR_INVALID_STATE,
    ERR_COMPARABLE_TOO_OLD,
)
from middleware import (
    auth,
    require_role,
    get_body,
    req_str,
    req_int,
    opt_num,
    opt_bool,
)
from response import sort_by_creation
from services import calc, domain

bp = Blueprint("comparables", __name__)


@bp.post("/engagements/<engagementId>/comparables")
def create_comparable(engagementId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    eng = domain.get_engagement(engagementId)
    body = get_body()
    address = req_str(body, "address")
    sale_date_raw = body.get("sale_date")
    if not isinstance(sale_date_raw, str) or not sale_date_raw.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "sale_date is required")
    try:
        sale_date = parse_dt(sale_date_raw)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "sale_date must be ISO 8601")
    if sale_date > store.clock:
        raise ApiError(ERR_INVALID_REQUEST, 400, "sale_date must not be in the future")
    sale_price_cents = req_int(body, "sale_price_cents", minimum=1)
    noi_at_sale_cents = req_int(body, "noi_at_sale_cents", minimum=1)
    size_sf = req_int(body, "size_sf", minimum=1)
    adjustment_pct = opt_num(body, "adjustment_pct", default=0)
    selected_for_support = opt_bool(body, "selected_for_support", default=True)
    # Priority 6: author ownership.
    if eng["author_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_APPRAISER,
            403,
            "Caller is not the engagement's author appraiser",
        )
    # Priority 8: engagement state.
    if eng["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is not IN_PROGRESS")
    # Priority 12: 24-month lookback from accepted_at.
    if sale_date < add_years(eng["accepted_at"], -2):
        raise ApiError(
            ERR_COMPARABLE_TOO_OLD,
            409,
            "sale_date is earlier than accepted_at - 24 months",
        )
    implied, adjusted = calc.comparable_rates(
        sale_price_cents, noi_at_sale_cents, adjustment_pct
    )
    rec = new_rec(
        {
            "engagement_id": eng["id"],
            "address": address,
            "sale_date": sale_date_raw,
            "sale_price_cents": sale_price_cents,
            "noi_at_sale_cents": noi_at_sale_cents,
            "size_sf": size_sf,
            "adjustment_pct": adjustment_pct,
            "selected_for_support": selected_for_support,
            "implied_cap_rate_bps": implied,
            "adjusted_cap_rate_bps": adjusted,
        }
    )
    store.comparables[rec["id"]] = rec
    return response.success(serialize(rec), status=201)


@bp.get("/comparables/<comparableId>")
def get_comparable(comparableId):
    auth()
    rec = domain.get_comparable(comparableId)
    return response.success(serialize(rec))


@bp.get("/comparables")
def list_comparables():
    auth()
    items = list(store.comparables.values())
    v = request.args.get("engagement_id")
    if v is not None:
        items = [r for r in items if r.get("engagement_id") == v]
    items = sort_by_creation(items)
    return response.list_response([serialize(r) for r in items])
