"""Suspension endpoints: get, dismiss, reinstate (PRD section 3.7)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import db as store
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import serialize
from services import calculations as calc
from services.common import touch, get_json_body, require_fields, require_int
from services.lookup import fetch

bp = Blueprint("suspensions", __name__)


def _fee_to_cents(reinstatement_fee):
    """round(reinstatement_fee * 100) — round-half-up of dollars*100."""
    cents = (Decimal(str(reinstatement_fee)) * Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(cents)


def _has_reinstatement_fee(record_id, required_cents):
    candidates = [
        f for f in store.fee_payments.values()
        if f["driver_record_id"] == record_id
        and f["purpose"] == "REINSTATEMENT"
        and f["status"] == "CAPTURED"
    ]
    if not candidates:
        return False
    candidates.sort(key=lambda f: (f["created_at"], f["id"]))
    most_recent = candidates[-1]
    return most_recent["amount_cents"] >= required_cents


@bp.get("/suspensions/<sid>")
def get_suspension(sid):
    _, role = get_user_context()
    require_role(role, {"AdjudicationOfficer", "LicenseClerk"})
    susp = fetch(store.suspensions, sid)
    return success(serialize.suspension(susp), 200, "object")


@bp.post("/suspensions/<sid>/dismiss")
def dismiss_suspension(sid):
    user_id, role = get_user_context()
    require_role(role, {"AdjudicationOfficer"})
    susp = fetch(store.suspensions, sid)
    get_json_body()
    # state (priority 5)
    if susp["status"] != "ACTIVE":
        raise err("ERR_SUSPENSION_NOT_ACTIVE", "Suspension is not ACTIVE")
    # triggering violation must be DISMISSED
    tvid = susp.get("triggering_violation_id")
    triggering = store.violations.get(tvid) if tvid else None
    if triggering is None or triggering["status"] != "DISMISSED":
        raise err("ERR_VIOLATION_NOT_DISMISSED", "Triggering violation is not DISMISSED")
    # segregation of duties
    if user_id == triggering["recorded_by_officer"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Recording officer cannot dismiss the suspension they triggered")
    susp["status"] = "LIFTED_BY_DISMISSAL"
    touch(susp)
    record = store.driver_records[susp["driver_record_id"]]
    record["licensing_status"] = "ACTIVE"
    # prior_suspension_count NOT incremented (LIFTED_BY_DISMISSAL not counted).
    touch(record)
    return success(serialize.suspension(susp), 200, "object")


@bp.post("/suspensions/<sid>/reinstate")
def reinstate_suspension(sid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    susp = fetch(store.suspensions, sid)
    body = get_json_body()
    require_fields(body, ["expected_driver_record_version"])
    expected_version = require_int(body, "expected_driver_record_version")
    record = store.driver_records[susp["driver_record_id"]]

    # OCC (priority 4) — before any business logic
    if expected_version != record["version"]:
        raise err("ERR_STALE_RECORD_VERSION",
                  "expected_driver_record_version does not match record version")
    # state (priority 5/13): record SUSPENDED and suspension SERVED
    if record["licensing_status"] != "SUSPENDED":
        raise err("ERR_RECORD_NOT_SUSPENDED", "Record is not SUSPENDED")
    if susp["status"] != "SERVED":
        if store.current_period < susp["eligible_period"]:
            raise err("ERR_NOT_YET_ELIGIBLE", "current clock < eligible_period")
        raise err("ERR_SUSPENSION_NOT_SERVED", "Suspension is not SERVED")
    # compute fee from snapshot
    pb = calc.point_balance(record, store)
    fee = calc.reinstatement_fee(pb)
    required_cents = _fee_to_cents(fee)
    if not _has_reinstatement_fee(record["id"], required_cents):
        raise err("ERR_REINSTATEMENT_FEE_UNPAID",
                  "No captured REINSTATEMENT fee >= reinstatement_fee")

    susp["point_balance_at_reinstatement"] = pb
    susp["reinstatement_fee"] = fee
    susp["status"] = "LIFTED_BY_REINSTATEMENT"
    touch(susp)
    record["licensing_status"] = "ACTIVE"
    # prior_suspension_count recomputed on read (now counts this suspension).
    touch(record)
    return success(serialize.suspension(susp), 200, "object")
