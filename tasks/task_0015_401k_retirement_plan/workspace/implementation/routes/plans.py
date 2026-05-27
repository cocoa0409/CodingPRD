"""Plan resource — create, get, list, lifecycle transitions."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
)
from middleware import auth_required
from response import success_array, success_object
from services.entities import (
    recompute_outstanding_loan_principal,
    recompute_vested_balance,
    serialize_plan,
    stamp_create,
    stamp_update,
)
from services.validators import require_dict, require_enum, require_int, require_str


bp = Blueprint("plans", __name__)


MATCH_FORMULAS = {"TIERED", "SAFE_HARBOR_ENHANCED"}
VESTING_SCHEDULES = {"CLIFF_3", "GRADED_6"}
PLAN_STATUSES = {"DRAFT", "ACTIVE", "FROZEN", "TERMINATED"}

DEFAULT_ANNUAL_COMP_LIMIT = 34_500_000
DEFAULT_ANNUAL_DEFERRAL_LIMIT = 2_300_000


def _get_plan_or_404(plan_id: str) -> dict:
    plan = db.plans.get(plan_id)
    if not plan:
        raise APIError(ERR_NOT_FOUND, 404, f"Plan '{plan_id}' not found")
    return plan


@bp.post("/plans")
@auth_required("PlanAdmin")
def create_plan():
    body = require_dict(request.get_json(silent=True))
    name = require_str(body, "name")
    plan_year = require_int(body, "plan_year", minimum=1900, maximum=2999)
    match_formula = require_enum(body, "match_formula", MATCH_FORMULAS)
    vesting_schedule = require_enum(body, "vesting_schedule", VESTING_SCHEDULES)
    annual_comp_limit = require_int(
        body, "annual_compensation_limit_cents", allow_missing=True, minimum=0
    )
    if annual_comp_limit is None:
        annual_comp_limit = DEFAULT_ANNUAL_COMP_LIMIT
    annual_deferral_limit = require_int(
        body, "annual_deferral_limit_cents", allow_missing=True, minimum=0
    )
    if annual_deferral_limit is None:
        annual_deferral_limit = DEFAULT_ANNUAL_DEFERRAL_LIMIT

    with db.LOCK:
        plan = stamp_create(
            {
                "name": name,
                "plan_year": plan_year,
                "match_formula": match_formula,
                "vesting_schedule": vesting_schedule,
                "annual_compensation_limit_cents": annual_comp_limit,
                "annual_deferral_limit_cents": annual_deferral_limit,
                "status": "DRAFT",
            }
        )
        db.plans[plan["id"]] = plan
    return success_object(serialize_plan(plan), status=201)


@bp.get("/plans/<plan_id>")
@auth_required("PlanAdmin", "Custodian")
def get_plan(plan_id: str):
    plan = _get_plan_or_404(plan_id)
    return success_object(serialize_plan(plan))


@bp.get("/plans")
@auth_required("PlanAdmin", "Custodian")
def list_plans():
    limit, offset, status_filter = _parse_list_qs()
    with db.LOCK:
        items = list(db.plans.values())
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_array(
        [serialize_plan(p) for p in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


def _parse_list_qs():
    """Parse limit, offset, optional status filter."""
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in PLAN_STATUSES:
        raise APIError(ERR_INVALID_REQUEST, 400, "invalid status filter")
    return limit, offset, status_filter


# -----------------------------------------------------------------------------
# Lifecycle transitions
# -----------------------------------------------------------------------------


@bp.post("/plans/<plan_id>/activate")
@auth_required("PlanAdmin")
def activate_plan(plan_id: str):
    with db.LOCK:
        plan = _get_plan_or_404(plan_id)
        if plan["status"] != "DRAFT":
            raise APIError(ERR_INVALID_STATE, 409, "Plan is not in DRAFT")
        # Preconditions per SCAFFOLD: match_formula + vesting_schedule set.
        # Creation already enforces both — but reaffirm for defense.
        if not plan.get("match_formula") or not plan.get("vesting_schedule"):
            raise APIError(ERR_INVALID_STATE, 409, "Plan missing match/vesting config")
        plan["status"] = "ACTIVE"
        stamp_update(plan)
    return success_object(serialize_plan(plan))


@bp.post("/plans/<plan_id>/freeze")
@auth_required("PlanAdmin")
def freeze_plan(plan_id: str):
    with db.LOCK:
        plan = _get_plan_or_404(plan_id)
        if plan["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Plan is not in ACTIVE")
        plan["status"] = "FROZEN"
        stamp_update(plan)
    return success_object(serialize_plan(plan))


@bp.post("/plans/<plan_id>/unfreeze")
@auth_required("PlanAdmin")
def unfreeze_plan(plan_id: str):
    with db.LOCK:
        plan = _get_plan_or_404(plan_id)
        if plan["status"] != "FROZEN":
            raise APIError(ERR_INVALID_STATE, 409, "Plan is not in FROZEN")
        plan["status"] = "ACTIVE"
        stamp_update(plan)
    return success_object(serialize_plan(plan))


@bp.post("/plans/<plan_id>/terminate")
@auth_required("PlanAdmin")
def terminate_plan(plan_id: str):
    body = require_dict(request.get_json(silent=True))
    # Validation order matches §2.10: existence -> state -> stale-version.
    with db.LOCK:
        plan = _get_plan_or_404(plan_id)
        if plan["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Plan is not in ACTIVE")
        expected_version = require_int(body, "expected_plan_version", minimum=0)
        if expected_version != plan["version"]:
            raise APIError(
                ERR_STALE_VERSION,
                412,
                f"expected_plan_version {expected_version} != current {plan['version']}",
            )

        plan["status"] = "TERMINATED"
        stamp_update(plan)

        # Cascade depth 2: every Participant in {ENROLLED, SUSPENDED} -> TERMINATED.
        for p in list(db.participants.values()):
            if p["plan_id"] != plan_id:
                continue
            if p["enrollment_status"] in {"ENROLLED", "SUSPENDED"}:
                p["enrollment_status"] = "TERMINATED"
                stamp_update(p)

                # Cascade depth 3: every DISBURSED loan on terminated participants
                # transitions to DEFAULTED with the same deemed-distribution
                # semantics as the operator-initiated default per PRD §3.4:
                # "initiated either by a plan administrator or as a cascaded
                # consequence of the participant being terminated — treats the
                # unpaid principal as a deemed distribution against the
                # participant's vested employer match: the participant's
                # `employer_balance_cents` is reduced by the loan's prior
                # `outstanding_principal_cents`..."
                for loan in list(db.loans.values()):
                    if loan["participant_id"] != p["id"]:
                        continue
                    if loan["status"] == "DISBURSED":
                        prior_outstanding = loan["outstanding_principal_cents"]
                        loan["status"] = "DEFAULTED"
                        stamp_update(loan)
                        # Depth-2: deduct unpaid principal from employer_balance_cents.
                        p["employer_balance_cents"] -= prior_outstanding
                # Reconcile derived balances downstream of the defaults.
                recompute_outstanding_loan_principal(p)
                recompute_vested_balance(p)
                # Bumping version is part of cascade per §2.6; do it again because
                # outstanding_loan_principal_cents (a derived field) just changed.
                # However, per §2.6, the participant version already bumped above
                # for the enrollment-status change; the loan defaults are their
                # own version bump on the loan. We do NOT bump the participant a
                # second time — the spec calls for "a version bump on the affected
                # row" per cascade event, and the participant's affected event is
                # the termination itself.
    return success_object(serialize_plan(plan))
