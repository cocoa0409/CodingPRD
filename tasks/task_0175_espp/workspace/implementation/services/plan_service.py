"""Plan service: create, update, activate, terminate, list."""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.errors import (
    APIError,
    err_duplicate_plan_name,
    err_invalid_period_state,
    err_not_found,
    err_period_length_out_of_range,
    err_plan_not_active,
    err_version_conflict,
)
from core.store import store
from core.utils import lock, new_id, parse_iso
from services.offering_period_service import _create_offering_period_internal
from services.timestamps import stamp_create, stamp_update


PLAN_DEFAULTS = {
    "max_contribution_rate_bp": 1500,
    "annual_accrual_cap_cents": 2500000,
    "lookback_enabled": True,
    "discount_bp": 1500,
}


def _validate_plan_config(
    *,
    offering_period_months: Optional[int],
    max_contribution_rate_bp: Optional[int],
    discount_bp: Optional[int],
) -> None:
    if offering_period_months is not None:
        if not isinstance(offering_period_months, int) or isinstance(offering_period_months, bool):
            raise err_period_length_out_of_range()
        if offering_period_months < 6 or offering_period_months > 24:
            raise err_period_length_out_of_range()
    if max_contribution_rate_bp is not None:
        if not isinstance(max_contribution_rate_bp, int) or isinstance(max_contribution_rate_bp, bool):
            raise APIError(
                "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                "max_contribution_rate_bp must be an integer.",
                422,
            )
        if max_contribution_rate_bp <= 0 or max_contribution_rate_bp > 1500:
            raise APIError(
                "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                "max_contribution_rate_bp must be in (0, 1500].",
                422,
            )
    if discount_bp is not None:
        if not isinstance(discount_bp, int) or isinstance(discount_bp, bool):
            raise APIError(
                "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                "discount_bp must be an integer.",
                422,
            )
        if discount_bp < 0 or discount_bp > 1500:
            raise APIError(
                "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                "discount_bp must be in [0, 1500].",
                422,
            )


def _validate_name(name: Optional[str]) -> None:
    if name is None:
        return
    if not isinstance(name, str) or not (1 <= len(name) <= 120):
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "Plan.name must be 1..120 chars.",
            422,
        )


def get_plan_or_404(plan_id: str) -> dict:
    p = store.plans.get(plan_id)
    if p is None:
        raise err_not_found(f"Plan {plan_id} not found.")
    return p


def assert_plan_active(plan: dict) -> None:
    if plan["status"] != "ACTIVE":
        raise err_plan_not_active(f"Plan {plan['id']} is {plan['status']}.")


def create_plan(payload: Dict[str, Any]) -> dict:
    name = payload.get("name")
    offering_period_months = payload.get("offering_period_months")
    effective_date_raw = payload.get("effective_date")

    if name is None or not isinstance(name, str) or not name.strip():
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "name is required.",
            422,
        )
    _validate_name(name)
    if offering_period_months is None:
        raise err_period_length_out_of_range("offering_period_months is required.")
    if effective_date_raw is None:
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "effective_date is required.",
            422,
        )

    max_contribution_rate_bp = payload.get("max_contribution_rate_bp", PLAN_DEFAULTS["max_contribution_rate_bp"])
    annual_accrual_cap_cents = payload.get("annual_accrual_cap_cents", PLAN_DEFAULTS["annual_accrual_cap_cents"])
    lookback_enabled = payload.get("lookback_enabled", PLAN_DEFAULTS["lookback_enabled"])
    discount_bp = payload.get("discount_bp", PLAN_DEFAULTS["discount_bp"])

    _validate_plan_config(
        offering_period_months=offering_period_months,
        max_contribution_rate_bp=max_contribution_rate_bp,
        discount_bp=discount_bp,
    )

    if not isinstance(annual_accrual_cap_cents, int) or isinstance(annual_accrual_cap_cents, bool) or annual_accrual_cap_cents <= 0:
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "annual_accrual_cap_cents must be a positive integer.",
            422,
        )
    if not isinstance(lookback_enabled, bool):
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "lookback_enabled must be boolean.",
            422,
        )

    try:
        eff_dt = parse_iso(effective_date_raw)
    except Exception:
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "effective_date must be ISO 8601.",
            422,
        )

    with lock():
        for existing in store.plans.values():
            if existing["name"] == name:
                raise err_duplicate_plan_name()

        plan = {
            "id": new_id(),
            "name": name,
            "status": "DRAFT",
            "offering_period_months": offering_period_months,
            "max_contribution_rate_bp": max_contribution_rate_bp,
            "annual_accrual_cap_cents": annual_accrual_cap_cents,
            "lookback_enabled": lookback_enabled,
            "discount_bp": discount_bp,
            "effective_date": effective_date_raw,
        }
        stamp_create(plan)
        store.plans[plan["id"]] = plan
    return plan


def patch_plan(plan_id: str, payload: Dict[str, Any]) -> dict:
    with lock():
        plan = get_plan_or_404(plan_id)
        if plan["status"] != "DRAFT":
            raise APIError(
                "ERR_INVALID_PERIOD_STATE",
                "Only DRAFT plans may be edited.",
                409,
            )

        # OCC check (priority 17 — after state checks).
        if "version" in payload:
            if payload["version"] != plan["version"]:
                raise err_version_conflict()

        if "name" in payload:
            new_name = payload["name"]
            _validate_name(new_name)
            for other in store.plans.values():
                if other["id"] != plan_id and other["name"] == new_name:
                    raise err_duplicate_plan_name()

        candidate_op_months = payload.get("offering_period_months", plan["offering_period_months"])
        candidate_max_rate = payload.get("max_contribution_rate_bp", plan["max_contribution_rate_bp"])
        candidate_discount = payload.get("discount_bp", plan["discount_bp"])
        _validate_plan_config(
            offering_period_months=candidate_op_months,
            max_contribution_rate_bp=candidate_max_rate,
            discount_bp=candidate_discount,
        )

        if "annual_accrual_cap_cents" in payload:
            v = payload["annual_accrual_cap_cents"]
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise APIError(
                    "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                    "annual_accrual_cap_cents must be a positive integer.",
                    422,
                )
        if "lookback_enabled" in payload and not isinstance(payload["lookback_enabled"], bool):
            raise APIError(
                "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                "lookback_enabled must be boolean.",
                422,
            )
        if "effective_date" in payload:
            try:
                parse_iso(payload["effective_date"])
            except Exception:
                raise APIError(
                    "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
                    "effective_date must be ISO 8601.",
                    422,
                )

        for field in (
            "name",
            "offering_period_months",
            "max_contribution_rate_bp",
            "annual_accrual_cap_cents",
            "lookback_enabled",
            "discount_bp",
            "effective_date",
        ):
            if field in payload:
                plan[field] = payload[field]

        stamp_update(plan)
    return plan


def activate_plan(plan_id: str) -> dict:
    with lock():
        plan = get_plan_or_404(plan_id)
        if plan["status"] != "DRAFT":
            raise err_invalid_period_state("Plan must be DRAFT to activate.")

        _validate_plan_config(
            offering_period_months=plan["offering_period_months"],
            max_contribution_rate_bp=plan["max_contribution_rate_bp"],
            discount_bp=plan["discount_bp"],
        )

        eff_dt = parse_iso(plan["effective_date"])
        current_time = parse_iso(store.clock["current_time"])
        if eff_dt < current_time:
            raise APIError(
                "ERR_INVALID_PERIOD_STATE",
                "effective_date must be >= current_time at activation.",
                409,
            )

        plan["status"] = "ACTIVE"
        stamp_update(plan)

        # Side effect: create the first OfferingPeriod.
        _create_offering_period_internal(
            plan=plan,
            sequence_number=1,
            start_date=plan["effective_date"],
        )
    return plan


def terminate_plan(plan_id: str) -> dict:
    with lock():
        plan = get_plan_or_404(plan_id)
        if plan["status"] != "ACTIVE":
            raise err_invalid_period_state("Plan must be ACTIVE to terminate.")
        for op in store.list_offering_periods_for_plan(plan_id):
            if op["status"] == "OPEN":
                raise err_invalid_period_state(
                    "Cannot terminate while an OPEN OfferingPeriod exists."
                )
        plan["status"] = "TERMINATED"
        stamp_update(plan)
    return plan


def list_plans(status_filter: Optional[str]) -> list:
    items = list(store.plans.values())
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: p["created_at"])
    return items
