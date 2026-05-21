"""Lease routes: draft, sign, pay, get."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import clock, format_timestamp
from ..errors import ApiError
from ..responses import success_response
from ..services.calculations import (
    recompute_outstanding_balance,
    recompute_violation_count_12mo,
)
from ..services.entities import (
    get_lease_or_404,
    get_lot_or_404,
    get_resident_body_or_404,
    init_common_fields,
    touch,
)
from ..services.serialization import serialize_lease
from ..store import store
from ..validation import get_json_body, parse_datetime, require_string


bp = Blueprint("leases", __name__)


@bp.route("/lots/<lot_id>/leases", methods=["POST"])
@require_auth("ParkManager")
def draft_lease(lot_id: str):
    lot = get_lot_or_404(lot_id)
    body = get_json_body()
    resident_id = require_string(body, "resident_id")
    start_date = parse_datetime(body, "start_date", required=True)

    # Body-resource existence
    get_resident_body_or_404(resident_id)

    with store.lock:
        lease = init_common_fields({
            "lot_id": lot_id,
            "resident_id": resident_id,
            "monthly_rent_cents": None,
            "start_date": format_timestamp(start_date),
            "status": "DRAFT",
            "outstanding_balance_cents": 0,
            "predecessor_lease_id": None,
        })
        store.leases[lease["id"]] = lease

    return success_response(serialize_lease(lease), status=201)


@bp.route("/leases/<lease_id>/sign", methods=["POST"])
@require_auth("ParkManager")
def sign_lease(lease_id: str):
    lease = get_lease_or_404(lease_id)

    with store.lock:
        # State precondition
        if lease["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Lease is not in DRAFT state.")
        lot = store.lots.get(lease["lot_id"])
        if lot is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Parent lot disappeared.")
        # Lot must have no current_lease_id
        if lot.get("current_lease_id") is not None:
            raise ApiError("ERR_LOT_OCCUPIED", "Lot already has an active lease.")
        # Resident must have zero recent violations
        resident = store.residents.get(lease["resident_id"])
        if resident is None:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "Resident missing.")
        recompute_violation_count_12mo(resident)
        if resident.get("violation_count_12mo", 0) > 0:
            # No specific error for this in the catalog; map to ERR_INVALID_STATE
            # since the lease itself can't transition under this constraint.
            raise ApiError("ERR_INVALID_STATE", "Resident has recent finalized-for-cause evictions.")

        # Side effects
        lease["status"] = "CURRENT"
        lease["monthly_rent_cents"] = int(lot["base_rent_cents"])
        touch(lease)
        lot["current_lease_id"] = lease["id"]
        touch(lot)

    return success_response(serialize_lease(lease), status=200)


@bp.route("/leases/<lease_id>/pay", methods=["POST"])
@require_auth("Resident")
def pay_lease(lease_id: str):
    lease = get_lease_or_404(lease_id)
    user_id = g.user_id

    # Ownership check
    if lease["resident_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", "Lease does not belong to the acting resident.")

    with store.lock:
        # State precondition: must have an outstanding balance > 0 (otherwise nothing to pay,
        # which we model as ERR_INVALID_STATE per concurrency rule)
        if lease["status"] not in ("DELINQUENT", "GRACE", "CURRENT"):
            raise ApiError("ERR_INVALID_STATE", "Lease is not in a payable state.")
        # Recompute fresh balance from outstanding bills
        balance_before = recompute_outstanding_balance(lease)
        if balance_before == 0:
            # Nothing to pay; the duplicate / race case rejects with ERR_INVALID_STATE.
            raise ApiError("ERR_INVALID_STATE", "No outstanding balance to pay.")

        now_iso = clock.iso_now()
        from ..services.calculations import _parse_dt  # local import to avoid cycle
        now_dt = clock.now()
        # Mark all unpaid bills for this lease (whose period has elapsed) as paid
        for bill in store.utility_bills.values():
            if bill.get("lease_id") != lease["id"]:
                continue
            if bill.get("paid_at") is not None:
                continue
            end_dt = bill.get("billing_period_end")
            if isinstance(end_dt, str):
                end_dt = _parse_dt(end_dt)
            if end_dt is None or end_dt > now_dt:
                continue
            bill["paid_at"] = now_iso
        # Recompute balance; should drop to 0
        new_balance = recompute_outstanding_balance(lease)

        # Cascade lease state
        prior_status = lease["status"]
        if prior_status == "DELINQUENT" and new_balance == 0:
            lease["status"] = "CURRENT"
        elif prior_status == "GRACE":
            # Eviction may still be in flight: status is driven by eviction case lifecycle.
            # Per PRD §3.4: pay alone does NOT dismiss an in-flight eviction. The lease
            # remains in GRACE while the eviction case is unresolved.
            pass
        touch(lease)

    return success_response(serialize_lease(lease), status=200)


@bp.route("/leases/<lease_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_lease(lease_id: str):
    lease = get_lease_or_404(lease_id)
    # Recompute outstanding balance on read for accurate reporting
    recompute_outstanding_balance(lease)
    return success_response(serialize_lease(lease), status=200)


__all__ = ["bp"]
