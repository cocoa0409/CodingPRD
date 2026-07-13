import uuid

from flask import Blueprint, request

from db import by_seq, db, new_row, touch
from errors import ApiError
from middleware import (
    auth,
    body,
    must_exist,
    must_exist_fk,
    req_enum,
    req_ssn_last4,
    req_str,
    require_subscriber_owner,
)
from response import ok, ok_list, paginate, read_pagination
from serializers import ser, ser_many
from services import calc

bp = Blueprint("subscribers", __name__)

BUREAU_ORDER = {"TRI": ["EQUIFAX", "EXPERIAN", "TRANSUNION"], "SINGLE": ["EQUIFAX"]}
RELATIONSHIPS = ("ADULT", "CHILD")
WALLET_ITEM_TYPES = (
    "CREDIT_CARD",
    "DEBIT_CARD",
    "DRIVERS_LICENSE",
    "PASSPORT",
    "SSN_CARD",
    "INSURANCE_CARD",
)


# ---------------------------------------------------------------- enrollment
@bp.post("/idp/subscribers")
def enroll():
    auth("Anonymous", "PlatformAdmin")
    data = body()

    plan = must_exist_fk("plans", data, "plan_id")

    email = req_str(data, "email")
    full_name = req_str(data, "full_name")
    date_of_birth = req_str(data, "date_of_birth")
    ssn_last4 = req_ssn_last4(data)
    if plan is None:
        req_str(data, "plan_id")  # raises ERR_INVALID_REQUEST when absent/ill-formed
    if any(s["email"] == email for s in db.subscribers.values()):
        raise ApiError("ERR_INVALID_REQUEST", "email is already registered.")

    subscriber = new_row(
        email=email,
        full_name=full_name,
        date_of_birth=date_of_birth,
        ssn_last4=ssn_last4,
        plan_id=plan["id"],
        enrollment_status="PENDING_VERIFICATION",
        monitoring_status="NOT_ENROLLED",
        verification_token=uuid.uuid4().hex,
        composite_credit_score=None,
        baseline_composite_credit_score=None,
        risk_score=None,
        underwriting_risk_score=None,
        insurance_remaining_cents=0,
        insurance_status="AVAILABLE",
        suspension_reason=None,
    )
    db.subscribers[subscriber["id"]] = subscriber
    return ok(ser(subscriber), 201)


@bp.get("/idp/subscribers")
def list_subscribers():
    auth("PlatformAdmin", "ClaimsAdjuster")
    limit, offset = read_pagination()

    rows = list(db.subscribers.values())
    plan_id = request.args.get("plan_id")
    if plan_id:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    enrollment_status = request.args.get("enrollment_status")
    if enrollment_status:
        rows = [r for r in rows if r["enrollment_status"] == enrollment_status]

    rows = by_seq(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_many(page), limit, offset, total)


@bp.get("/idp/subscribers/<subscriber_id>")
def read_subscriber(subscriber_id):
    role, user_id = auth(
        "Subscriber", "PlatformAdmin", "ClaimsAdjuster", "RestorationSpecialist"
    )
    subscriber = must_exist("subscribers", subscriber_id)
    require_subscriber_owner(role, user_id, subscriber["id"])
    return ok(ser(subscriber))


@bp.post("/idp/subscribers/<subscriber_id>/verify")
def verify(subscriber_id):
    role, user_id = auth("Anonymous", "Subscriber")
    subscriber = must_exist("subscribers", subscriber_id)
    require_subscriber_owner(role, user_id, subscriber["id"])

    data = body()
    token = req_str(data, "verification_token")

    # Priority 6 (verification token) precedes priority 8 (state legality).
    if token != subscriber["verification_token"]:
        raise ApiError("ERR_INVALID_VERIFICATION_TOKEN", "verification_token does not match.")
    if subscriber["enrollment_status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Subscriber is not PENDING_VERIFICATION.")

    plan = db.plans[subscriber["plan_id"]]

    subscriber["enrollment_status"] = "ACTIVE"
    subscriber["monitoring_status"] = "PENDING_DATA"

    for bureau in BUREAU_ORDER[plan["bureau_scope"]]:
        profile = new_row(
            subscriber_id=subscriber["id"],
            bureau=bureau,
            credit_score=None,
            score_pulled_at=None,
            freeze_status="UNFROZEN",
        )
        db.bureau_profiles[profile["id"]] = profile

    subscriber["insurance_remaining_cents"] = plan["insurance_limit_cents"]
    subscriber["insurance_status"] = "AVAILABLE"

    calc.recompute_risk(subscriber)
    touch(subscriber)
    return ok(ser(subscriber))


@bp.post("/idp/subscribers/<subscriber_id>/suspend")
def suspend(subscriber_id):
    auth("PlatformAdmin")
    subscriber = must_exist("subscribers", subscriber_id)
    data = body()
    reason = req_str(data, "reason")

    if subscriber["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Subscriber is not ACTIVE.")

    subscriber["enrollment_status"] = "SUSPENDED"
    subscriber["suspension_reason"] = reason
    if subscriber["monitoring_status"] in ("PENDING_DATA", "MONITORED"):
        subscriber["monitoring_status"] = "PAUSED"
    touch(subscriber)
    return ok(ser(subscriber))


@bp.post("/idp/subscribers/<subscriber_id>/reactivate")
def reactivate(subscriber_id):
    auth("PlatformAdmin")
    subscriber = must_exist("subscribers", subscriber_id)
    body()

    if subscriber["enrollment_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Subscriber is not SUSPENDED.")

    subscriber["enrollment_status"] = "ACTIVE"
    subscriber["suspension_reason"] = None
    if subscriber["monitoring_status"] == "PAUSED":
        subscriber["monitoring_status"] = (
            "MONITORED" if subscriber["composite_credit_score"] is not None else "PENDING_DATA"
        )
    touch(subscriber)
    return ok(ser(subscriber))


@bp.get("/idp/subscribers/<subscriber_id>/credit-summary")
def credit_summary(subscriber_id):
    role, user_id = auth("Subscriber", "PlatformAdmin", "ClaimsAdjuster")
    subscriber = must_exist("subscribers", subscriber_id)
    require_subscriber_owner(role, user_id, subscriber["id"])

    profiles = calc.profiles_of(subscriber["id"])
    return ok(
        {
            "subscriber_id": subscriber["id"],
            "composite_credit_score": calc.composite_credit_score(subscriber["id"]),
            "baseline_composite_credit_score": subscriber["baseline_composite_credit_score"],
            "bureau_count": len(profiles),
            "scored_bureau_count": sum(1 for p in profiles if p["credit_score"] is not None),
            "monitoring_status": subscriber["monitoring_status"],
            "risk_score": subscriber["risk_score"],
            "underwriting_risk_score": subscriber["underwriting_risk_score"],
            "insurance_remaining_cents": subscriber["insurance_remaining_cents"],
            "insurance_status": subscriber["insurance_status"],
        }
    )


# ------------------------------------------------------------- family members
@bp.post("/idp/subscribers/<subscriber_id>/family-members")
def add_family_member(subscriber_id):
    role, user_id = auth("Subscriber", "PlatformAdmin")
    subscriber = must_exist("subscribers", subscriber_id)
    require_subscriber_owner(role, user_id, subscriber["id"])

    data = body()
    full_name = req_str(data, "full_name")
    date_of_birth = req_str(data, "date_of_birth")
    ssn_last4 = req_ssn_last4(data)
    relationship = req_enum(data, "relationship", RELATIONSHIPS)

    plan = db.plans[subscriber["plan_id"]]
    existing = len(calc.family_of(subscriber["id"]))
    if existing >= plan["max_family_members"]:
        raise ApiError("ERR_FAMILY_LIMIT_EXCEEDED", "The plan's family allowance is exhausted.")

    covered = relationship == "ADULT" or plan["child_monitoring_included"]
    member = new_row(
        subscriber_id=subscriber["id"],
        full_name=full_name,
        date_of_birth=date_of_birth,
        ssn_last4=ssn_last4,
        relationship=relationship,
        monitoring_status="MONITORED" if covered else "NOT_COVERED",
    )
    db.family_members[member["id"]] = member
    return ok(ser(member), 201)


@bp.get("/idp/subscribers/<subscriber_id>/family-members")
def list_family_members(subscriber_id):
    role, user_id = auth("Subscriber", "PlatformAdmin", "ClaimsAdjuster")
    subscriber = must_exist("subscribers", subscriber_id)
    require_subscriber_owner(role, user_id, subscriber["id"])
    limit, offset = read_pagination()

    rows = by_seq(calc.family_of(subscriber["id"]))
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_many(page), limit, offset, total)


# ------------------------------------------------------------ bureau profiles
@bp.get("/idp/subscribers/<subscriber_id>/bureau-profiles")
def list_bureau_profiles(subscriber_id):
    role, user_id = auth("Subscriber", "PlatformAdmin", "ClaimsAdjuster")
    subscriber = must_exist("subscribers", subscriber_id)
    require_subscriber_owner(role, user_id, subscriber["id"])
    limit, offset = read_pagination()

    rows = by_seq(calc.profiles_of(subscriber["id"]))
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_many(page), limit, offset, total)


# --------------------------------------------------------------- wallet items
@bp.post("/idp/subscribers/<subscriber_id>/wallet-items")
def add_wallet_item(subscriber_id):
    role, user_id = auth("Subscriber", "PlatformAdmin")
    subscriber = must_exist("subscribers", subscriber_id)
    require_subscriber_owner(role, user_id, subscriber["id"])

    data = body()
    item = new_row(
        subscriber_id=subscriber["id"],
        item_type=req_enum(data, "item_type", WALLET_ITEM_TYPES),
        issuer=req_str(data, "issuer"),
        last4=req_str(data, "last4"),
        status="ACTIVE",
        reported_lost_at=None,
    )
    db.wallet_items[item["id"]] = item
    return ok(ser(item), 201)


@bp.get("/idp/subscribers/<subscriber_id>/wallet-items")
def list_wallet_items(subscriber_id):
    role, user_id = auth("Subscriber", "PlatformAdmin")
    subscriber = must_exist("subscribers", subscriber_id)
    require_subscriber_owner(role, user_id, subscriber["id"])
    limit, offset = read_pagination()

    rows = by_seq(
        [w for w in db.wallet_items.values() if w["subscriber_id"] == subscriber["id"]]
    )
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_many(page), limit, offset, total)
