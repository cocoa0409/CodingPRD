"""Seniors, subscription plans, subscriptions, dashboard."""
from flask import Blueprint, request

import db
import errors
from middleware import (require_roles, get_body, req_str, req_int, req_bool,
                        req_enum, req_date, check_senior_scope, scoped_list,
                        TIERS, CADENCES, PAYMENT_OUTCOMES, PRORATION_MODES)
from response import ok, list_ok
from services import (create_record, touch, ser, ser_senior, posture,
                      current_subscription, auto_resolve_alert, run_change_plan,
                      adherence_today, OPEN_ALERT_STATUSES)
from datetime import timedelta

bp = Blueprint("core", __name__)


# ------------------------------------------------------------- seniors -----

@bp.post("/v1/seniors")
def create_senior():
    require_roles(["PlatformAdmin"])
    b = get_body()
    full_name = req_str(b, "full_name")
    dob = req_date(b, "date_of_birth")
    address = req_str(b, "address")
    rec = create_record(db.seniors, {
        "full_name": full_name,
        "date_of_birth": dob,
        "address": address,
    })
    return ok(ser_senior(rec), 201)


@bp.get("/v1/seniors/<senior_id>")
def get_senior(senior_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver", "Senior"])
    s = db.seniors.get(senior_id)
    if s is None:
        raise errors.not_found("Senior not found")
    check_senior_scope(role, uid, senior_id)
    return ok(ser_senior(s))


@bp.get("/v1/seniors")
def list_seniors():
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    return list_ok(list(db.seniors.values()), ser_senior)


@bp.get("/v1/seniors/<senior_id>/dashboard")
def senior_dashboard(senior_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver", "Senior"])
    s = db.seniors.get(senior_id)
    if s is None:
        raise errors.not_found("Senior not found")
    check_senior_scope(role, uid, senior_id)
    devices = [d for d in db.devices.values()
               if d["senior_id"] == senior_id and d["status"] != "DECOMMISSIONED"]
    devices_online = sum(1 for d in devices if d["status"] == "ONLINE")
    last_ci = max((c["occurred_at"] for c in db.checkins.values()
                   if c["senior_id"] == senior_id), default=None)
    pending = [d["scheduled_at"] for d in db.doses.values()
               if d["senior_id"] == senior_id and d["status"] == "PENDING"]
    next_dose = min(pending) if pending else None
    from util import iso
    data = {
        "monitoring_posture": posture(senior_id),
        "open_alert_count": sum(1 for a in db.alerts.values()
                                if a["senior_id"] == senior_id
                                and a["status"] in OPEN_ALERT_STATUSES),
        "risk_tier": __import__("services").risk_tier(senior_id),
        "adherence_today_pct": adherence_today(senior_id),
        "devices_online": devices_online,
        "devices_total": len(devices),
        "last_checkin_at": iso(last_ci) if last_ci else None,
        "next_dose_scheduled_at": iso(next_dose) if next_dose else None,
    }
    return ok(data)


# ---------------------------------------------------- subscription plans ---

@bp.post("/v1/subscription-plans")
def create_plan():
    require_roles(["PlatformAdmin"])
    b = get_body()
    rec = create_record(db.plans, {
        "tier": req_enum(b, "tier", TIERS),
        "monthly_fee_cents": req_int(b, "monthly_fee_cents"),
        "included_motion_sensors": req_int(b, "included_motion_sensors"),
        "extra_sensor_fee_cents": req_int(b, "extra_sensor_fee_cents"),
        "max_contacts": req_int(b, "max_contacts"),
        "checkin_interval_hours": req_int(b, "checkin_interval_hours"),
        "medication_reminders_enabled": req_bool(b, "medication_reminders_enabled"),
        "wellness_report_enabled": req_bool(b, "wellness_report_enabled"),
        "wellness_report_cadence": req_enum(b, "wellness_report_cadence", CADENCES),
    })
    return ok(ser(rec), 201)


@bp.get("/v1/subscription-plans/<plan_id>")
def get_plan(plan_id):
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    p = db.plans.get(plan_id)
    if p is None:
        raise errors.not_found("Subscription plan not found")
    return ok(ser(p))


@bp.get("/v1/subscription-plans")
def list_plans():
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    return list_ok(list(db.plans.values()), ser)


# --------------------------------------------------------- subscriptions ---

@bp.post("/v1/subscriptions")
def create_subscription():
    require_roles(["PlatformAdmin"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    plan_id = req_str(b, "plan_id")
    if senior_id not in db.seniors:
        raise errors.not_found("Senior not found")
    if plan_id not in db.plans:
        raise errors.not_found("Subscription plan not found")
    rec = create_record(db.subscriptions, {
        "senior_id": senior_id,
        "plan_id": plan_id,
        "service_status": "PROVISIONING",
        "billing_status": "CURRENT",
        "current_period_end": None,
        "billing_credit_cents": 0,
        "lifetime_charged_cents": 0,
        "lifetime_credited_cents": 0,
        "consecutive_failed_payments": 0,
        "last_change_plan_credit_cents": None,
        "last_change_sensor_credit_cents": None,
        "last_change_total_credit_cents": None,
        "last_change_total_charge_cents": None,
        "last_change_net_cents": None,
    })
    rec["_activated_at"] = None
    return ok(ser(rec), 201)


def _get_subscription(subscription_id):
    sub = db.subscriptions.get(subscription_id)
    if sub is None:
        raise errors.not_found("Subscription not found")
    return sub


@bp.get("/v1/subscriptions/<subscription_id>")
def get_subscription(subscription_id):
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    return ok(ser(_get_subscription(subscription_id)))


@bp.get("/v1/subscriptions")
def list_subscriptions():
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    recs = list(db.subscriptions.values())
    sid = request.args.get("senior_id")
    pid = request.args.get("plan_id")
    if sid is not None:
        recs = [r for r in recs if r["senior_id"] == sid]
    if pid is not None:
        recs = [r for r in recs if r["plan_id"] == pid]
    return list_ok(recs, ser)


@bp.post("/v1/subscriptions/<subscription_id>/activate")
def activate_subscription(subscription_id):
    require_roles(["PlatformAdmin"])
    sub = _get_subscription(subscription_id)
    if sub["service_status"] != "PROVISIONING":
        raise errors.invalid_state("Subscription is not PROVISIONING")
    if sub["billing_status"] != "CURRENT":
        raise errors.billing_not_current()
    has_installed_kit = any(k for k in db.kits.values()
                            if k["senior_id"] == sub["senior_id"]
                            and k["status"] in ("INSTALLED", "ACTIVE"))
    if not has_installed_kit:
        raise errors.kit_not_delivered("No INSTALLED or ACTIVE kit for the senior")
    sub["service_status"] = "ACTIVE"
    sub["current_period_end"] = db.clock + timedelta(days=30)
    sub["_activated_at"] = db.clock
    touch(sub)
    for k in db.kits.values():
        if k["senior_id"] == sub["senior_id"] and k["status"] == "INSTALLED":
            k["status"] = "ACTIVE"
            touch(k)
    return ok(ser(sub))


@bp.post("/v1/subscriptions/<subscription_id>/record-payment")
def record_payment(subscription_id):
    require_roles(["PlatformAdmin"])
    b = get_body()
    outcome = req_enum(b, "outcome", PAYMENT_OUTCOMES)
    sub = _get_subscription(subscription_id)
    if sub["service_status"] == "CANCELLED":
        raise errors.invalid_state("Subscription is CANCELLED")
    if outcome == "SUCCEEDED":
        sub["billing_status"] = "CURRENT"
        sub["consecutive_failed_payments"] = 0
        touch(sub)
        return ok(ser(sub))
    # FAILED
    if sub["billing_status"] == "CURRENT":
        sub["billing_status"] = "PAST_DUE"
        sub["consecutive_failed_payments"] += 1
        touch(sub)
        return ok(ser(sub))
    if sub["billing_status"] == "PAST_DUE" and sub["consecutive_failed_payments"] >= 1:
        sub["billing_status"] = "DELINQUENT"
        sub["consecutive_failed_payments"] += 1
        if sub["service_status"] == "ACTIVE":
            sub["service_status"] = "SUSPENDED"
        touch(sub)
        # posture cascade: auto-resolve every open non-CRITICAL alert
        for a in list(db.alerts.values()):
            if (a["senior_id"] == sub["senior_id"] and a["status"] in OPEN_ALERT_STATUSES
                    and a["severity"] != "CRITICAL"):
                auto_resolve_alert(a)
        return ok(ser(sub))
    # already DELINQUENT
    sub["consecutive_failed_payments"] += 1
    touch(sub)
    return ok(ser(sub))


@bp.post("/v1/subscriptions/<subscription_id>/change-plan")
def change_plan(subscription_id):
    require_roles(["PlatformAdmin"])
    b = get_body()
    plan_id = req_str(b, "plan_id")
    mode = None
    from middleware import opt_enum
    mode = opt_enum(b, "proration_mode", PRORATION_MODES, "DAILY_PRORATE")
    sub = _get_subscription(subscription_id)
    new_plan = db.plans.get(plan_id)
    if new_plan is None:
        raise errors.not_found("Subscription plan not found")
    run_change_plan(sub, new_plan, mode)
    return ok(ser(sub))


@bp.post("/v1/subscriptions/<subscription_id>/resume")
def resume_subscription(subscription_id):
    require_roles(["PlatformAdmin"])
    sub = _get_subscription(subscription_id)
    if sub["service_status"] != "SUSPENDED":
        raise errors.invalid_state("Subscription is not SUSPENDED")
    if sub["billing_status"] != "CURRENT":
        raise errors.billing_not_current()
    sub["service_status"] = "ACTIVE"
    touch(sub)
    return ok(ser(sub))


@bp.post("/v1/subscriptions/<subscription_id>/cancel")
def cancel_subscription(subscription_id):
    require_roles(["PlatformAdmin"])
    sub = _get_subscription(subscription_id)
    if sub["service_status"] == "CANCELLED":
        raise errors.invalid_state("Subscription is already CANCELLED")
    sub["service_status"] = "CANCELLED"
    touch(sub)
    from services import end_schedule
    for s in list(db.medication_schedules.values()):
        if s["senior_id"] == sub["senior_id"] and s["status"] == "ACTIVE":
            end_schedule(s)
    return ok(ser(sub))
