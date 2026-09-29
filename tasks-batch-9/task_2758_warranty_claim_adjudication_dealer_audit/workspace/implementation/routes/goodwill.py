"""Goodwill authority for out-of-warranty repairs (PRD 3.5)."""

from decimal import Decimal

from flask import Blueprint

import db
import response
import util
from errors import ApiError
from middleware import (
    ADJUDICATION_MANAGER,
    AUDIT_MANAGER,
    CLAIM_ADJUDICATOR,
    FIELD_AUDITOR,
    WARRANTY_ADMIN,
    auth,
    fetch,
)
from routes.common import apply_filters, str_filter, two_decimals
from services import calc, cascade
from util import dec

bp = Blueprint("goodwill", __name__)

READ_ROLES = (WARRANTY_ADMIN, CLAIM_ADJUDICATOR, ADJUDICATION_MANAGER, FIELD_AUDITOR, AUDIT_MANAGER)


@bp.post("/warranty/claims/<claim_id>/goodwill-authorizations")
def request_goodwill(claim_id):
    actor = auth(CLAIM_ADJUDICATOR)
    claim = fetch(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    data = util.body()
    # ---- body shape ----
    requested_amount_cents = util.get_int(data, "requested_amount_cents")
    if requested_amount_cents <= 0:
        util.bad("Field 'requested_amount_cents' must be strictly positive.")
    policy_adjustment_pct = two_decimals(
        util.get_dec(data, "policy_adjustment_pct", minimum="0.00", maximum="0.50"), "policy_adjustment_pct"
    )
    justification = util.get_str(data, "justification")
    expected_claim_version = util.get_int(data, "expected_claim_version", required=False)
    # ---- version pinning ----
    if expected_claim_version is not None and expected_claim_version != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION", "The claim's version has advanced since it was read.")
    # ---- state ----
    if claim["coverage_type"] != "NONE" or claim["status"] not in ("SUBMITTED", "SUSPENDED"):
        raise ApiError(
            "ERR_GOODWILL_INVALID_STATE",
            "Goodwill may only be requested on a SUBMITTED or SUSPENDED claim whose coverage_type is NONE.",
        )
    # ---- authority limits ----
    vehicle = db.vehicles[claim["vehicle_id"]]
    margin, adjudicator_limit, manager_limit = calc.goodwill_authorization_limit(claim, vehicle)
    if requested_amount_cents > manager_limit:
        raise ApiError(
            "ERR_GOODWILL_LIMIT_EXCEEDED",
            "The requested amount exceeds the manager authority limit of %d cents." % manager_limit,
        )
    status = "PENDING" if requested_amount_cents <= adjudicator_limit else "ESCALATED"
    # ---- supersede any live predecessor ----
    for row in db.ordered(db.goodwill_auths):
        if row["claim_id"] != claim["id"] or row["status"] not in ("PENDING", "ESCALATED"):
            continue
        row["status"] = "WITHDRAWN"
        db.touch(row)
    record = db.new_record(
        db.goodwill_auths,
        claim_id=claim["id"],
        requested_by_user_id=actor.user_id,
        requested_amount_cents=requested_amount_cents,
        policy_adjustment_pct=policy_adjustment_pct,
        justification=justification,
        adjudicator_limit_cents=adjudicator_limit,
        manager_limit_cents=manager_limit,
        out_of_warranty_margin_pct=margin,
        status=status,
        approved_amount_cents=None,
        decided_by_user_id=None,
        denial_reason=None,
    )
    db.touch(claim)
    return response.created(record)


@bp.get("/warranty/goodwill-authorizations/<auth_id>")
def read_goodwill(auth_id):
    auth(*READ_ROLES)
    record = fetch(db.goodwill_auths, auth_id, "ERR_GOODWILL_AUTH_NOT_FOUND")
    return response.ok(record)


@bp.get("/warranty/goodwill-authorizations")
def list_goodwill():
    auth(*READ_ROLES)
    limit, offset = util.pagination()
    rows = db.ordered(db.goodwill_auths)
    rows = apply_filters(rows, [(str_filter("claim_id"), "claim_id"), (str_filter("status"), "status")])
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


@bp.post("/warranty/goodwill-authorizations/<auth_id>/decision")
def decide_goodwill(auth_id):
    actor = auth(CLAIM_ADJUDICATOR, ADJUDICATION_MANAGER)
    record = fetch(db.goodwill_auths, auth_id, "ERR_GOODWILL_AUTH_NOT_FOUND")
    if actor.user_id == record["requested_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The adjudicator who raised this authorization may not decide it.",
        )
    data = util.body()
    action = util.get_enum(data, "action", ("APPROVE", "DENY"))
    approved_amount_cents = None
    denial_reason = None
    if action == "APPROVE":
        approved_amount_cents = util.get_int(data, "approved_amount_cents")
        if approved_amount_cents <= 0:
            util.bad("Field 'approved_amount_cents' must be strictly positive.")
    else:
        denial_reason = util.get_str(data, "denial_reason")
    # ---- state ----
    if record["status"] not in ("PENDING", "ESCALATED"):
        raise ApiError(
            "ERR_GOODWILL_INVALID_STATE",
            "Only a PENDING or ESCALATED authorization may be decided.",
        )
    if record["status"] == "ESCALATED" and actor.role != ADJUDICATION_MANAGER:
        raise ApiError(
            "ERR_UNAUTHORIZED_FOR_ESCALATED_GOODWILL",
            "An ESCALATED authorization may only be decided by an AdjudicationManager.",
        )
    if action == "APPROVE":
        ceiling = (
            record["manager_limit_cents"]
            if actor.role == ADJUDICATION_MANAGER
            else record["adjudicator_limit_cents"]
        )
        if approved_amount_cents > ceiling:
            raise ApiError(
                "ERR_GOODWILL_LIMIT_EXCEEDED",
                "The approved amount exceeds the deciding role's authority limit of %d cents." % ceiling,
            )
        record["approved_amount_cents"] = approved_amount_cents
        record["decided_by_user_id"] = actor.user_id
        record["status"] = "APPROVED"
        db.touch(record)
        # ---- cascade onto the claim ----
        claim = db.claims[record["claim_id"]]
        claim["coverage_type"] = "GOODWILL"
        cascade.resolve_open_edits(claim, only_code="NO_COVERAGE")
        if cascade.recount_suspend_edits(claim) == 0 and claim["status"] == "SUSPENDED":
            claim["status"] = "SUBMITTED"
        db.touch(claim)
    else:
        record["denial_reason"] = denial_reason
        record["decided_by_user_id"] = actor.user_id
        record["status"] = "DENIED"
        db.touch(record)
    return response.ok(record)
