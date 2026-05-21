"""Contribution service: post and list."""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.errors import (
    APIError,
    err_annual_accrual_cap_exceeded,
    err_invalid_enrollment_state,
    err_not_found,
    err_period_not_open,
    err_plan_not_active,
)
from core.store import store
from core.utils import lock, new_id, parse_iso
from services.calculations import compute_contribution_amount
from services.timestamps import stamp_create


def post_contribution(
    *,
    enrollment_id: str,
    poster_user_id: str,
    payload: Dict[str, Any],
) -> dict:
    from services.enrollment_service import get_enrollment_or_404
    from services.offering_period_service import get_offering_period_or_404
    from services.plan_service import get_plan_or_404

    with lock():
        enrollment = get_enrollment_or_404(enrollment_id)
        op = get_offering_period_or_404(enrollment["offering_period_id"])
        plan = get_plan_or_404(op["plan_id"])

        if plan["status"] != "ACTIVE":
            raise err_plan_not_active()
        if op["status"] != "OPEN":
            raise err_period_not_open()
        if enrollment["status"] != "ACTIVE":
            raise err_invalid_enrollment_state()

        pay_period_end = payload.get("pay_period_end")
        gross_pay_cents = payload.get("gross_pay_cents")
        if pay_period_end is None:
            raise APIError(
                "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                "pay_period_end is required.",
                422,
            )
        try:
            parse_iso(pay_period_end)
        except Exception:
            raise APIError(
                "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                "pay_period_end must be ISO 8601.",
                422,
            )
        if not isinstance(gross_pay_cents, int) or isinstance(gross_pay_cents, bool) or gross_pay_cents < 0:
            raise APIError(
                "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                "gross_pay_cents must be a non-negative integer.",
                422,
            )

        amount_cents = compute_contribution_amount(
            gross_pay_cents=gross_pay_cents,
            contribution_rate_bp=enrollment["contribution_rate_bp"],
            annual_accrual_cap_cents=plan["annual_accrual_cap_cents"],
            ytd_accrual_cents=enrollment["ytd_accrual_cents"],
            discount_bp=plan["discount_bp"],
        )

        # Cap check on projected accrual (priority 11): if even amount_cents
        # would push projected accrual past the cap, reject.
        # Projected accrual charge from this contribution at grant-FMV basis is
        # approximated as the contribution itself converted to FMV-priced
        # shares; the simpler reading of the rule is:
        #   committed + (amount_cents grossed back up by discount) <= cap.
        # We use the inverse of the cap-translation: the in-flight grant-FMV
        # accrual delta == amount_cents * 10000 / (10000 - discount_bp), but
        # since amount_cents is already capped against the remaining cash cap,
        # the only failure mode is when remaining headroom is 0.
        remaining_accrual = plan["annual_accrual_cap_cents"] - enrollment["ytd_accrual_cents"]
        if remaining_accrual <= 0 and amount_cents > 0:
            raise err_annual_accrual_cap_exceeded()

        contribution = {
            "id": new_id(),
            "enrollment_id": enrollment_id,
            "pay_period_end": pay_period_end,
            "gross_pay_cents": gross_pay_cents,
            "amount_cents": amount_cents,
            "status": "POSTED",
        }
        # Contribution has only id + created_at, no updated_at / version.
        stamp_create(contribution, with_updated=False, with_version=False)
        store.contributions[contribution["id"]] = contribution
        store.contribution_posters[contribution["id"]] = poster_user_id
    return contribution


def list_contributions_for_enrollment(
    enrollment_id: str, *, status_filter: Optional[str] = None
) -> list:
    items = store.list_contributions_for_enrollment(enrollment_id)
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    return items


def has_period_posters_overlap(
    *, offering_period_id: str, candidate_user_id: str
) -> bool:
    """Return True if candidate_user_id has posted any contribution against an
    enrollment of the given offering period (any status)."""
    for c in store.contributions.values():
        # Look up enrollment.
        e = store.enrollments.get(c["enrollment_id"])
        if e is None:
            continue
        if e["offering_period_id"] != offering_period_id:
            continue
        if store.contribution_posters.get(c["id"]) == candidate_user_id:
            return True
    return False
