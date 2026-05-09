from decimal import Decimal
from flask import Blueprint, request
from db import db, make_common_fields, bump
from envelope import success
from errors import APIError, ERR_INVALID_INPUT
from validation import need_body, require_enum
from common import parse_ts, to_money
from clock import clock
from services.billing import (
    overdue_penalty, elapsed_hours, LOST_DEVICE_FEE, LOST_THRESHOLD_HOURS,
)
from services.cascade import create_repair_ticket

bp = Blueprint("test_endpoints", __name__)


@bp.post("/_state/reset")
def state_reset():
    db.reset()
    clock.reset()
    return success({})


@bp.post("/_clock/advance")
def clock_advance():
    body = request.get_json(silent=True) or {}
    if "to" in body and body["to"] is not None:
        if not isinstance(body["to"], str):
            raise APIError(ERR_INVALID_INPUT, 400, "Field 'to' must be a string")
        try:
            instant = parse_ts(body["to"])
        except ValueError:
            raise APIError(ERR_INVALID_INPUT, 400, "Invalid 'to' timestamp")
        clock.set(instant)
    elif "seconds" in body and body["seconds"] is not None:
        v = body["seconds"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise APIError(ERR_INVALID_INPUT, 400, "Field 'seconds' must be numeric")
        clock.advance(float(v))
    else:
        raise APIError(ERR_INVALID_INPUT, 400, "Provide 'to' or 'seconds'")
    return success({})


def _run_overdue():
    promoted = []
    for r in db.rentals.values():
        if r["rental_status"] != "ACTIVE":
            continue
        if elapsed_hours(r["rented_at"], clock.now()) > 24:
            r["rental_status"] = "OVERDUE"
            bump(r)
            promoted.append(r)
    return promoted


def _run_lost():
    """Promote OVERDUE rentals to LOST when elapsed_hours >= 168."""
    for r in list(db.rentals.values()):
        if r["rental_status"] != "OVERDUE":
            continue
        if elapsed_hours(r["rented_at"], clock.now()) < LOST_THRESHOLD_HOURS:
            continue
        # lost conversion
        r["charged_amount"] = LOST_DEVICE_FEE  # 99.00 flat
        user = db.users.get(r["user_id"])
        if user is not None:
            deposit_deduction = min(user["deposit_balance"], LOST_DEVICE_FEE)
            residual = LOST_DEVICE_FEE - deposit_deduction
            user["deposit_balance"] = to_money(user["deposit_balance"] - deposit_deduction)
            user["wallet_balance"] = to_money(user["wallet_balance"] - residual)
            bump(user)
        r["rental_status"] = "LOST"
        r["payment_status"] = "DEPOSIT_DEDUCTED"
        bump(r)
        device = db.devices.get(r["device_id"])
        if device is not None:
            device["status"] = "LOST"
            # current_cabinet_id and current_slot_index unchanged (stale snapshot)
            bump(device)


def _run_anomaly():
    """For each AVAILABLE device with battery_level < 5 in an OCCUPIED slot, create a RepairTicket
    (cascade chain follows automatically via create_repair_ticket)."""
    targets = []
    for d in list(db.devices.values()):
        if d["status"] != "AVAILABLE":
            continue
        if d["battery_level"] >= 5:
            continue
        cab_id = d.get("current_cabinet_id")
        slot_idx = d.get("current_slot_index")
        if cab_id is None or slot_idx is None:
            continue
        slot = None
        for s in db.slots.values():
            if s["cabinet_id"] == cab_id and s["slot_index"] == slot_idx:
                slot = s
                break
        if slot is None or slot["slot_status"] != "OCCUPIED":
            continue
        targets.append(d)

    for d in targets:
        create_repair_ticket(
            target_type="DEVICE",
            target_id=d["id"],
            source="AUTO_ANOMALY",
            issue_code="ABNORMAL_BATTERY",
        )


@bp.post("/_sweep/run")
def sweep_run():
    body = need_body(request.get_json(silent=True))
    sweep_type = require_enum(body, "sweep_type", {"overdue", "lost", "anomaly", "all"})
    if sweep_type == "overdue":
        _run_overdue()
    elif sweep_type == "lost":
        _run_lost()
    elif sweep_type == "anomaly":
        _run_anomaly()
    else:
        _run_overdue()
        _run_lost()
        _run_anomaly()
    return success({})


@bp.post("/_events/emit")
def events_emit():
    body = need_body(request.get_json(silent=True))
    if "event_type" not in body or not isinstance(body["event_type"], str):
        raise APIError(ERR_INVALID_INPUT, 400, "Field 'event_type' required")
    if "payload" not in body:
        raise APIError(ERR_INVALID_INPUT, 400, "Field 'payload' required")
    return success({})
