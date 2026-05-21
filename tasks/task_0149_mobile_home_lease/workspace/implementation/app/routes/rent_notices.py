"""Rent Increase Notice routes: draft, issue, get."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from ..auth import require_auth
from ..clock import clock, format_timestamp
from ..errors import ApiError
from ..responses import success_response
from ..services.calculations import compute_capped_new_rent_cents
from ..services.entities import (
    get_lease_or_404,
    get_notice_or_404,
    init_common_fields,
    touch,
)
from ..services.serialization import serialize_notice
from ..store import store
from ..validation import get_json_body, parse_datetime, require_int


bp = Blueprint("rent_notices", __name__)


@bp.route("/leases/<lease_id>/rent-increase-notices", methods=["POST"])
@require_auth("ParkManager")
def draft_notice(lease_id: str):
    lease = get_lease_or_404(lease_id)
    body = get_json_body()
    proposed = require_int(body, "proposed_new_rent_cents", strict_positive=True)
    effective_on = parse_datetime(body, "effective_on", required=True)

    with store.lock:
        notice = init_common_fields({
            "lease_id": lease_id,
            "proposed_new_rent_cents": int(proposed),
            "effective_on": format_timestamp(effective_on),
            "capped_new_rent_cents": None,
            "status": "DRAFT",
        })
        store.rent_notices[notice["id"]] = notice

    return success_response(serialize_notice(notice), status=201)


@bp.route("/rent-increase-notices/<notice_id>/issue", methods=["POST"])
@require_auth("ParkManager")
def issue_notice(notice_id: str):
    notice = get_notice_or_404(notice_id)

    with store.lock:
        # State precondition
        if notice["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Notice is not in DRAFT state.")
        lease = store.leases.get(notice["lease_id"])
        if lease is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Parent lease missing.")
        # Domain priority 15: GRACE blocks issuance (BEFORE non-positive check)
        if lease["status"] == "GRACE":
            raise ApiError("ERR_RENT_INCREASE_BLOCKED_DURING_EVICTION",
                           "Rent-increase issuance blocked while lease is in GRACE.")
        if lease["status"] not in ("CURRENT", "DELINQUENT"):
            raise ApiError("ERR_INVALID_STATE", "Lease is not in CURRENT/DELINQUENT state.")
        # Priority 13: 90-day window
        from ..services.calculations import _parse_dt
        eff_dt = notice["effective_on"]
        if isinstance(eff_dt, str):
            eff_dt = _parse_dt(eff_dt)
        now = clock.now()
        if eff_dt < now + timedelta(days=90):
            raise ApiError("ERR_NOTICE_WINDOW_TOO_SHORT",
                           "effective_on must be at least 90 days after now.")
        # Priority 16: strictly greater than current rent
        current = int(lease.get("monthly_rent_cents") or 0)
        if int(notice["proposed_new_rent_cents"]) <= current:
            raise ApiError("ERR_RENT_INCREASE_NONPOSITIVE",
                           "Proposed rent must be strictly greater than current rent.")
        # Compute cap
        park = store.parks.get(store.lots[lease["lot_id"]]["park_id"])
        if park is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Park missing.")
        capped = compute_capped_new_rent_cents(
            current_rent_cents=current,
            proposed_rent_cents=int(notice["proposed_new_rent_cents"]),
            state_code=park["state_code"],
            master_cpi_pct=float(park["master_cpi_pct"]),
        )
        notice["capped_new_rent_cents"] = capped
        notice["status"] = "ISSUED"
        touch(notice)

    return success_response(serialize_notice(notice), status=200)


@bp.route("/rent-increase-notices/<notice_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_notice(notice_id: str):
    notice = get_notice_or_404(notice_id)
    return success_response(serialize_notice(notice), status=200)


__all__ = ["bp"]
