"""Performance snapshots: monthly actuals vs the actualized forecast."""

from decimal import Decimal

from flask import Blueprint

from db import db
from errors import ApiError, not_found, already_terminal
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import new_record, touch, ser_snapshot
from util import (
    get_body, req_int, fk_exists, list_response, rhu_int,
)

bp = Blueprint("snapshots", __name__)

MISS_THRESHOLD_BP = -2000  # inclusive: exactly -2000 IS a miss


@bp.post("/api/performance-snapshots")
def create_snapshot():
    require_roles("RealEstateManager")
    body = get_body(required=True)
    site = fk_exists(body, "site_id", db.sites)
    period = req_int(body, "period_index", min_v=1)
    actual = req_int(body, "actual_sales_cents", min_v=0)
    # Layer 8: strictly sequential against FINALIZED snapshots only.
    finalized = sum(
        1 for s in db.snapshots.values()
        if s["site_id"] == site["id"] and s["snapshot_status"] == "FINALIZED")
    if period != finalized + 1:
        raise ApiError(
            "ERR_PERIOD_GAP", 422,
            f"period_index must equal {finalized + 1}")
    # Layer 9: the site must be trading.
    if site["site_status"] not in ("OPEN", "MEASURING", "UNDERPERFORMING"):
        raise ApiError(
            "ERR_SITE_NOT_OPEN", 409,
            f"Site in {site['site_status']} does not accept snapshots")
    rec = new_record()
    rec.update({
        "site_id": site["id"],
        "period_index": period,
        "actual_sales_cents": actual,
        "expected_sales_cents": None,
        "variance_bp": None,
        "snapshot_status": "RECORDED",
    })
    db.snapshots[rec["id"]] = rec
    return ok_object(ser_snapshot(rec), status=201)


@bp.get("/api/performance-snapshots")
def list_snapshots():
    require_roles(*ALL_API_ROLES)
    return list_response(db.snapshots.values(), ser_snapshot,
                         filters=["site_id", "snapshot_status"])


@bp.get("/api/performance-snapshots/<sid>")
def get_snapshot(sid):
    require_roles(*ALL_API_ROLES)
    rec = db.snapshots.get(sid)
    if rec is None:
        raise not_found(f"PerformanceSnapshot not found: {sid}")
    return ok_object(ser_snapshot(rec))


@bp.post("/api/performance-snapshots/<sid>/finalize")
def finalize_snapshot(sid):
    require_roles("RealEstateManager")
    rec = db.snapshots.get(sid)
    if rec is None:
        raise not_found(f"PerformanceSnapshot not found: {sid}")
    if rec["snapshot_status"] == "FINALIZED":
        raise already_terminal("PerformanceSnapshot is FINALIZED")
    site = db.sites[rec["site_id"]]
    # Baseline: the site's ACTUALIZED forecast; on the first finalize the
    # COMMITTEE_LOCKED forecast is actualized first and becomes the baseline.
    baseline = next(
        (f for f in db.forecasts.values()
         if f["site_id"] == site["id"]
         and f["forecast_status"] == "ACTUALIZED"), None)
    if baseline is None:
        baseline = next(
            (f for f in db.forecasts.values()
             if f["site_id"] == site["id"]
             and f["forecast_status"] == "COMMITTEE_LOCKED"), None)
    net = baseline["net_annual_sales_cents"] if baseline is not None else 0
    expected = rhu_int(Decimal(net) / Decimal(12))
    actual = rec["actual_sales_cents"]
    if expected == 0:
        variance = 0 if actual == 0 else 9999999
    else:
        variance = rhu_int(
            Decimal(actual - expected) * 10000 / Decimal(expected))
    rec["expected_sales_cents"] = expected
    rec["variance_bp"] = variance
    rec["snapshot_status"] = "FINALIZED"
    touch(rec)
    site_changed = False
    # First FINALIZED snapshot: OPEN -> MEASURING and the forecast actualizes.
    if site["site_status"] == "OPEN":
        site["site_status"] = "MEASURING"
        site_changed = True
        if baseline is not None and baseline["forecast_status"] == "COMMITTEE_LOCKED":
            baseline["forecast_status"] = "ACTUALIZED"
            touch(baseline)
    # Miss bookkeeping on the site.
    if variance <= MISS_THRESHOLD_BP:
        site["consecutive_miss_count"] += 1
        site_changed = True
    else:
        if site["consecutive_miss_count"] != 0:
            site["consecutive_miss_count"] = 0
            site_changed = True
    # Cascade 2: two consecutive misses degrade MEASURING -> UNDERPERFORMING.
    if (site["consecutive_miss_count"] >= 2
            and site["site_status"] == "MEASURING"):
        site["site_status"] = "UNDERPERFORMING"
        site_changed = True
    # Cascade 3: a better-than-miss finalize recovers UNDERPERFORMING.
    elif (variance > MISS_THRESHOLD_BP
          and site["site_status"] == "UNDERPERFORMING"):
        site["site_status"] = "MEASURING"
        site_changed = True
    if site_changed:
        touch(site)
    return ok_object(ser_snapshot(rec))
