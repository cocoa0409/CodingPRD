"""Volume cap request, decision, return and revision (PRD 3.3)."""

from flask import Blueprint

import calc
import domain
import serialize
import validation as v
from auth import guard, own_project
from envelope import object_response
from errors import fail
from store import db, new_row, touch

bp = Blueprint("volumecap", __name__)


@bp.post("/volume-cap-allocations")
def create_allocation():
    caller = guard("POST /volume-cap-allocations")
    body = v.body()
    own_project(caller, domain.soft_get(db.projects, body.get("project_id")))

    project_id = v.req_id(body, "project_id")
    cap_pool_id = v.req_id(body, "cap_pool_id")
    requested_amount_cents = v.req_int(body, "requested_amount_cents", minimum=1)
    closing_raw, _closing = v.req_dt(body, "requested_closing_date")

    # Foreign keys resolve in entity declaration order: CapPool precedes Project.
    pool = domain.get_or_404(db.cap_pools, cap_pool_id, "ERR_CAP_POOL_NOT_FOUND")
    project = domain.get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(caller, project)
    domain.require_developer_active(project)

    if domain.live_allocation_exists(project_id):
        fail("ERR_ALLOCATION_ALREADY_EXISTS",
             "The development already holds a live cap allocation.")

    row = new_row(db.allocations, {
        "project_id": project_id,
        "cap_pool_id": cap_pool_id,
        "requested_amount_cents": requested_amount_cents,
        "requested_closing_date": closing_raw,
        "status": "PENDING",
        "awarded_amount_cents": None,
        "expiry_date": None,
        "denial_reason": None,
        "return_reason": None,
        "decided_by_user_id": None,
        "decision_round": 1,
    })
    domain.rederive_pool(pool)
    return object_response(serialize.allocation(row), 201)


@bp.post("/volume-cap-allocations/<row_id>/decision")
def decide_allocation(row_id):
    caller = guard("POST /volume-cap-allocations/{id}/decision")
    body = v.body()
    decision = v.req_enum(body, "decision", ("AWARD", "DENY"))
    expected_version = v.req_int(body, "expected_cap_pool_version")
    awarded_amount_cents = None
    expiry_raw = None
    denial_reason = None
    if decision == "AWARD":
        awarded_amount_cents = v.req_int(body, "awarded_amount_cents", minimum=0)
        expiry_raw, _expiry = v.req_dt(body, "expiry_date")
    else:
        denial_reason = v.req_str(body, "denial_reason", allow_empty=False)

    allocation = domain.get_or_404(db.allocations, row_id, "ERR_ALLOCATION_NOT_FOUND")
    pool = domain.get_or_404(db.cap_pools, allocation.get("cap_pool_id"),
                             "ERR_CAP_POOL_NOT_FOUND")

    if expected_version != pool.get("version"):
        fail("ERR_STALE_CAP_POOL_VERSION",
             "expected_cap_pool_version %s does not match the pool's current version %s."
             % (expected_version, pool.get("version")))

    if allocation.get("status") != "PENDING":
        fail("ERR_ALLOCATION_STATE_INVALID",
             "An allocation in %s cannot be decided." % allocation.get("status"))

    project = domain.project_of_row(allocation)

    if decision == "AWARD":
        domain.require_developer_active(project)
        ledger = calc.pool_ledger(pool)
        if awarded_amount_cents > (allocation.get("requested_amount_cents") or 0):
            fail("ERR_INSUFFICIENT_VOLUME_CAP",
                 "The awarded amount exceeds the amount requested.")
        if awarded_amount_cents > ledger["awardable_cents"]:
            fail("ERR_INSUFFICIENT_VOLUME_CAP",
                 "The awarded amount exceeds the pool's awardable cap.")
        allocation["status"] = "AWARDED"
        allocation["awarded_amount_cents"] = awarded_amount_cents
        allocation["expiry_date"] = expiry_raw
        allocation["decided_by_user_id"] = caller.user_id
        touch(allocation)
        domain.rederive_pool(pool)
        domain.defer_on_exhaustion(pool, allocation)
    else:
        allocation["status"] = "DENIED"
        allocation["denial_reason"] = denial_reason
        allocation["decided_by_user_id"] = caller.user_id
        touch(allocation)
        domain.rederive_pool(pool)

    return object_response(serialize.allocation(allocation))


@bp.post("/volume-cap-allocations/<row_id>/return")
def return_allocation(row_id):
    caller = guard("POST /volume-cap-allocations/{id}/return")
    allocation = domain.soft_get(db.allocations, row_id)
    own_project(caller, domain.project_of_row(allocation))

    body = v.body()
    return_reason = v.req_str(body, "return_reason", allow_empty=False)

    allocation = domain.get_or_404(db.allocations, row_id, "ERR_ALLOCATION_NOT_FOUND")
    own_project(caller, domain.project_of_row(allocation))

    if allocation.get("status") != "AWARDED":
        fail("ERR_ALLOCATION_STATE_INVALID",
             "Only an AWARDED allocation may be returned.")
    if domain.allocation_is_committed_to_issue(allocation):
        fail("ERR_ALLOCATION_STATE_INVALID",
             "The award is already committed to a bond issue.")

    allocation["status"] = "RETURNED"
    allocation["return_reason"] = return_reason
    allocation["awarded_amount_cents"] = None
    allocation["expiry_date"] = None
    touch(allocation)

    pool = domain.soft_get(db.cap_pools, allocation.get("cap_pool_id"))
    if pool is not None:
        domain.rederive_pool(pool)
        domain.reinstate_deferred(pool)
    return object_response(serialize.allocation(allocation))


@bp.post("/volume-cap-allocations/<row_id>/revise")
def revise_allocation(row_id):
    caller = guard("POST /volume-cap-allocations/{id}/revise")
    allocation = domain.soft_get(db.allocations, row_id)
    own_project(caller, domain.project_of_row(allocation))

    body = v.body()
    requested_amount_cents = v.req_int(body, "requested_amount_cents", minimum=1)
    closing_raw, _closing = v.req_dt(body, "requested_closing_date")

    allocation = domain.get_or_404(db.allocations, row_id, "ERR_ALLOCATION_NOT_FOUND")
    own_project(caller, domain.project_of_row(allocation))

    previous = allocation.get("status")
    if previous not in ("DENIED", "DEFERRED", "RETURNED"):
        fail("ERR_ALLOCATION_STATE_INVALID",
             "An allocation in %s cannot be revised." % previous)

    allocation["status"] = "PENDING"
    allocation["requested_amount_cents"] = requested_amount_cents
    allocation["requested_closing_date"] = closing_raw
    allocation["decision_round"] = (allocation.get("decision_round") or 1) + 1
    allocation["awarded_amount_cents"] = None
    allocation["expiry_date"] = None
    allocation["denial_reason"] = None
    allocation["return_reason"] = None
    allocation["decided_by_user_id"] = None
    touch(allocation)

    if previous == "DEFERRED":
        project = domain.project_of_row(allocation)
        if project is not None:
            project["financing_stalled"] = False
            touch(project)

    pool = domain.soft_get(db.cap_pools, allocation.get("cap_pool_id"))
    domain.rederive_pool(pool)
    return object_response(serialize.allocation(allocation))
