"""SeasonalWindow endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope
from response import ok, ok_list
from services import stamp_new, public
from util import body, required, as_int, as_str, as_ymd, parse_ymd, pagination_args

bp = Blueprint("seasonal", __name__)


def _get_window_or_404(window_id):
    window = DB["seasonal_windows"].get(window_id)
    if window is None:
        raise ApiError(
            "ERR_SEASONAL_WINDOW_NOT_FOUND", 404, "Seasonal window not found"
        )
    return window


@bp.post("/vault-cash/seasonal-windows")
def create_window():
    auth(["CashOperationsAdmin"])
    data = body()
    site_id = as_str(required(data, "site_id"), "site_id")
    if site_id not in DB["vault_sites"]:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    name = as_str(required(data, "name"), "name")
    start_date = as_ymd(required(data, "start_date"), "start_date")
    end_date = as_ymd(required(data, "end_date"), "end_date")
    multiplier_bps = as_int(required(data, "multiplier_bps"), "multiplier_bps")
    if parse_ymd(end_date) < parse_ymd(start_date):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "end_date must be on or after start_date"
        )
    if multiplier_bps <= 10000:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "multiplier_bps must be greater than 10000"
        )
    # Disjointness: closed intervals must not overlap; adjacency allowed.
    new_start, new_end = parse_ymd(start_date), parse_ymd(end_date)
    for w in DB["seasonal_windows"].values():
        if w["site_id"] != site_id:
            continue
        w_start, w_end = parse_ymd(w["start_date"]), parse_ymd(w["end_date"])
        if new_start <= w_end and w_start <= new_end:
            raise ApiError(
                "ERR_SEASONAL_WINDOW_OVERLAP",
                409,
                "Seasonal window overlaps another window of the same site",
            )
    window = stamp_new({
        "id": new_id(),
        "site_id": site_id,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "multiplier_bps": multiplier_bps,
    })
    DB["seasonal_windows"][window["id"]] = window
    return ok(public(window), status=201)


@bp.get("/vault-cash/seasonal-windows")
def list_windows():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    site_id = request.args.get("site_id")
    rows = list(DB["seasonal_windows"].values())
    if site_id is not None:
        rows = [w for w in rows if w["site_id"] == site_id]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        rows = [w for w in rows if w["site_id"] == principal.home_site_id]
    rows.sort(key=lambda w: (w["created_at"], w["_seq"]))
    total = len(rows)
    return ok_list([public(w) for w in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/seasonal-windows/<windowId>")
def get_window(windowId):
    principal = auth(ALL_ROLES)
    window = _get_window_or_404(windowId)
    require_site_scope(principal, window["site_id"])
    return ok(public(window))
