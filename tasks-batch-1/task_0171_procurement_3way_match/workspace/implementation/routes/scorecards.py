"""VendorScorecard + clock endpoints (PRD §3.8, §2.4)."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db
from middleware import require_roles
from response import object_response, list_response
from services.common import (
    init_common, public, get_body, require_fields, invalid,
    parse_pagination, paginate, resolve, parse_instant,
)
from services.scorecard import compute_scorecard

bp = Blueprint("scorecards", __name__)

SCORECARD_READ_ROLES = ("ProcurementAdmin", "Buyer", "Approver")


@bp.route("/procurement/vendor-scorecards", methods=["POST"])
@require_roles("ProcurementAdmin")
def create_scorecard():
    body = get_body()
    require_fields(body, ["vendor_id", "period_start", "period_end"])
    vendor = resolve(db.vendors, body["vendor_id"])

    on_time_variant = body.get("on_time_variant", "STRICT")
    if on_time_variant is None:
        on_time_variant = "STRICT"
    if on_time_variant not in ("STRICT", "GRACE"):
        invalid("on_time_variant must be STRICT or GRACE")

    period_start = parse_instant(body["period_start"], "period_start")
    period_end = parse_instant(body["period_end"], "period_end")
    if not (period_end > period_start):
        invalid("period_end must be after period_start")

    # Half-open overlap (adjacency allowed) for the same vendor.
    for sc in db.vendor_scorecards.values():
        if sc["vendor_id"] != vendor["id"]:
            continue
        ex_start = sc["_period_start_dt"]
        ex_end = sc["_period_end_dt"]
        # Half-open [a,b) overlaps [c,d) when a < d and c < b.
        if period_start < ex_end and ex_start < period_end:
            raise ApiError(errors.ERR_SCORECARD_PERIOD_OVERLAP, 409,
                           "Scorecard period overlaps an existing period")

    metrics = compute_scorecard(vendor, period_start, period_end, on_time_variant)

    rec = {
        "vendor_id": vendor["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "on_time_variant": on_time_variant,
        "on_time_rate_pct": metrics["on_time_rate_pct"],
        "price_compliance_pct": metrics["price_compliance_pct"],
        "exception_pct": metrics["exception_pct"],
        "composite_score": metrics["composite_score"],
        "status": "FINAL",
        "_period_start_dt": period_start,
        "_period_end_dt": period_end,
    }
    init_common(rec)
    db.vendor_scorecards[rec["id"]] = rec
    return object_response(public(rec), status=201)


@bp.route("/procurement/vendor-scorecards/<sid>", methods=["GET"])
@require_roles(*SCORECARD_READ_ROLES)
def get_scorecard(sid):
    rec = resolve(db.vendor_scorecards, sid)
    return object_response(public(rec))


@bp.route("/procurement/vendor-scorecards", methods=["GET"])
@require_roles(*SCORECARD_READ_ROLES)
def list_scorecards():
    limit, offset = parse_pagination(request.args)
    vendor_id = request.args.get("vendor_id")
    items = []
    for rec in db.vendor_scorecards.values():
        if vendor_id is not None and rec["vendor_id"] != vendor_id:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# -----------------------------------------------------------------------------
# Test-driving clock
# -----------------------------------------------------------------------------
@bp.route("/procurement/_clock/set_current_utc", methods=["POST"])
@require_roles("ProcurementAdmin")
def set_clock():
    body = get_body()
    require_fields(body, ["to_iso8601"])
    instant = parse_instant(body["to_iso8601"], "to_iso8601")
    db.set_clock(instant)
    return object_response({})
