"""Reinsurance stop-loss recoveries (PRD 3.7)."""

from flask import Blueprint

import calc
import db
import derive
import middleware
import resolve
import response
import serialize
import validate
from errors import fail

bp = Blueprint("recoveries", __name__)

RECOVERY_STATES = ("DRAFT", "SUBMITTED", "APPROVED", "DENIED", "RECOVERED")
READ_ROLES = ("IpaAdmin", "ClaimsExaminer", "ReinsuranceUnderwriter",
              "PayerRepresentative")

TRANSITION_ROLES = {
    "DRAFT": ("ClaimsExaminer",),
    "SUBMITTED": ("ClaimsExaminer",),
    "APPROVED": ("ReinsuranceUnderwriter",),
    "DENIED": ("ReinsuranceUnderwriter",),
    "RECOVERED": ("IpaAdmin",),
}

APPROVABLE_POOL_STATES = ("ACCUMULATING", "CLOSED_FOR_INCURRAL", "RESERVED")


@bp.post("/ipa/stop-loss-recoveries")
def create_recovery():
    middleware.require("ClaimsExaminer")
    body = validate.body()
    pool_id = validate.req_str(body, "pool_id")
    enrollee_id = validate.req_str(body, "enrollee_id")

    # check 5 — declared input order
    pool = resolve.pool(pool_id)
    enrollee = resolve.enrollee(enrollee_id)

    agreement = db.agreement_of_pool(pool)
    # check 12
    if agreement is None or enrollee["agreement_id"] != agreement["id"]:
        fail("ERR_AGREEMENT_MISMATCH")

    attachment, eligible, excess, recovery_cents = calc.stop_loss_recovery_amounts(
        agreement, pool, enrollee["id"])
    # check 26 — the attachment point must be pierced strictly
    if excess <= 0:
        fail("ERR_STOP_LOSS_NOT_ATTACHED")

    recovery = db.create(
        db.recoveries,
        pool_id=pool["id"],
        enrollee_id=enrollee["id"],
        attachment_cents=attachment,
        eligible_paid_cents=eligible,
        excess_cents=excess,
        recovery_cents=recovery_cents,
        status="DRAFT",
        submitted_by_user_id=None,
        adjudicated_by_user_id=None,
        denial_reason=None,
    )
    return response.ok(serialize.recovery(recovery), 201)


@bp.get("/ipa/stop-loss-recoveries")
def list_recoveries():
    middleware.require(*READ_ROLES)
    pool_id = validate.query_str("pool_id")
    enrollee_id = validate.query_str("enrollee_id")
    status = validate.query_enum("status", RECOVERY_STATES)
    limit, offset = validate.pagination()

    items = db.ordered(db.recoveries.values())
    if pool_id is not None:
        items = [r for r in items if r["pool_id"] == pool_id]
    if enrollee_id is not None:
        items = [r for r in items if r["enrollee_id"] == enrollee_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.recovery(r) for r in window], limit, offset,
                            len(items))


@bp.get("/ipa/stop-loss-recoveries/<recovery_id>")
def read_recovery(recovery_id):
    user_id, role = middleware.require(*READ_ROLES)
    recovery = resolve.recovery(recovery_id)
    middleware.check_ownership(role, user_id,
                              agreement=db.agreement_of_recovery(recovery))
    return response.ok(serialize.recovery(recovery))


@bp.post("/ipa/stop-loss-recoveries/<recovery_id>/state")
def recovery_state(recovery_id):
    user_id, role = middleware.require("ClaimsExaminer", "ReinsuranceUnderwriter",
                                       "IpaAdmin")
    body = validate.body()
    to_state = validate.req_enum(body, "to_state", RECOVERY_STATES)
    if to_state == "DENIED":
        denial_reason = validate.req_str(body, "denial_reason")
    else:
        denial_reason = validate.opt_str(body, "denial_reason")

    recovery = resolve.recovery(recovery_id)
    middleware.require_transition_role(role, TRANSITION_ROLES[to_state])

    pool = db.pools.get(recovery["pool_id"])
    current = recovery["status"]

    if to_state == "SUBMITTED":
        if current != "DRAFT" or recovery["excess_cents"] <= 0:
            fail("ERR_INVALID_STATE_TRANSITION")
        recovery["status"] = "SUBMITTED"
        recovery["submitted_by_user_id"] = user_id
        db.touch(recovery)

    elif to_state == "APPROVED":
        if current != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if pool is None or pool["status"] not in APPROVABLE_POOL_STATES:
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 25 — segregation of duties
        if user_id == recovery["submitted_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")
        recovery["status"] = "APPROVED"
        recovery["adjudicated_by_user_id"] = user_id
        db.touch(recovery)
        derive.sync_pool_ledger(pool, force_touch=True)

    elif to_state == "DENIED":
        if current != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 25
        if user_id == recovery["submitted_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")
        recovery["status"] = "DENIED"
        recovery["adjudicated_by_user_id"] = user_id
        recovery["denial_reason"] = denial_reason
        db.touch(recovery)

    elif to_state == "RECOVERED":
        if current != "APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION")
        recovery["status"] = "RECOVERED"
        db.touch(recovery)

    else:  # pragma: no cover
        fail("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serialize.recovery(recovery))
