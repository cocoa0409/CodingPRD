"""Routes: delivery snapshots and impression events."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    db, envelope_ok, paginate, sorted_items, require_role, ANY_ROLE, get_body,
    req_str, req_int, req_enum, req_date, opt_dt, now_dt, rhu_int,
    err_not_found, err_invalid_state, err_invalid_request,
    err_snapshot_out_of_flight, err_duplicate_snapshot, err_frequency_cap,
    stamp_ledger, render_instant,
)
from domain import (
    snapshot_view, event_view, get_snapshot, get_li, maybe_auto_complete,
)

bp = Blueprint("delivery", __name__)


@bp.route("/delivery-snapshots", methods=["POST"])
def create_snapshot():
    require_role("Trafficker")
    body = get_body()
    li_id = req_str(body, "line_item_id")
    sd_raw, sd = req_date(body, "snapshot_date")
    impressions = req_int(body, "impressions", minimum=0)
    clicks = req_int(body, "clicks", minimum=0)
    if clicks > impressions:
        raise err_invalid_request("clicks must not exceed impressions")

    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    if li["status"] not in ("LIVE", "PAUSED", "COMPLETED"):
        raise err_invalid_state("Snapshots require the line item to be LIVE, PAUSED or COMPLETED")
    if sd < li["_start"] or sd > li["_end"]:
        raise err_snapshot_out_of_flight()
    for s in db.snapshots.values():
        if s["line_item_id"] == li_id and s["_date"] == sd:
            raise err_duplicate_snapshot()

    snap = {
        "line_item_id": li_id,
        "snapshot_date": sd_raw,
        "_date": sd,
        "impressions": impressions,
        "clicks": clicks,
        "spend_cents": rhu_int(impressions * li["cpm_rate_cents"], 1000),
        "status": "POSTED",
    }
    stamp_ledger(snap)
    db.snapshots[snap["id"]] = snap
    maybe_auto_complete(li)
    return envelope_ok(snapshot_view(snap), status=201)


@bp.route("/line-items/<li_id>/delivery-snapshots", methods=["GET"])
def list_snapshots(li_id):
    require_role(*ANY_ROLE)
    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    items = [s for s in db.snapshots.values() if s["line_item_id"] == li_id]
    return paginate([snapshot_view(s) for s in sorted_items(items)])


@bp.route("/delivery-snapshots/<sid>/transition", methods=["POST"])
def snapshot_transition(sid):
    require_role("Trafficker")
    body = get_body()
    req_enum(body, "action", ("VOID",))
    snap = get_snapshot(sid)
    if snap is None:
        raise err_not_found("Delivery snapshot not found")
    if snap["status"] != "POSTED":
        raise err_invalid_state("VOID requires status POSTED")
    snap["status"] = "VOIDED"
    return envelope_ok(snapshot_view(snap), status=200)


@bp.route("/impression-events", methods=["POST"])
def create_event():
    require_role("Trafficker")
    body = get_body()
    li_id = req_str(body, "line_item_id")
    user_key = req_str(body, "user_key")
    oc_raw, oc = opt_dt(body, "occurred_at")

    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    if li["status"] != "LIVE":
        raise err_invalid_state("Impression events require the line item to be LIVE")

    if oc is None:
        occurred_dt = now_dt()
        occurred_raw = render_instant(occurred_dt)
    else:
        occurred_dt = oc
        occurred_raw = oc_raw

    cap = li["frequency_cap_max_impressions"]
    if cap is not None:
        now = now_dt()
        window_start = now - timedelta(hours=li["frequency_cap_window_hours"])
        count = 0
        for e in db.events.values():
            if e["line_item_id"] != li_id or e["user_key"] != user_key:
                continue
            # Trailing window (now - window_hours, now): both bounds exclusive;
            # an event exactly window_hours old is excluded.
            if window_start < e["_occurred"] < now:
                count += 1
        if count >= cap:
            raise err_frequency_cap()

    ev = {
        "line_item_id": li_id,
        "user_key": user_key,
        "occurred_at": occurred_raw,
        "_occurred": occurred_dt,
    }
    stamp_ledger(ev)
    db.events[ev["id"]] = ev
    return envelope_ok(event_view(ev), status=201)


@bp.route("/line-items/<li_id>/impression-events", methods=["GET"])
def list_events(li_id):
    require_role(*ANY_ROLE)
    li = get_li(li_id)
    if li is None:
        raise err_not_found("Line item not found")
    items = [e for e in db.events.values() if e["line_item_id"] == li_id]
    user_key = request.args.get("user_key")
    if user_key is not None:
        items = [e for e in items if e["user_key"] == user_key]
    return paginate([event_view(e) for e in sorted_items(items)])
