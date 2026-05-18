"""Distribution endpoints (SCAFFOLD §1.5 distributions)."""
from __future__ import annotations

from flask import Blueprint, request

from config import DISTRIBUTION_STATUSES
from db import store
from errors import ApiError
from middleware import current_role, require_auth
from response import list_success, success
from services.common import (
    bump,
    check_version,
    get_json_body,
    paginate,
    pop_pagination,
    require_child,
    require_estate,
    sort_by_created_at,
)
from services.serializers import serialize_distribution


bp = Blueprint("distributions", __name__)


def _is_non_neg_int(v) -> bool:
    if isinstance(v, bool):
        return False
    return isinstance(v, int) and v >= 0


@bp.get("/estates/<estate_id>/distributions/<distribution_id>")
@require_auth(["Executor", "Beneficiary", "CourtClerk"])
def get_distribution(estate_id: str, distribution_id: str):
    with store.lock:
        require_estate(estate_id)
        d = require_child(store.distributions, estate_id, distribution_id)
    return success(serialize_distribution(d), 200)


@bp.get("/estates/<estate_id>/distributions")
@require_auth(["Executor", "Beneficiary", "CourtClerk"])
def list_distributions(estate_id: str):
    limit, offset = pop_pagination(request.args)
    status_f = request.args.get("status")
    beneficiary_f = request.args.get("beneficiary_id")
    if status_f is not None and status_f not in DISTRIBUTION_STATUSES:
        raise ApiError("ERR_BAD_REQUEST", 400, "status filter invalid.")

    with store.lock:
        require_estate(estate_id)
        rows = [d for d in store.distributions.values() if d["estate_id"] == estate_id]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if beneficiary_f:
            rows = [r for r in rows if r["beneficiary_id"] == beneficiary_f]
        rows = sort_by_created_at(rows)
        page, total = paginate(rows, limit, offset)
        items = [serialize_distribution(r) for r in page]
    return list_success(items, limit, offset, total, 200)


@bp.post("/estates/<estate_id>/distributions/<distribution_id>/state")
@require_auth(["Executor", "CourtClerk"])
def transition_distribution_state(estate_id: str, distribution_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in DISTRIBUTION_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Unknown target status for distribution transition.")
    role = current_role()

    with store.lock:
        estate = require_estate(estate_id)
        d = require_child(store.distributions, estate_id, distribution_id)
        check_version(d, body)
        current = d["status"]

        if current == "PLANNED" and to_status == "EXECUTED":
            if role != "Executor":
                raise ApiError("ERR_FORBIDDEN", 403,
                               "Only Executor may EXECUTE a distribution.")
            if estate["admin_phase"] != "DISTRIBUTING":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Distribution EXECUTE requires estate in DISTRIBUTING.")
            actual = body.get("actual_amount_cents")
            if not _is_non_neg_int(actual):
                raise ApiError("ERR_BAD_REQUEST", 400,
                               "actual_amount_cents is required and must be a non-negative integer.")
            if int(actual) != int(d["planned_amount_cents"]):
                raise ApiError("ERR_DISTRIBUTION_DRIFT", 422,
                               "actual_amount_cents must equal planned_amount_cents (no drift).")
            d["actual_amount_cents"] = int(actual)
            d["status"] = "EXECUTED"
            d["executed_at"] = store.now()
            bump(d)
            return success(serialize_distribution(d), 200)

        if current == "EXECUTED" and to_status == "REVERSED":
            if role != "CourtClerk":
                raise ApiError("ERR_FORBIDDEN", 403,
                               "Only CourtClerk may REVERSE a distribution.")
            if estate["admin_phase"] == "SETTLED":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Cannot reverse a distribution on a SETTLED estate.")
            beneficiary = store.beneficiaries.get(d["beneficiary_id"])
            if beneficiary and beneficiary["status"] == "REMOVED":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Cannot reverse a distribution whose beneficiary is REMOVED.")
            d["status"] = "REVERSED"
            bump(d)
            # Side effect: revert any Asset whose distribution_id == d.id.
            for a in store.assets.values():
                if a["estate_id"] != estate_id:
                    continue
                if a.get("distribution_id") == d["id"]:
                    a["status"] = "APPRAISED"
                    a["distribution_id"] = None
                    bump(a)
            # Recompute gross_estate (chronological invariant preserved).
            from services.calculations import recompute_estate_gross
            recompute_estate_gross(estate, "forward_looking")
            return success(serialize_distribution(d), 200)

        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Cannot transition distribution from {current} to {to_status}.")
