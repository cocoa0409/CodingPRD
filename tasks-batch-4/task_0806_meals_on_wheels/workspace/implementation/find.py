"""Existence lookups that raise the resource-specific NOT_FOUND error."""
import db
from core import ApiError


def _get(store, rid, error_id):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(error_id, 404, "Resource not found")
    return rec


def client(rid):
    return _get(db.clients, rid, "ERR_CLIENT_NOT_FOUND")


def assessment(rid):
    return _get(db.assessments, rid, "ERR_ASSESSMENT_NOT_FOUND")


def meal_plan(rid):
    return _get(db.meal_plans, rid, "ERR_MEAL_PLAN_NOT_FOUND")


def route(rid):
    return _get(db.routes, rid, "ERR_ROUTE_NOT_FOUND")


def driver(rid):
    return _get(db.drivers, rid, "ERR_DRIVER_NOT_FOUND")


def delivery(rid):
    return _get(db.deliveries, rid, "ERR_DELIVERY_NOT_FOUND")


def wellness_check(rid):
    return _get(db.wellness_checks, rid, "ERR_WELLNESS_CHECK_NOT_FOUND")


def welfare_alert(rid):
    return _get(db.welfare_alerts, rid, "ERR_ALERT_NOT_FOUND")


def contribution(rid):
    return _get(db.contributions, rid, "ERR_CONTRIBUTION_NOT_FOUND")


def vacation_hold(rid):
    return _get(db.vacation_holds, rid, "ERR_HOLD_NOT_FOUND")
