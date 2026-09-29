"""Advertiser onboarding, credit exposure and the agency umbrella (PRD 3.1)."""
from flask import Blueprint

from core import F, db, fail, insert, new_row, now, ok, rows, touch
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("advertisers", __name__)

ROLES_ALL = ("NetworkAdmin", "AccountManager", "CreditAnalyst",
             "MeasurementAnalyst", "BillingOps")
SERVICE_MODELS = ("SELF_SERVE", "MANAGED")
SUSPENSION_REASONS = ("CREDIT_BREACH", "COMPLIANCE", "MANUAL")

ONBOARDING_TRANSITIONS = {
    "submit": {"DRAFT": "KYC_REVIEW", "CREDIT_HOLD": "KYC_REVIEW"},
    "START_REVIEW": {"SUBMITTED": "KYC_REVIEW"},
    "APPROVE": {"KYC_REVIEW": "ACTIVE"},
    "HOLD": {"KYC_REVIEW": "CREDIT_HOLD"},
    "REJECT": {"KYC_REVIEW": "REJECTED"},
    "suspend": {"ACTIVE": "SUSPENDED"},
    "reinstate": {"SUSPENDED": "ACTIVE"},
    "terminate": {"ACTIVE": "TERMINATED", "SUSPENDED": "TERMINATED"},
}

LIST_FILTERS = (
    ("parent_advertiser_id", "parent_advertiser_id", "string"),
    ("onboarding_status", "onboarding_status", "string"),
    ("service_model", "service_model", "string"),
    ("brand_code", "brand_code", "string"),
)


# ---------------------------------------------------------------------------
def _service_model_check(service_model, fee_pct, manager_id):
    """Rejection check 45."""
    if service_model == "SELF_SERVE":
        if fee_pct != 0.0 or manager_id is not None:
            fail("ERR_SERVICE_MODEL_CONFLICT",
                 "A SELF_SERVE advertiser carries a zero fee and no account "
                 "manager.")
    else:
        if manager_id is None:
            fail("ERR_SERVICE_MODEL_CONFLICT",
                 "A MANAGED advertiser requires account_manager_user_id.")


def _parent_check(own_id, parent_id):
    """Rejection check 63."""
    if parent_id is None:
        return
    if own_id is not None and parent_id == own_id:
        fail("ERR_PARENT_ADVERTISER_INVALID",
             "An advertiser may not be its own parent.")
    parent = db.advertisers.get(parent_id)
    if parent.get("parent_advertiser_id") is not None:
        fail("ERR_PARENT_ADVERTISER_INVALID",
             "The umbrella is exactly one level deep.")
    if parent["onboarding_status"] != "ACTIVE":
        fail("ERR_PARENT_ADVERTISER_INVALID", "The parent advertiser is not ACTIVE.")


# ---------------------------------------------------------------------------
@bp.post("/rmn/advertisers")
def create_advertiser():
    specs = (
        F("legal_name", "string", required=True),
        F("brand_code", "string", required=True),
        F("service_model", "enum", enum=SERVICE_MODELS,
          default="SELF_SERVE", has_default=True),
        F("credit_limit_cents", "integer", minimum=0, default=0, has_default=True),
        F("parent_advertiser_id", "string", nullable=True),
        F("account_manager_user_id", "string", nullable=True),
        F("managed_service_fee_pct", "number", minimum=0.0, maximum=0.20,
          default=0.0, has_default=True),
        F("self_serve_daily_spend_cap_cents", "integer", minimum=0,
          default=500000, has_default=True),
    )
    ctx = guard(("NetworkAdmin", "AccountManager"), body_specs=specs,
                body_refs=(("advertiser", "parent_advertiser_id"),))
    data = ctx.data
    H.require_brand_code(data["brand_code"])
    _service_model_check(data["service_model"], data["managed_service_fee_pct"],
                         data.get("account_manager_user_id"))
    if any(a["brand_code"] == data["brand_code"] for a in db.advertisers.values()):
        fail("ERR_DUPLICATE_BRAND_CODE", "brand_code is already in use.")
    _parent_check(None, data.get("parent_advertiser_id"))

    row = new_row()
    row.update({
        "legal_name": data["legal_name"],
        "brand_code": data["brand_code"],
        "service_model": data["service_model"],
        "onboarding_status": "DRAFT",
        "parent_advertiser_id": data.get("parent_advertiser_id"),
        "account_manager_user_id": data.get("account_manager_user_id"),
        "credit_limit_cents": data["credit_limit_cents"],
        "kyc_document_count": 0,
        "suspension_reason": "NONE",
        "self_serve_daily_spend_cap_cents": data["self_serve_daily_spend_cap_cents"],
        "managed_service_fee_pct": data["managed_service_fee_pct"],
        "onboarding_submitted_by_user_id": None,
        "kyc_decided_by_user_id": None,
    })
    insert("advertiser", row)
    return ok(D.ser_advertiser(row), 201)


@bp.get("/rmn/advertisers")
def list_advertisers():
    ctx = guard(ROLES_ALL, paginated=True)
    return H.respond_list(ctx, "advertiser", rows("advertiser"), LIST_FILTERS)


@bp.get("/rmn/advertisers/<aid>")
def read_advertiser(aid):
    ctx = guard(ROLES_ALL + ("AdvertiserUser",),
                path_refs=(("advertiser", aid),))
    return ok(D.ser_advertiser(ctx.get("advertiser")))


@bp.patch("/rmn/advertisers/<aid>")
def patch_advertiser(aid):
    specs = (
        F("legal_name", "string"),
        F("service_model", "enum", enum=SERVICE_MODELS),
        F("credit_limit_cents", "integer", minimum=0),
        F("parent_advertiser_id", "string", nullable=True),
        F("account_manager_user_id", "string", nullable=True),
        F("managed_service_fee_pct", "number", minimum=0.0, maximum=0.20),
        F("self_serve_daily_spend_cap_cents", "integer", minimum=0),
    )
    ctx = guard(("NetworkAdmin", "AccountManager"),
                path_refs=(("advertiser", aid),), body_specs=specs,
                body_refs=(("advertiser", "parent_advertiser_id"),),
                mutating=True)
    adv = ctx.get("advertiser")
    if adv["onboarding_status"] not in ("DRAFT", "KYC_REVIEW", "CREDIT_HOLD",
                                       "ACTIVE"):
        fail("ERR_INVALID_ONBOARDING_TRANSITION",
             "An advertiser in %s may not be amended."
             % adv["onboarding_status"])
    data = ctx.data
    service_model = data.get("service_model", adv["service_model"])
    fee_pct = data.get("managed_service_fee_pct", adv["managed_service_fee_pct"])
    manager = (data["account_manager_user_id"]
               if "account_manager_user_id" in data
               else adv["account_manager_user_id"])
    parent = (data["parent_advertiser_id"] if "parent_advertiser_id" in data
              else adv["parent_advertiser_id"])
    _service_model_check(service_model, fee_pct, manager)
    _parent_check(adv["id"], parent)

    adv["legal_name"] = data.get("legal_name", adv["legal_name"])
    adv["service_model"] = service_model
    adv["credit_limit_cents"] = data.get("credit_limit_cents",
                                         adv["credit_limit_cents"])
    adv["parent_advertiser_id"] = parent
    adv["account_manager_user_id"] = manager
    adv["managed_service_fee_pct"] = fee_pct
    adv["self_serve_daily_spend_cap_cents"] = data.get(
        "self_serve_daily_spend_cap_cents",
        adv["self_serve_daily_spend_cap_cents"])
    touch(adv)
    return ok(D.ser_advertiser(adv))


@bp.post("/rmn/advertisers/<aid>/submit-onboarding")
def submit_onboarding(aid):
    specs = (F("kyc_document_count", "integer", required=True, minimum=0),)
    ctx = guard(("NetworkAdmin", "AccountManager", "AdvertiserUser"),
                path_refs=(("advertiser", aid),), body_specs=specs,
                mutating=True)
    adv = ctx.get("advertiser")
    target = H.require_transition(adv["onboarding_status"],
                                  ONBOARDING_TRANSITIONS["submit"],
                                  "ERR_INVALID_ONBOARDING_TRANSITION",
                                  "onboarding_status")
    minimum = 3 if adv["onboarding_status"] == "CREDIT_HOLD" else 2
    if ctx.data["kyc_document_count"] < minimum:
        fail("ERR_KYC_DOCUMENTS_INSUFFICIENT",
             "At least %d KYC documents are required." % minimum)
    _service_model_check(adv["service_model"], adv["managed_service_fee_pct"],
                         adv["account_manager_user_id"])
    _parent_check(adv["id"], adv["parent_advertiser_id"])

    adv["kyc_document_count"] = ctx.data["kyc_document_count"]
    adv["onboarding_submitted_by_user_id"] = ctx.user_id
    adv["onboarding_status"] = target
    touch(adv)
    return ok(D.ser_advertiser(adv))


@bp.post("/rmn/advertisers/<aid>/kyc-decision")
def kyc_decision(aid):
    specs = (
        F("decision", "enum", required=True,
          enum=("APPROVE", "HOLD", "REJECT", "START_REVIEW")),
        F("decision_note", "string"),
        F("adjusted_credit_limit_cents", "integer", minimum=0),
    )
    ctx = guard(("NetworkAdmin", "CreditAnalyst"),
                path_refs=(("advertiser", aid),), body_specs=specs,
                mutating=True)
    adv = ctx.get("advertiser")
    decision = ctx.data["decision"]
    target = H.require_transition(adv["onboarding_status"],
                                  ONBOARDING_TRANSITIONS[decision],
                                  "ERR_INVALID_ONBOARDING_TRANSITION",
                                  "onboarding_status")
    if ctx.user_id == adv["onboarding_submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The operator that submitted onboarding may not decide it.")
    if "adjusted_credit_limit_cents" in ctx.data:
        adv["credit_limit_cents"] = ctx.data["adjusted_credit_limit_cents"]
    if decision == "APPROVE":
        if (adv["credit_limit_cents"] < D.MIN_APPROVAL_CREDIT_LIMIT_CENTS
                and adv["parent_advertiser_id"] is None):
            fail("ERR_AMOUNT_BELOW_MINIMUM",
                 "Approval requires a credit limit of at least %d cents or an "
                 "umbrella parent." % D.MIN_APPROVAL_CREDIT_LIMIT_CENTS)
        adv["suspension_reason"] = "NONE"
    adv["kyc_decided_by_user_id"] = ctx.user_id
    adv["onboarding_status"] = target
    touch(adv)
    return ok(D.ser_advertiser(adv))


@bp.post("/rmn/advertisers/<aid>/suspend")
def suspend(aid):
    specs = (F("suspension_reason", "enum", required=True,
               enum=SUSPENSION_REASONS),)
    ctx = guard(("NetworkAdmin", "CreditAnalyst"),
                path_refs=(("advertiser", aid),), body_specs=specs,
                mutating=True)
    adv = ctx.get("advertiser")
    H.require_transition(adv["onboarding_status"],
                         ONBOARDING_TRANSITIONS["suspend"],
                         "ERR_INVALID_ONBOARDING_TRANSITION",
                         "onboarding_status")
    H.suspend_advertiser(adv, ctx.data["suspension_reason"])
    return ok(D.ser_advertiser(adv))


@bp.post("/rmn/advertisers/<aid>/reinstate")
def reinstate(aid):
    specs = (F("reinstatement_note", "string"),)
    ctx = guard(("NetworkAdmin", "CreditAnalyst"),
                path_refs=(("advertiser", aid),), body_specs=specs,
                mutating=True)
    adv = ctx.get("advertiser")
    target = H.require_transition(adv["onboarding_status"],
                                  ONBOARDING_TRANSITIONS["reinstate"],
                                  "ERR_INVALID_ONBOARDING_TRANSITION",
                                  "onboarding_status")
    for inv in D.invoices_of_advertiser(adv["id"]):
        if inv["invoice_status"] == "ISSUED" and inv["due_at"] is not None \
                and inv["due_at"] < now():
            fail("ERR_INVOICE_INVALID_STATE",
                 "An issued invoice is already past its due date.")
    if D.advertiser_exposure(adv) > adv["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "Credit exposure still exceeds the credit limit.")
    adv["onboarding_status"] = target
    adv["suspension_reason"] = "NONE"
    touch(adv)
    return ok(D.ser_advertiser(adv))


@bp.post("/rmn/advertisers/<aid>/terminate")
def terminate(aid):
    specs = (F("termination_reason", "string", required=True),)
    ctx = guard(("NetworkAdmin",), path_refs=(("advertiser", aid),),
                body_specs=specs, mutating=True)
    adv = ctx.get("advertiser")
    target = H.require_transition(adv["onboarding_status"],
                                  ONBOARDING_TRANSITIONS["terminate"],
                                  "ERR_INVALID_ONBOARDING_TRANSITION",
                                  "onboarding_status")
    plans = D.plans_of_advertiser(adv["id"])
    if any(p["plan_status"] in ("PENDING_APPROVAL", "APPROVED", "ACTIVE")
           for p in plans):
        fail("ERR_PLAN_INVALID_STATE",
             "A budget plan is still pending, approved or active.")
    for inv in D.invoices_of_advertiser(adv["id"]):
        if inv["invoice_status"] not in ("SETTLED", "WRITTEN_OFF"):
            fail("ERR_INVOICE_INVALID_STATE",
                 "Every invoice must be settled or written off first.")

    adv["onboarding_status"] = target
    touch(adv)
    for camp in D.campaigns_of_advertiser(adv["id"]):
        if camp["delivery_status"] != "ARCHIVED":
            camp["delivery_status"] = "ARCHIVED"
            touch(camp)
    for plan in plans:
        if plan["plan_status"] not in ("CLOSED", "REJECTED"):
            plan["plan_status"] = "CLOSED"
            touch(plan)
    for pool in db.trade_fund_accounts.values():
        if pool["advertiser_id"] != adv["id"]:
            continue
        if pool["account_status"] in ("OPEN", "FROZEN"):
            pool["account_status"] = "CLOSED"
            pool["frozen_reason"] = "NONE"
            touch(pool)
    return ok(D.ser_advertiser(adv))


@bp.get("/rmn/advertisers/<aid>/credit-summary")
def credit_summary(aid):
    ctx = guard(("NetworkAdmin", "CreditAnalyst", "BillingOps", "AdvertiserUser"),
                path_refs=(("advertiser", aid),))
    adv = ctx.get("advertiser")
    exposure = D.advertiser_exposure(adv)
    limit = D.effective_credit_limit(adv)
    parent = db.advertisers.get(adv.get("parent_advertiser_id"))
    plan_component = sum(p["committed_total_cents"]
                         for p in D.plans_of_advertiser(adv["id"])
                         if p["plan_status"] in ("APPROVED", "ACTIVE",
                                                 "EXHAUSTED"))
    invoice_component = sum(i["net_cash_due_cents"]
                            for i in D.invoices_of_advertiser(adv["id"])
                            if i["invoice_status"] in ("ISSUED", "DISPUTED",
                                                       "ADJUSTED"))
    return ok({
        "advertiser_id": adv["id"],
        "onboarding_status": adv["onboarding_status"],
        "service_model": adv["service_model"],
        "credit_limit_cents": adv["credit_limit_cents"],
        "parent_advertiser_id": adv["parent_advertiser_id"],
        "parent_credit_limit_cents": (parent["credit_limit_cents"]
                                      if parent is not None else None),
        "effective_credit_limit_cents": limit,
        "credit_exposure_cents": exposure,
        "plan_committed_cents": plan_component,
        "invoice_outstanding_cents": invoice_component,
        "headroom_cents": limit - exposure,
        "dispute_credit_balance_cents": D.dispute_credit_balance(adv),
    })
