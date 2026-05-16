"""Medigap policy endpoints."""
from flask import Blueprint, g, request

from auth import require_roles
from errors import err
from response import ok_object
from serializers import serialize_medigap_policy
from store import store
from utils import (
    check_version,
    iso_string,
    optional_field,
    require_field,
    require_number,
    round_half_up_cents,
    stamp_create,
    stamp_update,
)

bp = Blueprint("medigap", __name__)


@bp.route("/medigap-policies", methods=["POST"])
@require_roles("BenefitsCounselor")
def create_medigap():
    body = request.get_json(silent=True) or {}
    bid = require_field(body, "beneficiary_id")
    pid = require_field(body, "plan_id")
    uplift = optional_field(body, "underwriting_uplift_decimal", default=0.0)
    if uplift is None:
        uplift = 0.0
    if not isinstance(uplift, (int, float)) or isinstance(uplift, bool):
        raise err("ERR_VALIDATION", "underwriting_uplift_decimal must be number")
    uplift = float(uplift)
    if uplift < 0:
        raise err("ERR_VALIDATION", "underwriting_uplift_decimal must be >= 0")

    beneficiary = store.beneficiaries.get(bid)
    plan = store.plans.get(pid)
    if beneficiary is None or plan is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced beneficiary or plan not found")
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    if plan["plan_type"] != "MEDIGAP":
        raise err("ERR_VALIDATION", "Plan must be MEDIGAP")
    # PRD §3.7: state-residency check fires at GI evaluation (and at issue),
    # not at policy application. A Counselor may APPLY across states; the
    # plan_admin's evaluate-gi or issue call surfaces ERR_MEDIGAP_STATE_MISMATCH.

    now_iso = store.now_iso()
    mid = store.new_id()
    policy = {
        "id": mid,
        "beneficiary_id": bid,
        "plan_id": pid,
        "status": "APPLIED",
        "gi_window_id": None,
        "_applied_dt": store.clock,
        "_issued_dt": None,
        "premium_locked_cents": 0,
        "underwriting_uplift_decimal": uplift,
    }
    stamp_create(policy, store_now_iso=now_iso)
    store.medigap_policies[mid] = policy
    return ok_object(serialize_medigap_policy(policy), status=201)


def _load_policy(mid: str) -> dict:
    m = store.medigap_policies.get(mid)
    if not m:
        raise err("ERR_NOT_FOUND", "Medigap policy not found")
    return m


def _guard_not_deceased(policy: dict):
    beneficiary = store.beneficiaries[policy["beneficiary_id"]]
    if beneficiary["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")


@bp.route("/medigap-policies/<mid>/evaluate-gi", methods=["POST"])
@require_roles("PlanAdmin")
def evaluate_gi(mid):
    policy = _load_policy(mid)
    _guard_not_deceased(policy)
    if policy["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Policy must be APPLIED to evaluate GI")
    body = request.get_json(silent=True) or {}
    check_version(body, policy["version"])

    plan = store.plans[policy["plan_id"]]
    beneficiary = store.beneficiaries[policy["beneficiary_id"]]
    if plan.get("state_code") != beneficiary["state_code"]:
        raise err("ERR_MEDIGAP_STATE_MISMATCH", "Plan state does not match beneficiary state")

    applied_at = policy["_applied_dt"]
    # Find an OPEN MEDIGAP_GI period for this beneficiary that covers applied_at
    gi_period = None
    for p in store.enrollment_periods.values():
        if p["beneficiary_id"] != beneficiary["id"]:
            continue
        if p["period_type"] != "MEDIGAP_GI":
            continue
        if p["status"] != "OPEN":
            continue
        if p["_window_start_dt"] <= applied_at <= p["_window_end_dt"]:
            gi_period = p
            break
    if gi_period is None:
        raise err("ERR_PERIOD_NOT_OPEN", "No OPEN MEDIGAP_GI period covers applied_at")

    now_iso = store.now_iso()
    policy["status"] = "GUARANTEED_ISSUED"
    policy["gi_window_id"] = gi_period["id"]
    policy["premium_locked_cents"] = plan["monthly_premium_cents"]
    stamp_update(policy, store_now_iso=now_iso)

    gi_period["status"] = "CONSUMED"
    gi_period["consumed_by_enrollment_id"] = None  # not bound to enrollment; left null
    stamp_update(gi_period, store_now_iso=now_iso)

    return ok_object(serialize_medigap_policy(policy))


@bp.route("/medigap-policies/<mid>/begin-underwriting", methods=["POST"])
@require_roles("PlanAdmin")
def begin_underwriting(mid):
    policy = _load_policy(mid)
    _guard_not_deceased(policy)
    if policy["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Policy must be APPLIED")
    body = request.get_json(silent=True) or {}
    check_version(body, policy["version"])
    now_iso = store.now_iso()
    policy["status"] = "UNDERWRITING"
    stamp_update(policy, store_now_iso=now_iso)
    return ok_object(serialize_medigap_policy(policy))


@bp.route("/medigap-policies/<mid>/revise-application", methods=["POST"])
@require_roles("BenefitsCounselor")
def revise_application(mid):
    policy = _load_policy(mid)
    _guard_not_deceased(policy)
    if policy["status"] != "UNDERWRITING":
        raise err("ERR_INVALID_STATE", "Policy must be UNDERWRITING to revise")
    body = request.get_json(silent=True) or {}
    check_version(body, policy["version"])
    now_iso = store.now_iso()
    policy["status"] = "APPLIED"
    policy["underwriting_uplift_decimal"] = 0.0
    policy["_applied_dt"] = store.clock
    stamp_update(policy, store_now_iso=now_iso)
    return ok_object(serialize_medigap_policy(policy))


@bp.route("/medigap-policies/<mid>/issue", methods=["POST"])
@require_roles("PlanAdmin")
def issue(mid):
    policy = _load_policy(mid)
    _guard_not_deceased(policy)
    body = request.get_json(silent=True) or {}
    check_version(body, policy["version"])
    if policy["status"] == "GUARANTEED_ISSUED":
        if policy["premium_locked_cents"] <= 0:
            raise err("ERR_INVALID_PREMIUM", "premium_locked_cents must be > 0")
        # Move to ISSUED
        now_iso = store.now_iso()
        policy["status"] = "ISSUED"
        policy["_issued_dt"] = store.clock
        stamp_update(policy, store_now_iso=now_iso)
        return ok_object(serialize_medigap_policy(policy))
    elif policy["status"] == "UNDERWRITING":
        plan = store.plans[policy["plan_id"]]
        uplift = policy["underwriting_uplift_decimal"]
        if uplift < 0:
            raise err("ERR_VALIDATION", "underwriting_uplift_decimal must be >= 0")
        premium = round_half_up_cents(plan["monthly_premium_cents"] * (1 + uplift))
        if premium <= 0:
            raise err("ERR_INVALID_PREMIUM", "Computed premium must be > 0")
        now_iso = store.now_iso()
        policy["status"] = "ISSUED"
        policy["premium_locked_cents"] = premium
        policy["_issued_dt"] = store.clock
        stamp_update(policy, store_now_iso=now_iso)
        return ok_object(serialize_medigap_policy(policy))
    else:
        raise err("ERR_INVALID_STATE", "Policy must be GUARANTEED_ISSUED or UNDERWRITING to issue")


@bp.route("/medigap-policies/<mid>/deny", methods=["POST"])
@require_roles("PlanAdmin")
def deny(mid):
    policy = _load_policy(mid)
    _guard_not_deceased(policy)
    if policy["status"] != "UNDERWRITING":
        raise err("ERR_INVALID_STATE", "Policy must be UNDERWRITING to deny")
    body = request.get_json(silent=True) or {}
    check_version(body, policy["version"])
    now_iso = store.now_iso()
    policy["status"] = "DENIED"
    stamp_update(policy, store_now_iso=now_iso)
    return ok_object(serialize_medigap_policy(policy))


@bp.route("/medigap-policies/<mid>/cancel", methods=["POST"])
@require_roles("BenefitsCounselor")
def cancel(mid):
    policy = _load_policy(mid)
    _guard_not_deceased(policy)
    if policy["status"] not in ("APPLIED", "UNDERWRITING", "ISSUED"):
        raise err("ERR_INVALID_STATE", "Policy cannot be cancelled from this state")
    body = request.get_json(silent=True) or {}
    check_version(body, policy["version"])
    now_iso = store.now_iso()
    policy["status"] = "CANCELLED"
    stamp_update(policy, store_now_iso=now_iso)
    return ok_object(serialize_medigap_policy(policy))


@bp.route("/medigap-policies/<mid>", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def get_policy(mid):
    policy = _load_policy(mid)
    if g.role == "Beneficiary" and policy["beneficiary_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own policies")
    return ok_object(serialize_medigap_policy(policy))
