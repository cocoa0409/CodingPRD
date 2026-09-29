"""Vendor scorecards: computation, listing and publication."""

from flask import Blueprint, request

import calc
import serialize
import validate as v
from auth import authenticate, require_vendor_scope
from db import db, new_row, now, touch
from errors import api_error
from response import created, listing, ok, paginate, pagination
from r_vendors import get_vendor

bp = Blueprint("scorecards", __name__)

METRIC_VARIANTS = ("EVENT_EQUAL", "UNIT_WEIGHTED")


@bp.post("/dropship/vendors/<vendor_id>/scorecards")
def create_scorecard(vendor_id):
    authenticate(("VendorOpsAnalyst", "PlatformAdmin"))
    get_vendor(vendor_id)
    body = v.payload()

    # rank 12
    period_start = v.req_date(body, "period_start")
    period_end = v.req_date(body, "period_end")
    metric_variant = v.opt_enum(body, "metric_variant", METRIC_VARIANTS, "EVENT_EQUAL")
    seed_hours = v.opt_number(body, "seeded_prior_avg_ship_hours", None, None, 0, None)
    seed_on_time = v.opt_int(body, "seeded_prior_on_time_ship_rate_bps", None, 0, 10000)
    seed_cancel = v.opt_int(body, "seeded_prior_cancellation_rate_bps", None, 0, 10000)
    seed_defect = v.opt_int(body, "seeded_prior_defect_rate_bps", None, 0, 10000)

    # rank 13
    if period_end < period_start:
        api_error("ERR_INVALID_INTERVAL", "period_end must be on or after period_start")

    row = new_row()
    row.update({
        "vendor_id": vendor_id,
        "period_start": period_start,
        "period_end": period_end,
        "metric_variant": metric_variant,
        "seeded_prior_avg_ship_hours": seed_hours,
        "seeded_prior_on_time_ship_rate_bps": seed_on_time,
        "seeded_prior_cancellation_rate_bps": seed_cancel,
        "seeded_prior_defect_rate_bps": seed_defect,
        "transmitted_line_count": 0,
        "shipped_line_count": 0,
        "cancelled_line_count": 0,
        "defect_return_count": 0,
        "transmitted_unit_count": 0,
        "shipped_unit_count": 0,
        "cancelled_unit_count": 0,
        "defect_unit_count": 0,
        "on_time_ship_rate_bps": None,
        "cancellation_rate_bps": None,
        "defect_rate_bps": None,
        "avg_ship_hours": None,
        "composite_score": None,
        "tier": "UNRATED",
        "promise_padding_days": calc.PROMISE_DEFAULT_PADDING_DAYS,
        "status": "DRAFT",
        "published_at": None,
    })
    calc.compute_scorecard(row)
    db.scorecards[row["id"]] = row
    return created(serialize.scorecard(row))


@bp.get("/dropship/vendors/<vendor_id>/scorecards")
def list_scorecards(vendor_id):
    caller = authenticate(("PlatformAdmin", "VendorOpsAnalyst",
                           "MerchandiseManager", "VendorUser"))
    get_vendor(vendor_id)
    require_vendor_scope(caller, vendor_id)

    status = v.filter_enum(request.args, "status", ("DRAFT", "PUBLISHED"))
    metric_variant = v.filter_enum(request.args, "metric_variant", METRIC_VARIANTS)
    limit, offset = pagination(request.args)

    rows = [s for s in db.scorecards.values() if s["vendor_id"] == vendor_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if metric_variant is not None:
        rows = [s for s in rows if s["metric_variant"] == metric_variant]

    rows = sorted(rows, key=lambda s: (s["created_at"], s["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.scorecard(s) for s in page], limit, offset, total)


@bp.post("/dropship/scorecards/<scorecard_id>/publish")
def publish_scorecard(scorecard_id):
    authenticate(("PlatformAdmin",))

    scorecard = db.scorecards.get(scorecard_id)
    if scorecard is None:
        api_error("ERR_SCORECARD_NOT_FOUND", "scorecard %s does not exist" % scorecard_id)

    body = v.payload()
    expected = v.req_int(body, "expected_vendor_version", 0, None)

    vendor = db.vendors.get(scorecard["vendor_id"])
    # rank 18
    if vendor is None or expected != vendor["version"]:
        api_error("ERR_STALE_VENDOR_VERSION",
                  "expected_vendor_version %d does not match the vendor's current version" % expected)

    # rank 24
    if scorecard["status"] != "DRAFT":
        api_error("ERR_SCORECARD_INVALID_STATE",
                  "publish is not allowed from %s" % scorecard["status"])

    scorecard["status"] = "PUBLISHED"
    scorecard["published_at"] = now()
    touch(scorecard)

    vendor["performance_tier"] = scorecard["tier"]
    vendor["promise_padding_days"] = scorecard["promise_padding_days"]
    suspending = scorecard["tier"] == "PROBATION" and vendor["onboarding_status"] == "ACTIVE"
    if suspending:
        vendor["onboarding_status"] = "SUSPENDED"
        vendor["suspension_reason"] = "SCORECARD_PROBATION"
    touch(vendor)
    if suspending:
        calc.suspension_cascade(vendor)

    return ok(serialize.scorecard(scorecard))
