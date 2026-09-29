"""Care plan subscriptions and reimbursement claims."""

from flask import Blueprint

import calc
import services as svc
from auth import (ADMIN, CARE_OPS, COMPLIANCE, FIRMWARE_ENG, PATIENT, REIMBURSEMENT,
                  authorize, require_distinct_user, require_owner)
from bodyspec import Body, raw_body
from common import field, listed
from errors import ApiError
from resp import created, ok
from store import bump, db, days, now, table_rows

bp = Blueprint("finance", __name__)

TIERS = ("STANDARD", "PREMIUM")
OUTCOMES = ("SUCCEEDED", "DECLINED")
SUBJECT_KINDS = ("DEVICE_ORDER", "REPAIR_ORDER", "CARE_PLAN")
DECISIONS = ("APPROVE", "DENY")
DENIAL_REASONS = ("DOCUMENTATION_INCOMPLETE", "NOT_COVERED", "AMOUNT_EXCEEDS_ELIGIBLE",
                  "DUPLICATE_SUBJECT")
DOC_CODES = ("INVOICE", "AUDIOGRAM_OR_WAIVER", "PROOF_OF_PAYMENT", "LMN",
             "ITEMIZED_RECEIPT", "PRESCRIPTION")
REQUIRED_DOCS = {
    "DEVICE_ORDER": {"INVOICE", "AUDIOGRAM_OR_WAIVER", "PROOF_OF_PAYMENT", "LMN"},
    "REPAIR_ORDER": {"INVOICE", "PROOF_OF_PAYMENT"},
    "CARE_PLAN": {"INVOICE", "PROOF_OF_PAYMENT"},
}
SUBJECT_FIELD = {"DEVICE_ORDER": "device_order_id", "REPAIR_ORDER": "repair_order_id",
                 "CARE_PLAN": "care_plan_subscription_id"}
SUBJECT_TABLE = {"DEVICE_ORDER": "device_orders", "REPAIR_ORDER": "repair_orders",
                 "CARE_PLAN": "care_plan_subscriptions"}
ACTIVE_CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "PAID")


# ----------------------------------------------------- CarePlanSubscription
@bp.post("/care-plan-subscriptions")
def create_plan():
    actor = authorize(PATIENT, CARE_OPS)
    body = Body()
    patient_id = body.string("patient_id", min_len=1)
    order_id = body.string("device_order_id", min_len=1)
    tier = body.enum("plan_tier", TIERS)
    base_fee = body.integer("base_fee_cents", minimum=1)
    consent = body.boolean("firmware_auto_update_enabled", required=False, default=True)
    body.finish()
    patient = svc.ref(db.patients, patient_id)
    order = svc.ref(db.device_orders, order_id)
    require_owner(actor, patient["id"])
    plan = svc.new_row(db.care_plan_subscriptions, patient_id=patient["id"],
                       device_order_id=order["id"], plan_tier=tier, status="TRIALING",
                       base_fee_cents=base_fee, cycle_ordinal=0, cycle_start_utc=None,
                       cycle_end_utc=None, last_charge_cents=0, service_fee_cents=0,
                       loyalty_discount_cents=0, credit_balance_cents=0,
                       dunning_attempts=0, firmware_auto_update_enabled=consent)
    return created(plan)


@bp.get("/care-plan-subscriptions")
def list_plans():
    actor = authorize(PATIENT, CARE_OPS, REIMBURSEMENT, FIRMWARE_ENG, ADMIN)
    return listed(table_rows(db.care_plan_subscriptions),
                  {"patient_id": field("patient_id"),
                   "device_order_id": field("device_order_id"),
                   "status": field("status"), "plan_tier": field("plan_tier")},
                  actor=actor)


@bp.get("/care-plan-subscriptions/<plan_id>")
def get_plan(plan_id):
    actor = authorize(PATIENT, CARE_OPS, REIMBURSEMENT, FIRMWARE_ENG, ADMIN)
    plan = svc.find(db.care_plan_subscriptions, plan_id)
    require_owner(actor, plan["patient_id"])
    return ok(plan)


@bp.post("/care-plan-subscriptions/<plan_id>/change-tier")
def change_tier(plan_id):
    actor = authorize(PATIENT)
    plan = svc.find(db.care_plan_subscriptions, plan_id)
    require_owner(actor, plan["patient_id"])
    body = Body()
    tier = body.enum("plan_tier", TIERS)
    expected = body.integer("expected_subscription_version")
    body.finish()
    if expected != int(plan["version"]):
        raise ApiError("ERR_STALE_SUBSCRIPTION_VERSION")
    svc.ensure_state(plan, "status", ("ACTIVE", "PAST_DUE", "TRIALING"),
                     "care_plan_subscriptions")
    breakdown = calc.care_plan_cycle_charge(plan, tier)
    plan["plan_tier"] = tier
    plan["service_fee_cents"] = breakdown["service_fee_cents"]
    plan["loyalty_discount_cents"] = breakdown["loyalty_discount_cents"]
    plan["last_charge_cents"] = calc.prorated_charge(breakdown["last_charge_cents"],
                                                     plan.get("cycle_end_utc"))
    bump(plan)
    return ok(plan)


def _apply_cycle(plan):
    """Write the five-step charge, consume credit and advance the window."""
    breakdown = calc.care_plan_cycle_charge(plan)
    plan["service_fee_cents"] = breakdown["service_fee_cents"]
    plan["loyalty_discount_cents"] = breakdown["loyalty_discount_cents"]
    plan["last_charge_cents"] = breakdown["last_charge_cents"]
    applied = min(int(plan.get("credit_balance_cents") or 0), breakdown["last_charge_cents"])
    plan["credit_balance_cents"] = int(plan.get("credit_balance_cents") or 0) - applied
    plan["cycle_ordinal"] = int(plan.get("cycle_ordinal") or 0) + 1
    start = plan.get("cycle_end_utc") or now()
    plan["cycle_start_utc"] = start
    plan["cycle_end_utc"] = start + days(30)
    return breakdown["last_charge_cents"] - applied


@bp.post("/care-plan-subscriptions/<plan_id>/run-billing-cycle")
def run_billing_cycle(plan_id):
    authorize(ADMIN)
    plan = svc.find(db.care_plan_subscriptions, plan_id)
    body = Body()
    outcome = body.enum("charge_outcome", OUTCOMES)
    from_credit = body.boolean("pay_from_credit", required=False, default=False)
    body.finish()
    # §2.9: "A billing-cycle run against a cancelled subscription with a declining
    # instrument violates both rule 22 and rule 62; rule 22 wins, so the caller sees
    # ERR_INVALID_STATE."
    svc.ensure_state(plan, "status", ("ACTIVE",))
    if plan.get("cycle_end_utc") is None or now() < plan["cycle_end_utc"]:
        raise ApiError("ERR_INVALID_STATE", "the billing cycle has not closed yet")
    breakdown = calc.care_plan_cycle_charge(plan)
    if from_credit and int(plan.get("credit_balance_cents") or 0) < breakdown["last_charge_cents"]:
        raise ApiError("ERR_CREDIT_BALANCE_INSUFFICIENT")
    if outcome == "DECLINED" and \
            breakdown["last_charge_cents"] > int(plan.get("credit_balance_cents") or 0):
        plan["service_fee_cents"] = breakdown["service_fee_cents"]
        plan["loyalty_discount_cents"] = breakdown["loyalty_discount_cents"]
        plan["last_charge_cents"] = breakdown["last_charge_cents"]
        plan["status"] = "PAST_DUE"
        plan["dunning_attempts"] = 1
        bump(plan)
        raise ApiError("ERR_PAYMENT_DECLINED")
    _apply_cycle(plan)
    bump(plan)
    return ok(plan)


@bp.post("/care-plan-subscriptions/<plan_id>/retry-payment")
def retry_payment(plan_id):
    actor = authorize(PATIENT)
    plan = svc.find(db.care_plan_subscriptions, plan_id)
    require_owner(actor, plan["patient_id"])
    body = Body()
    outcome = body.enum("charge_outcome", OUTCOMES)
    body.finish()
    svc.ensure_state(plan, "status", ("PAST_DUE",), "care_plan_subscriptions")
    if int(plan.get("dunning_attempts") or 0) >= 3:
        raise ApiError("ERR_DUNNING_LIMIT_REACHED")
    if outcome == "SUCCEEDED":
        _apply_cycle(plan)
        plan["status"] = "ACTIVE"
        plan["dunning_attempts"] = 0
        bump(plan)
        return ok(plan)
    attempts = int(plan.get("dunning_attempts") or 0) + 1
    plan["dunning_attempts"] = attempts
    if attempts >= 3:
        plan["status"] = "SUSPENDED"
        bump(plan)
        _suspend_effects(plan)
    else:
        bump(plan)
    raise ApiError("ERR_PAYMENT_DECLINED")


def _suspend_effects(plan):
    order = db.device_orders.get(plan.get("device_order_id"))
    device = svc.device_for_order(order["id"]) if order else None
    if device is not None:
        svc.cancel_rollouts_for_device(device["id"], skip_mandatory_safety=True)


@bp.post("/care-plan-subscriptions/<plan_id>/reinstate")
def reinstate_plan(plan_id):
    authorize(CARE_OPS)
    plan = svc.find(db.care_plan_subscriptions, plan_id)
    svc.ensure_state(plan, "status", ("SUSPENDED",), "care_plan_subscriptions")
    order = db.device_orders.get(plan.get("device_order_id"))
    trial = svc.trial_for_order(order["id"]) if order else None
    if trial is not None:
        svc.touch_trial(trial)
        if trial.get("status") == "RETURN_SETTLED":
            raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    plan["status"] = "ACTIVE"
    plan["dunning_attempts"] = 0
    plan["cycle_start_utc"] = now()
    plan["cycle_end_utc"] = now() + days(30)
    bump(plan)
    return ok(plan)


@bp.post("/care-plan-subscriptions/<plan_id>/cancel")
def cancel_plan_endpoint(plan_id):
    actor = authorize(PATIENT, CARE_OPS)
    plan = svc.find(db.care_plan_subscriptions, plan_id)
    require_owner(actor, plan["patient_id"])
    Body().string("reason_note", required=False, min_len=1)
    allowed = ("ACTIVE", "PAST_DUE") if actor.is_patient else \
        ("ACTIVE", "PAST_DUE", "SUSPENDED", "TRIALING")
    svc.ensure_state(plan, "status", allowed, "care_plan_subscriptions")
    svc.cancel_plan(plan)
    return ok(plan)


# ------------------------------------------------------- ReimbursementClaim
def _documentation_complete(claim):
    codes = set(claim.get("document_codes") or [])
    claim["documentation_complete"] = REQUIRED_DOCS[claim["subject_kind"]].issubset(codes)
    return claim["documentation_complete"]


def _duplicate_subject(claim, exclude_id=None):
    key = SUBJECT_FIELD[claim["subject_kind"]]
    value = claim.get(key)
    if value is None:
        return False
    for other in db.reimbursement_claims.values():
        if other["id"] == claim["id"] or other["id"] == exclude_id:
            continue
        if other.get(key) == value and other.get("status") in ACTIVE_CLAIM_STATUSES:
            return True
    return False


@bp.post("/reimbursement-claims")
def create_reimbursement_claim():
    actor = authorize(PATIENT, REIMBURSEMENT)
    data = raw_body()
    body = Body(data)
    patient_id = body.string("patient_id", min_len=1)
    subject_kind = body.enum("subject_kind", SUBJECT_KINDS)
    claimed = body.integer("claimed_amount_cents", minimum=1)
    order_id = body.string("device_order_id", required=False, min_len=1)
    repair_id = body.string("repair_order_id", required=False, min_len=1)
    plan_id = body.string("care_plan_subscription_id", required=False, min_len=1)
    appeal_of = body.string("appeal_of_claim_id", required=False, min_len=1)
    doc_codes = body.array("document_codes", required=False, default=[], item_type=str)
    cap = body.integer("insurance_benefit_cap_cents", required=False, default=0, minimum=0)
    used = body.integer("insurance_benefit_used_cents", required=False, default=0, minimum=0)
    fsa = body.integer("fsa_balance_cents", required=False, default=0, minimum=0)
    body.finish()
    patient = svc.ref(db.patients, patient_id)
    require_owner(actor, patient["id"])
    appealed = None
    if appeal_of is not None:
        appealed = svc.ref(db.reimbursement_claims, appeal_of)
    refs = {"device_order_id": order_id, "repair_order_id": repair_id,
            "care_plan_subscription_id": plan_id}
    if appealed is not None:
        subject_kind = appealed["subject_kind"]
        refs = {k: appealed.get(k) for k in refs}
    for key, value in refs.items():
        if value is None:
            continue
        table = {"device_order_id": db.device_orders, "repair_order_id": db.repair_orders,
                 "care_plan_subscription_id": db.care_plan_subscriptions}[key]
        svc.ref(table, value)
    wanted = SUBJECT_FIELD[subject_kind]
    for key, value in refs.items():
        if key == wanted and value is None:
            raise ApiError("ERR_SUBJECT_KIND_MISMATCH")
        if key != wanted and value is not None:
            raise ApiError("ERR_SUBJECT_KIND_MISMATCH")
    if appealed is not None:
        if appealed.get("denial_reason") == "DUPLICATE_SUBJECT":
            raise ApiError("ERR_APPEAL_ALREADY_EXISTS")
        for other in db.reimbursement_claims.values():
            if other.get("appeal_of_claim_id") == appealed["id"]:
                raise ApiError("ERR_APPEAL_ALREADY_EXISTS")
    claim = svc.new_row(db.reimbursement_claims, patient_id=patient["id"],
                        subject_kind=subject_kind, device_order_id=refs["device_order_id"],
                        repair_order_id=refs["repair_order_id"],
                        care_plan_subscription_id=refs["care_plan_subscription_id"],
                        appeal_of_claim_id=appeal_of, status="DRAFT",
                        submitted_by_user_id=None, approved_by_user_id=None,
                        document_codes=list(doc_codes), documentation_complete=False,
                        claimed_amount_cents=claimed, eligible_amount_cents=0,
                        insurance_benefit_cap_cents=cap, insurance_benefit_used_cents=used,
                        fsa_balance_cents=fsa, insurance_paid_cents=0, fsa_paid_cents=0,
                        patient_responsibility_cents=0, info_request_count=0,
                        denial_reason=None)
    if _duplicate_subject(claim):
        del db.reimbursement_claims[claim["id"]]
        raise ApiError("ERR_DUPLICATE_REIMBURSEMENT_SUBJECT")
    _documentation_complete(claim)
    if appealed is not None and appealed.get("status") == "DENIED":
        appealed["status"] = "UNDER_REVIEW"
        bump(appealed)
    return created(claim)


@bp.get("/reimbursement-claims")
def list_reimbursement_claims():
    actor = authorize(PATIENT, REIMBURSEMENT, COMPLIANCE, ADMIN)
    return listed(table_rows(db.reimbursement_claims),
                  {"patient_id": field("patient_id"),
                   "device_order_id": field("device_order_id"),
                   "repair_order_id": field("repair_order_id"),
                   "care_plan_subscription_id": field("care_plan_subscription_id"),
                   "appeal_of_claim_id": field("appeal_of_claim_id"),
                   "status": field("status"), "subject_kind": field("subject_kind")},
                  actor=actor)


@bp.get("/reimbursement-claims/<claim_id>")
def get_reimbursement_claim(claim_id):
    actor = authorize(PATIENT, REIMBURSEMENT, COMPLIANCE, ADMIN)
    claim = svc.find(db.reimbursement_claims, claim_id)
    require_owner(actor, claim["patient_id"])
    return ok(claim)


@bp.post("/reimbursement-claims/<claim_id>/submit")
def submit_reimbursement_claim(claim_id):
    actor = authorize(REIMBURSEMENT)
    claim = svc.find(db.reimbursement_claims, claim_id)
    svc.ensure_state(claim, "status", ("DRAFT",), "reimbursement_claims")
    if _duplicate_subject(claim):
        raise ApiError("ERR_DUPLICATE_REIMBURSEMENT_SUBJECT")
    if not _documentation_complete(claim):
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")
    kind = claim["subject_kind"]
    subject = getattr(db, SUBJECT_TABLE[kind]).get(claim.get(SUBJECT_FIELD[kind]))
    if subject is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if kind == "DEVICE_ORDER" and \
            subject.get("payment_status") not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    claim["submitted_by_user_id"] = actor.user_id
    claim["status"] = "SUBMITTED"
    calc.reimbursement_allocation(claim)
    bump(claim)
    return ok(claim)


@bp.post("/reimbursement-claims/<claim_id>/start-review")
def start_review(claim_id):
    authorize(REIMBURSEMENT)
    claim = svc.find(db.reimbursement_claims, claim_id)
    svc.ensure_state(claim, "status", ("SUBMITTED",), "reimbursement_claims")
    claim["status"] = "UNDER_REVIEW"
    bump(claim)
    return ok(claim)


@bp.post("/reimbursement-claims/<claim_id>/request-info")
def request_info(claim_id):
    authorize(REIMBURSEMENT)
    claim = svc.find(db.reimbursement_claims, claim_id)
    body = Body()
    body.array("requested_document_codes", item_type=str)
    body.finish()
    svc.ensure_state(claim, "status", ("UNDER_REVIEW",), "reimbursement_claims")
    if int(claim.get("info_request_count") or 0) >= 2:
        raise ApiError("ERR_INFO_REQUEST_LIMIT_REACHED")
    claim["info_request_count"] = int(claim.get("info_request_count") or 0) + 1
    claim["status"] = "INFO_REQUESTED"
    bump(claim)
    return ok(claim)


@bp.post("/reimbursement-claims/<claim_id>/supply-info")
def supply_info(claim_id):
    actor = authorize(PATIENT)
    claim = svc.find(db.reimbursement_claims, claim_id)
    require_owner(actor, claim["patient_id"])
    body = Body()
    codes = body.array("document_codes", item_type=str)
    used = body.integer("insurance_benefit_used_cents", required=False, minimum=0)
    fsa = body.integer("fsa_balance_cents", required=False, minimum=0)
    body.finish()
    svc.ensure_state(claim, "status", ("INFO_REQUESTED",), "reimbursement_claims")
    merged = list(claim.get("document_codes") or [])
    for code in codes:
        if code not in merged:
            merged.append(code)
    claim["document_codes"] = merged
    if used is not None:
        claim["insurance_benefit_used_cents"] = used
    if fsa is not None:
        claim["fsa_balance_cents"] = fsa
    if not _documentation_complete(claim):
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")
    claim["status"] = "SUBMITTED"
    calc.reimbursement_allocation(claim)
    bump(claim)
    return ok(claim)


@bp.post("/reimbursement-claims/<claim_id>/decide")
def decide_reimbursement_claim(claim_id):
    actor = authorize(REIMBURSEMENT)
    claim = svc.find(db.reimbursement_claims, claim_id)
    body = Body()
    decision = body.enum("decision", DECISIONS)
    denial_reason = body.enum("denial_reason", DENIAL_REASONS, required=False)
    body.finish()
    require_distinct_user(actor, claim.get("submitted_by_user_id"))
    svc.ensure_state(claim, "status", ("UNDER_REVIEW",), "reimbursement_claims")
    if decision == "APPROVE":
        if int(claim["claimed_amount_cents"]) > int(claim.get("eligible_amount_cents") or 0):
            raise ApiError("ERR_CLAIM_AMOUNT_EXCEEDS_ELIGIBLE")
        claim["approved_by_user_id"] = actor.user_id
        claim["status"] = "APPROVED"
        bump(claim)
        return ok(claim)
    if denial_reason is None:
        raise ApiError("ERR_VALIDATION", "denial_reason is required on a denial")
    claim["denial_reason"] = denial_reason
    claim["status"] = "DENIED"
    claim["insurance_paid_cents"] = 0
    claim["fsa_paid_cents"] = 0
    claim["patient_responsibility_cents"] = int(claim.get("eligible_amount_cents") or 0)
    bump(claim)
    return ok(claim)


@bp.post("/reimbursement-claims/<claim_id>/pay")
def pay_reimbursement_claim(claim_id):
    authorize(REIMBURSEMENT)
    claim = svc.find(db.reimbursement_claims, claim_id)
    svc.ensure_state(claim, "status", ("APPROVED",), "reimbursement_claims")
    if claim.get("approved_by_user_id") is None:
        raise ApiError("ERR_INVALID_STATE")
    if int(claim.get("insurance_paid_cents") or 0) + int(claim.get("fsa_paid_cents") or 0) <= 0:
        raise ApiError("ERR_INVALID_STATE", "no benefit was allocated to pay")
    claim["status"] = "PAID"
    bump(claim)
    return ok(claim)


@bp.post("/reimbursement-claims/<claim_id>/void")
def void_reimbursement_claim(claim_id):
    authorize(COMPLIANCE)
    claim = svc.find(db.reimbursement_claims, claim_id)
    Body().string("reason_note", required=False, min_len=1)
    svc.ensure_state(claim, "status", ("SUBMITTED", "APPROVED"), "reimbursement_claims")
    claim["status"] = "VOIDED"
    claim["insurance_paid_cents"] = 0
    claim["fsa_paid_cents"] = 0
    claim["patient_responsibility_cents"] = int(claim.get("eligible_amount_cents") or 0)
    bump(claim)
    return ok(claim)
