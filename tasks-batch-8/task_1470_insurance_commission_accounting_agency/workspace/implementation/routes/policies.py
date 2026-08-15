"""Policy endpoints: intake (with auto disclosure), bind, voluntary cancel."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import (
    BILLING_TYPES,
    bind_policy,
    cancellation_cascade,
    find_covering_schedule,
    new_resource,
    rate_amount,
    ser_policy,
)
from util import (
    apply_filters,
    as_date_str,
    as_enum,
    as_pos_int,
    as_str,
    get_body,
    req,
    respond_list,
)

bp = Blueprint("policies", __name__)


@bp.post("/agency/policies")
def create_policy():
    auth(ADMIN_ACCT)
    data = get_body()
    # Priority 3: body FK references, in the order listed by PRD 2.9.
    product_id = data.get("product_id")
    if isinstance(product_id, str) and product_id not in DB["products"]:
        raise ApiError("ERR_NOT_FOUND", 404, "product_id does not reference an existing product")
    producer_id = data.get("producer_id")
    if isinstance(producer_id, str) and producer_id not in DB["producers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "producer_id does not reference an existing producer")
    # Priority 8: uniqueness.
    pn = data.get("policy_number")
    if isinstance(pn, str) and any(
        p["policy_number"] == pn for p in DB["policies"].values()
    ):
        raise ApiError("ERR_POLICY_NUMBER_EXISTS", 409, "policy_number already in use")
    # Priority 10: shape.
    policy_number = as_str(req(data, "policy_number"), "policy_number")
    product_id = as_str(req(data, "product_id"), "product_id")
    producer_id = as_str(req(data, "producer_id"), "producer_id")
    insured_name = as_str(req(data, "insured_name"), "insured_name")
    billing_type = as_enum(req(data, "billing_type"), "billing_type", BILLING_TYPES)
    premium = as_pos_int(req(data, "premium_annual_cents"), "premium_annual_cents")
    effective_date = as_date_str(req(data, "effective_date"), "effective_date")
    policy = new_resource({
        "policy_number": policy_number,
        "product_id": product_id,
        "producer_id": producer_id,
        "insured_name": insured_name,
        "billing_type": billing_type,
        "premium_annual_cents": premium,
        "effective_date": effective_date,
        "status": "QUOTED",
        "cancel_effective_date": None,
        "cancelled_at": None,
    })
    DB["policies"][policy["id"]] = policy
    # Auto-generate the ProducerDisclosure (GENERATED). projected_comp_cents is
    # the full first-year BASE commission from the covering ACTIVE schedule;
    # 0 when no such schedule exists yet.
    producer = DB["producers"][producer_id]
    projected = 0
    schedule = find_covering_schedule(product_id, producer["tier"], effective_date)
    if schedule is not None:
        projected = rate_amount(premium, schedule["commission_rate_bps"])
    disclosure = new_resource({
        "policy_id": policy["id"],
        "producer_id": producer_id,
        "projected_comp_cents": projected,
        "status": "GENERATED",
        "disclosed_at": None,
        "acknowledged_at": None,
    })
    DB["disclosures"][disclosure["id"]] = disclosure
    return ok(ser_policy(policy), 201)


@bp.get("/agency/policies")
def list_policies():
    auth(ALL_ROLES)
    items = apply_filters(
        DB["policies"].values(),
        {
            "producer_id": "producer_id",
            "product_id": "product_id",
            "status": "status",
            "billing_type": "billing_type",
        },
    )
    return respond_list(items, ser_policy)


@bp.get("/agency/policies/<policyId>")
def get_policy(policyId):
    auth(ALL_ROLES)
    p = DB["policies"].get(policyId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Policy not found")
    return ok(ser_policy(p))


@bp.post("/agency/policies/<policyId>/bind")
def bind(policyId):
    auth(ADMIN_ACCT)
    policy = DB["policies"].get(policyId)
    if policy is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Policy not found")
    # Priority 4: state admissibility.
    if policy["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Policy is not QUOTED")
    # Priority 5: compliance gate — disclosure must have left GENERATED.
    disclosure = next(
        (d for d in DB["disclosures"].values() if d["policy_id"] == policy["id"]), None
    )
    if disclosure is None or disclosure["status"] not in ("DELIVERED", "ACKNOWLEDGED"):
        raise ApiError(
            "ERR_DISCLOSURE_REQUIRED", 409, "ProducerDisclosure must be DELIVERED or ACKNOWLEDGED"
        )
    # Priority 6: temporal window rule.
    producer = DB["producers"][policy["producer_id"]]
    schedule = find_covering_schedule(
        policy["product_id"], producer["tier"], policy["effective_date"]
    )
    if schedule is None:
        raise ApiError(
            "ERR_NO_EFFECTIVE_SCHEDULE",
            409,
            "No ACTIVE schedule covers the policy effective_date",
        )
    # Priority 7: cross-entity state.
    if producer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", 409, "Writing producer is not ACTIVE")
    bind_policy(policy, producer, schedule)
    return ok(ser_policy(policy))


@bp.post("/agency/policies/<policyId>/cancel")
def cancel(policyId):
    auth(ADMIN_ACCT)
    policy = DB["policies"].get(policyId)
    if policy is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Policy not found")
    # Priority 4: state admissibility.
    if policy["status"] not in ("ACTIVE", "GRACE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Policy is not ACTIVE or GRACE")
    data = get_body()
    # Priority 10: shape (incl. cancel_effective_date not before effective_date).
    ced = as_date_str(req(data, "cancel_effective_date"), "cancel_effective_date")
    if ced < policy["effective_date"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "cancel_effective_date must not be earlier than effective_date",
        )
    cancellation_cascade(policy, ced, "CANCELLATION_UNEARNED", "CANCELLED_VOLUNTARY")
    return ok(ser_policy(policy))
