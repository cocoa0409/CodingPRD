"""Policy aggregate-root routes (PRD §3.2, §3.4-§3.6; scaffold §1.5)."""
from flask import Blueprint

from clock import clock
from db import db, new_common, new_id, now_iso, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_success
from serializers import public
from services.calculations import (
    cancellation_refund,
    rated_coverage_premium,
    rider_premium,
)
from services.lookups import (
    children_by_policy,
    get_policy,
    get_product,
    total_attendance,
)
from services.policy_ops import append_ledger as _append_ledger
from services.policy_ops import reconcile_premium as _reconcile_premium
from validators import (
    get_body,
    get_pagination,
    opt_bool,
    opt_int,
    query_str,
    req_enum,
    req_int,
)

bp = Blueprint("policies", __name__)

POLICY_FORMS = {"SINGLE_EVENT", "ANNUAL"}


def _paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return [public(x) for x in page], limit, offset, total


# ---- Create / list / get ---------------------------------------------------
@bp.route("/policies", methods=["POST"])
def create_policy():
    user_id, role = get_user_context()
    require_role(role, {"Policyholder"})
    body = get_body()
    policy_form = req_enum(body, "policy_form", POLICY_FORMS)
    serves_alcohol = opt_bool(body, "serves_alcohol", default=False)
    free_look_days = opt_int(body, "free_look_days", default=15, minimum=0)

    policy = new_common()
    policy.update({
        "policyholder_id": user_id,
        "policy_form": policy_form,
        "serves_alcohol": serves_alcohol,
        "free_look_days": free_look_days,
        "_created_dt": clock.now(),
        "bind_at": None,
        "base_premium_cents": 0,
        "rider_premium_cents": 0,
        "total_premium_cents": 0,
        "premium_earned_cents": 0,
        "refund_due_cents": 0,
        "lifecycle_status": "QUOTED",
        "billing_status": "UNPAID",
        "_bind_at_dt": None,
    })
    db.policies[policy["id"]] = policy
    return success(public(policy), status=201)


@bp.route("/policies", methods=["GET"])
def list_policies():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    f_form = query_str("policy_form")
    f_life = query_str("lifecycle_status")
    f_bill = query_str("billing_status")
    items = list(db.policies.values())
    if f_form is not None:
        items = [p for p in items if p["policy_form"] == f_form]
    if f_life is not None:
        items = [p for p in items if p["lifecycle_status"] == f_life]
    if f_bill is not None:
        items = [p for p in items if p["billing_status"] == f_bill]
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)


@bp.route("/policies/<policy_id>", methods=["GET"])
def get_policy_route(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    policy = get_policy(policy_id)
    return success(public(policy), status=200)


# ---- Bind (QUOTED -> BOUND), PRD §3.4 --------------------------------------
@bp.route("/policies/<policy_id>/bind", methods=["POST"])
def bind_policy(policy_id):
    _, role = get_user_context()
    require_role(role, {"UnderwritingAgent"})
    policy = get_policy(policy_id)

    # State precondition.
    if policy["lifecycle_status"] != "QUOTED":
        raise err("ERR_POLICY_NOT_QUOTED", "policy is not QUOTED")

    profiles = children_by_policy(db.event_profiles, policy_id)
    if len(profiles) < 1:
        raise err("ERR_NO_EVENT_PROFILE", "policy has no event profile")

    selected_coverages = [c for c in children_by_policy(db.coverages, policy_id) if c["status"] == "SELECTED"]
    if len(selected_coverages) < 1:
        raise err("ERR_NO_COVERAGE_SELECTED", "policy has no SELECTED coverage")

    if policy["policy_form"] == "SINGLE_EVENT" and len(profiles) != 1:
        raise err("ERR_SINGLE_EVENT_MULTIPLE_PROFILES", "SINGLE_EVENT policy must have exactly one event profile")

    # If any SELECTED coverage's product is LIQUOR_LIABILITY then serves_alcohol must be true.
    for c in selected_coverages:
        product = db.coverage_products[c["coverage_product_id"]]
        if product["coverage_type"] == "LIQUOR_LIABILITY" and not policy["serves_alcohol"]:
            raise err("ERR_LIQUOR_REQUIRES_ALCOHOL", "LIQUOR_LIABILITY requires serves_alcohol == true")

    # Cascade: rate every SELECTED coverage, flip SELECTED -> ACTIVE.
    attendance = total_attendance(policy_id)
    for c in selected_coverages:
        product = db.coverage_products[c["coverage_product_id"]]
        c["rated_premium_cents"] = rated_coverage_premium(product, attendance)
        c["status"] = "ACTIVE"
        touch(c)

    # Rate every SELECTED rider, flip SELECTED -> ACTIVE.
    for r in children_by_policy(db.riders, policy_id):
        if r["status"] == "SELECTED":
            r["rider_premium_cents"] = rider_premium(r["scheduled_value_cents"])
            r["status"] = "ACTIVE"
            touch(r)

    _reconcile_premium(policy)

    now = clock.now()
    policy["_bind_at_dt"] = now
    policy["bind_at"] = now_iso()
    policy["lifecycle_status"] = "BOUND"
    touch(policy)

    _append_ledger(policy_id, "PREMIUM_CHARGE", policy["total_premium_cents"])
    return success(public(policy), status=200)


# ---- Pay (billing UNPAID -> PAID), PRD §3.5 --------------------------------
@bp.route("/policies/<policy_id>/pay", methods=["POST"])
def pay_policy(policy_id):
    user_id, role = get_user_context()
    require_role(role, {"Policyholder"})
    policy = get_policy(policy_id)
    # Ownership check (priority 3) before state checks.
    if policy["policyholder_id"] != user_id:
        raise err("ERR_NOT_POLICY_OWNER", "acting policyholder does not own this policy")
    body = get_body()
    amount_cents = req_int(body, "amount_cents")

    if policy["lifecycle_status"] != "BOUND":
        raise err("ERR_POLICY_NOT_BOUND", "policy is not BOUND")
    if policy["billing_status"] != "UNPAID":
        raise err("ERR_PREMIUM_ALREADY_PAID", "premium already paid")
    if amount_cents != policy["total_premium_cents"]:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "amount_cents must equal total_premium_cents")

    policy["billing_status"] = "PAID"
    touch(policy)
    return success(public(policy), status=200)


# ---- Activate coverage (BOUND -> IN_FORCE), PRD §3.5 -----------------------
@bp.route("/policies/<policy_id>/activate-coverage", methods=["POST"])
def activate_coverage(policy_id):
    _, role = get_user_context()
    require_role(role, {"UnderwritingAgent"})
    policy = get_policy(policy_id)
    if policy["lifecycle_status"] != "BOUND":
        raise err("ERR_POLICY_NOT_BOUND", "policy is not BOUND")
    if policy["billing_status"] != "PAID":
        raise err("ERR_PREMIUM_UNPAID", "premium is not PAID")
    policy["lifecycle_status"] = "IN_FORCE"
    touch(policy)
    return success(public(policy), status=200)


# ---- Cancel (BOUND/IN_FORCE -> CANCELLED), PRD §3.6 ------------------------
@bp.route("/policies/<policy_id>/cancel", methods=["POST"])
def cancel_policy(policy_id):
    user_id, role = get_user_context()
    require_role(role, {"Policyholder"})
    policy = get_policy(policy_id)
    if policy["policyholder_id"] != user_id:
        raise err("ERR_NOT_POLICY_OWNER", "acting policyholder does not own this policy")

    if policy["lifecycle_status"] not in ("BOUND", "IN_FORCE"):
        raise err("ERR_POLICY_NOT_CANCELLABLE", "policy is not in a cancellable state")

    open_claims = [
        c for c in children_by_policy(db.claims, policy_id)
        if c["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED")
    ]
    if open_claims:
        raise err("ERR_OPEN_CLAIM_BLOCKS_CANCEL", "policy has an open claim")

    refund_due, premium_earned = cancellation_refund(
        policy["total_premium_cents"],
        policy["_bind_at_dt"],
        clock.now(),
        policy["free_look_days"],
    )
    policy["refund_due_cents"] = refund_due
    policy["premium_earned_cents"] = premium_earned
    policy["lifecycle_status"] = "CANCELLED"

    if refund_due > 0:
        policy["billing_status"] = "REFUNDED"
    else:
        policy["billing_status"] = "EARNED"

    # Cascade across the aggregate: void coverages/riders, revoke issued certs.
    for c in children_by_policy(db.coverages, policy_id):
        if c["status"] == "ACTIVE":
            c["status"] = "VOIDED"
            touch(c)
    for r in children_by_policy(db.riders, policy_id):
        if r["status"] == "ACTIVE":
            r["status"] = "VOIDED"
            touch(r)
    for cert in children_by_policy(db.certificates, policy_id):
        if cert["status"] == "ISSUED":
            cert["status"] = "REVOKED"
            touch(cert)

    touch(policy)

    if refund_due > 0:
        _append_ledger(policy_id, "REFUND", -refund_due)

    return success(public(policy), status=200)


# ---- Expire (IN_FORCE -> EXPIRED), PRD §3.5 --------------------------------
@bp.route("/policies/<policy_id>/expire", methods=["POST"])
def expire_policy(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    policy = get_policy(policy_id)
    if policy["lifecycle_status"] != "IN_FORCE":
        raise err("ERR_POLICY_NOT_IN_FORCE", "policy is not IN_FORCE")

    now = clock.now()
    for ep in children_by_policy(db.event_profiles, policy_id):
        if not (now > ep["_event_end_dt"]):
            raise err("ERR_EVENT_NOT_ENDED", "clock is not strictly after every event_end_at")

    policy["lifecycle_status"] = "EXPIRED"
    policy["billing_status"] = "EARNED"
    policy["premium_earned_cents"] = policy["total_premium_cents"]
    touch(policy)
    return success(public(policy), status=200)


# ---- Ledger list -----------------------------------------------------------
@bp.route("/policies/<policy_id>/ledger", methods=["GET"])
def list_ledger(policy_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "UnderwritingAgent", "Policyholder", "ClaimsAdjuster"})
    get_policy(policy_id)
    f_kind = query_str("entry_kind")
    items = [e for e in db.ledger_entries.values() if e["policy_id"] == policy_id]
    items.sort(key=lambda e: e["_seq"])
    if f_kind is not None:
        items = [e for e in items if e["entry_kind"] == f_kind]
    data, limit, offset, total = _paginate(items)
    return list_success(data, limit, offset, total)
