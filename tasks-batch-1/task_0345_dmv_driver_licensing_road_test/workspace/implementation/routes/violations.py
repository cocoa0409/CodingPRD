"""Violation endpoints (PRD section 3.7)."""
from flask import Blueprint, request

import db
from db import db as store
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import serialize
from services import calculations as calc
from services.common import (
    new_common, touch, get_json_body, paginate, require_fields, require_int,
)
from services.lookup import fetch

bp = Blueprint("violations", __name__)


def _maybe_open_suspension(record, triggering_violation_id):
    """If point_balance >= threshold and licensing_status ACTIVE, open suspension."""
    pb = calc.point_balance(record, store)
    if pb >= db.SUSPENSION_POINT_THRESHOLD and record["licensing_status"] == "ACTIVE":
        prior_count = calc.prior_suspension_count(record, store)
        duration = calc.suspension_duration(pb, prior_count)
        start = store.current_period
        susp = new_common(
            driver_record_id=record["id"],
            triggering_violation_id=triggering_violation_id,
            point_balance_at_start=pb,
            start_period=start,
            duration_days=duration,
            eligible_period=start + duration,
            point_balance_at_reinstatement=None,
            reinstatement_fee=None,
            status="ACTIVE",
        )
        store.suspensions[susp["id"]] = susp
        record["licensing_status"] = "SUSPENDED"
        touch(record)


@bp.post("/violations")
def record_violation():
    user_id, role = get_user_context()
    require_role(role, {"AdjudicationOfficer"})
    body = get_json_body()
    require_fields(body, ["driver_record_id", "code", "points", "occurred_period"])
    driver_record_id = body["driver_record_id"]
    record = fetch(store.driver_records, driver_record_id)
    code = body["code"]
    if not isinstance(code, str) or code.strip() == "":
        raise err("ERR_INVALID_REQUEST", "code must be a non-empty string")
    points = require_int(body, "points", minimum=1)
    occurred_period = require_int(body, "occurred_period")
    # field-domain (priority 3.5): occurred_period <= current clock
    if occurred_period > store.current_period:
        raise err("ERR_OCCURRED_IN_FUTURE", "occurred_period lies in the future")

    violation = new_common(
        driver_record_id=driver_record_id,
        code=code,
        points=points,
        occurred_period=occurred_period,
        recorded_by_officer=user_id,
        status="ACTIVE",
    )
    store.violations[violation["id"]] = violation
    # may auto-trigger a suspension
    _maybe_open_suspension(record, violation["id"])
    return success(serialize.violation(violation), 201, "object")


@bp.get("/violations/<vid>")
def get_violation(vid):
    _, role = get_user_context()
    require_role(role, {"AdjudicationOfficer", "LicenseClerk"})
    violation = fetch(store.violations, vid)
    return success(serialize.violation(violation), 200, "object")


@bp.get("/violations/<vid>/suspensions")
def list_violation_suspensions(vid):
    _, role = get_user_context()
    require_role(role, {"AdjudicationOfficer", "LicenseClerk"})
    fetch(store.violations, vid)
    status = request.args.get("status")
    items = [
        s for s in store.suspensions.values()
        if s.get("triggering_violation_id") == vid
        and (status is None or s["status"] == status)
    ]
    data, pagination = paginate(items, serialize.suspension)
    return success(data, 200, "array", pagination)


@bp.post("/violations/<vid>/dismiss")
def dismiss_violation(vid):
    _, role = get_user_context()
    require_role(role, {"AdjudicationOfficer"})
    violation = fetch(store.violations, vid)
    if violation["status"] != "ACTIVE":
        raise err("ERR_VIOLATION_NOT_ACTIVE", "Violation is not ACTIVE")
    violation["status"] = "DISMISSED"
    touch(violation)
    # point_balance is recomputed on read; nothing else to mutate here.
    return success(serialize.violation(violation), 200, "object")
