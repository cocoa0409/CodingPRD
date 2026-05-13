"""Corporate event routes — splits, dividends, restructuring, blackouts, CoC, IPO."""

from flask import Blueprint, request
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_INVALID_TIME_INTERVAL,
    ERR_BLACKOUT_OVERLAPS_WINDOW,
)
from services.common import (
    init_append_only, get_body, get_or_404,
    get_pagination, paginate_list, sort_by_created_at_asc,
    require_enum, require_iso_datetime,
)
from services.time_util import format_iso, parse_iso
from services.serializers import serialize_corporate_event, serialize_price_version
from services.calculations import compute_price_for_event
from services.audit import append_audit


bp = Blueprint("corporate_events", __name__)


EVENT_TYPES = {
    "EARNINGS_BLACKOUT", "MATERIAL_EVENT_BLACKOUT",
    "STOCK_SPLIT", "CASH_DIVIDEND", "RESTRUCTURING",
    "CHANGE_OF_CONTROL", "IPO",
}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    return not (a_end <= b_start or b_end <= a_start)


@bp.post("/option-plans/<plan_id>/corporate-events")
@auth_required(["PlanAdministrator"])
def create_event(plan_id):
    plan = get_or_404("option_plans", plan_id)
    body = get_body()
    event_type = require_enum(body, "event_type", EVENT_TYPES)
    effective_dt = require_iso_datetime(body, "effective_ts")
    end_dt = None
    if event_type in ("EARNINGS_BLACKOUT", "MATERIAL_EVENT_BLACKOUT"):
        end_dt = require_iso_datetime(body, "blackout_end_ts")
        if end_dt <= effective_dt:
            raise_error(ERR_INVALID_TIME_INTERVAL, "blackout_end_ts must be > effective_ts")
        # Check overlap with existing windows
        for w in DB["exercise_windows"].values():
            if w["plan_id"] != plan_id:
                continue
            if w["status"] in ("CLOSED", "ARCHIVED"):
                continue
            w_open = parse_iso(w["open_ts"])
            w_close = parse_iso(w["close_ts"])
            if _intervals_overlap(w_open, w_close, effective_dt, end_dt):
                raise_error(ERR_BLACKOUT_OVERLAPS_WINDOW, "Blackout overlaps existing window")
    # Type-specific shape validations
    snum = sden = div_cents = factor_bps = None
    if event_type == "STOCK_SPLIT":
        snum = body.get("split_ratio_numerator")
        sden = body.get("split_ratio_denominator")
        if (not isinstance(snum, int) or isinstance(snum, bool) or snum < 1
                or not isinstance(sden, int) or isinstance(sden, bool) or sden < 1):
            raise_error(ERR_INVALID_REQUEST, "split ratios must be integers >= 1")
    elif event_type == "CASH_DIVIDEND":
        div_cents = body.get("dividend_amount_cents")
        if not isinstance(div_cents, int) or isinstance(div_cents, bool) or div_cents < 1:
            raise_error(ERR_INVALID_REQUEST, "dividend_amount_cents must be >= 1")
    elif event_type == "RESTRUCTURING":
        factor_bps = body.get("restructure_factor_bps")
        if (not isinstance(factor_bps, int) or isinstance(factor_bps, bool)
                or factor_bps < 100 or factor_bps > 100000):
            raise_error(ERR_INVALID_REQUEST, "restructure_factor_bps must be in [100, 100000]")

    eid = new_id()
    event = {
        "id": eid,
        "plan_id": plan_id,
        "event_type": event_type,
        "effective_ts": format_iso(effective_dt),
        "blackout_end_ts": format_iso(end_dt) if end_dt else None,
        "split_ratio_numerator": snum,
        "split_ratio_denominator": sden,
        "dividend_amount_cents": div_cents,
        "restructure_factor_bps": factor_bps,
    }
    init_append_only(event)
    DB["corporate_events"][eid] = event

    # Cascade: STOCK_SPLIT, CASH_DIVIDEND, RESTRUCTURING emit new price version per batch
    if event_type in ("STOCK_SPLIT", "CASH_DIVIDEND", "RESTRUCTURING"):
        for batch in list(DB["grant_batches"].values()):
            if batch["plan_id"] != plan_id:
                continue
            # Find current tip for this batch
            tip = _tip_for_batch(batch["id"])
            if tip is None:
                continue  # no v1 yet — skip
            new_price = compute_price_for_event(int(tip["price_per_option_cents"]), event)
            vid = new_id()
            v = {
                "id": vid,
                "plan_id": plan_id,
                "batch_id": batch["id"],
                "version_index": int(tip["version_index"]) + 1,
                "parent_version_id": tip["id"],
                "cause": event_type,
                "corporate_event_id": eid,
                "price_per_option_cents": new_price,
                "effective_from_ts": plan.get("current_clock_ts"),
                "disclosed_at": None,
            }
            init_append_only(v)
            DB["exercise_price_versions"][vid] = v
            append_audit(plan, "PRICE_VERSION_CREATED", "ExercisePriceVersion", vid,
                         {"batch_id": batch["id"], "cause": event_type,
                          "version_index": v["version_index"],
                          "price_per_option_cents": new_price})
    return success_response(serialize_corporate_event(event), http_status=201)


def _tip_for_batch(batch_id):
    best = None
    for v in DB["exercise_price_versions"].values():
        if v["batch_id"] != batch_id:
            continue
        if best is None or v["version_index"] > best["version_index"]:
            best = v
    return best


@bp.get("/option-plans/<plan_id>/corporate-events")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "AuditViewer"])
def list_events(plan_id):
    get_or_404("option_plans", plan_id)
    limit, offset = get_pagination()
    items = [e for e in DB["corporate_events"].values() if e["plan_id"] == plan_id]
    et = request.args.get("event_type")
    if et:
        items = [e for e in items if e["event_type"] == et]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_corporate_event(e) for e in sliced], total, limit, offset)
