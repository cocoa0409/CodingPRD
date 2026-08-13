"""Ongoing monitoring endpoints: metrics, append-only readings, breach events."""
from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import BUSINESS_ROLES, require_roles
from response import success, success_list
from routes.models import get_model_or_404
from serializers import breach_event_json, metric_json, reading_json
from services import risk, workflow
from utils import new_id
from validate import get_body, pagination_params, v_dt, v_enum, v_number, v_str

bp = Blueprint("monitoring", __name__)


def get_metric_or_404(metric_id):
    mt = store.metrics.get(metric_id)
    if mt is None:
        raise ApiError(
            "ERR_NOT_FOUND", 404, "Monitoring metric '%s' does not exist" % metric_id
        )
    return mt


@bp.post("/mrm/models/<model_id>/monitoring-metrics")
def create_metric(model_id):
    body = get_body()
    metric_name = v_str(body, "metric_name")
    direction = v_enum(body, "direction", ("ABOVE_IS_BREACH", "BELOW_IS_BREACH"))
    threshold_value = v_number(body, "threshold_value")
    require_roles("ModelOwner")
    with store.lock:
        model = get_model_or_404(model_id)
        if g.user_id != model["owner_user_id"]:
            raise ApiError(
                "ERR_NOT_MODEL_OWNER",
                403,
                "Only the model owner may register monitoring metrics",
            )
        if model["status"] == "RETIRED":
            raise ApiError("ERR_MODEL_ALREADY_RETIRED", 409, "Model is RETIRED")
        if model["status"] != "APPROVED_FOR_USE":
            raise ApiError(
                "ERR_MODEL_NOT_APPROVED_FOR_USE",
                409,
                "Monitoring metrics can only be registered on an APPROVED_FOR_USE model",
            )
        now = store.now()
        mt = {
            "id": new_id(),
            "model_id": model_id,
            "metric_name": metric_name,
            "direction": direction,
            "threshold_value": threshold_value,
            "status": "ACTIVE",
            "consecutive_breach_count": 0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.metrics[mt["id"]] = mt
        return success(metric_json(mt), 201)


@bp.get("/mrm/models/<model_id>/monitoring-metrics")
def list_metrics(model_id):
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_status = request.args.get("status")
    with store.lock:
        get_model_or_404(model_id)
        items = [m for m in store.metrics.values() if m["model_id"] == model_id]
        items.sort(key=lambda m: (m["created_at"], m["_seq"]))
        if f_status is not None:
            items = [m for m in items if m["status"] == f_status]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([metric_json(m) for m in page], limit, offset, total)


@bp.get("/mrm/monitoring-metrics/<metric_id>")
def get_metric(metric_id):
    require_roles(*BUSINESS_ROLES)
    with store.lock:
        return success(metric_json(get_metric_or_404(metric_id)))


@bp.post("/mrm/monitoring-metrics/<metric_id>/readings")
def record_reading(metric_id):
    body = get_body()
    value = v_number(body, "value")
    observed_at = v_dt(body, "observed_at")
    require_roles("ModelOwner")
    with store.lock:
        mt = get_metric_or_404(metric_id)
        model = store.models[mt["model_id"]]
        # Ownership: caller must own the metric's model.
        if g.user_id != model["owner_user_id"]:
            raise ApiError(
                "ERR_NOT_MODEL_OWNER",
                403,
                "Only the owner of the metric's model may record readings",
            )
        # State gate
        if mt["status"] != "ACTIVE":
            raise ApiError(
                "ERR_METRIC_NOT_ACTIVE",
                409,
                "Readings can only be recorded on an ACTIVE metric",
            )
        # Temporal gate: chronological order (equal timestamps are acceptable).
        prior = [r for r in store.readings.values() if r["metric_id"] == metric_id]
        if prior:
            latest_observed = max(r["observed_at"] for r in prior)
            if observed_at < latest_observed:
                raise ApiError(
                    "ERR_READING_OUT_OF_ORDER",
                    409,
                    "observed_at precedes the metric's latest reading",
                )
        now = store.now()
        breach = risk.is_breach(mt, value)
        reading = {
            "id": new_id(),
            "metric_id": metric_id,
            "value": value,
            "observed_at": observed_at,
            "is_breach": breach,
            "created_at": now,
            "_seq": store.next_seq(),
        }
        store.readings[reading["id"]] = reading

        posture_before = risk.monitoring_posture(model["id"])
        if breach:
            mt["consecutive_breach_count"] += 1
            workflow.mutate(mt)
            event = {
                "id": new_id(),
                "metric_id": metric_id,
                "metric_name": mt["metric_name"],
                "reading_id": reading["id"],
                "breach_value": value,
                "status": "OPEN",
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "_seq": store.next_seq(),
            }
            store.breach_events[event["id"]] = event
            if risk.monitoring_posture(model["id"]) != posture_before:
                workflow.mutate(model)
            if mt["consecutive_breach_count"] == risk.CONSECUTIVE_BREACH_LIMIT:
                # Fires only on the transition to exactly 3 consecutive breaches.
                workflow.create_finding(
                    model,
                    "HIGH",
                    "AUTO: 3 consecutive breaches on %s" % mt["metric_name"],
                    "MONITORING",
                    "system",
                )
        else:
            if mt["consecutive_breach_count"] != 0:
                mt["consecutive_breach_count"] = 0
                workflow.mutate(mt)
        return success(reading_json(reading), 201)


@bp.get("/mrm/monitoring-metrics/<metric_id>/readings")
def list_readings(metric_id):
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    with store.lock:
        get_metric_or_404(metric_id)
        items = [r for r in store.readings.values() if r["metric_id"] == metric_id]
        # Chronological observation order.
        items.sort(key=lambda r: (r["observed_at"], r["_seq"]))
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([reading_json(r) for r in page], limit, offset, total)


@bp.get("/mrm/monitoring-metrics/<metric_id>/breach-events")
def list_breach_events(metric_id):
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_status = request.args.get("status")
    with store.lock:
        get_metric_or_404(metric_id)
        items = [b for b in store.breach_events.values() if b["metric_id"] == metric_id]
        items.sort(key=lambda b: (b["created_at"], b["_seq"]))
        if f_status is not None:
            items = [b for b in items if b["status"] == f_status]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([breach_event_json(b) for b in page], limit, offset, total)


@bp.post("/mrm/breach-events/<event_id>/resolve")
def resolve_breach_event(event_id):
    require_roles("ModelOwner")
    with store.lock:
        event = store.breach_events.get(event_id)
        if event is None:
            raise ApiError(
                "ERR_NOT_FOUND", 404, "Breach event '%s' does not exist" % event_id
            )
        mt = store.metrics[event["metric_id"]]
        model = store.models[mt["model_id"]]
        # Ownership before the state gate (pipeline §2.8).
        if g.user_id != model["owner_user_id"]:
            raise ApiError(
                "ERR_NOT_MODEL_OWNER",
                403,
                "Only the owner of the event's model may resolve it",
            )
        if event["status"] != "OPEN":
            raise ApiError(
                "ERR_BREACH_EVENT_ALREADY_RESOLVED",
                409,
                "Breach event is already RESOLVED",
            )
        posture_before = risk.monitoring_posture(model["id"])
        event["status"] = "RESOLVED"
        workflow.mutate(event)
        if risk.monitoring_posture(model["id"]) != posture_before:
            workflow.mutate(model)
        return success(breach_event_json(event))
