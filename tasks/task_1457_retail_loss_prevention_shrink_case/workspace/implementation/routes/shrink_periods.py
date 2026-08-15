"""Shrink period endpoints (PRD §3.9)."""

from decimal import Decimal

from flask import Blueprint, request

from db import db, clock_now, fmt_iso, parse_iso
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import (
    body, req_string, req_int, req_datetime, get_or_404,
)
from services.entities import make_shrink_period, make_case, pub, touch
from services.calculations import (
    recompute_period_accruals, compute_variance, VARIANCE_BREACH_PCT,
)
from errors import (
    err400, err409, err412,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_STORE_CLOSED,
    ERR_PERIOD_OVERLAP, ERR_PERIOD_LOCKED, ERR_STALE_PERIOD_VERSION,
    ERR_COUNT_REQUIRED,
)

bp = Blueprint("shrink_periods", __name__)


@bp.route("/shrink-periods", methods=["POST"])
def create_period():
    user_id, role = get_auth()
    require_role(role, {"LPAdmin"})
    data = body()
    store_id = req_string(data, "store_id")
    period_start = req_datetime(data, "period_start")
    period_end = req_datetime(data, "period_end")
    book_inventory_cents = req_int(data, "book_inventory_cents", minimum=1)
    period_sales_cents = req_int(data, "period_sales_cents", minimum=0)

    if parse_iso(period_end) < parse_iso(period_start):
        raise err400(ERR_INVALID_REQUEST,
                     "period_end must be on or after period_start")

    store = get_or_404(db.stores, store_id, "store")
    if store["status"] != "ACTIVE":
        raise err409(ERR_STORE_CLOSED, "Store is CLOSED")

    # strictly disjoint closed intervals per store: touching endpoints conflict
    new_s = parse_iso(period_start)
    new_e = parse_iso(period_end)
    for p in db.shrink_periods.values():
        if p["store_id"] != store_id:
            continue
        ex_s = parse_iso(p["period_start"])
        ex_e = parse_iso(p["period_end"])
        # closed-interval intersection: [s1,e1] & [s2,e2] != empty
        if new_s <= ex_e and ex_s <= new_e:
            raise err409(ERR_PERIOD_OVERLAP,
                         "Period overlaps or abuts an existing period for this "
                         "store")

    period = make_shrink_period(store_id, period_start, period_end,
                                book_inventory_cents, period_sales_cents)
    recompute_period_accruals(period)
    db.shrink_periods[period["id"]] = period
    return success_object(pub(period), status=201)


@bp.route("/shrink-periods", methods=["GET"])
def list_periods():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    store_id = _q("store_id")
    status = _q("status")
    auto_case_id = _q("auto_case_id")
    items = sorted(db.shrink_periods.values(),
                   key=lambda p: (p["created_at"], p["id"]))
    if store_id is not None:
        items = [p for p in items if p["store_id"] == store_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if auto_case_id is not None:
        items = [p for p in items if p.get("auto_case_id") == auto_case_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(p) for p in page], limit, offset, total)


@bp.route("/shrink-periods/<period_id>", methods=["GET"])
def get_period(period_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    period = get_or_404(db.shrink_periods, period_id, "shrink period")
    return success_object(pub(period))


@bp.route("/shrink-periods/<period_id>/record-count", methods=["POST"])
def record_count(period_id):
    user_id, role = get_auth()
    require_role(role, {"LPAdmin"})
    data = body()
    counted_inventory_cents = req_int(data, "counted_inventory_cents", minimum=0)
    expected_version = req_int(data, "expected_shrink_period_version")
    period = get_or_404(db.shrink_periods, period_id, "shrink period")
    if period["status"] in ("RECONCILED", "CLOSED"):
        raise err409(ERR_PERIOD_LOCKED,
                     "Period is %s and no longer accepts counts"
                     % period["status"])
    if period["status"] not in ("OPEN", "COUNTED"):
        raise err409(ERR_PERIOD_LOCKED, "Period does not accept counts")
    # OCC
    if expected_version != period["version"]:
        raise err412(ERR_STALE_PERIOD_VERSION,
                     "expected_shrink_period_version does not match the period's "
                     "current version")
    period["counted_inventory_cents"] = counted_inventory_cents
    period["counted_at"] = fmt_iso(clock_now())
    period["status"] = "COUNTED"
    touch(period)  # increments version by 1 per spec
    return success_object(pub(period))


@bp.route("/shrink-periods/<period_id>/reconcile", methods=["POST"])
def reconcile_period(period_id):
    user_id, role = get_auth()
    require_role(role, {"LPAdmin"})
    period = get_or_404(db.shrink_periods, period_id, "shrink period")
    if period["status"] == "OPEN":
        raise err409(ERR_COUNT_REQUIRED,
                     "A physical count is required before reconcile")
    if period["status"] != "COUNTED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Period must be COUNTED to reconcile")

    # (1) variance snapshot uses live known_loss_posted_cents
    variance_cents, variance_pct = compute_variance(period)
    period["variance_cents"] = variance_cents
    period["variance_pct"] = float(variance_pct)
    # (2) transition to RECONCILED — stops accepting postings
    period["status"] = "RECONCILED"
    touch(period)

    # breach -> auto-create shrink-investigation case
    if abs(variance_pct) >= VARIANCE_BREACH_PCT:
        store = db.stores[period["store_id"]]
        manual_loss = max(0, -variance_cents)
        case = make_case(store, "SHRINK_VARIANCE", "UNKNOWN", None,
                         "system", manual_loss_cents=manual_loss)
        db.cases[case["id"]] = case
        case["total_loss_cents"] = max(0, case["manual_loss_cents"])
        touch(case)
        period["auto_case_id"] = case["id"]
        touch(period)
    return success_object(pub(period))


@bp.route("/shrink-periods/<period_id>/close", methods=["POST"])
def close_period(period_id):
    user_id, role = get_auth()
    require_role(role, {"LPAdmin"})
    period = get_or_404(db.shrink_periods, period_id, "shrink period")
    if period["status"] != "RECONCILED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Period must be RECONCILED to close")
    period["status"] = "CLOSED"
    touch(period)
    return success_object(pub(period))


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
