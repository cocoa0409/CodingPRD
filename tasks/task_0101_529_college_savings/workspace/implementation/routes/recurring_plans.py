"""Recurring plan endpoints."""

from datetime import timedelta
from flask import Blueprint, g, request
from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, lock
from core.clock import CLOCK
from core.validation import (
    require_body, require_field, require_enum,
)
from core.models import (
    recurring_plan_create, recurring_plan_view, touch,
)
from core.store import iso_now_from_dt


bp = Blueprint("recurring_plans", __name__)

VALID_CADENCES = {7, 14, 30, 90, 365}


def _check_donor_owns_account(account):
    if g.user_role == "Donor" and account["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this account")


def _check_donor_owns_plan(plan):
    if g.user_role != "Donor":
        return
    a = STORE.accounts.get(plan["account_id"])
    if not a or a["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this plan")


def _next_run_at_iso(cadence_days: int) -> str:
    dt = CLOCK.now() + timedelta(seconds=cadence_days * 86400)
    return iso_now_from_dt(dt)


@bp.post("/accounts/<aid>/recurring-plans")
@require_roles("Donor")
def create_plan(aid):
    body = require_body(request)
    donor_id = require_field(body, "donor_id", kind="string")
    amount_cents = require_field(body, "amount_cents", kind="positive_int")
    cadence_days = require_field(body, "cadence_days", kind="positive_int")
    if cadence_days not in VALID_CADENCES:
        raise_error("ERR_VALIDATION_FAILED",
                    f"cadence_days must be one of {sorted(VALID_CADENCES)}")

    with lock():
        a = STORE.accounts.get(aid)
        if not a:
            raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
        _check_donor_owns_account(a)
        if not STORE.donors.get(donor_id):
            raise_error("ERR_NOT_FOUND", f"Donor {donor_id} not found")
        if a["status"] != "OPEN":
            raise_error("ERR_ACCOUNT_RESTRICTED",
                        f"Account is {a['status']}; cannot create recurring plan")
        plan = recurring_plan_create(
            aid, donor_id, amount_cents, cadence_days, _next_run_at_iso(cadence_days)
        )
    return success_object(recurring_plan_view(plan), 201)


@bp.patch("/recurring-plans/<pid>")
@require_roles("Donor")
def patch_plan(pid):
    body = require_body(request)
    with lock():
        plan = STORE.recurring_plans.get(pid)
        if not plan:
            raise_error("ERR_NOT_FOUND", f"RecurringPlan {pid} not found")
        _check_donor_owns_plan(plan)

        # PATCH allows amount_cents?, cadence_days?, version (optional OCC).
        if "amount_cents" in body and body["amount_cents"] is not None:
            v = body["amount_cents"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise_error("ERR_VALIDATION_FAILED",
                            "amount_cents must be a positive integer")
        if "cadence_days" in body and body["cadence_days"] is not None:
            v = body["cadence_days"]
            if isinstance(v, bool) or not isinstance(v, int) or v not in VALID_CADENCES:
                raise_error("ERR_VALIDATION_FAILED",
                            f"cadence_days must be one of {sorted(VALID_CADENCES)}")

        # OCC: priority 18.
        if "version" in body and body["version"] is not None:
            v = body["version"]
            if not isinstance(v, int) or v != plan["version"]:
                raise_error("ERR_VERSION_CONFLICT",
                            "version supplied does not match current row version")

        if "amount_cents" in body and body["amount_cents"] is not None:
            plan["amount_cents"] = body["amount_cents"]
        if "cadence_days" in body and body["cadence_days"] is not None:
            plan["cadence_days"] = body["cadence_days"]
        touch(plan)
    return success_object(recurring_plan_view(plan))


@bp.post("/recurring-plans/<pid>/pause")
@require_roles("Donor")
def pause_plan(pid):
    with lock():
        plan = STORE.recurring_plans.get(pid)
        if not plan:
            raise_error("ERR_NOT_FOUND", f"RecurringPlan {pid} not found")
        _check_donor_owns_plan(plan)
        if plan["status"] != "ACTIVE":
            raise_error("ERR_INVALID_STATE",
                        f"Cannot pause plan in status {plan['status']}")
        plan["status"] = "PAUSED"
        touch(plan)
    return success_object(recurring_plan_view(plan))


@bp.post("/recurring-plans/<pid>/resume")
@require_roles("Donor")
def resume_plan(pid):
    with lock():
        plan = STORE.recurring_plans.get(pid)
        if not plan:
            raise_error("ERR_NOT_FOUND", f"RecurringPlan {pid} not found")
        _check_donor_owns_plan(plan)
        a = STORE.accounts.get(plan["account_id"])
        if not a:
            raise_error("ERR_NOT_FOUND", "Account missing for this plan")
        # State priority: account restricted then invalid state.
        if a["status"] != "OPEN":
            raise_error("ERR_ACCOUNT_RESTRICTED",
                        f"Account is {a['status']}; cannot resume plan")
        if plan["status"] != "PAUSED":
            raise_error("ERR_INVALID_STATE",
                        f"Cannot resume plan in status {plan['status']}")
        plan["status"] = "ACTIVE"
        plan["next_run_at"] = _next_run_at_iso(plan["cadence_days"])
        touch(plan)
    return success_object(recurring_plan_view(plan))


@bp.post("/recurring-plans/<pid>/cancel")
@require_roles("Donor")
def cancel_plan(pid):
    with lock():
        plan = STORE.recurring_plans.get(pid)
        if not plan:
            raise_error("ERR_NOT_FOUND", f"RecurringPlan {pid} not found")
        _check_donor_owns_plan(plan)
        if plan["status"] not in {"ACTIVE", "PAUSED"}:
            raise_error("ERR_INVALID_STATE",
                        f"Cannot cancel plan in status {plan['status']}")
        plan["status"] = "CANCELLED"
        touch(plan)
    return success_object(recurring_plan_view(plan))
