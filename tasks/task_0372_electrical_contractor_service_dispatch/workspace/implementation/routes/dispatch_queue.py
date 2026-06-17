"""Dispatch queue (PRD §3.10, SCAFFOLD dispatch_ranking).

Ranked next-job recommendations for a zone. Candidates: every ServiceJob in
QUOTED status whose zone (customer.service_zip prefix) matches the requested
zone (panel/EV jobs included). Ranked by, in strict order:
  1. EMERGENCY before STANDARD
  2. priority_dispatch members before non-priority
  3. created_at ASC (final deterministic tie-break; id is never used)
"""
from flask import Blueprint, request

import db
import response
from errors import err
from helpers import paginate, parse_pagination, serialize_list
from middleware import get_identity, require_roles
from services import domain

bp = Blueprint("dispatch_queue", __name__)


def _is_priority_member(job):
    if job.get("membership_id") is None:
        return False
    membership = db.memberships.get(job["membership_id"])
    if membership is None:
        return False
    plan = db.membership_plans.get(membership["plan_id"])
    return bool(plan is not None and plan["priority_dispatch"])


@bp.get("/v1/dispatch-queue")
def dispatch_queue():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    zone = request.args.get("zone")
    if zone is None or zone == "":
        raise err("ERR_INVALID_REQUEST", "zone query parameter is required")
    limit, offset = parse_pagination()

    candidates = []
    for job in db.service_jobs.values():
        if job["status"] != "QUOTED":
            continue
        customer = db.customers.get(job["customer_id"])
        if customer is None:
            continue
        if domain.job_zone(customer) != zone:
            continue
        candidates.append(job)

    # Sort key: EMERGENCY first, priority_dispatch members first, created_at ASC.
    # All keys ascending => emergency_rank 0 for EMERGENCY, member_rank 0 for
    # priority members. created_at is the final tie-break (never id).
    def sort_key(job):
        emergency_rank = 0 if job["priority"] == "EMERGENCY" else 1
        member_rank = 0 if _is_priority_member(job) else 1
        return (emergency_rank, member_rank, job["created_at"])

    candidates.sort(key=sort_key)
    page, total = paginate(candidates, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)
