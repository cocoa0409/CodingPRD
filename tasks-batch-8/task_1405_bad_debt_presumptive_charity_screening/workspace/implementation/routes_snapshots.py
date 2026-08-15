"""VendorPerformanceSnapshot endpoints: generate, get, list (PRD 3.4).
Snapshots are immutable once created (append-only)."""

from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, not_found
from middleware import ROLE_OFFICER, authenticate
from response import ok_list, ok_object
from services import VENDOR_MIN_RECOVERY_BPS, serialize_snapshot
from util import (
    append_only_record,
    day_start,
    get_body,
    now_iso,
    paginate,
    parse_date_value,
    parse_dt,
    req_str,
)

bp = Blueprint("vendor_snapshots", __name__)


def get_snapshot_or_404(snapshot_id):
    s = db.vendor_snapshots.get(snapshot_id)
    if s is None:
        raise not_found("vendor performance snapshot not found")
    return s


@bp.post("/self-pay/vendor-performance-snapshots")
def create_snapshot():
    authenticate([ROLE_OFFICER])
    b = get_body()
    vendor_name = req_str(b, "vendor_name")
    start_d, start_s = parse_date_value(req_str(b, "snapshot_period_start"))
    end_d, end_s = parse_date_value(req_str(b, "snapshot_period_end"))
    if end_d <= start_d:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "snapshot_period_end must be after snapshot_period_start",
            400,
        )
    start_dt = day_start(start_d)   # inclusive
    end_dt = day_start(end_d)       # exclusive (half-open window)

    candidates = [
        p for p in db.early_out_placements.values()
        if p["vendor_name"] == vendor_name
        and start_dt <= parse_dt(p["placed_at"]) < end_dt
    ]
    candidate_ids = {p["id"] for p in candidates}
    recovered = sum(
        r["amount_cents"] for r in db.recovery_transactions.values()
        if r["payment_kind"] == "EARLY_OUT_REMITTANCE"
        and r.get("attributed_placement_id") in candidate_ids
        and start_dt <= parse_dt(r["posted_at"]) < end_dt
    )
    denominator = sum(p["placement_balance_cents"] for p in candidates)
    if denominator == 0:
        rate_bps = 0
    else:
        rate_bps = (recovered * 10000) // denominator  # floor to whole bps

    rec = append_only_record()
    rec.update({
        "vendor_name": vendor_name,
        "snapshot_period_start": start_s,
        "snapshot_period_end": end_s,
        "placements_in_window": len(candidates),
        "recovered_in_window_cents": recovered,
        "recovery_rate_bps": rate_bps,
        "meets_minimum_threshold": rate_bps >= VENDOR_MIN_RECOVERY_BPS,
        "snapshot_generated_at": now_iso(),
    })
    db.vendor_snapshots[rec["id"]] = rec
    return ok_object(serialize_snapshot(rec), 201)


@bp.get("/self-pay/vendor-performance-snapshots/<snapshot_id>")
def get_snapshot(snapshot_id):
    authenticate([ROLE_OFFICER])
    return ok_object(serialize_snapshot(get_snapshot_or_404(snapshot_id)))


@bp.get("/self-pay/vendor-performance-snapshots")
def list_snapshots():
    authenticate([ROLE_OFFICER])
    items = list(db.vendor_snapshots.values())
    vendor_f = request.args.get("vendor_name")
    if vendor_f is not None:
        items = [s for s in items if s["vendor_name"] == vendor_f]
    page, meta = paginate(items)
    return ok_list([serialize_snapshot(s) for s in page], meta)
