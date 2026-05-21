"""Eviction Case routes: file, cure, dismiss, get."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import clock, format_timestamp
from ..errors import ApiError
from ..responses import success_response
from ..services.calculations import (
    recompute_outstanding_balance,
    recompute_violation_count_12mo,
)
from ..services.cascades import (
    lease_back_from_grace,
    lease_grace_to_terminated,
    lease_to_grace_from_eviction,
)
from ..services.entities import (
    get_eviction_or_404,
    get_lease_or_404,
    init_common_fields,
    touch,
)
from ..services.serialization import serialize_eviction
from ..store import store
from ..validation import get_json_body, require_enum


bp = Blueprint("evictions", __name__)


_CURE_WINDOW_DAYS = {
    "NONPAYMENT": 30,
    "RULE_VIOLATION": 14,
    "ILLEGAL_USE": 0,
}


@bp.route("/leases/<lease_id>/eviction-cases", methods=["POST"])
@require_auth("ParkManager")
def file_case(lease_id: str):
    lease = get_lease_or_404(lease_id)
    body = get_json_body()
    violation_type = require_enum(body, "violation_type", {"NONPAYMENT", "RULE_VIOLATION", "ILLEGAL_USE"})

    with store.lock:
        # Lease must be in a state that admits an eviction (CURRENT or DELINQUENT primarily)
        if lease["status"] not in ("CURRENT", "DELINQUENT"):
            raise ApiError("ERR_INVALID_STATE", "Lease is not in a state that admits an eviction filing.")

        now = clock.now()
        case = init_common_fields({
            "lease_id": lease_id,
            "violation_type": violation_type,
            # PRD §2.4: ISO 8601 UTC with millisecond precision.
            "filed_at": format_timestamp(now),
            "cure_deadline": None,
            "status": "FILED",
        })

        window = _CURE_WINDOW_DAYS[violation_type]
        if window > 0:
            case["cure_deadline"] = format_timestamp(now + timedelta(days=window))
            # Auto-transition FILED -> IN_CURE; Lease -> GRACE
            case["status"] = "IN_CURE"
            store.eviction_cases[case["id"]] = case
            touch(case)
            lease_to_grace_from_eviction(lease)
        else:
            # ILLEGAL_USE: FILED -> FINALIZED_FOR_CAUSE direct; Lease -> GRACE -> TERMINATED cascade
            case["status"] = "FINALIZED_FOR_CAUSE"
            store.eviction_cases[case["id"]] = case
            touch(case)
            # Drive lease through GRACE -> TERMINATED (works from CURRENT/DELINQUENT)
            lease_to_grace_from_eviction(lease)
            lease_grace_to_terminated(lease)

    return success_response(serialize_eviction(case), status=201)


@bp.route("/eviction-cases/<case_id>/cure", methods=["POST"])
@require_auth("Resident")
def cure_case(case_id: str):
    case = get_eviction_or_404(case_id)
    user_id = g.user_id
    lease = store.leases.get(case["lease_id"])
    if lease is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Lease missing.")

    # Ownership check (priority 5)
    if lease["resident_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER", "Eviction does not belong to the acting resident.")

    with store.lock:
        # Priority 8: ILLEGAL_USE forbids cure (no IN_CURE reachable, but tester may attempt anyway)
        if case.get("violation_type") == "ILLEGAL_USE":
            raise ApiError("ERR_NO_CURE_PERMITTED", "ILLEGAL_USE violations have no cure window.")
        # Priority 6: source-state legality
        if case["status"] != "IN_CURE":
            raise ApiError("ERR_INVALID_STATE", "EvictionCase is not in IN_CURE state.")
        # Priority 14: cure window
        from ..services.calculations import _parse_dt
        deadline = case.get("cure_deadline")
        if isinstance(deadline, str):
            deadline = _parse_dt(deadline)
        now = clock.now()
        if deadline is None or now >= deadline:
            raise ApiError("ERR_CURE_WINDOW_EXPIRED", "Cure deadline has passed.")
        # Priority 17: NONPAYMENT requires balance == 0
        if case["violation_type"] == "NONPAYMENT":
            bal = recompute_outstanding_balance(lease)
            if bal != 0:
                raise ApiError("ERR_BALANCE_NOT_ZERO", "Outstanding balance must be zero to cure a NONPAYMENT case.")

        # Transition
        case["status"] = "CURED"
        touch(case)
        # Lease GRACE -> CURRENT or DELINQUENT
        lease_back_from_grace(lease)

    return success_response(serialize_eviction(case), status=200)


@bp.route("/eviction-cases/<case_id>/dismiss", methods=["POST"])
@require_auth("ParkManager")
def dismiss_case(case_id: str):
    case = get_eviction_or_404(case_id)
    lease = store.leases.get(case["lease_id"])
    if lease is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Lease missing.")

    with store.lock:
        # Only non-terminal cases may be dismissed; terminal = FINALIZED_FOR_CAUSE or DISMISSED
        if case["status"] not in ("FILED", "IN_CURE", "CURED"):
            raise ApiError("ERR_INVALID_STATE", "EvictionCase is not in a dismissible state.")
        prior = case["status"]
        case["status"] = "DISMISSED"
        touch(case)
        # Cascade lease only from IN_CURE
        if prior == "IN_CURE":
            lease_back_from_grace(lease)

    return success_response(serialize_eviction(case), status=200)


@bp.route("/eviction-cases/<case_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_case(case_id: str):
    case = get_eviction_or_404(case_id)
    return success_response(serialize_eviction(case), status=200)


__all__ = ["bp"]
