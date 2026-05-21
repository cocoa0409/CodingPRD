"""Test harness sweep endpoints: billing, evictions, rent-effective."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint

from ..auth import require_auth
from ..clock import clock, format_timestamp
from ..errors import ApiError
from ..responses import success_response
from ..services.calculations import (
    _parse_dt,
    apportion_master_total,
    compute_rent_due_cents,
    recompute_outstanding_balance,
    recompute_violation_count_12mo,
)
from ..services.cascades import lease_grace_to_terminated
from ..services.entities import (
    get_park_or_404,
    init_bill_fields,
    touch,
)
from ..services.serialization import (
    serialize_eviction,
    serialize_notice,
    serialize_utility_bill,
)
from ..store import store
from ..validation import get_json_body, parse_datetime, require_int, require_string


bp = Blueprint("sweeps", __name__)


@bp.route("/_sweep/billing", methods=["POST"])
@require_auth("PlatformAdmin")
def sweep_billing():
    body = get_json_body()
    park_id = require_string(body, "park_id")
    period_start = parse_datetime(body, "billing_period_start", required=True)
    period_end = parse_datetime(body, "billing_period_end", required=True)
    master_total = require_int(body, "master_total_cents", minimum=0)
    if period_end <= period_start:
        raise ApiError("ERR_VALIDATION", "billing_period_end must be after billing_period_start.")

    park = get_park_or_404(park_id)
    method = park["utility_apportionment_method"]

    with store.lock:
        # Build occupied_lots list per the rule: lot.current_lease_id non-null AND
        # lease.status in {CURRENT, DELINQUENT, GRACE}
        occupied: list[dict[str, Any]] = []
        for lot in store.lots.values():
            if lot["park_id"] != park_id:
                continue
            cid = lot.get("current_lease_id")
            if cid is None:
                continue
            lease = store.leases.get(cid)
            if lease is None:
                continue
            if lease["status"] not in ("CURRENT", "DELINQUENT", "GRACE"):
                continue
            occupied.append(lot)

        # Apportion master_total across occupied lots
        shares = apportion_master_total(occupied, int(master_total), method)

        # Compose ordering: lots sorted by created_at for deterministic output and bill creation
        bills_created: list[dict[str, Any]] = []
        affected_lease_ids: set[str] = set()
        for idx, lot in enumerate(occupied):
            lease_id = lot.get("current_lease_id")
            lease = store.leases.get(lease_id) if lease_id else None
            rent_due = compute_rent_due_cents(lease, period_start, period_end)
            lot_share = shares[idx]
            total_due = int(rent_due) + int(lot_share)
            bill = init_bill_fields({
                "lot_id": lot["id"],
                "lease_id": lease_id,
                "billing_period_start": format_timestamp(period_start),
                "billing_period_end": format_timestamp(period_end),
                "master_total_cents": int(master_total),
                "lot_share_cents": int(lot_share),
                "rent_due_cents": int(rent_due),
                "total_due_cents": total_due,
                "paid_at": None,
            })
            store.utility_bills[bill["id"]] = bill
            bills_created.append(bill)
            if lease_id:
                affected_lease_ids.add(lease_id)

        # Recompute outstanding balances and apply CURRENT -> DELINQUENT transitions
        for lid in affected_lease_ids:
            lease = store.leases.get(lid)
            if lease is None:
                continue
            balance = recompute_outstanding_balance(lease)
            if balance > 0 and lease["status"] == "CURRENT":
                lease["status"] = "DELINQUENT"
                touch(lease)
            elif balance > 0 and lease["status"] == "DELINQUENT":
                touch(lease)  # version bumps due to balance change
            elif balance > 0:
                touch(lease)
            else:
                # balance == 0: no state change, but updated_at refreshes for the sweep
                pass

    return success_response(
        [serialize_utility_bill(b) for b in bills_created],
        status=200,
        response_type="array",
    )


@bp.route("/_sweep/evictions", methods=["POST"])
@require_auth("PlatformAdmin")
def sweep_evictions():
    finalized: list[dict[str, Any]] = []
    now = clock.now()
    with store.lock:
        for case in list(store.eviction_cases.values()):
            if case.get("status") != "IN_CURE":
                continue
            deadline = case.get("cure_deadline")
            if isinstance(deadline, str):
                deadline = _parse_dt(deadline)
            if deadline is None or now < deadline:
                continue
            case["status"] = "FINALIZED_FOR_CAUSE"
            touch(case)
            lease = store.leases.get(case.get("lease_id", ""))
            if lease is not None and lease.get("status") in ("GRACE", "CURRENT", "DELINQUENT"):
                # If somehow still CURRENT/DELINQUENT, route through GRACE first
                if lease["status"] != "GRACE":
                    lease["status"] = "GRACE"
                    touch(lease)
                lease_grace_to_terminated(lease)
            finalized.append(case)
            # Also recompute resident violation count
            if lease is not None:
                resident = store.residents.get(lease.get("resident_id", ""))
                if resident is not None:
                    recompute_violation_count_12mo(resident)
                    touch(resident)

    return success_response(
        [serialize_eviction(c) for c in finalized],
        status=200,
        response_type="array",
    )


@bp.route("/_sweep/rent-effective", methods=["POST"])
@require_auth("PlatformAdmin")
def sweep_rent_effective():
    promoted: list[dict[str, Any]] = []
    now = clock.now()
    with store.lock:
        for notice in list(store.rent_notices.values()):
            if notice.get("status") != "ISSUED":
                continue
            eff = notice.get("effective_on")
            if isinstance(eff, str):
                eff = _parse_dt(eff)
            if eff is None or now < eff:
                continue
            lease = store.leases.get(notice.get("lease_id", ""))
            if lease is None:
                continue
            if lease.get("status") not in ("CURRENT", "DELINQUENT"):
                # If lease has terminated/assumed since issuance, void the notice
                if lease.get("status") in ("TERMINATED", "ASSUMED"):
                    notice["status"] = "VOIDED"
                    touch(notice)
                continue
            new_rent = int(notice.get("capped_new_rent_cents") or 0)
            lease["monthly_rent_cents"] = new_rent
            touch(lease)
            lot = store.lots.get(lease.get("lot_id", ""))
            if lot is not None:
                lot["base_rent_cents"] = new_rent
                touch(lot)
            notice["status"] = "EFFECTIVE"
            touch(notice)
            promoted.append(notice)

    return success_response(
        [serialize_notice(n) for n in promoted],
        status=200,
        response_type="array",
    )


__all__ = ["bp"]
