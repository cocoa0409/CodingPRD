"""The board's logical clock and the delinquency sweep."""

from flask import Blueprint

from db import by_created_at, db, now, touch
from errors import ApiError
from middleware import endpoint
from response import raw_response
from services import aggregates, cascades, constants as C
from util import days, iso, parse_dt
from validation import body

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("BoardAdmin")
def set_clock():
    payload = body()
    if "to_iso8601" not in payload or payload["to_iso8601"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is required.")
    target = parse_dt(payload["to_iso8601"])
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    # A pure assignment: no row is recomputed and no state advances.
    db.clock = target
    return raw_response({"current_utc": iso(db.clock)})


@bp.post("/_ops/delinquency-sweep")
@endpoint("FeeAdministrator")
def delinquency_sweep():
    swept_at = now()

    # Stage 1: past-due assessments slide into delinquency.
    due = [
        order
        for order in db.orders.values()
        if order["fee_status"] == "ASSESSED" and order["fee_due_on"] is not None
        and order["fee_due_on"] <= swept_at
    ]
    due.sort(key=lambda order: (order["fee_due_on"], order["created_at"], order["_seq"]))
    for order in due:
        order["fee_status"] = "DELINQUENT"
        touch(order)
    delinquent_order_count = len(due)

    # Stage 2: the register is worked forward.
    graced_registration_count = 0
    lapsed_registration_count = 0
    registrations = sorted(
        db.registrations.values(),
        key=lambda reg: (reg["expires_on"], reg["created_at"], reg["_seq"]),
    )
    for registration in registrations:
        moved = False
        if registration["status"] == "ACTIVE" and registration["expires_on"] <= swept_at:
            registration["status"] = "GRACE"
            graced_registration_count += 1
            moved = True
        if (
            registration["status"] == "GRACE"
            and swept_at > registration["expires_on"] + days(C.LAPSE_RECOVERY_DAYS)
        ):
            registration["status"] = "LAPSED"
            lapsed_registration_count += 1
            moved = True
            touch(registration)
            cascades.reject_pending_filings(
                registration, "PRIOR_REGISTRATION_LAPSED", renewal_only=True
            )
        elif moved:
            touch(registration)

    # Stage 3: owner arrears, standing and suspension stamps.
    suspended_owner_count = 0
    for owner in by_created_at(list(db.owners.values())):
        _changed, flipped = aggregates.recompute_owner(owner)
        if flipped:
            suspended_owner_count += 1

    return raw_response(
        {
            "delinquent_order_count": delinquent_order_count,
            "graced_registration_count": graced_registration_count,
            "lapsed_registration_count": lapsed_registration_count,
            "suspended_owner_count": suspended_owner_count,
            "swept_at": iso(swept_at),
        }
    )
