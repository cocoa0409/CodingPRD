"""Enrollment service: create, patch, withdraw, list."""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.errors import (
    APIError,
    err_contribution_rate_out_of_range,
    err_duplicate_enrollment,
    err_forbidden,
    err_invalid_enrollment_state,
    err_not_found,
    err_not_owner,
    err_period_not_open,
    err_plan_not_active,
    err_version_conflict,
)
from core.store import store
from core.utils import lock, new_id
from services.timestamps import stamp_create, stamp_update


def get_enrollment_or_404(enrollment_id: str) -> dict:
    e = store.enrollments.get(enrollment_id)
    if e is None:
        raise err_not_found(f"Enrollment {enrollment_id} not found.")
    return e


def _validate_rate(rate_bp, *, max_rate_bp: int) -> None:
    if not isinstance(rate_bp, int) or isinstance(rate_bp, bool):
        raise err_contribution_rate_out_of_range()
    if rate_bp <= 0 or rate_bp > max_rate_bp:
        raise err_contribution_rate_out_of_range()


def create_enrollment(
    *, offering_period_id: str, participant_id: str, payload: Dict[str, Any]
) -> dict:
    from services.offering_period_service import get_offering_period_or_404
    from services.plan_service import get_plan_or_404

    with lock():
        op = get_offering_period_or_404(offering_period_id)
        plan = get_plan_or_404(op["plan_id"])

        # State: plan must be ACTIVE.
        if plan["status"] != "ACTIVE":
            raise err_plan_not_active()

        # State: period must be OPEN.
        if op["status"] != "OPEN":
            raise err_period_not_open(
                f"OfferingPeriod {offering_period_id} is {op['status']}."
            )

        rate_bp = payload.get("contribution_rate_bp")
        _validate_rate(rate_bp, max_rate_bp=plan["max_contribution_rate_bp"])

        # Uniqueness: at most one enrollment per (offering_period_id, participant_id).
        for existing in store.enrollments.values():
            if (
                existing["offering_period_id"] == offering_period_id
                and existing["participant_id"] == participant_id
            ):
                raise err_duplicate_enrollment()

        enrollment = {
            "id": new_id(),
            "offering_period_id": offering_period_id,
            "participant_id": participant_id,
            "contribution_rate_bp": rate_bp,
            "status": "ACTIVE",
            "ytd_accrual_cents": 0,
        }
        stamp_create(enrollment)
        store.enrollments[enrollment["id"]] = enrollment
    return enrollment


def patch_enrollment(
    *, enrollment_id: str, acting_user_id: str, payload: Dict[str, Any]
) -> dict:
    from services.offering_period_service import get_offering_period_or_404
    from services.plan_service import get_plan_or_404

    with lock():
        e = get_enrollment_or_404(enrollment_id)
        op = get_offering_period_or_404(e["offering_period_id"])
        plan = get_plan_or_404(op["plan_id"])

        if plan["status"] != "ACTIVE":
            raise err_plan_not_active()
        if op["status"] != "OPEN":
            raise err_period_not_open()

        # Ownership.
        if e["participant_id"] != acting_user_id:
            raise err_not_owner()

        # State.
        if e["status"] != "ACTIVE":
            raise err_invalid_enrollment_state()

        # Business constraint on rate.
        if "contribution_rate_bp" in payload:
            _validate_rate(
                payload["contribution_rate_bp"],
                max_rate_bp=plan["max_contribution_rate_bp"],
            )

        # OCC.
        if "version" in payload and payload["version"] != e["version"]:
            raise err_version_conflict()

        if "contribution_rate_bp" in payload:
            e["contribution_rate_bp"] = payload["contribution_rate_bp"]

        stamp_update(e)
    return e


def withdraw_enrollment(*, enrollment_id: str, acting_user_id: str) -> dict:
    from services.offering_period_service import get_offering_period_or_404
    from services.plan_service import get_plan_or_404

    with lock():
        e = get_enrollment_or_404(enrollment_id)
        op = get_offering_period_or_404(e["offering_period_id"])
        plan = get_plan_or_404(op["plan_id"])

        if plan["status"] != "ACTIVE":
            raise err_plan_not_active()
        if op["status"] != "OPEN":
            raise err_period_not_open()

        if e["participant_id"] != acting_user_id:
            raise err_not_owner()

        if e["status"] != "ACTIVE":
            raise err_invalid_enrollment_state()

        e["status"] = "WITHDRAWN"
        stamp_update(e)

        # Refund all POSTED contributions on this enrollment.
        for c in store.contributions.values():
            if c["enrollment_id"] == enrollment_id and c["status"] == "POSTED":
                c["status"] = "REFUNDED"
                # Contribution has no updated_at / version; leave as-is.
    return e
