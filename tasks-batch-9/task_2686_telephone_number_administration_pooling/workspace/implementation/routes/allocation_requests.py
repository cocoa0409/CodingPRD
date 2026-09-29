"""Allocation requests: filing, review, entitlement and the pool draw (PRD 3.4 / 3.5)."""

from flask import Blueprint

from db import base_record, by_created, days, db, now, r2, touch
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    body,
    check_action_role,
    opt_int,
    opt_str,
    req_enum,
    req_id,
    req_int,
    req_str,
    require_roles,
)
from response import object_response, paginate
from routes.common import field, filter_rows
from services import constants as C
from services import calc, core, serialize

bp = Blueprint("allocation_requests", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER)

REVIEW_ACTION_ROLES = {
    "APPROVE": (ROLE_APPROVER,),
    "REQUEST_INFO": (ROLE_ADMIN,),
    "DENY": (ROLE_ADMIN,),
    "WITHDRAW": (ROLE_CARRIER,),
}


def _snapshots(carrier, rate_center, request_type):
    filing = core.effective_filing(carrier["id"], rate_center["id"])
    if filing is None:
        utilization = None
    else:
        utilization = r2(core.effective_utilization(carrier["id"], rate_center["id"]))
    months = r2(
        calc.snapshot_months_to_exhaust(carrier["id"], rate_center, request_type)
    )
    return utilization, months


@bp.route("/numbering/allocation-requests", methods=["POST"])
def file_request():
    actor = require_roles(ROLE_CARRIER)
    payload = body()
    carrier_id = req_id(payload, "carrier_id")
    rate_center_id = req_id(payload, "rate_center_id")
    request_type = req_enum(payload, "request_type", C.REQUEST_TYPES)
    requested = req_int(payload, "requested_block_count", 1, 10)
    if request_type == "SAFETY_VALVE":
        justification = req_str(payload, "justification", 1, 500)
    else:
        justification = opt_str(payload, "justification", 1, 500)
    expected_version = req_int(payload, "expected_rate_center_version", 0)

    carrier = core.get_carrier(carrier_id)
    rate_center = core.get_rate_center(rate_center_id)

    if actor.user_id != carrier["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "a carrier may only file for itself")

    if expected_version != rate_center["version"]:
        fail("ERR_STALE_RATE_CENTER_VERSION", "expected_rate_center_version is stale")

    if core.eligibility_status(carrier) not in ("ELIGIBLE", "PROBATION"):
        fail("ERR_CARRIER_NOT_ELIGIBLE", "the carrier is not eligible")
    if core.license_expired(carrier):
        fail("ERR_LICENSE_EXPIRED", "the carrier licence has expired")

    npa = core.get_npa(rate_center["npa_id"])
    if rate_center["state_code"] != npa["state_code"]:
        fail("ERR_JURISDICTION_MISMATCH", "the rate center is outside its area code")
    if request_type == "INITIAL" and rate_center["state_code"] != carrier["home_state_code"]:
        fail("ERR_JURISDICTION_MISMATCH", "an initial request must be in the home state")

    if request_type == "INITIAL" and not core.accepts_initial_requests(rate_center):
        fail(
            "ERR_RATE_CENTER_NOT_ACCEPTING_INITIAL",
            "the rate center is closed to initial requests",
        )

    if request_type in ("GROWTH", "POOL_REPLENISH", "SAFETY_VALVE"):
        if core.effective_filing(carrier["id"], rate_center["id"]) is None:
            fail("ERR_UTILIZATION_FILING_REQUIRED", "an effective filing is required")

    if request_type == "SAFETY_VALVE":
        if (
            carrier["safety_valve_grant_count"] >= C.SAFETY_VALVE_MAX_GRANTS_PER_CARRIER
            or requested > C.SAFETY_VALVE_MAX_BLOCKS
        ):
            fail("ERR_SAFETY_VALVE_LIMIT_EXCEEDED", "the safety-valve ceiling is reached")

    utilization, months = _snapshots(carrier, rate_center, request_type)

    record = base_record(
        carrier_id=carrier["id"],
        rate_center_id=rate_center["id"],
        request_type=request_type,
        requested_block_count=requested,
        justification=justification,
        status="PENDING_REVIEW",
        info_request_count=0,
        utilization_pct_at_submission=utilization,
        months_to_exhaust_at_submission=months,
        granted_block_count=0,
        assigned_block_ids=[],
        reviewer_user_id=None,
        approver_user_id=None,
        decided_at=None,
        denial_reason=None,
        superseded_by_request_id=None,
    )
    db.allocation_requests[record["id"]] = record

    open_rows = [
        r
        for r in db.allocation_requests.values()
        if r["carrier_id"] == carrier["id"]
        and r["rate_center_id"] == rate_center["id"]
        and r["id"] != record["id"]
        and r["status"] in ("PENDING_REVIEW", "INFO_REQUESTED")
    ]
    for older in by_created(open_rows):
        older["status"] = "SUPERSEDED"
        older["superseded_by_request_id"] = record["id"]
        older["decided_at"] = now()
        touch(older)
        rate_center["pending_request_count"] = max(
            0, rate_center["pending_request_count"] - 1
        )

    rate_center["pending_request_count"] += 1
    touch(rate_center)

    return object_response(serialize.allocation_request(record), 201)


@bp.route("/numbering/allocation-requests", methods=["GET"])
def list_requests():
    require_roles(*READERS)
    rows = by_created(db.allocation_requests.values())
    rows = filter_rows(
        rows,
        [
            ("carrier_id", field("carrier_id")),
            ("rate_center_id", field("rate_center_id")),
            ("request_type", field("request_type")),
            ("status", field("status")),
            ("superseded_by_request_id", field("superseded_by_request_id")),
        ],
    )
    return paginate(rows, serialize.allocation_request)


@bp.route("/numbering/allocation-requests/<request_id>", methods=["GET"])
def get_request(request_id):
    require_roles(*READERS)
    return object_response(serialize.allocation_request(core.get_request(request_id)))


@bp.route("/numbering/allocation-requests/<request_id>/reviews", methods=["POST"])
def review_request(request_id):
    actor = require_roles(ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER)
    payload = body()
    action = req_enum(payload, "action", C.REVIEW_ACTIONS)
    if action == "REQUEST_INFO":
        req_str(payload, "info_note", 1, 1000)
    else:
        opt_str(payload, "info_note", 1, 1000)
    granted = opt_int(payload, "granted_block_count", 0, None)
    opt_str(payload, "denial_note", 1, 1000)

    request_row = core.get_request(request_id)

    check_action_role(actor, action, REVIEW_ACTION_ROLES)

    if action == "WITHDRAW" and actor.user_id != request_row["carrier_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "only the filing carrier may withdraw")

    if request_row["status"] in C.REQUEST_TERMINAL:
        fail("ERR_TERMINAL_STATE", "the request is already decided")

    status = request_row["status"]
    rate_center = core.get_rate_center(request_row["rate_center_id"])
    carrier = core.get_carrier(request_row["carrier_id"])

    if action == "REQUEST_INFO":
        if status != "PENDING_REVIEW":
            fail("ERR_INVALID_STATE_TRANSITION", "REQUEST_INFO is not available")
        if request_row["info_request_count"] >= C.INFO_REQUEST_MAX_CYCLES:
            fail("ERR_INFO_CYCLE_LIMIT_REACHED", "the information cycle ceiling is reached")
        request_row["status"] = "INFO_REQUESTED"
        request_row["info_request_count"] += 1
        if request_row["reviewer_user_id"] is None:
            request_row["reviewer_user_id"] = actor.user_id
        touch(request_row)
    elif action == "WITHDRAW":
        if status not in ("PENDING_REVIEW", "INFO_REQUESTED"):
            fail("ERR_INVALID_STATE_TRANSITION", "WITHDRAW is not available")
        request_row["status"] = "WITHDRAWN"
        request_row["decided_at"] = now()
        touch(request_row)
        rate_center["pending_request_count"] = max(
            0, rate_center["pending_request_count"] - 1
        )
        touch(rate_center)
    elif action == "DENY":
        if status not in ("PENDING_REVIEW", "INFO_REQUESTED"):
            fail("ERR_INVALID_STATE_TRANSITION", "DENY is not available")
        if (
            request_row["reviewer_user_id"] is not None
            and request_row["reviewer_user_id"] == actor.user_id
        ):
            fail("ERR_SEGREGATION_OF_DUTIES", "the reviewer may not also deny")
        request_row["status"] = "DENIED"
        request_row["denial_reason"] = "REVIEWER_DENIED"
        if request_row["reviewer_user_id"] is None:
            request_row["reviewer_user_id"] = actor.user_id
        request_row["decided_at"] = now()
        touch(request_row)
        rate_center["pending_request_count"] = max(
            0, rate_center["pending_request_count"] - 1
        )
        touch(rate_center)
    else:
        _approve(actor, request_row, carrier, rate_center, granted)

    return object_response(serialize.allocation_request(request_row))


def _approve(actor, request_row, carrier, rate_center, granted):
    if request_row["status"] != "PENDING_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION", "APPROVE is only available from PENDING_REVIEW")

    if (
        request_row["reviewer_user_id"] is not None
        and request_row["reviewer_user_id"] == actor.user_id
    ):
        fail("ERR_SEGREGATION_OF_DUTIES", "the reviewer may not also approve")

    eligibility = core.eligibility_status(carrier)
    if eligibility in ("INELIGIBLE", "SUSPENDED"):
        fail("ERR_CARRIER_NOT_ELIGIBLE", "the carrier is not eligible")
    if core.license_expired(carrier):
        fail("ERR_LICENSE_EXPIRED", "the carrier licence has expired")
    if eligibility == "PROBATION":
        fail("ERR_CARRIER_ON_PROBATION", "the carrier is on probation")

    request_type = request_row["request_type"]
    sizing = calc.growth_grant_size(request_row, rate_center)
    candidates = sizing["candidates"]

    if not candidates and calc.pool_precandidates(rate_center):
        fail("ERR_BLOCK_NOT_POOLING_ELIGIBLE", "every pooled block is contaminated")

    if request_type in ("GROWTH", "POOL_REPLENISH"):
        if calc.utilization_tier_cap(sizing["utilization"]) == 0:
            fail("ERR_UTILIZATION_THRESHOLD_NOT_MET", "utilization is below 60.00")

    if request_type != "SAFETY_VALVE":
        horizon = calc.gate_months_to_exhaust(carrier["id"], rate_center)
        if horizon > C.MONTHS_TO_EXHAUST_MAX:
            fail("ERR_EXHAUST_HORIZON_TOO_LONG", "the exhaust horizon exceeds 6 months")

    if request_type == "SAFETY_VALVE":
        if (
            carrier["safety_valve_grant_count"] >= C.SAFETY_VALVE_MAX_GRANTS_PER_CARRIER
            or request_row["requested_block_count"] > C.SAFETY_VALVE_MAX_BLOCKS
        ):
            fail("ERR_SAFETY_VALVE_LIMIT_EXCEEDED", "the safety-valve ceiling is reached")

    if not candidates:
        fail("ERR_POOL_INSUFFICIENT_BLOCKS", "the pool holds no assignable block")

    entitlement = sizing["entitlement"]
    if granted is not None and granted > entitlement:
        fail("ERR_GRANT_EXCEEDS_ENTITLEMENT", "the grant exceeds the entitlement")
    grant = granted if granted is not None else entitlement

    drawn = candidates[:grant]
    instant = now()

    request_row["status"] = "APPROVED"
    request_row["granted_block_count"] = len(drawn)
    request_row["assigned_block_ids"] = [b["id"] for b in drawn]
    request_row["approver_user_id"] = actor.user_id
    request_row["decided_at"] = instant
    touch(request_row)

    rate_center["pending_request_count"] = max(
        0, rate_center["pending_request_count"] - 1
    )

    for block in drawn:
        block["allocation_status"] = "RESERVED"
        block["holder_carrier_id"] = carrier["id"]
        block["assigned_at"] = instant
        block["activation_due_at"] = instant + days(C.ACTIVATION_WINDOW_DAYS)
        block["activated_at"] = None
        touch(block)

    if request_row["request_type"] == "SAFETY_VALVE":
        carrier["safety_valve_grant_count"] += 1

    touch(rate_center)
    touch(carrier)

    npa = db.npas.get(rate_center["npa_id"])
    if npa is not None:
        if not core.recompute_npa_posture(npa):
            touch(npa)


@bp.route("/numbering/allocation-requests/<request_id>/resubmissions", methods=["POST"])
def resubmit_request(request_id):
    actor = require_roles(ROLE_CARRIER)
    payload = body()
    revised = req_int(payload, "revised_requested_block_count", 1, 10)
    response_note = req_str(payload, "response_note", 1, 500)

    request_row = core.get_request(request_id)

    if actor.user_id != request_row["carrier_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "only the filing carrier may resubmit")

    if request_row["status"] in C.REQUEST_TERMINAL:
        fail("ERR_TERMINAL_STATE", "the request is already decided")
    if request_row["status"] != "INFO_REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION", "the request is not awaiting information")

    carrier = core.get_carrier(request_row["carrier_id"])
    rate_center = core.get_rate_center(request_row["rate_center_id"])

    request_row["requested_block_count"] = revised
    request_row["justification"] = response_note
    utilization, months = _snapshots(carrier, rate_center, request_row["request_type"])
    request_row["utilization_pct_at_submission"] = utilization
    request_row["months_to_exhaust_at_submission"] = months
    request_row["status"] = "PENDING_REVIEW"
    touch(request_row)

    return object_response(serialize.allocation_request(request_row))
