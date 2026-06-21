"""Usage event routes: ingest, read, list, allocate, void."""
from flask import Blueprint, request

import db
from errors import (fail, ERR_INVALID_STATE, ERR_SHARES_NOT_LOCKED,
                    ERR_RIGHTS_NOT_AVAILABLE)
from middleware import authorize
from response import success
from services import serialize as S
from services import calculations as C
from services.common import (stamp_create, touch, require_body, require_enum,
                             require_str, require_int, optional_int,
                             require_datetime, parse_pagination, paginate,
                             sorted_by_creation, parse_dt)
from services.lookup import path_get, fk_get
from services.allocation import distribute_earnings

bp = Blueprint("usage_events", __name__)

USAGE_TYPES = {"PERFORMANCE", "MECHANICAL"}
# usage_type -> required rights_type licensing class (PRD §3.3).
USAGE_RIGHTS_CLASS = {"PERFORMANCE": "PERFORMANCE", "MECHANICAL": "MECHANICAL"}


@bp.route("/usage-events", methods=["POST"])
def ingest_usage_event():
    authorize({"RoyaltyOperator"})
    data = require_body(request.get_json(silent=True))
    recording_id = data.get("recording_id")
    fk_get(db.recordings, recording_id)
    usage_type = require_enum(data, "usage_type", USAGE_TYPES)
    territory = require_str(data, "territory")
    occurred_at_dt = require_datetime(data, "occurred_at")
    quantity = require_int(data, "quantity", minimum=1)
    # gross_revenue_cents required for PERFORMANCE, ignored for MECHANICAL.
    gross_revenue_cents = optional_int(data, "gross_revenue_cents", 0, minimum=0)
    rec = {
        "recording_id": recording_id,
        "usage_type": usage_type,
        "territory": territory,
        "occurred_at": data["occurred_at"],
        "quantity": quantity,
        "gross_revenue_cents": gross_revenue_cents,
        "status": "INGESTED",
        "royalty_cents": 0,
        "allocated_holder_count": 0,
    }
    stamp_create(rec)
    db.usage_events[rec["id"]] = rec
    return success(S.usage_event(rec), status=201)


@bp.route("/usage-events/<rid>", methods=["GET"])
def get_usage_event(rid):
    authorize({"Administrator", "RoyaltyOperator"})
    rec = path_get(db.usage_events, rid)
    return success(S.usage_event(rec))


@bp.route("/usage-events", methods=["GET"])
def list_usage_events():
    authorize({"Administrator", "RoyaltyOperator"})
    limit, offset = parse_pagination(request.args)
    items = list(db.usage_events.values())
    recording_id = request.args.get("recording_id")
    status = request.args.get("status")
    usage_type = request.args.get("usage_type")
    if recording_id is not None:
        items = [e for e in items if e["recording_id"] == recording_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if usage_type is not None:
        items = [e for e in items if e["usage_type"] == usage_type]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.usage_event(e) for e in page], pagination=meta)


def _rights_window_covers(recording_id, rights_type, territory, instant_dt):
    """True if an ACTIVE RightsWindow of rights_type on the recording covers the
    territory and (for usage) the instant within its half-open term."""
    ts = instant_dt.timestamp()
    for w in db.rights_windows.values():
        if w["recording_id"] != recording_id:
            continue
        if w["status"] != "ACTIVE":
            continue
        if w["rights_type"] != rights_type:
            continue
        # Territory coverage: WW window covers any territory; otherwise exact.
        if w["territory"] != "WW" and w["territory"] != territory:
            continue
        start = parse_dt(w["term_start"]).timestamp()
        end = parse_dt(w["term_end"]).timestamp()
        if start <= ts < end:
            return True
    return False


@bp.route("/usage-events/<rid>/allocate", methods=["POST"])
def allocate_usage_event(rid):
    authorize({"RoyaltyOperator"})
    event = path_get(db.usage_events, rid)
    # 1. State (priority 6).
    if event["status"] != "INGESTED":
        fail(ERR_INVALID_STATE, "Usage event is not INGESTED")
    recording = db.recordings[event["recording_id"]]
    work = db.works[recording["work_id"]]
    # 2. Shares locked (priority 11): both Work and Recording locked.
    if not (work["shares_locked"] and recording["shares_locked"]):
        fail(ERR_SHARES_NOT_LOCKED, "Work and Recording shares must both be locked")
    occurred_at_dt = parse_dt(event["occurred_at"])
    # 3. Rights window (priority 12): matching rights_type covering territory + instant.
    rights_type = USAGE_RIGHTS_CLASS[event["usage_type"]]
    if not _rights_window_covers(recording["id"], rights_type,
                                 event["territory"], occurred_at_dt):
        fail(ERR_RIGHTS_NOT_AVAILABLE, "No covering ACTIVE rights window for this usage")
    # 4. Compute royalty pool (rounded once).
    if event["usage_type"] == "PERFORMANCE":
        pool = C.performance_pool_royalty(work, event)
        holders = [{"rightsholder_id": s["rightsholder_id"], "split_bps": s["split_bps"]}
                   for s in db.composition_shares.values()
                   if s["work_id"] == work["id"]]
    else:  # MECHANICAL
        pool = C.mechanical_statutory_royalty(recording, event)
        holders = [{"rightsholder_id": s["rightsholder_id"], "split_bps": s["split_bps"]}
                   for s in db.recording_shares.values()
                   if s["recording_id"] == recording["id"]]
    allocations = C.allocate_to_holders(pool, holders)
    # 5. Open-statement precondition + distribution (priority 13). Atomic:
    #    raises ERR_NO_OPEN_STATEMENT before writing anything if any holder lacks
    #    a covering DRAFT statement for occurred_at.
    holder_count = distribute_earnings(allocations, occurred_at_dt,
                                       "USAGE_EVENT", event["id"])
    event["royalty_cents"] = pool
    event["allocated_holder_count"] = holder_count
    event["status"] = "ALLOCATED"
    touch(event)
    return success(S.usage_event(event))


@bp.route("/usage-events/<rid>/void", methods=["POST"])
def void_usage_event(rid):
    authorize({"RoyaltyOperator"})
    event = path_get(db.usage_events, rid)
    if event["status"] != "INGESTED":
        fail(ERR_INVALID_STATE, "Only an INGESTED usage event can be voided")
    event["status"] = "VOIDED"
    touch(event)
    return success(S.usage_event(event))
