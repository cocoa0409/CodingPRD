"""Estimate endpoints (PRD 3.4): creation with OCC and auto-withdrawal,
tiered approve/reject decisions with segregation of duties."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_APPROVAL_TIER_REQUIRED,
    ERR_SEGREGATION_OF_DUTIES, ERR_ESTIMATE_BELOW_ACTUALS,
)
from middleware import authorized
from response import success_object
from services.core import (
    new_record, touch, serialize_estimate, wo_estimates, wo_estimate_seq,
    wo_actual_direct_cents, estimate_routing_tier, WO_ESTIMABLE_STATUSES,
    WO_DECIDABLE_STATUSES,
)
from validate import (
    get_body, req_int, opt_str, require_path_resource, require_body_ref,
)
from routes.helpers import list_response, get_one

bp = Blueprint("estimates", __name__)


@bp.route("/ucp/estimates", methods=["POST"])
def create_estimate():
    caller = authorized(["ProjectEngineer"])
    body = get_body()
    # Priority 3 — body FK existence.
    wo = require_body_ref(body, "work_order_id", "work_orders")
    # Priority 4 — shape (expected_work_order_version is mandatory, PRD 2.7).
    estimated_cost_cents = req_int(body, "estimated_cost_cents", positive=True)
    expected_version = req_int(body, "expected_work_order_version")
    notes = opt_str(body, "notes")
    # Priority 6 — OCC on WorkOrder.version (before state legality, PRD 2.8).
    if expected_version != wo["version"]:
        raise_error(ERR_STALE_VERSION, "expected_work_order_version does not match the work order's current version")
    # Priority 7 — state.
    if wo["status"] not in WO_ESTIMABLE_STATUSES:
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")

    # Creating an estimate legitimately withdraws the currently PROPOSED one.
    for e in wo_estimates(wo["id"]):
        if e["status"] == "PROPOSED":
            e["status"] = "WITHDRAWN"
            touch(e)

    rec = new_record()
    rec.update({
        "work_order_id": wo["id"],
        "estimate_seq": wo_estimate_seq(wo["id"]) + 1,
        "estimated_cost_cents": estimated_cost_cents,
        "notes": notes,
        "status": "PROPOSED",
        "supersedes_estimate_id": None,
        "submitted_by_user_id": caller.user_id,
        "decided_by_user_id": None,
        "routing_tier": None,
    })
    db["estimates"][rec["id"]] = rec
    touch(wo)  # estimate_seq advanced
    return success_object(serialize_estimate(rec), status=201)


@bp.route("/ucp/estimates/<estimate_id>", methods=["GET"])
def get_estimate(estimate_id):
    return get_one("estimates", serialize_estimate, estimate_id)


@bp.route("/ucp/estimates", methods=["GET"])
def list_estimates():
    filters = {
        "work_order_id": request.args.get("work_order_id"),
        "status": request.args.get("status"),
        "supersedes_estimate_id": request.args.get("supersedes_estimate_id"),
    }
    return list_response("estimates", serialize_estimate, filters)


def _decision_prechecks(estimate_id, with_occ):
    """Shared decide-time guard chain in PRD 2.8 order:
    shape of the mandatory OCC field (4) -> tier (5) -> OCC (6, approve only)
    -> state (7) -> SoD (8)."""
    caller = authorized(["WorkOrderSupervisor", "Controller"])
    est = require_path_resource("estimates", estimate_id)
    body = get_body()
    wo = db["work_orders"][est["work_order_id"]]
    expected_version = None
    if with_occ:
        # Priority 4 — expected_work_order_version is a mandatory input (PRD 2.7).
        expected_version = req_int(body, "expected_work_order_version")
    # Priority 5 — routing tier computed at decision time.
    tier = estimate_routing_tier(est["estimated_cost_cents"], wo["id"])
    if tier == "CONTROLLER" and caller.role != "Controller":
        raise_error(ERR_APPROVAL_TIER_REQUIRED, "this decision requires the Controller")
    # Priority 6 — the optimistic-concurrency check itself.
    if with_occ and expected_version != wo["version"]:
        raise_error(ERR_STALE_VERSION, "expected_work_order_version does not match the work order's current version")
    # Priority 7 — work-order state and estimate from-state.
    if wo["status"] not in WO_DECIDABLE_STATUSES:
        raise_error(ERR_INVALID_STATE, f"work order is {wo['status']}")
    if est["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, f"estimate is {est['status']}")
    # Priority 8 — segregation of duties vs the submitter.
    if caller.user_id == est["submitted_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "decider must differ from submitter")
    return caller, est, wo, tier


@bp.route("/ucp/estimates/<estimate_id>/approve", methods=["POST"])
def approve_estimate(estimate_id):
    caller, est, wo, tier = _decision_prechecks(estimate_id, with_occ=True)
    # Priority 11 — never approve below actuals.
    if est["estimated_cost_cents"] < wo_actual_direct_cents(wo["id"]):
        raise_error(ERR_ESTIMATE_BELOW_ACTUALS, "estimate is below the work order's actual direct costs")

    program = db["capital_programs"][wo["program_id"]]
    # Supersede the previously APPROVED estimate and link back to it.
    prev = None
    for e in wo_estimates(wo["id"]):
        if e["status"] == "APPROVED":
            prev = e
            break
    if prev is not None:
        prev["status"] = "SUPERSEDED"
        touch(prev)
        est["supersedes_estimate_id"] = prev["id"]

    est["status"] = "APPROVED"
    est["routing_tier"] = tier
    est["decided_by_user_id"] = caller.user_id
    touch(est)
    # approved_estimate_cents / variance_posture recompute on the order; when
    # authorized-or-later the program's committed balance shifts by the delta.
    touch(wo)
    if wo["status"] in ("AUTHORIZED", "IN_PROGRESS", "SUSPENDED"):
        touch(program)
    return success_object(serialize_estimate(est))


@bp.route("/ucp/estimates/<estimate_id>/reject", methods=["POST"])
def reject_estimate(estimate_id):
    # Same tier routing and SoD as approve; no OCC field, no fiscal rewiring.
    caller, est, wo, tier = _decision_prechecks(estimate_id, with_occ=False)
    est["status"] = "REJECTED"
    est["decided_by_user_id"] = caller.user_id
    touch(est)
    return success_object(serialize_estimate(est))
