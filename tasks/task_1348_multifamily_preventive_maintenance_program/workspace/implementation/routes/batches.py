"""Entry batches and their lifecycle (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import errors as E
from errors import ApiError
from db import store, new_common_fields, touch, parse_dt, fmt_ts, now
from middleware import auth, require_role, body, v_str, paginate
from response import ok_object, ok_list
from services.core import (get_property, get_batch, require_active_property,
                           estimated_visit_cost)
from services.compliance import add_ledger_entry, committed_cents
from services.serializers import batch_view

bp = Blueprint("batches", __name__)

PM = ("PropertyManager",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")


@bp.route("/pm/batches", methods=["POST"])
def create_batch():
    _, role = auth()
    require_role(role, PM)
    data = body()
    prop = None
    if data.get("property_id") is not None:
        prop = get_property(data["property_id"])
        require_active_property(prop)
    pid = v_str(data, "property_id")
    label = v_str(data, "batch_label")
    ws_raw = v_str(data, "window_start")
    we_raw = v_str(data, "window_end")
    try:
        ws, _ = parse_dt(ws_raw)
    except ValueError:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "window_start is not a valid ISO 8601 datetime")
    try:
        we, _ = parse_dt(we_raw)
    except ValueError:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "window_end is not a valid ISO 8601 datetime")
    if we <= ws:
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "window_end must be strictly after window_start")
    if prop is None:
        prop = get_property(pid)
        require_active_property(prop)
    rec = new_common_fields()
    rec.update({
        "property_id": prop["id"],
        "batch_label": label,
        "window_start": ws_raw,
        "window_end": we_raw,
        "_window_start": ws,
        "_window_end": we,
        "status": "DRAFT",
        "notice_sent_at": None,
        "_notice_dt": None,
    })
    store.batches[rec["id"]] = rec
    return ok_object(batch_view(rec), 201)


@bp.route("/pm/batches/<batch_id>", methods=["GET"])
def get_batch_route(batch_id):
    _, role = auth()
    require_role(role, ALL)
    b = get_batch(batch_id)
    return ok_object(batch_view(b), 200)


@bp.route("/pm/properties/<property_id>/batches", methods=["GET"])
def list_batches(property_id):
    _, role = auth()
    require_role(role, ALL)
    prop = get_property(property_id)
    rows = [b for b in store.batches.values() if b["property_id"] == prop["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([batch_view(b) for b in page], limit, offset, total)


def _batch_visits(batch_id):
    return [v for v in store.visits.values() if v["batch_id"] == batch_id]


@bp.route("/pm/batches/<batch_id>/publish", methods=["POST"])
def publish_batch(batch_id):
    _, role = auth()
    require_role(role, PM)
    b = get_batch(batch_id)
    prop = store.properties.get(b["property_id"])
    require_active_property(prop)
    # Stage 5: state legality.
    if b["status"] != "DRAFT":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Batch in %s cannot be published" % b["status"])
    data = body()
    # Stage 6: OCC — expected_batch_version must be carried and match.
    if "expected_batch_version" not in data or data["expected_batch_version"] is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "expected_batch_version is required")
    if not isinstance(data["expected_batch_version"], int) \
            or isinstance(data["expected_batch_version"], bool):
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "expected_batch_version must be an integer")
    if data["expected_batch_version"] != b["version"]:
        raise ApiError(E.ERR_STALE_VERSION, 412,
                       "expected_batch_version does not match the batch's current version")
    # Stage 8: empty roster, then window-in-past, then visit windows.
    live = [v for v in _batch_visits(b["id"]) if v["visit_status"] != "CANCELLED"]
    if not live:
        raise ApiError(E.ERR_EMPTY_BATCH, 409, "Batch has no non-CANCELLED visits")
    clock = now()
    if not (b["_window_start"] > clock):
        raise ApiError(E.ERR_WINDOW_IN_PAST, 409,
                       "window_start is not in the future")
    for v in live:
        if not (b["_window_start"] <= v["_sched_dt"] < b["_window_end"]):
            raise ApiError(E.ERR_VISIT_OUTSIDE_WINDOW, 409,
                           "Visit %s scheduled outside the batch window" % v["id"])
    # Stage 13: fiscal gate — every plan ADOPTED first, then headroom.
    plans = {}
    for v in live:
        if v["plan_id"] not in plans:
            plans[v["plan_id"]] = store.plans.get(v["plan_id"])
    for plan in plans.values():
        if plan is None or plan["status"] != "ADOPTED":
            raise ApiError(E.ERR_PLAN_NOT_ADOPTED, 402,
                           "Plan must be ADOPTED before batch publish")
    new_commit_by_plan = {}
    for v in live:
        tpl = store.templates[v["template_id"]]
        est = estimated_visit_cost(tpl, prop)
        new_commit_by_plan[v["plan_id"]] = new_commit_by_plan.get(v["plan_id"], 0) + est
    for pid, add in new_commit_by_plan.items():
        plan = plans[pid]
        if committed_cents(pid) + add > plan["budget_cents"]:
            raise ApiError(E.ERR_BUDGET_EXCEEDED, 402,
                           "Plan budget would be exceeded by this publish")
    # Side effects: notice stamp, version bump, cascade + commits.
    clock = now()
    b["notice_sent_at"] = fmt_ts(clock)
    b["_notice_dt"] = clock
    b["status"] = "PUBLISHED"
    touch(b)
    for v in live:
        if v["visit_status"] == "SCHEDULED":
            v["visit_status"] = "NOTIFIED"
            touch(v)
        tpl = store.templates[v["template_id"]]
        est = estimated_visit_cost(tpl, prop)
        add_ledger_entry(
            v["plan_id"], "VISIT_COMMIT", est,
            source_visit_id=v["id"],
            memo="VISIT_COMMIT for visit %s at publish of batch %s" % (v["id"], b["id"]))
    return ok_object(batch_view(b), 200)


@bp.route("/pm/batches/<batch_id>/lock", methods=["POST"])
def lock_batch(batch_id):
    _, role = auth()
    require_role(role, PM)
    b = get_batch(batch_id)
    prop = store.properties.get(b["property_id"])
    require_active_property(prop)
    if b["status"] != "PUBLISHED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Batch in %s cannot be locked" % b["status"])
    if now() < b["_window_start"] - timedelta(hours=1):
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Batch cannot be locked before window_start - 1 hour")
    b["status"] = "LOCKED"
    touch(b)
    return ok_object(batch_view(b), 200)


@bp.route("/pm/batches/<batch_id>/cancel", methods=["POST"])
def cancel_batch(batch_id):
    _, role = auth()
    require_role(role, PM)
    b = get_batch(batch_id)
    prop = store.properties.get(b["property_id"])
    require_active_property(prop)
    if b["status"] != "DRAFT":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Batch in %s cannot be cancelled" % b["status"])
    b["status"] = "CANCELLED"
    touch(b)
    for v in _batch_visits(b["id"]):
        if v["visit_status"] == "SCHEDULED":
            v["visit_status"] = "CANCELLED"
            touch(v)
    return ok_object(batch_view(b), 200)
