"""Medical Financing / Patient Payment Plan API — Flask entry point.

In-memory store, logical clock, no seeded data. Boots clean on every process
start (start.sh re-invocation wipes all state by restarting the process).
"""
import os

from flask import Flask, request

import db
import calculations as calc
import services as svc
from errors import (ApiError, err,
                    ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER, ERR_NOT_FOUND,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
                    ERR_REFERENTIAL_MISMATCH, ERR_TEMPORAL_CONFLICT,
                    ERR_ACCOUNT_NOT_ELIGIBLE, ERR_INSUFFICIENT_CREDIT,
                    ERR_DUPLICATE_RESOURCE, ERR_PAYOFF_NOT_REVERSIBLE)
from middleware import authenticate, require_role
from models import new_entity, touch, serialize
from response import success, error
import validation as V
from timeutil import parse_iso, add_months, end_of_month

app = Flask(__name__)
app.url_map.strict_slashes = False


# =====================================================================
# Error handling
# =====================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# =====================================================================
# Shared helpers
# =====================================================================
COLLECTIONS = {
    "provider": db.providers,
    "promotional_plan": db.promotional_plans,
    "provider_promotion": db.provider_promotions,
    "credit_application": db.credit_applications,
    "patient_account": db.patient_accounts,
    "autopay_enrollment": db.autopay_enrollments,
    "financed_purchase": db.financed_purchases,
    "settlement": db.settlements,
    "payment": db.payments,
    "billing_statement": db.billing_statements,
    "refund": db.refunds,
}


def find_or_404(collection, resource_id):
    ent = collection.get(resource_id)
    if ent is None:
        raise err(ERR_NOT_FOUND, "Resource %s not found" % resource_id)
    return ent


def paginate(items):
    """Apply limit/offset (PRD §2.3). items are already sorted by created_at ASC.
    Returns (page_items, pagination_meta)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def sorted_by_created(values):
    return sorted(values, key=lambda e: (e["created_at"], e["_seq"]))


def list_response(values, post_filter=None):
    items = sorted_by_created(values)
    if post_filter:
        items = [i for i in items if post_filter(i)]
    page, pagination = paginate(items)
    return success([serialize(i) for i in page], status=200, pagination=pagination)


# --- ownership checks (PRD §2.1, priority 3) ---
def check_patient_owns(principal, account_id):
    if principal.role == "Patient" and principal.user_id != account_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Patient does not own this account")


def check_provider_owns(principal, provider_id):
    if principal.role == "Provider" and principal.user_id != provider_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Provider does not own this resource")


# =====================================================================
# Provider endpoints
# =====================================================================
@app.route("/providers", methods=["POST"])
def create_provider():
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    body = V.get_body()
    legal_name = V.require_str(body, "legal_name")
    specialty = V.require_enum(body, "specialty",
                               {"DENTAL", "VISION", "VETERINARY", "DERMATOLOGY", "GENERAL"})
    tax_id = V.require_str(body, "tax_id")
    rate = V.require_number(body, "base_merchant_discount_rate")
    V.range_inclusive(rate, "base_merchant_discount_rate", 0, 0.30)
    # uniqueness among non-TERMINATED providers (priority 12)
    for prov in db.providers.values():
        if prov["tax_id"] == tax_id and prov["status"] != "TERMINATED":
            raise err(ERR_DUPLICATE_RESOURCE, "tax_id already in use")
    provider = new_entity({
        "legal_name": legal_name,
        "specialty": specialty,
        "tax_id": tax_id,
        "base_merchant_discount_rate": rate,
        "status": "PENDING",
        "monthly_settled_volume_cents": 0,
        "settled_net_cents": 0,
    })
    db.providers[provider["id"]] = provider
    return success(serialize(provider), status=201)


@app.route("/providers/<rid>", methods=["GET"])
def get_provider(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    check_provider_owns(p, rid)
    provider = find_or_404(db.providers, rid)
    svc.recompute_provider_volumes(provider)
    return success(serialize(provider), status=200)


@app.route("/providers", methods=["GET"])
def list_providers():
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    status = request.args.get("status")
    specialty = request.args.get("specialty")

    def flt(prov):
        if status is not None and prov["status"] != status:
            return False
        if specialty is not None and prov["specialty"] != specialty:
            return False
        return True
    for prov in db.providers.values():
        svc.recompute_provider_volumes(prov)
    return list_response(db.providers.values(), post_filter=flt)


def _provider_transition(rid, allowed_from, target):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    provider = find_or_404(db.providers, rid)
    if provider["status"] not in allowed_from:
        raise err(ERR_INVALID_STATE, "Provider not in a state for this transition")
    return p, provider


@app.route("/providers/<rid>/enroll", methods=["POST"])
def enroll_provider(rid):
    _, provider = _provider_transition(rid, {"PENDING", "SUSPENDED"}, "ENROLLED")
    provider["status"] = "ENROLLED"
    touch(provider)
    svc.recompute_provider_volumes(provider)
    return success(serialize(provider), status=200)


@app.route("/providers/<rid>/suspend", methods=["POST"])
def suspend_provider(rid):
    _, provider = _provider_transition(rid, {"ENROLLED"}, "SUSPENDED")
    provider["status"] = "SUSPENDED"
    touch(provider)
    svc.recompute_provider_volumes(provider)
    return success(serialize(provider), status=200)


@app.route("/providers/<rid>/terminate", methods=["POST"])
def terminate_provider(rid):
    _, provider = _provider_transition(rid, {"ENROLLED", "SUSPENDED"}, "TERMINATED")
    for purchase in db.financed_purchases.values():
        if purchase["provider_id"] == provider["id"] and purchase["settlement_status"] == "AUTHORIZED":
            raise err(ERR_INVALID_STATE,
                      "Provider has AUTHORIZED purchases; cannot terminate")
    provider["status"] = "TERMINATED"
    touch(provider)
    svc.recompute_provider_volumes(provider)
    return success(serialize(provider), status=200)


@app.route("/providers/<rid>/settlements", methods=["GET"])
def provider_settlements(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    check_provider_owns(p, rid)
    find_or_404(db.providers, rid)
    status = request.args.get("status")

    def flt(s):
        if s["provider_id"] != rid:
            return False
        if status is not None and s["status"] != status:
            return False
        return True
    return list_response(db.settlements.values(), post_filter=flt)


# =====================================================================
# PromotionalPlan endpoints
# =====================================================================
@app.route("/promotional-plans", methods=["POST"])
def create_plan():
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    body = V.get_body()
    name = V.require_str(body, "name")
    plan_category = V.require_enum(body, "plan_category",
                                   {"DEFERRED_INTEREST", "EQUAL_PAYMENT", "REDUCED_APR"})
    months = V.require_int(body, "deferred_period_months")
    promo_apr = V.require_number(body, "promo_apr")
    factor = V.require_number(body, "min_payment_factor")
    V.range_inclusive(months, "deferred_period_months", 1, 60)
    V.range_inclusive(promo_apr, "promo_apr", 0, 0.3599)
    V.factor_range(factor, "min_payment_factor")
    plan = new_entity({
        "name": name,
        "plan_category": plan_category,
        "deferred_period_months": months,
        "promo_apr": promo_apr,
        "min_payment_factor": factor,
        "status": "DRAFT",
    })
    db.promotional_plans[plan["id"]] = plan
    return success(serialize(plan), status=201)


@app.route("/promotional-plans/<rid>", methods=["GET"])
def get_plan(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    plan = find_or_404(db.promotional_plans, rid)
    return success(serialize(plan), status=200)


@app.route("/promotional-plans", methods=["GET"])
def list_plans():
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    category = request.args.get("plan_category")
    status = request.args.get("status")

    def flt(plan):
        if category is not None and plan["plan_category"] != category:
            return False
        if status is not None and plan["status"] != status:
            return False
        return True
    return list_response(db.promotional_plans.values(), post_filter=flt)


@app.route("/promotional-plans/<rid>/activate", methods=["POST"])
def activate_plan(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    plan = find_or_404(db.promotional_plans, rid)
    if plan["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Plan not DRAFT")
    plan["status"] = "ACTIVE"
    touch(plan)
    return success(serialize(plan), status=200)


@app.route("/promotional-plans/<rid>/retire", methods=["POST"])
def retire_plan(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    plan = find_or_404(db.promotional_plans, rid)
    if plan["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Plan not ACTIVE")
    plan["status"] = "RETIRED"
    touch(plan)
    return success(serialize(plan), status=200)


# =====================================================================
# ProviderPromotion endpoints
# =====================================================================
@app.route("/provider-promotions", methods=["POST"])
def create_provider_promotion():
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    body = V.get_body()
    provider_id = V.require_str(body, "provider_id")
    plan_id = V.require_str(body, "promotional_plan_id")
    eff_start_raw = V.require_str(body, "effective_start")
    eff_end_raw = V.require_str(body, "effective_end")
    # existence left-to-right (priority 4)
    provider = find_or_404(db.providers, provider_id)
    plan = find_or_404(db.promotional_plans, plan_id)
    eff_start = parse_iso(eff_start_raw)
    eff_end = parse_iso(eff_end_raw)
    if eff_start is None or eff_end is None:
        raise err(ERR_INVALID_REQUEST, "effective_start/effective_end must be ISO-8601")
    if not (eff_end > eff_start):
        raise err(ERR_INVALID_REQUEST, "effective_end must be strictly after effective_start")
    # plan must be ACTIVE (state, priority 6)
    if plan["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Plan must be ACTIVE to enroll a provider")
    # temporal overlap with existing ACTIVE promotion for same (provider, plan_category)
    for existing in db.provider_promotions.values():
        if existing["provider_id"] != provider_id or existing["status"] != "ACTIVE":
            continue
        ex_plan = db.promotional_plans[existing["promotional_plan_id"]]
        if ex_plan["plan_category"] != plan["plan_category"]:
            continue
        if eff_start < existing["effective_end"] and existing["effective_start"] < eff_end:
            raise err(ERR_TEMPORAL_CONFLICT,
                      "Overlapping ACTIVE promotion for this provider and plan category")
    promo = new_entity({
        "provider_id": provider_id,
        "promotional_plan_id": plan_id,
        "effective_start": eff_start,
        "effective_end": eff_end,
        "status": "ACTIVE",
    })
    db.provider_promotions[promo["id"]] = promo
    return success(serialize(promo), status=201)


@app.route("/provider-promotions/<rid>", methods=["GET"])
def get_provider_promotion(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    promo = find_or_404(db.provider_promotions, rid)
    if p.role == "Provider":
        check_provider_owns(p, promo["provider_id"])
    return success(serialize(promo), status=200)


@app.route("/provider-promotions", methods=["GET"])
def list_provider_promotions():
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    provider_id = request.args.get("provider_id")
    plan_id = request.args.get("promotional_plan_id")
    status = request.args.get("status")

    def flt(promo):
        if p.role == "Provider" and promo["provider_id"] != p.user_id:
            return False
        if provider_id is not None and promo["provider_id"] != provider_id:
            return False
        if plan_id is not None and promo["promotional_plan_id"] != plan_id:
            return False
        if status is not None and promo["status"] != status:
            return False
        return True
    return list_response(db.provider_promotions.values(), post_filter=flt)


@app.route("/provider-promotions/<rid>/withdraw", methods=["POST"])
def withdraw_provider_promotion(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    promo = find_or_404(db.provider_promotions, rid)
    if promo["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Promotion not ACTIVE")
    promo["status"] = "WITHDRAWN"
    touch(promo)
    return success(serialize(promo), status=200)


# =====================================================================
# CreditApplication endpoints
# =====================================================================
@app.route("/credit-applications", methods=["POST"])
def create_credit_application():
    # Public surface: Anonymous or Provider. Headers not required (priority 1
    # applies_to excludes this endpoint), but if a role is given it must be valid.
    p = authenticate(allow_unauthenticated=True)
    if p.role is not None:
        require_role(p, ["Anonymous", "Provider"])
    body = V.get_body()
    full_name = V.require_str(body, "applicant_full_name")
    ssn_last4 = V.require_str(body, "applicant_ssn_last4")
    income = V.require_int(body, "stated_annual_income_cents")
    requested = V.require_int(body, "requested_limit_cents")
    V.amount_nonnegative(income, "stated_annual_income_cents")
    V.amount_positive(requested, "requested_limit_cents")
    # uniqueness among non-DECLINED applications
    for appn in db.credit_applications.values():
        if appn["applicant_ssn_last4"] == ssn_last4 and appn["status"] != "DECLINED":
            raise err(ERR_DUPLICATE_RESOURCE, "applicant_ssn_last4 already in use")
    provisional = calc.credit_provisional(income, requested)
    appn = new_entity({
        "applicant_full_name": full_name,
        "applicant_ssn_last4": ssn_last4,
        "stated_annual_income_cents": income,
        "requested_limit_cents": requested,
        "provisional_limit_cents": provisional,
        "approved_limit_cents": None,
        "status": "SUBMITTED",
        "patient_account_id": None,
    })
    db.credit_applications[appn["id"]] = appn
    return success(serialize(appn), status=201)


@app.route("/credit-applications/<rid>", methods=["GET"])
def get_credit_application(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    appn = find_or_404(db.credit_applications, rid)
    return success(serialize(appn), status=200)


@app.route("/credit-applications", methods=["GET"])
def list_credit_applications():
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    status = request.args.get("status")
    account_id = request.args.get("patient_account_id")

    def flt(appn):
        if status is not None and appn["status"] != status:
            return False
        if account_id is not None and appn["patient_account_id"] != account_id:
            return False
        return True
    return list_response(db.credit_applications.values(), post_filter=flt)


@app.route("/credit-applications/<rid>/approve", methods=["POST"])
def approve_credit_application(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    appn = find_or_404(db.credit_applications, rid)
    if appn["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application not SUBMITTED")
    approved = calc.credit_final(appn["stated_annual_income_cents"],
                                 appn["requested_limit_cents"],
                                 appn["applicant_full_name"])
    appn["approved_limit_cents"] = approved
    if approved > 0:
        account = new_entity({
            "credit_application_id": appn["id"],
            "account_holder_name": appn["applicant_full_name"],
            "credit_limit_cents": approved,
            "current_balance_cents": 0,
            "available_credit_cents": approved,
            "delinquency_strikes": 0,
            "status": "ACTIVE",
        })
        db.patient_accounts[account["id"]] = account
        appn["patient_account_id"] = account["id"]
        appn["status"] = "APPROVED"
    else:
        appn["status"] = "DECLINED"
    touch(appn)
    return success(serialize(appn), status=200)


@app.route("/credit-applications/<rid>/decline", methods=["POST"])
def decline_credit_application(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    appn = find_or_404(db.credit_applications, rid)
    if appn["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application not SUBMITTED")
    appn["approved_limit_cents"] = 0
    appn["status"] = "DECLINED"
    touch(appn)
    return success(serialize(appn), status=200)


# =====================================================================
# PatientAccount endpoints
# =====================================================================
@app.route("/accounts/<rid>", methods=["GET"])
def get_account(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    check_patient_owns(p, rid)
    account = find_or_404(db.patient_accounts, rid)
    return success(serialize(account), status=200)


@app.route("/accounts", methods=["GET"])
def list_accounts():
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    status = request.args.get("status")
    app_id = request.args.get("credit_application_id")

    def flt(acc):
        if status is not None and acc["status"] != status:
            return False
        if app_id is not None and acc["credit_application_id"] != app_id:
            return False
        return True
    return list_response(db.patient_accounts.values(), post_filter=flt)


@app.route("/accounts/<rid>/financed-purchases", methods=["GET"])
def account_financed_purchases(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    check_patient_owns(p, rid)
    find_or_404(db.patient_accounts, rid)
    settlement_status = request.args.get("settlement_status")
    promo_status = request.args.get("promo_status")

    def flt(fp):
        if fp["patient_account_id"] != rid:
            return False
        if settlement_status is not None and fp["settlement_status"] != settlement_status:
            return False
        if promo_status is not None and fp["promo_status"] != promo_status:
            return False
        return True
    return list_response(db.financed_purchases.values(), post_filter=flt)


@app.route("/accounts/<rid>/payments", methods=["GET"])
def account_payments(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    check_patient_owns(p, rid)
    find_or_404(db.patient_accounts, rid)
    status = request.args.get("status")

    def flt(pay):
        if pay["patient_account_id"] != rid:
            return False
        if status is not None and pay["status"] != status:
            return False
        return True
    return list_response(db.payments.values(), post_filter=flt)


@app.route("/accounts/<rid>/statements", methods=["GET"])
def account_statements(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    check_patient_owns(p, rid)
    find_or_404(db.patient_accounts, rid)
    status = request.args.get("status")

    def flt(stmt):
        if stmt["patient_account_id"] != rid:
            return False
        if status is not None and stmt["status"] != status:
            return False
        return True
    return list_response(db.billing_statements.values(), post_filter=flt)


@app.route("/accounts/<rid>/autopay-enrollments", methods=["GET"])
def account_autopay(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    check_patient_owns(p, rid)
    find_or_404(db.patient_accounts, rid)
    status = request.args.get("status")

    def flt(ae):
        if ae["patient_account_id"] != rid:
            return False
        if status is not None and ae["status"] != status:
            return False
        return True
    return list_response(db.autopay_enrollments.values(), post_filter=flt)


@app.route("/accounts/<rid>/close", methods=["POST"])
def close_account(rid):
    p = authenticate()
    require_role(p, ["Patient"])
    check_patient_owns(p, rid)
    account = find_or_404(db.patient_accounts, rid)
    if account["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Account not ACTIVE")
    if account["current_balance_cents"] != 0:
        raise err(ERR_INVALID_STATE, "Account balance is not zero")
    for fp in db.financed_purchases.values():
        if fp["patient_account_id"] == rid and fp["settlement_status"] == "AUTHORIZED":
            raise err(ERR_INVALID_STATE, "Account has AUTHORIZED purchases")
    account["status"] = "CLOSED"
    for ae in db.autopay_enrollments.values():
        if ae["patient_account_id"] == rid and ae["status"] in ("ACTIVE", "PAUSED"):
            ae["status"] = "REVOKED"
            touch(ae)
    touch(account)
    return success(serialize(account), status=200)


# =====================================================================
# AutopayEnrollment endpoints
# =====================================================================
@app.route("/autopay-enrollments", methods=["POST"])
def create_autopay():
    p = authenticate()
    require_role(p, ["Patient"])
    body = V.get_body()
    account_id = V.require_str(body, "patient_account_id")
    funding_token = V.require_str(body, "funding_token")
    draft_day = V.require_int(body, "draft_day_of_month")
    check_patient_owns(p, account_id)
    account = find_or_404(db.patient_accounts, account_id)
    V.range_inclusive(draft_day, "draft_day_of_month", 1, 28)
    # uniqueness: at most one ACTIVE per account
    for ae in db.autopay_enrollments.values():
        if ae["patient_account_id"] == account_id and ae["status"] == "ACTIVE":
            raise err(ERR_DUPLICATE_RESOURCE, "An ACTIVE autopay enrollment already exists")
    enrollment = new_entity({
        "patient_account_id": account_id,
        "funding_token": funding_token,
        "draft_day_of_month": draft_day,
        "status": "ACTIVE",
    })
    db.autopay_enrollments[enrollment["id"]] = enrollment
    return success(serialize(enrollment), status=201)


@app.route("/autopay-enrollments/<rid>", methods=["GET"])
def get_autopay(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    enrollment = find_or_404(db.autopay_enrollments, rid)
    if p.role == "Patient":
        check_patient_owns(p, enrollment["patient_account_id"])
    return success(serialize(enrollment), status=200)


def _autopay_owned(rid):
    enrollment = db.autopay_enrollments.get(rid)
    return enrollment


@app.route("/autopay-enrollments/<rid>/pause", methods=["POST"])
def pause_autopay(rid):
    p = authenticate()
    require_role(p, ["Patient"])
    enrollment = find_or_404(db.autopay_enrollments, rid)
    check_patient_owns(p, enrollment["patient_account_id"])
    if enrollment["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Enrollment not ACTIVE")
    enrollment["status"] = "PAUSED"
    touch(enrollment)
    return success(serialize(enrollment), status=200)


@app.route("/autopay-enrollments/<rid>/resume", methods=["POST"])
def resume_autopay(rid):
    p = authenticate()
    require_role(p, ["Patient"])
    enrollment = find_or_404(db.autopay_enrollments, rid)
    check_patient_owns(p, enrollment["patient_account_id"])
    if enrollment["status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, "Enrollment not PAUSED")
    account = db.patient_accounts.get(enrollment["patient_account_id"])
    if account is None or account["status"] not in ("ACTIVE", "DELINQUENT"):
        raise err(ERR_INVALID_STATE, "Parent account not ACTIVE/DELINQUENT")
    enrollment["status"] = "ACTIVE"
    touch(enrollment)
    return success(serialize(enrollment), status=200)


@app.route("/autopay-enrollments/<rid>/revoke", methods=["POST"])
def revoke_autopay(rid):
    p = authenticate()
    require_role(p, ["Patient"])
    enrollment = find_or_404(db.autopay_enrollments, rid)
    check_patient_owns(p, enrollment["patient_account_id"])
    if enrollment["status"] not in ("ACTIVE", "PAUSED"):
        raise err(ERR_INVALID_STATE, "Enrollment not ACTIVE/PAUSED")
    enrollment["status"] = "REVOKED"
    touch(enrollment)
    return success(serialize(enrollment), status=200)


# =====================================================================
# FinancedPurchase endpoints
# =====================================================================
@app.route("/financed-purchases", methods=["POST"])
def authorize_purchase():
    p = authenticate()
    require_role(p, ["Provider"])
    body = V.get_body()
    provider_id = V.require_str(body, "provider_id")
    account_id = V.require_str(body, "patient_account_id")
    promo_id = V.require_str(body, "provider_promotion_id")
    principal = V.require_int(body, "principal_cents")
    expected_version = V.require_int(body, "expected_patient_account_version")
    # ownership (priority 3): provider must own provider_id
    check_provider_owns(p, provider_id)
    # existence left-to-right (priority 4)
    provider = find_or_404(db.providers, provider_id)
    account = find_or_404(db.patient_accounts, account_id)
    promo = find_or_404(db.provider_promotions, promo_id)
    # range (ERR_VALIDATION_AMOUNT)
    V.amount_positive(principal, "principal_cents")
    # OCC (priority 7)
    if expected_version != account["version"]:
        raise err(ERR_STALE_VERSION, "Stale patient account version")
    # referential coherence (priority 8): promo belongs to provider and is ACTIVE
    if promo["provider_id"] != provider_id:
        raise err(ERR_REFERENTIAL_MISMATCH, "Promotion not owned by this provider")
    if promo["status"] != "ACTIVE":
        raise err(ERR_REFERENTIAL_MISMATCH, "Promotion is not ACTIVE")
    # temporal coherence (priority 9): clock in [effective_start, effective_end)
    now = db.clock.now()
    if not (promo["effective_start"] <= now < promo["effective_end"]):
        raise err(ERR_TEMPORAL_CONFLICT, "Authorization clock outside the promo window")
    # eligibility gate (priority 10): provider ENROLLED + account ACTIVE
    if provider["status"] != "ENROLLED":
        raise err(ERR_ACCOUNT_NOT_ELIGIBLE, "Provider is not ENROLLED")
    if account["status"] != "ACTIVE":
        raise err(ERR_ACCOUNT_NOT_ELIGIBLE, "Account is not ACTIVE")
    # fiscal capacity (priority 11)
    if principal > account["available_credit_cents"]:
        raise err(ERR_INSUFFICIENT_CREDIT, "Principal exceeds available credit")
    # compute promo window
    plan = db.promotional_plans[promo["promotional_plan_id"]]
    promo_start = now
    promo_end = add_months(promo_start, plan["deferred_period_months"])
    purchase = new_entity({
        "provider_id": provider_id,
        "patient_account_id": account_id,
        "provider_promotion_id": promo_id,
        "principal_cents": principal,
        "promo_start": promo_start,
        "promo_end": promo_end,
        "principal_paid_cents": 0,
        "deferred_interest_posted_cents": 0,
        "settlement_status": "AUTHORIZED",
        "promo_status": "DEFERRED",
        "_interest_paid_cents": 0,
    })
    db.financed_purchases[purchase["id"]] = purchase
    # account side effects
    account["available_credit_cents"] -= principal
    account["current_balance_cents"] += principal
    touch(account)
    return success(serialize(purchase), status=201)


@app.route("/financed-purchases/<rid>", methods=["GET"])
def get_purchase(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider", "Patient"])
    purchase = find_or_404(db.financed_purchases, rid)
    if p.role == "Provider":
        check_provider_owns(p, purchase["provider_id"])
    elif p.role == "Patient":
        check_patient_owns(p, purchase["patient_account_id"])
    return success(serialize(purchase), status=200)


@app.route("/financed-purchases", methods=["GET"])
def list_purchases():
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    provider_id = request.args.get("provider_id")
    account_id = request.args.get("patient_account_id")
    promo_id = request.args.get("provider_promotion_id")
    settlement_status = request.args.get("settlement_status")
    promo_status = request.args.get("promo_status")

    def flt(fp):
        if p.role == "Provider" and fp["provider_id"] != p.user_id:
            return False
        if provider_id is not None and fp["provider_id"] != provider_id:
            return False
        if account_id is not None and fp["patient_account_id"] != account_id:
            return False
        if promo_id is not None and fp["provider_promotion_id"] != promo_id:
            return False
        if settlement_status is not None and fp["settlement_status"] != settlement_status:
            return False
        if promo_status is not None and fp["promo_status"] != promo_status:
            return False
        return True
    return list_response(db.financed_purchases.values(), post_filter=flt)


@app.route("/financed-purchases/<rid>/payoff-projection", methods=["GET"])
def payoff_projection(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider", "Patient"])
    purchase = find_or_404(db.financed_purchases, rid)
    if p.role == "Provider":
        check_provider_owns(p, purchase["provider_id"])
    elif p.role == "Patient":
        check_patient_owns(p, purchase["patient_account_id"])
    projected, remaining, days = calc.projected_forfeit_interest(purchase, db.clock.now())
    return success({
        "projected_forfeit_interest_cents": projected,
        "principal_remaining_cents": remaining,
        "days_remaining": days,
    }, status=200)


@app.route("/financed-purchases/<rid>/settle", methods=["POST"])
def settle_purchase(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    purchase = find_or_404(db.financed_purchases, rid)
    body = V.get_body()
    expected_version = V.require_int(body, "expected_financed_purchase_version")
    # state (priority 6)
    if purchase["settlement_status"] != "AUTHORIZED":
        raise err(ERR_INVALID_STATE, "Purchase not AUTHORIZED")
    # OCC (priority 7)
    if expected_version != purchase["version"]:
        raise err(ERR_STALE_VERSION, "Stale financed purchase version")
    provider = db.providers.get(purchase["provider_id"])
    account = db.patient_accounts.get(purchase["patient_account_id"])
    # eligibility gate (priority 10): provider ENROLLED + account ACTIVE|DELINQUENT
    if provider is None or provider["status"] != "ENROLLED":
        raise err(ERR_ACCOUNT_NOT_ELIGIBLE, "Provider is not ENROLLED")
    if account is None or account["status"] not in ("ACTIVE", "DELINQUENT"):
        raise err(ERR_ACCOUNT_NOT_ELIGIBLE, "Account not ACTIVE/DELINQUENT")
    settlement = svc.create_settlement(purchase, provider)
    purchase["settlement_status"] = "SETTLED"
    touch(purchase)
    return success(serialize(settlement), status=201)


# =====================================================================
# Settlement endpoints
# =====================================================================
@app.route("/settlements/<rid>", methods=["GET"])
def get_settlement(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    settlement = find_or_404(db.settlements, rid)
    if p.role == "Provider":
        check_provider_owns(p, settlement["provider_id"])
    return success(serialize(settlement), status=200)


@app.route("/settlements", methods=["GET"])
def list_settlements():
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    provider_id = request.args.get("provider_id")
    fp_id = request.args.get("financed_purchase_id")
    status = request.args.get("status")

    def flt(s):
        if p.role == "Provider" and s["provider_id"] != p.user_id:
            return False
        if provider_id is not None and s["provider_id"] != provider_id:
            return False
        if fp_id is not None and s["financed_purchase_id"] != fp_id:
            return False
        if status is not None and s["status"] != status:
            return False
        return True
    return list_response(db.settlements.values(), post_filter=flt)


@app.route("/settlements/<rid>/pay", methods=["POST"])
def pay_settlement(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    settlement = find_or_404(db.settlements, rid)
    if settlement["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Settlement not PENDING")
    provider = db.providers.get(settlement["provider_id"])
    if provider is None or provider["status"] != "ENROLLED":
        raise err(ERR_ACCOUNT_NOT_ELIGIBLE, "Provider is not ENROLLED")
    settlement["status"] = "PAID"
    settlement["_was_paid"] = True
    settlement["_paid_month"] = (db.clock.now().year, db.clock.now().month)
    touch(settlement)
    svc.recompute_provider_volumes(provider)
    touch(provider)
    return success(serialize(settlement), status=200)


# =====================================================================
# Payment endpoints
# =====================================================================
def _post_payment(account, amount, payment_type):
    payment = new_entity({
        "patient_account_id": account["id"],
        "amount_cents": amount,
        "payment_type": payment_type,
        "posted_at": db.clock.now(),
        "allocation": [],
        "status": "POSTED",
        "_flipped_purchase_ids": [],
    })
    db.payments[payment["id"]] = payment
    svc.allocate_payment(account, payment)
    return payment


@app.route("/payments", methods=["POST"])
def create_payment():
    p = authenticate()
    require_role(p, ["Patient"])
    body = V.get_body()
    account_id = V.require_str(body, "patient_account_id")
    amount = V.require_int(body, "amount_cents")
    payment_type = V.require_enum(body, "payment_type", {"AUTOPAY", "MANUAL", "PAYOFF"})
    check_patient_owns(p, account_id)
    account = find_or_404(db.patient_accounts, account_id)
    V.amount_positive(amount, "amount_cents")
    # eligibility gate (priority 10): DEFAULTED rejects all but PAYOFF; CLOSED never debited
    if account["status"] == "CLOSED":
        raise err(ERR_ACCOUNT_NOT_ELIGIBLE, "Account is CLOSED")
    if account["status"] == "DEFAULTED" and payment_type != "PAYOFF":
        raise err(ERR_ACCOUNT_NOT_ELIGIBLE, "DEFAULTED account accepts only PAYOFF")
    # fiscal capacity (priority 11): MANUAL/AUTOPAY must not exceed balance; PAYOFF may equal
    if payment_type in ("MANUAL", "AUTOPAY"):
        if amount > account["current_balance_cents"]:
            raise err(ERR_INSUFFICIENT_CREDIT, "Amount exceeds current balance")
    else:  # PAYOFF
        if amount > account["current_balance_cents"]:
            raise err(ERR_INSUFFICIENT_CREDIT, "PAYOFF exceeds current balance")
    payment = _post_payment(account, amount, payment_type)
    return success(serialize(payment), status=201)


@app.route("/payments/<rid>", methods=["GET"])
def get_payment(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    payment = find_or_404(db.payments, rid)
    if p.role == "Patient":
        check_patient_owns(p, payment["patient_account_id"])
    return success(serialize(payment), status=200)


@app.route("/payments", methods=["GET"])
def list_payments():
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    account_id = request.args.get("patient_account_id")
    status = request.args.get("status")
    payment_type = request.args.get("payment_type")

    def flt(pay):
        if p.role == "Patient" and pay["patient_account_id"] != p.user_id:
            return False
        if account_id is not None and pay["patient_account_id"] != account_id:
            return False
        if status is not None and pay["status"] != status:
            return False
        if payment_type is not None and pay["payment_type"] != payment_type:
            return False
        return True
    return list_response(db.payments.values(), post_filter=flt)


@app.route("/payments/<rid>/reverse", methods=["POST"])
def reverse_payment_endpoint(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin"])
    payment = find_or_404(db.payments, rid)
    if payment["status"] != "POSTED":
        raise err(ERR_INVALID_STATE, "Payment not POSTED")
    if payment["payment_type"] == "PAYOFF":
        raise err(ERR_PAYOFF_NOT_REVERSIBLE, "PAYOFF payments cannot be reversed")
    account = db.patient_accounts.get(payment["patient_account_id"])
    svc.reverse_payment(account, payment)
    payment["status"] = "REVERSED"
    touch(payment)
    return success(serialize(payment), status=200)


# =====================================================================
# Refund endpoints
# =====================================================================
@app.route("/refunds", methods=["POST"])
def create_refund():
    p = authenticate()
    require_role(p, ["Provider"])
    body = V.get_body()
    fp_id = V.require_str(body, "financed_purchase_id")
    refund_kind = V.require_enum(body, "refund_kind", {"VOID", "REFUND"})
    amount = V.require_int(body, "amount_cents")
    purchase = find_or_404(db.financed_purchases, fp_id)
    # ownership (priority 3): provider must own the purchase
    check_provider_owns(p, purchase["provider_id"])
    V.amount_positive(amount, "amount_cents")
    # state (priority 6): VOID requires AUTHORIZED; REFUND requires SETTLED
    if refund_kind == "VOID" and purchase["settlement_status"] != "AUTHORIZED":
        raise err(ERR_INVALID_STATE, "VOID allowed only while AUTHORIZED")
    if refund_kind == "REFUND" and purchase["settlement_status"] != "SETTLED":
        raise err(ERR_INVALID_STATE, "REFUND allowed only while SETTLED")
    # referential (priority 8): amount must equal principal (full compensation)
    if amount != purchase["principal_cents"]:
        raise err(ERR_REFERENTIAL_MISMATCH, "amount_cents must equal the purchase principal")
    account = db.patient_accounts.get(purchase["patient_account_id"])
    refund = new_entity({
        "financed_purchase_id": fp_id,
        "refund_kind": refund_kind,
        "amount_cents": amount,
        "status": "APPLIED",
    })
    db.refunds[refund["id"]] = refund
    if refund_kind == "VOID":
        svc.apply_void(purchase, account)
    else:
        svc.apply_refund(purchase, account)
    touch(account)
    return success(serialize(refund), status=201)


@app.route("/refunds/<rid>", methods=["GET"])
def get_refund(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    refund = find_or_404(db.refunds, rid)
    purchase = db.financed_purchases.get(refund["financed_purchase_id"])
    if p.role == "Provider" and purchase is not None:
        check_provider_owns(p, purchase["provider_id"])
    return success(serialize(refund), status=200)


@app.route("/refunds", methods=["GET"])
def list_refunds():
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Provider"])
    fp_id = request.args.get("financed_purchase_id")
    refund_kind = request.args.get("refund_kind")

    def flt(refund):
        purchase = db.financed_purchases.get(refund["financed_purchase_id"])
        if p.role == "Provider":
            if purchase is None or purchase["provider_id"] != p.user_id:
                return False
        if fp_id is not None and refund["financed_purchase_id"] != fp_id:
            return False
        if refund_kind is not None and refund["refund_kind"] != refund_kind:
            return False
        return True
    return list_response(db.refunds.values(), post_filter=flt)


# =====================================================================
# BillingStatement endpoint
# =====================================================================
@app.route("/statements/<rid>", methods=["GET"])
def get_statement(rid):
    p = authenticate()
    require_role(p, ["PlatformAdmin", "Patient"])
    stmt = find_or_404(db.billing_statements, rid)
    if p.role == "Patient":
        check_patient_owns(p, stmt["patient_account_id"])
    return success(serialize(stmt), status=200)


# =====================================================================
# Test-driving endpoints (/_clock, /_cycle, /_autopay)
# These do not require auth headers (PRD §2.1), but are PlatformAdmin-scoped;
# if a role is supplied it must be PlatformAdmin.
# =====================================================================
def _admin_test_auth():
    p = authenticate(allow_unauthenticated=True)
    if p.role is not None:
        require_role(p, ["PlatformAdmin"])
    return p


@app.route("/_clock/set", methods=["POST"])
def clock_set():
    _admin_test_auth()
    body = V.get_body()
    to_iso = V.require_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO-8601")
    db.clock.set(dt)
    return success({"current_utc": db.iso(db.clock.now())}, status=200)


@app.route("/_clock/advance", methods=["POST"])
def clock_advance():
    _admin_test_auth()
    body = V.get_body()
    to_iso = V.require_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO-8601")
    db.clock.set(dt)
    forfeited = []
    # For every DEFERRED purchase whose promo_end <= new clock and principal not
    # fully paid and not refunded/void: forfeit (PRD §3.8).
    for purchase in sorted(db.financed_purchases.values(),
                           key=lambda x: (x["promo_end"], x["created_at"], x["_seq"])):
        if purchase["promo_status"] != "DEFERRED":
            continue
        if purchase["settlement_status"] in ("REFUNDED", "VOID"):
            continue
        if purchase["promo_end"] > db.clock.now():
            continue
        if purchase["principal_paid_cents"] >= purchase["principal_cents"]:
            continue
        interest = calc.deferred_interest(purchase)
        purchase["deferred_interest_posted_cents"] = interest
        purchase["promo_status"] = "INTEREST_FORFEITED"
        touch(purchase)
        account = db.patient_accounts.get(purchase["patient_account_id"])
        if account is not None:
            account["current_balance_cents"] += interest
            touch(account)
        forfeited.append(purchase["id"])
    return success({"current_utc": db.iso(db.clock.now()),
                    "forfeited_purchase_ids": forfeited}, status=200)


@app.route("/_cycle/open_statement", methods=["POST"])
def open_statement():
    _admin_test_auth()
    body = V.get_body()
    account_id = V.require_str(body, "patient_account_id")
    period_start_raw = V.require_str(body, "period_start")
    period_end_raw = V.require_str(body, "period_end")
    account = find_or_404(db.patient_accounts, account_id)
    period_start = parse_iso(period_start_raw)
    period_end = parse_iso(period_end_raw)
    if period_start is None or period_end is None:
        raise err(ERR_INVALID_REQUEST, "period_start/period_end must be ISO-8601")
    # closed-adjacency: if a prior statement exists, period_start must equal prior.period_end + 1 day
    prior = _latest_statement(account_id)
    if prior is not None:
        from datetime import timedelta
        required_start = prior["period_end"] + timedelta(days=1)
        if period_start != required_start:
            raise err(ERR_TEMPORAL_CONFLICT,
                      "period_start must equal prior period_end + 1 day")
    stmt = new_entity({
        "patient_account_id": account_id,
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance_cents": account["current_balance_cents"],
        "minimum_payment_due_cents": None,
        "amount_paid_in_cycle_cents": 0,
        "min_payment_satisfied": None,
        "due_date": period_end,
        "status": "OPEN",
    })
    db.billing_statements[stmt["id"]] = stmt
    return success(serialize(stmt), status=201)


def _latest_statement(account_id):
    stmts = [s for s in db.billing_statements.values()
             if s["patient_account_id"] == account_id]
    if not stmts:
        return None
    return max(stmts, key=lambda s: (s["period_end"], s["_seq"]))


def _open_stmt(account_id):
    for s in db.billing_statements.values():
        if s["patient_account_id"] == account_id and s["status"] == "OPEN":
            return s
    return None


@app.route("/_cycle/close_statement", methods=["POST"])
def close_statement():
    _admin_test_auth()
    body = V.get_body()
    account_id = V.require_str(body, "patient_account_id")
    account = find_or_404(db.patient_accounts, account_id)
    stmt = _open_stmt(account_id)
    if stmt is None:
        raise err(ERR_INVALID_STATE, "No OPEN statement for this account")
    if db.clock.now() < stmt["period_end"]:
        raise err(ERR_INVALID_STATE, "Clock is before period_end")
    # compute figures
    paid = svc._amount_paid_in_cycle(account_id, stmt["period_start"], stmt["period_end"])
    closing_balance = account["current_balance_cents"]
    minimum = calc.minimum_payment(account, closing_balance)
    satisfied = paid >= minimum
    stmt["amount_paid_in_cycle_cents"] = paid
    stmt["minimum_payment_due_cents"] = minimum
    stmt["min_payment_satisfied"] = satisfied
    stmt["status"] = "CLOSED"
    touch(stmt)
    # drive delinquency machine (PRD §3.7)
    _drive_delinquency(account, satisfied)
    # open next statement (period_start = period_end + 1 day, PRD §3.7). The
    # PRD fixes only the next period_start; the next period_end follows the
    # natural monthly billing cadence — the last calendar day of the month that
    # contains period_start — so repeated closes can drive the delinquency
    # machine on month boundaries.
    from datetime import timedelta
    next_start = stmt["period_end"] + timedelta(days=1)
    next_end = end_of_month(next_start)
    next_stmt = new_entity({
        "patient_account_id": account_id,
        "period_start": next_start,
        "period_end": next_end,
        "opening_balance_cents": account["current_balance_cents"],
        "minimum_payment_due_cents": None,
        "amount_paid_in_cycle_cents": 0,
        "min_payment_satisfied": None,
        "due_date": next_end,
        "status": "OPEN",
    })
    db.billing_statements[next_stmt["id"]] = next_stmt
    return success(serialize(stmt), status=200)


def _drive_delinquency(account, satisfied):
    if account["status"] in ("DEFAULTED", "CLOSED"):
        return
    if satisfied:
        account["delinquency_strikes"] = 0
        if account["status"] == "DELINQUENT":
            account["status"] = "ACTIVE"
        return
    # unsatisfied
    account["delinquency_strikes"] += 1
    strikes = account["delinquency_strikes"]
    if strikes >= 3:
        account["status"] = "DEFAULTED"
        for ae in db.autopay_enrollments.values():
            if ae["patient_account_id"] == account["id"] and ae["status"] == "ACTIVE":
                ae["status"] = "REVOKED"
                touch(ae)
    else:
        account["status"] = "DELINQUENT"


@app.route("/_autopay/run", methods=["POST"])
def autopay_run():
    _admin_test_auth()
    body = V.get_body()
    enrollment_id = V.require_str(body, "autopay_enrollment_id")
    enrollment = find_or_404(db.autopay_enrollments, enrollment_id)
    account = db.patient_accounts.get(enrollment["patient_account_id"])
    if account is None:
        raise err(ERR_NOT_FOUND, "Account not found")
    stmt = _open_stmt(account["id"])
    open_min = 0
    if stmt is not None:
        open_min = calc.minimum_payment(account, account["current_balance_cents"])
    draft_amount = min(open_min, account["current_balance_cents"])
    payment = _post_payment(account, draft_amount, "AUTOPAY")
    return success(serialize(payment), status=201)


# =====================================================================
# Entry point
# =====================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    # Serve through waitress, a production WSGI server. Under the per-test restart
    # loop (8 rounds concurrently) the Werkzeug dev server intermittently produces
    # client-side BadStatusLine errors from keep-alive/connection races during
    # shutdown; waitress handles connection lifecycle robustly and eliminates that
    # flakiness. Fall back to the Flask dev server if waitress is unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8,
              channel_timeout=60, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
