"""InsuranceClaim endpoints (PRD §3.6): submit, approve (chronological drawdown),
deny, mark-paid, void (compensating reversal)."""

from flask import Blueprint, request

import errors
from db import db, lock
from helpers import (
    get_json_body, require_str, require_int, stamp_new,
    parse_pagination, sort_and_paginate, touch,
)
from lookups import get_or_404, fk_or_404
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list
from services.domain import approve_claim_benefit

bp = Blueprint("insurance_claims", __name__)


@bp.post("/insurance-claims")
@require_roles("BillingSpecialist")
def create_insurance_claim():
    body = get_json_body()
    policy_id = require_str(body, "policy_id")
    plan_id = require_str(body, "plan_id")
    billed_amount_cents = require_int(body, "billed_amount_cents", non_negative=True)
    with lock:
        fk_or_404(db.insurance_policies, policy_id)
        fk_or_404(db.treatment_plans, plan_id)
        rec = {
            "policy_id": policy_id,
            "plan_id": plan_id,
            "billed_amount_cents": billed_amount_cents,
            "benefit_cents": 0,
            "status": "SUBMITTED",
        }
        stamp_new(rec)
        db.insurance_claims[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/insurance-claims/<claim_id>")
@require_roles("BillingSpecialist", "ClinicAdmin")
def get_insurance_claim(claim_id):
    with lock:
        rec = get_or_404(db.insurance_claims, claim_id)
        return success(public(rec), 200)


@bp.get("/insurance-claims")
@require_roles("BillingSpecialist", "ClinicAdmin")
def list_insurance_claims():
    with lock:
        limit, offset = parse_pagination()
        policy_id = request.args.get("policy_id")
        plan_id = request.args.get("plan_id")
        records = list(db.insurance_claims.values())
        if policy_id is not None:
            records = [r for r in records if r["policy_id"] == policy_id]
        if plan_id is not None:
            records = [r for r in records if r["plan_id"] == plan_id]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


@bp.post("/insurance-claims/<claim_id>/approve")
@require_roles("BillingSpecialist")
def approve_insurance_claim(claim_id):
    with lock:
        claim = get_or_404(db.insurance_claims, claim_id)
        policy = db.insurance_policies.get(claim["policy_id"])
        if claim["status"] != "SUBMITTED":
            raise errors.invalid_state()
        if policy["status"] != "ACTIVE":
            raise errors.policy_terminated()
        if not policy.get("ortho_rider"):
            raise errors.no_ortho_rider()
        claim["status"] = "APPROVED"
        approve_claim_benefit(claim, policy)
        touch(claim)
        return success(public(claim), 200)


@bp.post("/insurance-claims/<claim_id>/deny")
@require_roles("BillingSpecialist")
def deny_insurance_claim(claim_id):
    with lock:
        claim = get_or_404(db.insurance_claims, claim_id)
        if claim["status"] != "SUBMITTED":
            raise errors.invalid_state()
        claim["status"] = "DENIED"
        touch(claim)
        return success(public(claim), 200)


@bp.post("/insurance-claims/<claim_id>/mark-paid")
@require_roles("BillingSpecialist")
def mark_paid_insurance_claim(claim_id):
    with lock:
        claim = get_or_404(db.insurance_claims, claim_id)
        if claim["status"] != "APPROVED":
            raise errors.invalid_state()
        claim["status"] = "PAID"
        touch(claim)
        return success(public(claim), 200)


@bp.post("/insurance-claims/<claim_id>/void")
@require_roles("BillingSpecialist")
def void_insurance_claim(claim_id):
    with lock:
        claim = get_or_404(db.insurance_claims, claim_id)
        policy = db.insurance_policies.get(claim["policy_id"])
        if claim["status"] != "APPROVED":
            raise errors.invalid_state()
        # Compensating reversal: restore the pool, then zero the benefit.
        policy["remaining_max_cents"] += claim["benefit_cents"]
        touch(policy)
        claim["benefit_cents"] = 0
        claim["status"] = "VOID"
        touch(claim)
        return success(public(claim), 200)
