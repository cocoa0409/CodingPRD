"""Insurance: reserving benefit, adjudicating it, and paying out of network (PRD 3.8)."""
from flask import Blueprint, request

import calc
import schema
import services
import store
from auth import authenticate
from envelope import array_response, object_response, paginate
from errors import err
from serializers import dump, dump_all

bp = Blueprint("insurance", __name__)

VOIDABLE = ("SUBMITTED", "ADJUDICATED_APPROVED", "ADJUDICATED_DENIED")


@bp.post("/insurance-claims")
def create_claim():
    authenticate("BenefitsAdmin")
    b = schema.body()
    order_id = schema.string_field(b, "order_id")
    service_lines = schema.service_lines_field(b, "service_lines")
    expected_version = schema.int_field(b, "expected_order_version")

    order = schema.get_order(order_id)

    # Priority 7 -- OCC on the parent order's version.
    if expected_version != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION")

    customer = store.customers.get(order["customer_id"])
    policy_id = customer.get("insurance_policy_id") if customer else None
    policy = store.policies.get(policy_id) if policy_id else None

    # An explicit filing supersedes: the existing non-VOID claim goes VOID and
    # credits its policy back by exactly what it reserved.
    existing_id = order["active_claim_id"]
    if existing_id:
        existing = store.claims.get(existing_id)
        if existing is not None and existing["status"] != "VOID":
            services.void_claim(existing)

    claim = store.new_record(
        order_id=order_id,
        policy_id=policy_id,
        service_lines=service_lines,
        status="SUBMITTED",
        reserved_frame_benefit_cents=order["benefit_frame_cents"],
        allowed_amount_cents=None,
        approved_amount_cents=0,
        reimbursed_amount_cents=0,
        denial_reason=None,
    )
    store.claims[claim["id"]] = claim

    services.policy_move(policy, -claim["reserved_frame_benefit_cents"])

    order["active_claim_id"] = claim["id"]
    store.touch(order)

    return object_response(dump("claim", claim), 201)


@bp.get("/insurance-claims/<claim_id>")
def read_claim(claim_id):
    authenticate("BenefitsAdmin", "PlatformAdmin", "Customer")
    rec = schema.get_claim(claim_id)
    return object_response(dump("claim", rec))


@bp.get("/insurance-claims")
def list_claims():
    authenticate("BenefitsAdmin", "PlatformAdmin")
    items = store.ordered(store.claims)
    for field in ("order_id", "policy_id", "status"):
        value = request.args.get(field)
        if value:
            items = [c for c in items if c[field] == value]
    window, meta = paginate(items)
    return array_response(dump_all("claim", window), meta)


@bp.post("/insurance-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    authenticate("BenefitsAdmin")
    b = schema.body()
    decision = schema.enum_field(b, "decision", ("APPROVED", "DENIED"))
    allowed_amount = schema.int_field(
        b, "allowed_amount_cents", required=(decision == "APPROVED"), default=None, minimum=0
    )
    denial_reason = schema.string_field(
        b, "denial_reason", required=(decision == "DENIED"), default=None
    )

    claim = schema.get_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE")

    if decision == "DENIED":
        # The reserved frame benefit stays reserved -- only a VOID releases it.
        claim["status"] = "ADJUDICATED_DENIED"
        claim["denial_reason"] = denial_reason
        store.touch(claim)
        return object_response(dump("claim", claim))

    claim["status"] = "ADJUDICATED_APPROVED"
    claim["allowed_amount_cents"] = allowed_amount

    policy = store.policies.get(claim["policy_id"])
    order = store.orders.get(claim["order_id"])

    if policy is not None and policy["network"] == "IN_NETWORK" and order is not None:
        final_benefit, final_due = calc.final_quote(order, allowed_amount)
        claim["approved_amount_cents"] = final_benefit
        order["benefit_applied_cents"] = final_benefit
        order["customer_due_cents"] = final_due
        order["quote_variant"] = "FINAL"
        store.touch(order)
    else:
        # OUT_OF_NETWORK (or a policy-less order): no re-quote at all.
        claim["approved_amount_cents"] = 0

    store.touch(claim)
    return object_response(dump("claim", claim))


@bp.post("/insurance-claims/<claim_id>/reimburse")
def reimburse_claim(claim_id):
    authenticate("BenefitsAdmin")
    claim = schema.get_claim(claim_id)

    if claim["status"] != "ADJUDICATED_APPROVED":
        raise err("ERR_INVALID_STATE")

    policy = store.policies.get(claim["policy_id"])
    if policy is None or policy["network"] != "OUT_OF_NETWORK":
        raise err("ERR_INVALID_STATE")

    # Priority 30 -- annual reimbursement headroom.
    if policy["annual_max_cents"] - policy["annual_reimbursed_cents"] <= 0:
        raise err("ERR_ANNUAL_MAX_EXCEEDED")

    paid = calc.oon_reimbursement(claim, policy)
    claim["reimbursed_amount_cents"] = paid
    claim["status"] = "REIMBURSED"
    store.touch(claim)

    if paid != 0:
        policy["annual_reimbursed_cents"] += paid
        store.touch(policy)

    return object_response(dump("claim", claim))
