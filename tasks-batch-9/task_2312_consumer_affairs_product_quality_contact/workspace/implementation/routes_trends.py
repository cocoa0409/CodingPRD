"""Trend signals, investigations, recalls and the quality operations checkpoint."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
from common import (
    ROLE_CARE_SUPERVISOR,
    ROLE_QUALITY_LEAD,
    ROLE_REGULATORY_OFFICER,
    authorize,
    check_required,
    err,
    fmt_datetime,
    get_body,
    must_get,
    pagination,
    paginated,
    q_str,
    sort_records,
    store,
    success,
    touch,
    v_bool,
    v_datetime,
    v_enum,
    v_string,
)

bp = Blueprint("trends", __name__)

SCOPE_LEVELS = ("LOT", "LINE", "PLANT")
OPEN_SIGNAL_STATES = ("DETECTED", "INVESTIGATION_OPEN", "RECALL_EVALUATION")
HOLD_EXEMPT_COMPLAINT_STATES = ("RESOLVED", "CLOSED", "DUPLICATE", "ON_QUALITY_HOLD")


@bp.post("/trend-signals")
def create_signal():
    authorize([ROLE_QUALITY_LEAD])
    body = get_body()
    if "plant_id" in body and body["plant_id"] is not None:
        must_get("plants", body["plant_id"])
    if "production_line_id" in body and body["production_line_id"] is not None:
        must_get("production_lines", body["production_line_id"])
    if "lot_id" in body and body["lot_id"] is not None:
        must_get("production_lots", body["lot_id"])
    check_required(body, ["scope_level", "plant_id", "window_start", "window_end"])
    scope_level = v_enum(body, "scope_level", SCOPE_LEVELS)
    plant_id = v_string(body, "plant_id", 1)
    window_start = v_datetime(body, "window_start")
    window_end = v_datetime(body, "window_end")
    line_id = v_string(body, "production_line_id", 1)
    lot_id = v_string(body, "lot_id", 1)

    for signal in sort_records(list(store.trend_signals.values())):
        if signal["status"] not in OPEN_SIGNAL_STATES:
            continue
        if svc.scope_key(signal) != (scope_level, plant_id, line_id, lot_id):
            continue
        if svc.windows_overlap(
            window_start, window_end, signal["window_start"], signal["window_end"]
        ):
            raise err(
                "ERR_SIGNAL_WINDOW_OVERLAP",
                "an open signal for this scope already covers part of this window",
            )

    if not window_end > window_start:
        raise err("ERR_WINDOW_INVALID", "window_end must be strictly after window_start")

    shape_ok = True
    if scope_level == "LOT":
        shape_ok = line_id is not None and lot_id is not None
        if shape_ok:
            lot = store.production_lots[lot_id]
            line = store.production_lines[line_id]
            shape_ok = lot["production_line_id"] == line_id and line["plant_id"] == plant_id
    elif scope_level == "LINE":
        shape_ok = line_id is not None and lot_id is None
        if shape_ok:
            shape_ok = store.production_lines[line_id]["plant_id"] == plant_id
    else:
        shape_ok = line_id is None and lot_id is None
    if not shape_ok:
        raise err(
            "ERR_SCOPE_SHAPE_INVALID",
            "scope_level, production_line_id and lot_id are not mutually consistent",
        )

    if scope_level == "LOT":
        lots = [store.production_lots[lot_id]]
    elif scope_level == "LINE":
        lots = svc.lots_of_line(line_id)
    else:
        lots = svc.lots_of_plant(plant_id)
    lot_ids = {l["id"] for l in lots}

    members = [
        c
        for c in calc.eligible_complaints(window_start, window_end)
        if c.get("lot_id") in lot_ids
    ]
    figures = svc.evaluate_scope(members, lots, scope_level)
    if not members:
        raise err(
            "ERR_SIGNAL_EMPTY_MEMBERSHIP", "the declared window contains no eligible complaint"
        )

    signal = svc.create_signal(
        scope_level, plant_id, line_id, lot_id, window_start, window_end, figures, "MANUAL"
    )
    for complaint in members:
        svc.add_membership(signal, complaint)
        ser.sync_complaint_signal_count(complaint)
    ser.sync_signal(signal)
    return success(ser.trend_signal(signal), 201)


@bp.get("/trend-signals")
def list_signals():
    authorize([ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR, ROLE_REGULATORY_OFFICER])
    limit, offset = pagination()
    filters = {
        "plant_id": q_str("plant_id"),
        "production_line_id": q_str("production_line_id"),
        "lot_id": q_str("lot_id"),
        "scope_level": q_str("scope_level"),
        "status": q_str("status"),
        "detection_source": q_str("detection_source"),
    }
    items = []
    for rec in sort_records(list(store.trend_signals.values())):
        if any(value is not None and rec.get(key) != value for key, value in filters.items()):
            continue
        items.append(ser.trend_signal(rec))
    return paginated(items, limit, offset)


@bp.get("/trend-signals/<record_id>")
def get_signal(record_id):
    authorize([ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR, ROLE_REGULATORY_OFFICER])
    rec = must_get("trend_signals", record_id)
    return success(ser.trend_signal(rec))


@bp.get("/trend-signals/<record_id>/memberships")
def list_memberships(record_id):
    authorize([ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR, ROLE_REGULATORY_OFFICER])
    must_get("trend_signals", record_id)
    limit, offset = pagination()
    items = [ser.signal_membership(m) for m in svc.memberships_of_signal(record_id)]
    return paginated(items, limit, offset)


@bp.post("/trend-signals/<record_id>/open-investigation")
def open_investigation(record_id):
    actor = authorize([ROLE_QUALITY_LEAD])
    rec = must_get("trend_signals", record_id)
    body = get_body()
    v_string(body, "investigation_note", 0)

    if rec["status"] != "DETECTED":
        raise err(
            "ERR_TREND_SIGNAL_STATE_INVALID", "only a DETECTED signal may open an investigation"
        )
    if rec["membership_count"] < 1:
        raise err("ERR_SIGNAL_EMPTY_MEMBERSHIP", "the signal has no member complaints")

    rec["status"] = "INVESTIGATION_OPEN"
    rec["opened_by_ref"] = actor.user_id
    touch(rec)
    ser.sync_plant(store.plants.get(rec["plant_id"]))
    return success(ser.trend_signal(rec))


@bp.post("/trend-signals/<record_id>/dismiss")
def dismiss_signal(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("trend_signals", record_id)
    body = get_body()
    v_string(body, "reason", 0)

    if rec["status"] != "DETECTED":
        raise err("ERR_TREND_SIGNAL_STATE_INVALID", "only a DETECTED signal may be dismissed")
    rec["status"] = "DISMISSED"
    touch(rec)
    ser.sync_plant(store.plants.get(rec["plant_id"]))
    return success(ser.trend_signal(rec))


@bp.post("/trend-signals/<record_id>/escalate-recall-evaluation")
def escalate_signal(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("trend_signals", record_id)
    body = get_body()
    v_string(body, "escalation_note", 0)

    if rec["status"] != "INVESTIGATION_OPEN":
        raise err(
            "ERR_TREND_SIGNAL_STATE_INVALID",
            "only an INVESTIGATION_OPEN signal may be escalated",
        )
    members = svc.member_complaints(record_id)
    if not any(calc.effective_band(c) in ("S1", "S2") for c in members):
        raise err(
            "ERR_SEVERITY_TOO_LOW_FOR_RECALL",
            "no member complaint reaches severity band S1 or S2",
        )

    rec["status"] = "RECALL_EVALUATION"
    touch(rec)

    for complaint in members:
        if complaint["handling_status"] in HOLD_EXEMPT_COMPLAINT_STATES:
            continue
        svc.impose_quality_hold(complaint)
        ser.sync_consumer(store.consumers.get(complaint["consumer_id"]))

    source = "SIGNAL:%s" % rec["id"]
    for lot in svc.lots_in_signal_scope(rec):
        svc.hold_lot(lot, source)

    ser.sync_plant(store.plants.get(rec["plant_id"]))
    return success(ser.trend_signal(rec))


@bp.post("/trend-signals/<record_id>/initiate-recall")
def initiate_recall(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("trend_signals", record_id)
    body = get_body()
    check_required(body, ["recall_reference"])
    v_string(body, "recall_reference", 1)

    if rec["status"] != "RECALL_EVALUATION":
        raise err(
            "ERR_TREND_SIGNAL_STATE_INVALID",
            "only a signal under RECALL_EVALUATION may initiate a recall",
        )

    for complaint in svc.member_complaints(record_id):
        if complaint["regulatory_status"] != "REPORTABLE":
            continue
        filed = any(
            report["status"] == "SUBMITTED"
            for report in svc.reports_of_complaint(complaint["id"])
        )
        if not filed:
            raise err(
                "ERR_REGULATORY_SUBMISSION_PENDING",
                "a reportable member complaint has no submitted regulatory report",
            )

    rec["status"] = "RECALL_INITIATED"
    touch(rec)

    for lot in svc.lots_in_signal_scope(rec):
        if lot["release_status"] != "WITHDRAWN":
            lot["release_status"] = "WITHDRAWN"
            touch(lot)

    ser.sync_plant(store.plants.get(rec["plant_id"]))
    return success(ser.trend_signal(rec))


@bp.post("/trend-signals/<record_id>/close-no-action")
def close_no_action(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("trend_signals", record_id)
    body = get_body()
    v_string(body, "closing_note", 0)

    if rec["status"] not in ("INVESTIGATION_OPEN", "RECALL_EVALUATION"):
        raise err(
            "ERR_TREND_SIGNAL_STATE_INVALID",
            "only an open investigation or recall evaluation may be closed",
        )
    rec["status"] = "CLOSED_NO_ACTION"
    touch(rec)

    source = "SIGNAL:%s" % rec["id"]
    for lot in svc.lots_in_signal_scope(rec):
        svc.drop_hold_source(lot, source)

    ser.sync_plant(store.plants.get(rec["plant_id"]))
    return success(ser.trend_signal(rec))


# ---------------------------------------------------------------------------
# operations checkpoint
# ---------------------------------------------------------------------------
@bp.post("/quality-ops-runs")
def quality_ops_run():
    authorize([ROLE_QUALITY_LEAD])
    body = get_body()
    dry_run = v_bool(body, "dry_run", False)

    snapshot = store.snapshot() if dry_run else None
    result = svc.run_quality_ops()
    if dry_run:
        store.restore(snapshot)

    payload = dict(result)
    payload["run_at"] = fmt_datetime(result["run_at"])
    return success(payload)
