"""Donation allocations: fixed-order split arithmetic, SoD, capacity re-checks.

Create gate order follows PRD section 3.8 (a refining section):
log VERIFIED -> duplicate active allocation -> exact split sum -> per-line
screening (active -> grade-C -> weekly capacity).
"""
from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err, err_forbidden_role, err_invalid_request, err_not_found, err_sod, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import pagination_args, req_list, req_str, require_field

bp = Blueprint("allocations", __name__)

CREATE_ROLES = ["GardenAdmin", "Coordinator"]
OFFICERS = ["GardenAdmin", "FoodSafetyOfficer"]
TRANSITION_ROLES = ["GardenAdmin", "Coordinator", "FoodSafetyOfficer"]
ALLOCATION_TARGETS = {"APPROVED", "REJECTED", "DISTRIBUTED"}


def _get_allocation(allocation_id):
    alloc = db.allocations.get(allocation_id)
    if alloc is None:
        raise err_not_found("allocation")
    return alloc


@bp.post("/api/donation-allocations")
def create_allocation():
    ctx = require_auth()
    require_role(ctx, CREATE_ROLES)
    data = body()
    # existence (tier 3): harvest log, then each line's recipient
    harvest_log_id = require_field(data, "harvest_log_id")
    log = db.harvests.get(harvest_log_id)
    if log is None:
        raise err_not_found("harvest")
    lines_raw = req_list(data, "lines")
    if not lines_raw:
        raise err_invalid_request("lines must be a non-empty array")
    lines = []
    for line in lines_raw:
        if not isinstance(line, dict):
            raise err_invalid_request("each line must be an object")
        recipient_id = require_field(line, "recipient_id")
        recipient = db.recipients.get(recipient_id)
        if recipient is None:
            raise err_not_found("recipient")
        grams = line.get("grams")
        if isinstance(grams, bool) or not isinstance(grams, int) or grams <= 0:
            raise err_invalid_request("line grams must be an integer > 0")
        lines.append({"recipient_id": recipient_id, "grams": grams})
    # cross-entity guard (tier 7): log must be VERIFIED
    if log["status"] != "VERIFIED":
        raise err("ERR_HARVEST_LOG_NOT_VERIFIED", "harvest log must be VERIFIED")
    # uniqueness (tier 11): at most one non-terminal allocation per log
    if any(a["harvest_log_id"] == harvest_log_id and a["status"] in services.ALLOCATION_ACTIVE
           for a in db.allocations.values()):
        raise err("ERR_DUPLICATE_ACTIVE_ALLOCATION",
                  "harvest log already has a non-terminal allocation")
    # split arithmetic (pinned rounding order): volunteer share floored first
    weight = log["weight_grams"]
    volunteer_share = (weight * 20) // 100  # floor(weight * 0.20) in integer math
    donatable = weight - volunteer_share
    if sum(line["grams"] for line in lines) != donatable:
        raise err("ERR_SPLIT_MISMATCH",
                  f"line grams must sum exactly to donatable_grams ({donatable})")
    # per-line screening, in request order
    for line in lines:
        recipient = db.recipients[line["recipient_id"]]
        if not recipient["active"]:
            raise err("ERR_RECIPIENT_INACTIVE", "recipient is inactive")
        if log["quality_grade"] == "C" and not recipient["accepts_grade_c"]:
            raise err("ERR_RECIPIENT_GRADE_RESTRICTED",
                      "grade-C harvest cannot be allocated to this recipient")
        committed = services.recipient_committed_this_week(recipient["id"])
        if committed + line["grams"] > recipient["weekly_capacity_grams"]:
            raise err("ERR_RECIPIENT_CAPACITY_EXCEEDED",
                      "recipient weekly capacity would be exceeded")
    rec = services.create_record({
        "harvest_log_id": harvest_log_id,
        "volunteer_share_grams": volunteer_share,
        "donatable_grams": donatable,
        "lines": lines,
        "rejection_reason": None,
        "status": "PENDING",
    })
    db.allocations[rec["id"]] = rec
    return ok(services.allocation_view(rec), status=201)


@bp.get("/api/donation-allocations")
def list_allocations():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)

    def recipient_match(alloc):
        raw = request.args.get("recipient_id")
        if raw is None:
            return True
        return any(line["recipient_id"] == raw for line in alloc["lines"])

    items = services.list_view(
        db.allocations.values(),
        {"harvest_log_id": "harvest_log_id", "status": "status"},
        request.args, services.allocation_view,
    )
    items = [a for a in items if recipient_match(a)]
    total = len(items)
    return ok([services.allocation_view(a) for a in items[offset:offset + limit]],
              pagination=(limit, offset, total))


@bp.get("/api/donation-allocations/<allocationId>")
def get_allocation(allocationId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.allocation_view(_get_allocation(allocationId)))


@bp.post("/api/donation-allocations/<allocationId>/transition")
def transition_allocation(allocationId):
    ctx = require_auth()
    require_role(ctx, TRANSITION_ROLES)
    alloc = _get_allocation(allocationId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in ALLOCATION_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(ALLOCATION_TARGETS)}")
    # per-transition actors
    if to_state in {"APPROVED", "REJECTED"} and ctx.role not in OFFICERS:
        raise err_forbidden_role()
    if to_state == "DISTRIBUTED" and ctx.role not in CREATE_ROLES:
        raise err_forbidden_role()
    log = db.harvests.get(alloc["harvest_log_id"])
    # SoD (tier 4): approver must not be the harvest logger (GardenAdmin passes)
    if to_state == "APPROVED" and ctx.role != "GardenAdmin" and log is not None \
            and ctx.user_id == log["logged_by_volunteer_id"]:
        raise err_sod()

    if to_state == "APPROVED":
        if alloc["status"] != "PENDING":
            raise err_state("ALLOCATION")
        if log is None or log["status"] != "VERIFIED":
            raise err("ERR_HARVEST_LOG_NOT_VERIFIED", "harvest log is no longer VERIFIED")
        for line in alloc["lines"]:
            recipient = db.recipients.get(line["recipient_id"])
            if recipient is None or not recipient["active"]:
                raise err("ERR_RECIPIENT_INACTIVE", "recipient is inactive")
            committed = services.recipient_committed_this_week(
                line["recipient_id"], exclude_allocation_id=alloc["id"])
            if committed + line["grams"] > recipient["weekly_capacity_grams"]:
                raise err("ERR_RECIPIENT_CAPACITY_EXCEEDED",
                          "recipient weekly capacity would be exceeded")
        alloc["status"] = "APPROVED"
        services.bump(alloc)

    elif to_state == "REJECTED":
        reason = data.get("rejection_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise err_invalid_request("rejection_reason must be non-empty")
        if alloc["status"] != "PENDING":
            raise err_state("ALLOCATION")
        alloc["status"] = "REJECTED"
        alloc["rejection_reason"] = reason
        services.bump(alloc)

    elif to_state == "DISTRIBUTED":
        if alloc["status"] != "APPROVED":
            raise err_state("ALLOCATION")
        alloc["status"] = "DISTRIBUTED"
        services.bump(alloc)
        # cascade: harvest log VERIFIED -> SPLIT_FINALIZED
        if log is not None and log["status"] == "VERIFIED":
            log["status"] = "SPLIT_FINALIZED"
            services.bump(log)

    return ok(services.allocation_view(alloc))
