"""Temporary services and patrol visits."""
import math
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request
import db
from db import clock, format_ts, parse_ts
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import (
    base_record, touch, get_or_404, serialize_temporary_service,
    serialize_patrol_visit, find_current_assignment,
    round_half_up_int, PRIORITY_MULTIPLIER,
)

bp = Blueprint("services", __name__)

SERVICE_KINDS = {"POWER", "LIGHTING", "PATROL"}


@bp.route("/jobs/<jid>/temporary-services", methods=["POST"])
def create_service(jid):
    require_role("Dispatcher")
    job = get_or_404(db.jobs, jid, "Job")
    body = get_body()
    require_fields(body, ["kind", "starts_at", "ends_at"])
    kind = check_enum(body["kind"], SERVICE_KINDS, "kind")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    if job["work_status"] != "SECURED":
        raise err("ERR_INVALID_STATE", "Job must be SECURED to start a service")
    try:
        starts_at = parse_ts(body["starts_at"])
        ends_at = parse_ts(body["ends_at"])
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid timestamp format")
    if ends_at <= starts_at:
        raise err("ERR_INVALID_REQUEST", "ends_at must be after starts_at")
    prop = db.properties.get(job["property_id"])
    market = db.markets.get(prop["market_id"])
    generator_units = body.get("generator_units", 1)
    if kind == "POWER":
        if not isinstance(generator_units, int) or generator_units < 1:
            raise err("ERR_INVALID_REQUEST", "generator_units must be a positive integer")
        # capacity check across the market
        used = 0
        for s in db.temporary_services.values():
            if s["kind"] == "POWER" and s["status"] in ("ACTIVE", "PAUSED"):
                sj = db.jobs.get(s["job_id"])
                if sj is None:
                    continue
                sp = db.properties.get(sj["property_id"])
                if sp and sp["market_id"] == market["id"]:
                    used += s.get("generator_units", 1)
        if used + generator_units > market["generator_pool_units"]:
            raise err("ERR_GENERATOR_POOL_EXHAUSTED", "Generator pool exhausted")
        daily_rate = market["temp_power_daily_rate_cents"]
    elif kind == "LIGHTING":
        daily_rate = market["temp_lighting_daily_rate_cents"]
    else:
        daily_rate = 0
    rec = base_record()
    rec.update({
        "job_id": job["id"],
        "kind": kind,
        "starts_at": format_ts(starts_at),
        "ends_at": format_ts(ends_at),
        "generator_units": generator_units if kind == "POWER" else None,
        "daily_rate_cents": daily_rate,
        "status": "ACTIVE",
        "deactivated_at": None,
        "billable_days": None,
        "service_total_cents": None,
    })
    db.temporary_services[rec["id"]] = rec
    return success_obj(serialize_temporary_service(rec), 201)


@bp.route("/jobs/<jid>/temporary-services", methods=["GET"])
def list_services(jid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    get_or_404(db.jobs, jid, "Job")
    limit, offset = paginate_args()
    items = [s for s in db.temporary_services.values() if s["job_id"] == jid]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_temporary_service(s) for s in page], total, limit, offset)


@bp.route("/temporary-services/<sid>", methods=["GET"])
def get_service(sid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.temporary_services, sid, "TemporaryService")
    return success_obj(serialize_temporary_service(rec))


@bp.route("/temporary-services/<sid>/deactivate", methods=["POST"])
def deactivate_service(sid):
    require_role("Dispatcher")
    rec = get_or_404(db.temporary_services, sid, "TemporaryService")
    if rec["status"] == "COMPLETED":
        raise err("ERR_ALREADY_TERMINAL", "Service already COMPLETED")
    if rec["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Service must be ACTIVE or PAUSED")
    now_dt = clock.now()
    starts_at = parse_ts(rec["starts_at"])
    ends_at = parse_ts(rec["ends_at"])
    effective_end = min(ends_at, now_dt)
    active_seconds = (effective_end - starts_at).total_seconds()
    if active_seconds < 0:
        active_seconds = 0
    billable_days = max(1, math.ceil(active_seconds / 86400))
    rec["deactivated_at"] = format_ts(now_dt)
    rec["billable_days"] = billable_days
    if rec["kind"] == "PATROL":
        rec["service_total_cents"] = 0
    else:
        rec["service_total_cents"] = billable_days * rec["daily_rate_cents"]
    rec["status"] = "COMPLETED"
    touch(rec)
    return success_obj(serialize_temporary_service(rec))


@bp.route("/temporary-services/<sid>/patrol-visits", methods=["POST"])
def create_patrol_visit(sid):
    require_role("Dispatcher")
    svc = get_or_404(db.temporary_services, sid, "TemporaryService")
    body = get_body()
    require_fields(body, ["window_start", "window_end"])
    if svc["kind"] != "PATROL":
        raise err("ERR_SERVICE_NOT_PATROL", "Patrol visits only on PATROL services")
    try:
        window_start = parse_ts(body["window_start"])
        window_end = parse_ts(body["window_end"])
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid timestamp format")
    if window_end <= window_start:
        raise err("ERR_INVALID_REQUEST", "window_end must be after window_start")
    now_dt = clock.now()
    if window_end <= now_dt:
        raise err("ERR_VISIT_WINDOW_PAST", "window_end must be strictly after current clock")
    # Overlap check (half-open intervals; adjacency allowed)
    for v in db.patrol_visits.values():
        if v["temporary_service_id"] != sid:
            continue
        if v["status"] not in ("SCHEDULED",):
            continue
        vs = parse_ts(v["window_start"])
        ve = parse_ts(v["window_end"])
        # overlap if new_start < existing_end AND new_end > existing_start
        if window_start < ve and window_end > vs:
            raise err("ERR_OVERLAP_CONFLICT", "Window overlaps existing visit")
    job = db.jobs.get(svc["job_id"])
    prop = db.properties.get(job["property_id"])
    market = db.markets.get(prop["market_id"])
    multiplier = PRIORITY_MULTIPLIER[job["priority"]]
    fee = round_half_up_int(Decimal(market["patrol_visit_fee_cents"]) * multiplier)
    rec = base_record()
    rec.update({
        "temporary_service_id": sid,
        "window_start": format_ts(window_start),
        "window_end": format_ts(window_end),
        "status": "SCHEDULED",
        "checked_in_at": None,
        "fee_cents": fee,
    })
    db.patrol_visits[rec["id"]] = rec
    return success_obj(serialize_patrol_visit(rec), 201)


@bp.route("/temporary-services/<sid>/patrol-visits", methods=["GET"])
def list_patrol_visits(sid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    get_or_404(db.temporary_services, sid, "TemporaryService")
    limit, offset = paginate_args()
    items = [v for v in db.patrol_visits.values() if v["temporary_service_id"] == sid]
    items.sort(key=lambda v: v["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_patrol_visit(v) for v in page], total, limit, offset)


@bp.route("/patrol-visits/<vid>/check-in", methods=["POST"])
def patrol_check_in(vid):
    user_id, _ = require_role("Subcontractor")
    visit = get_or_404(db.patrol_visits, vid, "PatrolVisit")
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = check_enum(body["outcome"], {"CHECKED_IN", "MISSED"}, "outcome")
    svc = db.temporary_services.get(visit["temporary_service_id"])
    if svc is None:
        raise err("ERR_NOT_FOUND", "Parent service not found")
    job = db.jobs.get(svc["job_id"])
    # assignee check: the job's currently accepted assignment (which may have
    # advanced to ARRIVED or COMPLETED since acceptance)
    assignee = find_current_assignment(job["id"])
    if assignee is None or assignee["subcontractor_id"] != user_id:
        raise err("ERR_NOT_ASSIGNEE", "Caller is not the assignee")
    if visit["status"] in ("CHECKED_IN", "MISSED"):
        raise err("ERR_ALREADY_TERMINAL", "Visit is terminal")
    if visit["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit must be SCHEDULED")
    now_dt = clock.now()
    ws = parse_ts(visit["window_start"])
    we = parse_ts(visit["window_end"])
    if outcome == "CHECKED_IN":
        if not (ws <= now_dt < we):
            raise err("ERR_VISIT_NOT_DUE", "Check-in outside window")
        visit["status"] = "CHECKED_IN"
        visit["checked_in_at"] = format_ts(now_dt)
        touch(visit)
        return success_obj(serialize_patrol_visit(visit))
    else:  # MISSED
        if now_dt < we:
            raise err("ERR_VISIT_NOT_DUE", "Cannot mark MISSED before window end")
        visit["status"] = "MISSED"
        touch(visit)
        # Cascade hop 1: parent service ACTIVE -> PAUSED
        if svc["status"] == "ACTIVE":
            svc["status"] = "PAUSED"
            touch(svc)
            # Cascade hop 2: job SECURED -> BREACH_HOLD
            if job["work_status"] == "SECURED":
                job["work_status"] = "BREACH_HOLD"
                job["safety_cleared"] = False
                touch(job)
                # Cascade hop 3: every other ACTIVE service of job -> PAUSED
                for s in db.temporary_services.values():
                    if s["job_id"] == job["id"] and s["id"] != svc["id"] and s["status"] == "ACTIVE":
                        s["status"] = "PAUSED"
                        touch(s)
        # Spawn replacement visit shifted +24h
        new_ws = ws + timedelta(hours=24)
        new_we = we + timedelta(hours=24)
        prop = db.properties.get(job["property_id"])
        market = db.markets.get(prop["market_id"])
        multiplier = PRIORITY_MULTIPLIER[job["priority"]]
        fee = round_half_up_int(Decimal(market["patrol_visit_fee_cents"]) * multiplier)
        replacement = base_record()
        replacement.update({
            "temporary_service_id": svc["id"],
            "window_start": format_ts(new_ws),
            "window_end": format_ts(new_we),
            "status": "SCHEDULED",
            "checked_in_at": None,
            "fee_cents": fee,
        })
        db.patrol_visits[replacement["id"]] = replacement
        return success_obj(serialize_patrol_visit(visit))
