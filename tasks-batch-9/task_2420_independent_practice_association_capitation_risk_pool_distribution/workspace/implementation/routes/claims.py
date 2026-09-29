"""Delegated adjudication of downstream claims (PRD 3.6)."""

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

bp = Blueprint("claims", __name__)

POOL_TYPES = ("PROFESSIONAL", "INSTITUTIONAL")
CLAIM_STATES = ("RECEIVED", "ADJUDICATED_APPROVED", "ADJUDICATED_DENIED", "PAID",
                "VOIDED")
READ_ROLES = ("IpaAdmin", "NetworkManager", "ClaimsExaminer", "ReinsuranceUnderwriter",
              "PayerRepresentative", "PhysicianUser")

TRANSITION_ROLES = {
    "ADJUDICATED_APPROVED": ("ClaimsExaminer",),
    "ADJUDICATED_DENIED": ("ClaimsExaminer",),
    "PAID": ("ClaimsExaminer",),
    "VOIDED": ("ClaimsExaminer",),
    "RECEIVED": ("NetworkManager", "PhysicianUser"),
}

VOIDABLE_POOL_STATES = ("ACCUMULATING", "CLOSED_FOR_INCURRAL")


@bp.post("/ipa/downstream-claims")
def create_claim():
    middleware.require("ClaimsExaminer", "IpaAdmin")
    body = validate.body()
    agreement_id = validate.req_str(body, "agreement_id")
    enrollee_id = validate.req_str(body, "enrollee_id")
    attributed_physician_id = validate.req_str(body, "attributed_physician_id")
    pool_type = validate.req_enum(body, "pool_type", POOL_TYPES)
    downstream_provider_name = validate.req_str(body, "downstream_provider_name")
    billed_cents = validate.req_int(body, "billed_cents", minimum=0)
    service_date = validate.req_instant(body, "service_date")

    # check 5 — declared input order
    agreement = resolve.agreement(agreement_id)
    enrollee = resolve.enrollee(enrollee_id)
    physician = resolve.physician(attributed_physician_id)

    # check 8
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")
    # check 12
    if (enrollee["agreement_id"] != agreement["id"]
            or physician["agreement_id"] != agreement["id"]):
        fail("ERR_AGREEMENT_MISMATCH")
    # check 16 — the incurral period must cover the service date
    pool = derive.pool_for_service_date(agreement["id"], pool_type, service_date)
    if pool is None:
        fail("ERR_NO_POOL_FOR_SERVICE_DATE")

    claim = db.create(
        db.claims,
        agreement_id=agreement["id"],
        enrollee_id=enrollee["id"],
        attributed_physician_id=physician["id"],
        pool_id=pool["id"],
        pool_type=pool_type,
        downstream_provider_name=downstream_provider_name,
        billed_cents=billed_cents,
        service_date=service_date,
        received_date=db.clock(),
        allowed_cents=None,
        paid_cents=None,
        status="RECEIVED",
        denial_reason=None,
        appeal_count=0,
    )
    return response.ok(serialize.claim(claim), 201)


@bp.get("/ipa/downstream-claims")
def list_claims():
    middleware.require(*READ_ROLES)
    agreement_id = validate.query_str("agreement_id")
    enrollee_id = validate.query_str("enrollee_id")
    attributed_physician_id = validate.query_str("attributed_physician_id")
    pool_id = validate.query_str("pool_id")
    status = validate.query_enum("status", CLAIM_STATES)
    limit, offset = validate.pagination()

    items = db.ordered(db.claims.values())
    if agreement_id is not None:
        items = [c for c in items if c["agreement_id"] == agreement_id]
    if enrollee_id is not None:
        items = [c for c in items if c["enrollee_id"] == enrollee_id]
    if attributed_physician_id is not None:
        items = [c for c in items
                 if c["attributed_physician_id"] == attributed_physician_id]
    if pool_id is not None:
        items = [c for c in items if c["pool_id"] == pool_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.claim(c) for c in window], limit, offset,
                            len(items))


@bp.get("/ipa/downstream-claims/<claim_id>")
def read_claim(claim_id):
    user_id, role = middleware.require(*READ_ROLES)
    claim = resolve.claim(claim_id)
    middleware.check_ownership(role, user_id,
                              physician_ids=[claim["attributed_physician_id"]],
                              agreement=db.agreement_of_claim(claim))
    return response.ok(serialize.claim(claim))


@bp.post("/ipa/downstream-claims/<claim_id>/state")
def claim_state(claim_id):
    user_id, role = middleware.require("ClaimsExaminer", "NetworkManager",
                                       "PhysicianUser")
    body = validate.body()
    to_state = validate.req_enum(body, "to_state", CLAIM_STATES)
    if to_state == "ADJUDICATED_APPROVED":
        allowed_cents = validate.req_int(body, "allowed_cents", minimum=0)
    else:
        allowed_cents = validate.opt_int(body, "allowed_cents", minimum=0)
    if to_state == "ADJUDICATED_DENIED":
        denial_reason = validate.req_str(body, "denial_reason")
    else:
        denial_reason = validate.opt_str(body, "denial_reason")

    claim = resolve.claim(claim_id)
    middleware.require_transition_role(role, TRANSITION_ROLES[to_state])
    middleware.check_ownership(role, user_id,
                              physician_ids=[claim["attributed_physician_id"]],
                              agreement=db.agreement_of_claim(claim))

    pool = db.pools.get(claim["pool_id"])
    agreement = db.agreement_of_claim(claim)
    enrollee = db.enrollees.get(claim["enrollee_id"])
    current = claim["status"]

    if to_state == "ADJUDICATED_APPROVED":
        if current != "RECEIVED":
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 28
        if allowed_cents > claim["billed_cents"]:
            fail("ERR_ALLOWED_EXCEEDS_BILLED")
        claim["status"] = "ADJUDICATED_APPROVED"
        claim["allowed_cents"] = allowed_cents
        claim["denial_reason"] = None
        db.touch(claim)

    elif to_state == "ADJUDICATED_DENIED":
        if current != "RECEIVED":
            fail("ERR_INVALID_STATE_TRANSITION")
        claim["status"] = "ADJUDICATED_DENIED"
        claim["denial_reason"] = denial_reason
        claim["allowed_cents"] = 0
        db.touch(claim)

    elif to_state == "RECEIVED":
        if current != "ADJUDICATED_DENIED" or claim["appeal_count"] >= calc.APPEAL_LIMIT:
            fail("ERR_INVALID_STATE_TRANSITION")
        claim["status"] = "RECEIVED"
        claim["appeal_count"] += 1
        claim["denial_reason"] = None
        claim["allowed_cents"] = None
        db.touch(claim)

    elif to_state == "PAID":
        if current != "ADJUDICATED_APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if pool is None or pool["status"] == "SETTLED":
            fail("ERR_INVALID_STATE_TRANSITION")
        # L1
        claim["status"] = "PAID"
        claim["paid_cents"] = claim["allowed_cents"]
        db.touch(claim)
        # L2 / L3 / L4
        derive.sync_pool_ledger(pool, force_touch=True)
        if enrollee is not None:
            derive.sync_enrollee_paid_claims(enrollee, force_touch=True)
        if agreement is not None:
            derive.sync_capitation_posture(agreement)

    elif to_state == "VOIDED":
        if current == "PAID":
            if pool is None or pool["status"] not in VOIDABLE_POOL_STATES:
                fail("ERR_INVALID_STATE_TRANSITION")
            claim["status"] = "VOIDED"
            claim["paid_cents"] = None
            db.touch(claim)
            derive.sync_pool_ledger(pool, force_touch=True)
            if enrollee is not None:
                derive.sync_enrollee_paid_claims(enrollee, force_touch=True)
            if agreement is not None:
                derive.sync_capitation_posture(agreement)
        elif current == "ADJUDICATED_DENIED":
            if claim["appeal_count"] != calc.APPEAL_LIMIT:
                fail("ERR_INVALID_STATE_TRANSITION")
            claim["status"] = "VOIDED"
            db.touch(claim)
        else:
            fail("ERR_INVALID_STATE_TRANSITION")

    else:  # pragma: no cover
        fail("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serialize.claim(claim))
