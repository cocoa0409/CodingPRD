"""Test-driving endpoints: logical clock, payment, shipment and firmware injectors."""

from flask import Blueprint

import calc
import services as svc
from auth import ADMIN, authorize
from bodyspec import Body
from errors import ApiError
from resp import ok
from routes_firmware import FAILURE_CODES, FAILURE_PAUSE_THRESHOLD
from store import bump, db, days, iso, now

bp = Blueprint("testing", __name__)

PAY_OUTCOMES = ("AUTHORIZED", "DECLINED")
SCAN_EVENTS = ("DELIVERED", "RETURN_PICKED_UP")
REPORT_OUTCOMES = ("SUCCESS", "FAILURE")


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(ADMIN)
    body = Body()
    instant = body.datetime("to_iso8601")
    body.finish()
    db.clock = instant
    # §2.4: an expired referral, return authorization or trial period transitions "on the next
    # read or write that touches them, not at the moment the clock advanced", so moving the
    # clock must not sweep them eagerly.
    return ok({"current_utc": iso(now())})


@bp.post("/_payments/simulate")
def simulate_payment():
    authorize(ADMIN)
    body = Body()
    order_id = body.string("device_order_id", min_len=1)
    outcome = body.enum("outcome", PAY_OUTCOMES)
    body.finish()
    order = svc.ref(db.device_orders, order_id)
    if order["payment_status"] != "PENDING_AUTH":
        raise ApiError("ERR_INVALID_STATE")
    if outcome == "AUTHORIZED":
        order["payment_status"] = "AUTHORIZED"
        bump(order)
        return ok(order)
    order["payment_status"] = "AUTH_FAILED"
    if order["fulfillment_status"] in ("PENDING_FIT_CONFIRM", "READY_TO_SHIP", "MEDICAL_HOLD"):
        if order["fulfillment_status"] == "READY_TO_SHIP":
            svc.release_reservation(order)
            svc.unassign_device(order)
        order["fulfillment_status"] = "CANCELLED"
    bump(order)
    return ok(order)


@bp.post("/_shipments/scan")
def shipment_scan():
    authorize(ADMIN)
    body = Body()
    order_id = body.string("device_order_id", min_len=1)
    event = body.enum("event", SCAN_EVENTS)
    body.finish()
    order = svc.ref(db.device_orders, order_id)
    if event == "DELIVERED":
        svc.ensure_state(order, "fulfillment_status", ("SHIPPED",), "device_orders")
        order["fulfillment_status"] = "DELIVERED"
        order["delivered_at"] = now()
        bump(order)
        device = svc.device_for_order(order["id"])
        if device is not None:
            device["status"] = "WITH_PATIENT"
            bump(device)
        trial = svc.trial_for_order(order["id"])
        if trial is None:
            nominal = now() + days(int(order["pinned_trial_days"]))
            trial = svc.new_row(db.trial_periods, device_order_id=order["id"],
                                patient_id=order["patient_id"], status="ACTIVE",
                                started_at=now(), nominal_end_utc=nominal,
                                effective_end_utc=nominal, pause_intervals=[],
                                paused_days=0, days_used=0, extension_days_granted=0)
            calc.trial_days_used(trial)
        plan = svc.plan_for_order(order["id"])
        if plan is not None and plan.get("status") == "TRIALING":
            plan["status"] = "ACTIVE"
            plan["cycle_start_utc"] = order["delivered_at"]
            plan["cycle_end_utc"] = order["delivered_at"] + days(30)
            plan["cycle_ordinal"] = 0
            bump(plan)
        return ok(order)

    # RETURN_PICKED_UP
    svc.ensure_state(order, "fulfillment_status", ("DELIVERED",), "device_orders")
    trial = svc.trial_for_order(order["id"])
    auth = None
    if trial is not None:
        for row in sorted(db.return_authorizations.values(), key=lambda r: r["created_at"]):
            if row.get("trial_period_id") == trial["id"] and row.get("status") == "ISSUED":
                auth = row
    if auth is None:
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    if now() > auth["return_deadline_utc"]:
        raise ApiError("ERR_RETURN_DEADLINE_PASSED")
    auth["status"] = "IN_TRANSIT"
    bump(auth)
    order["fulfillment_status"] = "RETURN_IN_TRANSIT"
    bump(order)
    return ok(order)


@bp.post("/_firmware/report")
def firmware_report():
    authorize(ADMIN)
    body = Body()
    rollout_id = body.string("firmware_rollout_id", min_len=1)
    outcome = body.enum("outcome", REPORT_OUTCOMES)
    failure_code = body.enum("failure_code", FAILURE_CODES, required=False)
    body.finish()
    rollout = svc.ref(db.firmware_rollouts, rollout_id)
    svc.ensure_state(rollout, "status", ("INSTALLING",), "firmware_rollouts")
    campaign = db.firmware_campaigns.get(rollout["firmware_campaign_id"])
    device = db.devices.get(rollout["device_id"])
    if outcome == "SUCCESS":
        if device is None or device.get("firmware_version") != rollout.get("from_version_observed"):
            raise ApiError("ERR_FIRMWARE_VERSION_DRIFT")
        rollout["status"] = "INSTALLED"
        rollout["installed_at"] = now()
        bump(rollout)
        device["firmware_version"] = (campaign or {}).get("to_version")
        bump(device)
        if campaign is not None:
            svc.recompute_campaign_counters(campaign)
        return ok(rollout)
    rollout["status"] = "FAILED"
    rollout["failure_code"] = failure_code or "TIMEOUT"
    bump(rollout)
    if campaign is not None:
        svc.recompute_campaign_counters(campaign)
        if float(campaign.get("failure_rate_pct") or 0) > FAILURE_PAUSE_THRESHOLD and \
                campaign.get("status") == "ROLLING":
            campaign["status"] = "PAUSED"
            bump(campaign)
    return ok(rollout)
