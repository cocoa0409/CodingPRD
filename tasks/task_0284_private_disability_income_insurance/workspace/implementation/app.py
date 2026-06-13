"""Private Disability Income Insurance API — Flask entry point.

Implements the full /disability surface: insurers + deterministic clock, occupation
classes, policyholders, policies (parallel lifecycle x premium dimensions), claims
(cyclic state machine), income reports (OCC-guarded supersede), disability proofs,
benefit periods (accrual ledger lines), offset awards (estimate/finalize/void), and
the claim ledger. Storage is in-memory only; the store starts empty on every boot.
"""
import os
from decimal import Decimal

from flask import Flask, request

import calc
import services as svc
from db import store, utc_now_iso, new_id
from errors import (
    ApiError, raise_err, ERR_FORBIDDEN_ROLE,
    ERR_INSURER_NOT_FOUND, ERR_OCCUPATION_CLASS_NOT_FOUND, ERR_POLICYHOLDER_NOT_FOUND,
    ERR_POLICY_NOT_FOUND, ERR_CLAIM_NOT_FOUND, ERR_BENEFIT_PERIOD_NOT_FOUND,
    ERR_OFFSET_AWARD_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STALE_CLAIM_VERSION,
    ERR_POLICY_NOT_PENDING, ERR_POLICY_NOT_ACTIVE, ERR_OCCUPATION_CLASS_DECLINED,
    ERR_PREMIUM_NOT_CURRENT, ERR_PREMIUM_NOT_IN_GRACE, ERR_PREMIUM_IN_DEFAULT,
    ERR_OPEN_CLAIM_EXISTS, ERR_CLAIM_NOT_DRAFT, ERR_CLAIM_NOT_SUBMITTED,
    ERR_CLAIM_NOT_UNDER_REVIEW, ERR_CLAIM_NOT_PENDING_INFO, ERR_CLAIM_NOT_APPROVED,
    ERR_CLAIM_NOT_SUSPENDED, ERR_CLAIM_NOT_PAYABLE, ERR_RESIDUAL_INCOME_REPORT_REQUIRED,
    ERR_ELIMINATION_NOT_SATISFIED, ERR_BENEFIT_PERIOD_EXHAUSTED, ERR_BENEFIT_PERIOD_WOULD_EXCEED,
    ERR_PROOF_NOT_CURRENT, ERR_COVERAGE_MONTH_OCCUPIED, ERR_OFFSET_WINDOW_OVERLAP,
    ERR_OFFSET_NOT_ESTIMATED, ERR_OFFSET_NOT_VOIDABLE, ERR_BENEFIT_PERIOD_NOT_ACCRUED,
)
from middleware import get_auth, require_role
from response import success_object, success_array, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

ALL_ROLES = ["Underwriter", "ClaimsAdjudicator", "Policyholder", "SystemOperator"]


# ===========================================================================
# Error handlers
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(_e):
    return error_response("ERR_INSURER_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_e):
    return error_response("ERR_FORBIDDEN_ROLE", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 422)


# ===========================================================================
# Request helpers
# ===========================================================================
def body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def pagination_params():
    limit_str = request.args.get("limit")
    offset_str = request.args.get("offset")
    try:
        limit = int(limit_str) if limit_str is not None else 10
        offset = int(offset_str) if offset_str is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise_err(ERR_INVALID_REQUEST, "limit must be 1..100; offset >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def sorted_by_creation(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def require_int(data, field, *, minimum=None, maximum=None, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field {field!r}")
        return default
    val = data[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_err(ERR_INVALID_REQUEST, f"{field!r} must be an integer")
    if minimum is not None and val < minimum:
        raise_err(ERR_INVALID_REQUEST, f"{field!r} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise_err(ERR_INVALID_REQUEST, f"{field!r} must be <= {maximum}")
    return val


def require_str(data, field, *, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field {field!r}")
        return default
    val = data[field]
    if not isinstance(val, str) or not val.strip():
        raise_err(ERR_INVALID_REQUEST, f"{field!r} must be a non-empty string")
    return val


def require_enum(data, field, allowed, *, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field {field!r}")
        return default
    val = data[field]
    if val not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"{field!r} must be one of {sorted(allowed)}")
    return val


def require_bool(data, field, *, required=False, default=False):
    if field not in data or data[field] is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field {field!r}")
        return default
    val = data[field]
    if not isinstance(val, bool):
        raise_err(ERR_INVALID_REQUEST, f"{field!r} must be a boolean")
    return val


# Lookups raising the resource-specific not-found error (PRD §2.8).
def get_insurer_or_404(iid):
    e = store.insurers.get(iid)
    if e is None:
        raise_err(ERR_INSURER_NOT_FOUND, f"Insurer {iid} not found")
    return e


def get_occupation_class_or_404(oid):
    e = store.occupation_classes.get(oid)
    if e is None:
        raise_err(ERR_OCCUPATION_CLASS_NOT_FOUND, f"OccupationClass {oid} not found")
    return e


def get_policyholder_or_404(pid):
    e = store.policyholders.get(pid)
    if e is None:
        raise_err(ERR_POLICYHOLDER_NOT_FOUND, f"Policyholder {pid} not found")
    return e


def get_policy_or_404(pid):
    e = store.policies.get(pid)
    if e is None:
        raise_err(ERR_POLICY_NOT_FOUND, f"Policy {pid} not found")
    return e


def get_claim_or_404(cid):
    e = store.claims.get(cid)
    if e is None:
        raise_err(ERR_CLAIM_NOT_FOUND, f"Claim {cid} not found")
    return e


def get_benefit_period_or_404(bid):
    e = store.benefit_periods.get(bid)
    if e is None:
        raise_err(ERR_BENEFIT_PERIOD_NOT_FOUND, f"BenefitPeriod {bid} not found")
    return e


def get_offset_award_or_404(oid):
    e = store.offset_awards.get(oid)
    if e is None:
        raise_err(ERR_OFFSET_AWARD_NOT_FOUND, f"OffsetAward {oid} not found")
    return e


def common_create_fields():
    now = utc_now_iso()
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1,
            "_seq": store.next_seq()}


def policyholder_owns_claim(user_id: str, claim: dict) -> bool:
    policy = store.policies.get(claim["policy_id"])
    if policy is None:
        return False
    return policy["policyholder_id"] == user_id


# ===========================================================================
# Insurer + clock
# ===========================================================================
@app.route("/disability/insurers", methods=["POST"])
def create_insurer():
    _uid, role = get_auth()
    require_role(role, ["Underwriter"])
    data = body()
    name = require_str(data, "name")
    rec = common_create_fields()
    rec.update({"name": name, "current_month_index": 0})
    store.insurers[rec["id"]] = rec
    return success_object(svc.insurer_view(rec), 201)


@app.route("/disability/insurers/<iid>", methods=["GET"])
def get_insurer(iid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    rec = get_insurer_or_404(iid)
    return success_object(svc.insurer_view(rec), 200)


@app.route("/disability/insurers/<iid>/clock/advance", methods=["POST"])
def advance_clock(iid):
    _uid, role = get_auth()
    require_role(role, ["SystemOperator"])
    rec = get_insurer_or_404(iid)
    data = body()
    by_months = require_int(data, "by_months", minimum=1, maximum=100000)
    rec["current_month_index"] += by_months
    svc.touch(rec)
    return success_object(svc.insurer_view(rec), 200)


# ===========================================================================
# OccupationClass
# ===========================================================================
@app.route("/disability/occupation-classes", methods=["POST"])
def create_occupation_class():
    _uid, role = get_auth()
    require_role(role, ["Underwriter"])
    data = body()
    insurer_id = require_str(data, "insurer_id")
    # FK existence (priority 4) before field-shape range/enum checks (priority 13).
    get_insurer_or_404(insurer_id)
    code = require_str(data, "code")
    risk_tier = require_enum(data, "risk_tier", {"LOW", "MEDIUM", "HIGH", "DECLINE"})
    max_benefit_months = require_int(data, "max_benefit_months", minimum=1, maximum=600)
    min_elimination_days = require_int(data, "min_elimination_days", minimum=0)
    own_occ_window_months_cap = require_int(data, "own_occ_window_months_cap", minimum=0)
    rec = common_create_fields()
    rec.update({
        "insurer_id": insurer_id, "code": code, "risk_tier": risk_tier,
        "max_benefit_months": max_benefit_months, "min_elimination_days": min_elimination_days,
        "own_occ_window_months_cap": own_occ_window_months_cap,
    })
    store.occupation_classes[rec["id"]] = rec
    return success_object(svc.occupation_class_view(rec), 201)


@app.route("/disability/occupation-classes", methods=["GET"])
def list_occupation_classes():
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.occupation_classes.values())
    insurer_id = request.args.get("insurer_id")
    if insurer_id is not None:
        items = [e for e in items if e["insurer_id"] == insurer_id]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.occupation_class_view(e) for e in page], limit, offset, total)


@app.route("/disability/occupation-classes/<oid>", methods=["GET"])
def get_occupation_class(oid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    rec = get_occupation_class_or_404(oid)
    return success_object(svc.occupation_class_view(rec), 200)


# ===========================================================================
# Policyholder
# ===========================================================================
@app.route("/disability/policyholders", methods=["POST"])
def create_policyholder():
    _uid, role = get_auth()
    require_role(role, ["Underwriter"])
    data = body()
    insurer_id = require_str(data, "insurer_id")
    # FK existence (priority 4) before field-shape range checks (priority 13).
    get_insurer_or_404(insurer_id)
    full_name = require_str(data, "full_name")
    pre_income = require_int(data, "pre_disability_monthly_income_cents", minimum=1)
    rec = common_create_fields()
    rec.update({
        "insurer_id": insurer_id, "full_name": full_name,
        "pre_disability_monthly_income_cents": pre_income,
    })
    store.policyholders[rec["id"]] = rec
    return success_object(svc.policyholder_view(rec), 201)


@app.route("/disability/policyholders", methods=["GET"])
def list_policyholders():
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.policyholders.values())
    insurer_id = request.args.get("insurer_id")
    if insurer_id is not None:
        items = [e for e in items if e["insurer_id"] == insurer_id]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.policyholder_view(e) for e in page], limit, offset, total)


@app.route("/disability/policyholders/<pid>", methods=["GET"])
def get_policyholder(pid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    rec = get_policyholder_or_404(pid)
    return success_object(svc.policyholder_view(rec), 200)


# ===========================================================================
# Policy
# ===========================================================================
@app.route("/disability/policies", methods=["POST"])
def create_policy():
    _uid, role = get_auth()
    require_role(role, ["Underwriter"])
    data = body()
    # FK fields first (presence/type), then resolve existence (priority 4) before
    # the deeper field-shape range/enum/cap checks (priority 13).
    insurer_id = require_str(data, "insurer_id")
    policyholder_id = require_str(data, "policyholder_id")
    occupation_class_id = require_str(data, "occupation_class_id")
    get_insurer_or_404(insurer_id)
    get_policyholder_or_404(policyholder_id)
    occ = get_occupation_class_or_404(occupation_class_id)

    monthly_benefit_cents = require_int(data, "monthly_benefit_cents", minimum=1)
    benefit_period_months = require_int(data, "benefit_period_months", minimum=1)
    elimination_period_days = require_int(data, "elimination_period_days", minimum=0)
    occupation_definition = require_enum(data, "occupation_definition", {"OWN_OCC", "ANY_OCC"})
    own_occ_window_months = require_int(data, "own_occ_window_months", minimum=0,
                                        required=False, default=0)
    cola_rider = require_bool(data, "cola_rider", required=False, default=False)
    # cola_annual_rate: number in [0, 0.10].
    cola_annual_rate = data.get("cola_annual_rate", 0)
    if cola_annual_rate is None:
        cola_annual_rate = 0
    if isinstance(cola_annual_rate, bool) or not isinstance(cola_annual_rate, (int, float)):
        raise_err(ERR_INVALID_REQUEST, "cola_annual_rate must be a number")
    if cola_annual_rate < 0 or cola_annual_rate > 0.10:
        raise_err(ERR_INVALID_REQUEST, "cola_annual_rate must be between 0 and 0.10")
    # cola_annual_rate must be 0 when cola_rider is false.
    if not cola_rider and cola_annual_rate > 0:
        raise_err(ERR_INVALID_REQUEST, "cola_annual_rate must be 0 when cola_rider is false")

    # Cross-entity caps against the occupation class (PRD §2.9).
    if own_occ_window_months > occ["own_occ_window_months_cap"]:
        raise_err(ERR_INVALID_REQUEST, "own_occ_window_months exceeds occupation class cap")
    if elimination_period_days < occ["min_elimination_days"]:
        raise_err(ERR_INVALID_REQUEST, "elimination_period_days below occupation class minimum")
    if benefit_period_months > occ["max_benefit_months"]:
        raise_err(ERR_INVALID_REQUEST, "benefit_period_months exceeds occupation class maximum")

    rec = common_create_fields()
    rec.update({
        "insurer_id": insurer_id, "policyholder_id": policyholder_id,
        "occupation_class_id": occupation_class_id,
        "monthly_benefit_cents": monthly_benefit_cents,
        "benefit_period_months": benefit_period_months,
        "elimination_period_days": elimination_period_days,
        "occupation_definition": occupation_definition,
        "own_occ_window_months": own_occ_window_months,
        "cola_rider": cola_rider, "cola_annual_rate": cola_annual_rate,
        "lifecycle_status": "PENDING", "premium_status": "CURRENT",
        "benefit_months_consumed": 0.0,
    })
    store.policies[rec["id"]] = rec
    return success_object(svc.policy_view(rec), 201)


@app.route("/disability/policies", methods=["GET"])
def list_policies():
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.policies.values())
    for key in ("insurer_id", "policyholder_id", "occupation_class_id"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.policy_view(e) for e in page], limit, offset, total)


@app.route("/disability/policies/<pid>", methods=["GET"])
def get_policy(pid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    rec = get_policy_or_404(pid)
    return success_object(svc.policy_view(rec), 200)


@app.route("/disability/policies/<pid>/activate", methods=["POST"])
def activate_policy(pid):
    _uid, role = get_auth()
    require_role(role, ["Underwriter"])
    policy = get_policy_or_404(pid)
    if policy["lifecycle_status"] != "PENDING":
        raise_err(ERR_POLICY_NOT_PENDING, "Policy lifecycle_status is not PENDING")
    occ = store.occupation_classes.get(policy["occupation_class_id"])
    if occ is not None and occ["risk_tier"] == "DECLINE":
        raise_err(ERR_OCCUPATION_CLASS_DECLINED, "Occupation class risk_tier is DECLINE")
    policy["lifecycle_status"] = "ACTIVE"
    svc.touch(policy)
    return success_object(svc.policy_view(policy), 200)


@app.route("/disability/policies/<pid>/terminate", methods=["POST"])
def terminate_policy(pid):
    _uid, role = get_auth()
    require_role(role, ["Underwriter"])
    policy = get_policy_or_404(pid)
    if policy["lifecycle_status"] != "ACTIVE":
        raise_err(ERR_POLICY_NOT_ACTIVE, "Policy lifecycle_status is not ACTIVE")
    # No claim UNDER_REVIEW or PENDING_INFO blocks termination.
    for claim in store.claims.values():
        if claim["policy_id"] == pid and claim["status"] in ("UNDER_REVIEW", "PENDING_INFO"):
            raise_err(ERR_OPEN_CLAIM_EXISTS, "An open claim blocks termination")
    policy["lifecycle_status"] = "TERMINATED"
    svc.touch(policy)
    # Closing cascade: APPROVED or SUSPENDED claims -> CLOSED.
    for claim in store.claims.values():
        if claim["policy_id"] == pid and claim["status"] in ("APPROVED", "SUSPENDED"):
            claim["status"] = "CLOSED"
            svc.touch(claim)
    return success_object(svc.policy_view(policy), 200)


@app.route("/disability/policies/<pid>/premium/miss", methods=["POST"])
def premium_miss(pid):
    _uid, role = get_auth()
    require_role(role, ["Underwriter"])
    policy = get_policy_or_404(pid)
    if policy["premium_status"] == "CURRENT":
        # First leg requires lifecycle ACTIVE.
        if policy["lifecycle_status"] != "ACTIVE":
            raise_err(ERR_POLICY_NOT_ACTIVE, "Policy lifecycle_status is not ACTIVE")
        policy["premium_status"] = "GRACE"
        svc.touch(policy)
    elif policy["premium_status"] == "GRACE":
        # Second leg: GRACE -> DEFAULT, triggers lapse cascade.
        policy["premium_status"] = "DEFAULT"
        svc.touch(policy)
        # Lapse cascade: lifecycle ACTIVE -> LAPSED, suspend APPROVED claims.
        if policy["lifecycle_status"] == "ACTIVE":
            policy["lifecycle_status"] = "LAPSED"
            svc.touch(policy)
            for claim in store.claims.values():
                if claim["policy_id"] == pid and claim["status"] == "APPROVED":
                    claim["status"] = "SUSPENDED"
                    svc.touch(claim)
    else:
        # premium_status == DEFAULT — neither leg applies; expected GRACE for second miss.
        raise_err(ERR_PREMIUM_NOT_IN_GRACE, "premium_status is not GRACE")
    return success_object(svc.policy_view(policy), 200)


@app.route("/disability/policies/<pid>/premium/pay", methods=["POST"])
def premium_pay(pid):
    _uid, role = get_auth()
    require_role(role, ["Underwriter"])
    policy = get_policy_or_404(pid)
    if policy["premium_status"] != "GRACE":
        raise_err(ERR_PREMIUM_NOT_IN_GRACE, "premium_status is not GRACE")
    policy["premium_status"] = "CURRENT"
    svc.touch(policy)
    return success_object(svc.policy_view(policy), 200)


# ===========================================================================
# Claim
# ===========================================================================
@app.route("/disability/claims", methods=["POST"])
def create_claim():
    uid, role = get_auth()
    require_role(role, ["Policyholder"])
    data = body()
    insurer_id = require_str(data, "insurer_id")
    policy_id = require_str(data, "policy_id")
    # FK existence (priority 4) before field-shape range/enum checks (priority 13).
    get_insurer_or_404(insurer_id)
    policy = get_policy_or_404(policy_id)
    # Policyholder ownership: claim's policy must belong to the acting policyholder.
    if policy["policyholder_id"] != uid:
        raise_err(ERR_FORBIDDEN_ROLE, "Policyholder does not own this policy")
    disability_onset_month = require_int(data, "disability_onset_month", minimum=0)
    claimed_disability_type = require_enum(data, "claimed_disability_type", {"TOTAL", "RESIDUAL"})
    elimination_satisfied_month, own_occ_expiry_month = calc.claim_window_months(
        disability_onset_month, policy["elimination_period_days"],
        policy["occupation_definition"], policy["own_occ_window_months"],
    )
    rec = common_create_fields()
    rec.update({
        "insurer_id": insurer_id, "policy_id": policy_id,
        "disability_onset_month": disability_onset_month,
        "claimed_disability_type": claimed_disability_type,
        "elimination_satisfied_month": elimination_satisfied_month,
        "own_occ_expiry_month": own_occ_expiry_month,
        "next_proof_due_month": 0,
        "status": "DRAFT",
    })
    store.claims[rec["id"]] = rec
    return success_object(svc.claim_view(rec), 201)


@app.route("/disability/claims", methods=["GET"])
def list_claims():
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.claims.values())
    for key in ("insurer_id", "policy_id"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.claim_view(e) for e in page], limit, offset, total)


@app.route("/disability/claims/<cid>", methods=["GET"])
def get_claim(cid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    rec = get_claim_or_404(cid)
    return success_object(svc.claim_view(rec), 200)


def _policyholder_claim_guard(uid, role, claim):
    """Ownership check for Policyholder-only write actions on a claim (PRD §2.1)."""
    if role == "Policyholder" and not svc_owns(uid, claim):
        raise_err(ERR_FORBIDDEN_ROLE, "Policyholder does not own this claim")


def svc_owns(uid, claim):
    policy = store.policies.get(claim["policy_id"])
    return policy is not None and policy["policyholder_id"] == uid


@app.route("/disability/claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    uid, role = get_auth()
    require_role(role, ["Policyholder"])
    claim = get_claim_or_404(cid)
    _policyholder_claim_guard(uid, role, claim)
    if claim["status"] != "DRAFT":
        raise_err(ERR_CLAIM_NOT_DRAFT, "Claim status is not DRAFT")
    policy = get_policy_or_404(claim["policy_id"])
    if policy["lifecycle_status"] != "ACTIVE":
        raise_err(ERR_POLICY_NOT_ACTIVE, "Policy lifecycle_status is not ACTIVE")
    if claim["claimed_disability_type"] == "RESIDUAL":
        has_report = any(r["claim_id"] == cid for r in store.income_reports.values())
        if not has_report:
            raise_err(ERR_RESIDUAL_INCOME_REPORT_REQUIRED,
                      "RESIDUAL claim requires at least one income report before submission")
    claim["status"] = "SUBMITTED"
    svc.touch(claim)
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/begin-review", methods=["POST"])
def begin_review(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_NOT_SUBMITTED, "Claim status is not SUBMITTED")
    claim["status"] = "UNDER_REVIEW"
    svc.touch(claim)
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/request-info", methods=["POST"])
def request_info(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "UNDER_REVIEW":
        raise_err(ERR_CLAIM_NOT_UNDER_REVIEW, "Claim status is not UNDER_REVIEW")
    claim["status"] = "PENDING_INFO"
    svc.touch(claim)
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/resume-review", methods=["POST"])
def resume_review(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "PENDING_INFO":
        raise_err(ERR_CLAIM_NOT_PENDING_INFO, "Claim status is not PENDING_INFO")
    claim["status"] = "UNDER_REVIEW"
    svc.touch(claim)
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "UNDER_REVIEW":
        raise_err(ERR_CLAIM_NOT_UNDER_REVIEW, "Claim status is not UNDER_REVIEW")
    policy = get_policy_or_404(claim["policy_id"])
    if policy["lifecycle_status"] != "ACTIVE":
        raise_err(ERR_POLICY_NOT_ACTIVE, "Policy lifecycle_status is not ACTIVE")
    if policy["premium_status"] == "DEFAULT":
        raise_err(ERR_PREMIUM_IN_DEFAULT, "Policy premium_status is DEFAULT")
    insurer = store.insurers.get(claim["insurer_id"])
    current_month = insurer["current_month_index"] if insurer else 0
    if current_month < claim["elimination_satisfied_month"]:
        raise_err(ERR_ELIMINATION_NOT_SATISFIED, "Elimination period not yet satisfied")
    if svc.consumed_decimal(policy) >= Decimal(policy["benefit_period_months"]):
        raise_err(ERR_BENEFIT_PERIOD_EXHAUSTED, "Benefit period already exhausted")
    claim["status"] = "APPROVED"
    svc.touch(claim)
    # Create ClaimLedger if not present (all totals 0).
    if cid not in store.claim_ledgers:
        ledger = common_create_fields()
        ledger.update({
            "claim_id": cid, "total_gross_paid_cents": 0,
            "total_net_paid_cents": 0, "overpayment_balance_cents": 0,
        })
        store.claim_ledgers[cid] = ledger
    # next_proof_due_month = elimination_satisfied_month + PROOF_INTERVAL_MONTHS.
    claim["next_proof_due_month"] = claim["elimination_satisfied_month"] + calc.PROOF_INTERVAL_MONTHS
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "UNDER_REVIEW":
        raise_err(ERR_CLAIM_NOT_UNDER_REVIEW, "Claim status is not UNDER_REVIEW")
    claim["status"] = "DENIED"
    svc.touch(claim)
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/suspend", methods=["POST"])
def suspend_claim(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_NOT_APPROVED, "Claim status is not APPROVED")
    claim["status"] = "SUSPENDED"
    svc.touch(claim)
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/reinstate", methods=["POST"])
def reinstate_claim(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "SUSPENDED":
        raise_err(ERR_CLAIM_NOT_SUSPENDED, "Claim status is not SUSPENDED")
    policy = get_policy_or_404(claim["policy_id"])
    if policy["lifecycle_status"] != "ACTIVE":
        raise_err(ERR_POLICY_NOT_ACTIVE, "Policy lifecycle_status is not ACTIVE")
    claim["status"] = "APPROVED"
    svc.touch(claim)
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/reverse", methods=["POST"])
def reverse_claim(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_NOT_APPROVED, "Claim status is not APPROVED")
    policy = get_policy_or_404(claim["policy_id"])
    claim["status"] = "DENIED"
    svc.touch(claim)
    # Compensation cascade: every ACCRUED period -> REVERSED.
    reversed_fraction = Decimal("0")
    for bp in svc.accrued_periods(cid):
        reversed_fraction += Decimal(str(bp["benefit_fraction"]))
        bp["status"] = "REVERSED"
        svc.touch(bp)
    # Policy.benefit_months_consumed decreased by reversed fraction sum.
    if reversed_fraction != 0:
        svc.adjust_consumed(policy, -reversed_fraction)
    # Ledger totals -> 0 (no ACCRUED periods remain); overpayment_balance -> 0.
    ledger = store.claim_ledgers.get(cid)
    if ledger is not None:
        changed = (ledger["total_gross_paid_cents"] != 0
                   or ledger["total_net_paid_cents"] != 0
                   or ledger["overpayment_balance_cents"] != 0)
        ledger["total_gross_paid_cents"] = 0
        ledger["total_net_paid_cents"] = 0
        ledger["overpayment_balance_cents"] = 0
        if changed:
            svc.touch(ledger)
    return success_object(svc.claim_view(claim), 200)


@app.route("/disability/claims/<cid>/close", methods=["POST"])
def close_claim(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_NOT_APPROVED, "Claim status is not APPROVED")
    claim["status"] = "CLOSED"
    svc.touch(claim)
    return success_object(svc.claim_view(claim), 200)


# ===========================================================================
# IncomeReport (OCC-guarded supersede)
# ===========================================================================
@app.route("/disability/claims/<cid>/income-reports", methods=["POST"])
def create_income_report(cid):
    uid, role = get_auth()
    require_role(role, ["Policyholder"])
    claim = get_claim_or_404(cid)
    _policyholder_claim_guard(uid, role, claim)
    data = body()
    # OCC check (priority 5) runs before business logic.
    expected = require_int(data, "expected_claim_version", minimum=0)
    if expected != claim["version"]:
        raise_err(ERR_STALE_CLAIM_VERSION, "expected_claim_version does not match claim version")
    effective_month = require_int(data, "effective_month", minimum=claim["disability_onset_month"])
    current_income = require_int(data, "current_monthly_income_cents", minimum=0)

    policy = get_policy_or_404(claim["policy_id"])
    policyholder = store.policyholders.get(policy["policyholder_id"])
    pre_income = policyholder["pre_disability_monthly_income_cents"] if policyholder else 0
    ratio = calc.income_loss_ratio(pre_income, current_income)

    rec = common_create_fields()
    rec.update({
        "claim_id": cid, "effective_month": effective_month,
        "current_monthly_income_cents": current_income,
        "income_loss_ratio": float(ratio), "is_superseded": False,
    })
    # Supersede any prior report with strictly lesser effective_month.
    for prior in store.income_reports.values():
        if (prior["claim_id"] == cid and prior["effective_month"] < effective_month
                and not prior["is_superseded"]):
            prior["is_superseded"] = True
            svc.touch(prior)
    store.income_reports[rec["id"]] = rec
    # Recording an income report increments the claim version.
    svc.touch(claim)
    return success_object(svc.income_report_view(rec), 201)


@app.route("/disability/claims/<cid>/income-reports", methods=["GET"])
def list_income_reports(cid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    get_claim_or_404(cid)
    limit, offset = pagination_params()
    items = [r for r in store.income_reports.values() if r["claim_id"] == cid]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.income_report_view(e) for e in page], limit, offset, total)


# ===========================================================================
# DisabilityProof (append-only)
# ===========================================================================
@app.route("/disability/claims/<cid>/disability-proofs", methods=["POST"])
def create_disability_proof(cid):
    uid, role = get_auth()
    require_role(role, ["Policyholder"])
    claim = get_claim_or_404(cid)
    _policyholder_claim_guard(uid, role, claim)
    data = body()
    attestation_month = require_int(data, "attestation_month", minimum=claim["disability_onset_month"])
    still_disabled = require_bool(data, "still_disabled", required=True)
    accepted = bool(still_disabled and attestation_month <= claim["next_proof_due_month"])
    now = utc_now_iso()
    rec = {
        "id": new_id(), "created_at": now, "_seq": store.next_seq(),
        "claim_id": cid, "attestation_month": attestation_month,
        "still_disabled": still_disabled, "accepted": accepted,
    }
    store.disability_proofs[rec["id"]] = rec
    if accepted:
        claim["next_proof_due_month"] += calc.PROOF_INTERVAL_MONTHS
        svc.touch(claim)
    return success_object(svc.disability_proof_view(rec), 201)


@app.route("/disability/claims/<cid>/disability-proofs", methods=["GET"])
def list_disability_proofs(cid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    get_claim_or_404(cid)
    limit, offset = pagination_params()
    items = [r for r in store.disability_proofs.values() if r["claim_id"] == cid]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.disability_proof_view(e) for e in page], limit, offset, total)


# ===========================================================================
# BenefitPeriod (accrual)
# ===========================================================================
@app.route("/disability/claims/<cid>/benefit-periods", methods=["POST"])
def create_benefit_period(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    data = body()
    coverage_month = require_int(data, "coverage_month", minimum=0)
    # priority 10: parent claim must be APPROVED.
    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_NOT_PAYABLE, "Parent claim is not APPROVED")
    policy = get_policy_or_404(claim["policy_id"])
    # priority 11: coverage_month within payable window.
    if coverage_month < claim["elimination_satisfied_month"] or coverage_month > claim["next_proof_due_month"]:
        raise_err(ERR_PROOF_NOT_CURRENT, "coverage_month outside payable window")
    # priority 9: no duplicate ACCRUED coverage_month.
    for bp in store.benefit_periods.values():
        if (bp["claim_id"] == cid and bp["status"] == "ACCRUED"
                and bp["coverage_month"] == coverage_month):
            raise_err(ERR_COVERAGE_MONTH_OCCUPIED, "coverage_month already covered")

    # Compute benefit_fraction first (pinned evaluation order).
    fraction = svc.compute_benefit_fraction(claim, policy, coverage_month)

    # priority 12: would-exceed check (equality allowed and exhausts).
    new_consumed = svc.consumed_decimal(policy) + fraction
    if calc.round4(new_consumed) > Decimal(policy["benefit_period_months"]):
        raise_err(ERR_BENEFIT_PERIOD_WOULD_EXCEED,
                  "Accrual would drive benefit_months_consumed beyond benefit_period_months")

    rec = common_create_fields()
    rec.update({
        "claim_id": cid, "policy_id": policy["id"], "coverage_month": coverage_month,
        "benefit_fraction": float(fraction), "status": "ACCRUED",
        "gross_benefit_cents": 0, "offset_applied_cents": 0, "net_benefit_cents": 0,
    })
    svc.price_period(rec, claim, policy)
    store.benefit_periods[rec["id"]] = rec

    # Policy.benefit_months_consumed += fraction.
    svc.adjust_consumed(policy, fraction)
    # Ledger totals recomputed.
    svc.recompute_ledger_totals(cid)
    # Exhaustion: if consumed >= benefit_period_months, claim -> BENEFIT_EXHAUSTED.
    if svc.consumed_decimal(policy) >= Decimal(policy["benefit_period_months"]):
        claim["status"] = "BENEFIT_EXHAUSTED"
        svc.touch(claim)
    return success_object(svc.benefit_period_view(rec), 201)


@app.route("/disability/claims/<cid>/benefit-periods", methods=["GET"])
def list_claim_benefit_periods(cid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    get_claim_or_404(cid)
    limit, offset = pagination_params()
    items = [bp for bp in store.benefit_periods.values() if bp["claim_id"] == cid]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.benefit_period_view(e) for e in page], limit, offset, total)


@app.route("/disability/benefit-periods", methods=["GET"])
def list_benefit_periods():
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.benefit_periods.values())
    for key in ("policy_id", "claim_id"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.benefit_period_view(e) for e in page], limit, offset, total)


@app.route("/disability/benefit-periods/<bid>", methods=["GET"])
def get_benefit_period(bid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    rec = get_benefit_period_or_404(bid)
    return success_object(svc.benefit_period_view(rec), 200)


@app.route("/disability/benefit-periods/<bid>/void", methods=["POST"])
def void_benefit_period(bid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    bp = get_benefit_period_or_404(bid)
    if bp["status"] != "ACCRUED":
        raise_err(ERR_BENEFIT_PERIOD_NOT_ACCRUED, "BenefitPeriod status is not ACCRUED")
    claim = get_claim_or_404(bp["claim_id"])
    if claim["status"] not in ("APPROVED", "SUSPENDED"):
        raise_err(ERR_CLAIM_NOT_PAYABLE, "Parent claim is not APPROVED or SUSPENDED")
    policy = get_policy_or_404(bp["policy_id"])
    fraction = Decimal(str(bp["benefit_fraction"]))
    bp["status"] = "REVERSED"
    svc.touch(bp)
    svc.recompute_ledger_totals(bp["claim_id"])
    svc.adjust_consumed(policy, -fraction)
    return success_object(svc.benefit_period_view(bp), 200)


# ===========================================================================
# OffsetAward
# ===========================================================================
@app.route("/disability/claims/<cid>/offset-awards", methods=["POST"])
def create_offset_award(cid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    claim = get_claim_or_404(cid)
    data = body()
    offset_source = require_enum(data, "offset_source", {"SSDI", "WORKERS_COMP"})
    monthly_offset = require_int(data, "monthly_offset_cents", minimum=0)
    start_month = require_int(data, "start_month", minimum=0)
    end_month = require_int(data, "end_month", minimum=0)
    if end_month < start_month:
        raise_err(ERR_INVALID_REQUEST, "end_month must be >= start_month")
    # priority 6: parent claim must be APPROVED (checked before overlap).
    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_NOT_APPROVED, "Parent claim is not APPROVED")
    # priority 8: overlap check — same offset_source, non-VOID, closed-interval, touching collides.
    for a in store.offset_awards.values():
        if (a["claim_id"] == cid and a["status"] != "VOID"
                and a["offset_source"] == offset_source):
            if start_month <= a["end_month"] and a["start_month"] <= end_month:
                raise_err(ERR_OFFSET_WINDOW_OVERLAP, "Offset window collides with an existing award")

    rec = common_create_fields()
    rec.update({
        "claim_id": cid, "offset_source": offset_source,
        "monthly_offset_cents": monthly_offset,
        "estimated_offset_cents": monthly_offset,
        "final_monthly_offset_cents": 0,
        "start_month": start_month, "end_month": end_month,
        "status": "ESTIMATED",
    })
    store.offset_awards[rec["id"]] = rec
    # Recompute covered ACCRUED periods' offset/net and ledger net total.
    _reprice_covered(claim, start_month, end_month)
    svc.recompute_ledger_totals(cid)
    return success_object(svc.offset_award_view(rec), 201)


def _reprice_covered(claim, start_month, end_month, exclude_award_id=None):
    policy = store.policies.get(claim["policy_id"])
    if policy is None:
        return
    for bp in svc.accrued_periods(claim["id"]):
        if start_month <= bp["coverage_month"] <= end_month:
            svc.price_period(bp, claim, policy, exclude_award_id=exclude_award_id)
            svc.touch(bp)


@app.route("/disability/claims/<cid>/offset-awards", methods=["GET"])
def list_offset_awards(cid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    get_claim_or_404(cid)
    limit, offset = pagination_params()
    items = [a for a in store.offset_awards.values() if a["claim_id"] == cid]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_array([svc.offset_award_view(e) for e in page], limit, offset, total)


@app.route("/disability/offset-awards/<oid>", methods=["GET"])
def get_offset_award(oid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    rec = get_offset_award_or_404(oid)
    return success_object(svc.offset_award_view(rec), 200)


@app.route("/disability/offset-awards/<oid>/finalize", methods=["POST"])
def finalize_offset_award(oid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    award = get_offset_award_or_404(oid)
    if award["status"] != "ESTIMATED":
        raise_err(ERR_OFFSET_NOT_ESTIMATED, "OffsetAward status is not ESTIMATED")
    claim = get_claim_or_404(award["claim_id"])
    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_NOT_APPROVED, "Parent claim is not APPROVED")
    data = body()
    final_val = require_int(data, "final_monthly_offset_cents", minimum=0,
                            required=False, default=award["estimated_offset_cents"])
    award["status"] = "FINALIZED"
    award["final_monthly_offset_cents"] = final_val
    svc.touch(award)
    # Cascade: reprice covered ACCRUED periods; recompute ledger net total.
    covered = [bp for bp in svc.accrued_periods(claim["id"])
               if award["start_month"] <= bp["coverage_month"] <= award["end_month"]]
    _reprice_covered(claim, award["start_month"], award["end_month"])
    svc.recompute_ledger_totals(award["claim_id"])
    # Overpayment delta: positive (final - estimated) per covered ACCRUED month.
    delta_per_month = max(0, final_val - award["estimated_offset_cents"])
    if delta_per_month and covered:
        ledger = store.claim_ledgers.get(award["claim_id"])
        if ledger is not None:
            ledger["overpayment_balance_cents"] += delta_per_month * len(covered)
            svc.touch(ledger)
    return success_object(svc.offset_award_view(award), 200)


@app.route("/disability/offset-awards/<oid>/void", methods=["POST"])
def void_offset_award(oid):
    _uid, role = get_auth()
    require_role(role, ["ClaimsAdjudicator"])
    award = get_offset_award_or_404(oid)
    if award["status"] not in ("ESTIMATED", "FINALIZED"):
        raise_err(ERR_OFFSET_NOT_VOIDABLE, "OffsetAward is not voidable")
    claim = get_claim_or_404(award["claim_id"])
    was_finalized = award["status"] == "FINALIZED"
    # Compute the overpayment delta this award contributed (to undo exactly).
    covered = [bp for bp in svc.accrued_periods(claim["id"])
               if award["start_month"] <= bp["coverage_month"] <= award["end_month"]]
    delta_per_month = max(0, award["final_monthly_offset_cents"] - award["estimated_offset_cents"])
    award["status"] = "VOID"
    svc.touch(award)
    # Reprice covered ACCRUED periods excluding this (now VOID) award.
    _reprice_covered(claim, award["start_month"], award["end_month"])
    svc.recompute_ledger_totals(award["claim_id"])
    # Subtract the exact overpayment delta finalize added (conserved-quantity invariant).
    if was_finalized and delta_per_month and covered:
        ledger = store.claim_ledgers.get(award["claim_id"])
        if ledger is not None:
            ledger["overpayment_balance_cents"] -= delta_per_month * len(covered)
            svc.touch(ledger)
    return success_object(svc.offset_award_view(award), 200)


# ===========================================================================
# ClaimLedger (computed read; output is ClaimLedger[])
# ===========================================================================
@app.route("/disability/claims/<cid>/ledger", methods=["GET"])
def get_claim_ledger(cid):
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    get_claim_or_404(cid)
    limit, offset = pagination_params()
    ledger = store.claim_ledgers.get(cid)
    items = [ledger] if ledger is not None else []
    page, total = paginate(items, limit, offset)
    return success_array([svc.claim_ledger_view(e) for e in page], limit, offset, total)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
