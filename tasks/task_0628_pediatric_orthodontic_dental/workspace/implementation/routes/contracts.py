"""Contract + Installment endpoints (PRD §3.7), with OCC on the plan version."""

from flask import Blueprint, request

import errors
from db import db, lock
from helpers import (
    get_json_body, require_str, require_int, require_bool, stamp_new,
    parse_pagination, sort_and_paginate, touch,
)
from lookups import get_or_404, fk_or_404, require_guardian_owns_plan
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list
from clock import clock, parse_iso8601
from services.domain import (
    build_installments, enter_delinquency,
)

bp = Blueprint("contracts", __name__)


# -----------------------------------------------------------------------------
# Contract
# -----------------------------------------------------------------------------

@bp.post("/contracts")
@require_roles("BillingSpecialist", "Guardian")
def create_contract():
    body = get_json_body()
    plan_id = require_str(body, "plan_id")
    expected_plan_version = require_int(body, "expected_plan_version")
    down_payment_cents = require_int(body, "down_payment_cents", non_negative=True)
    term_months = require_int(body, "term_months", minimum=1)
    autopay_enabled = require_bool(body, "autopay_enabled", default=True)
    with lock:
        # Priority 3: existence.
        plan = fk_or_404(db.treatment_plans, plan_id)
        # Priority 2: ownership for Guardian.
        require_guardian_owns_plan(plan)
        # Priority 5: OCC on the plan version.
        if expected_plan_version != plan["version"]:
            raise errors.stale_plan_version()
        # Priority 6: state — the plan must be ACTIVE to finance it.
        if plan["status"] != "ACTIVE":
            raise errors.invalid_state()
        # Priority 12: down payment must not exceed estimated patient responsibility.
        est_resp = plan["estimated_patient_responsibility_cents"]
        financed = est_resp - down_payment_cents
        if financed < 0:
            raise errors.down_payment_exceeds()

        rec = {
            "plan_id": plan_id,
            "expected_plan_version": expected_plan_version,
            "down_payment_cents": down_payment_cents,
            "term_months": term_months,
            "autopay_enabled": autopay_enabled,
            "financed_amount_cents": financed,
            "balance_remaining_cents": financed,
            "billing_status": "CURRENT",
            "lifecycle_status": "ACTIVE",
        }
        stamp_new(rec)
        db.contracts[rec["id"]] = rec
        build_installments(rec, financed, term_months)
        # Creating a contract increments the owning plan's version (PRD §3.7).
        touch(plan)
        return success(public(rec), 201)


@bp.get("/contracts/<contract_id>")
@require_roles("BillingSpecialist", "ClinicAdmin", "Guardian")
def get_contract(contract_id):
    with lock:
        rec = get_or_404(db.contracts, contract_id)
        _guardian_owns_contract(rec)
        return success(public(rec), 200)


@bp.get("/contracts")
@require_roles("BillingSpecialist", "ClinicAdmin", "Guardian")
def list_contracts():
    from flask import g
    with lock:
        limit, offset = parse_pagination()
        plan_id = request.args.get("plan_id")
        records = list(db.contracts.values())
        if plan_id is not None:
            records = [r for r in records if r["plan_id"] == plan_id]
        if g.user_role == "Guardian":
            records = [r for r in records if _contract_owned_by_guardian(r)]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


def _contract_owned_by_guardian(contract):
    from lookups import family_of_patient, guardian_owns_family
    plan = db.treatment_plans.get(contract["plan_id"])
    if not plan:
        return False
    pat = db.patients.get(plan["patient_id"])
    return pat is not None and guardian_owns_family(family_of_patient(pat))


def _guardian_owns_contract(contract):
    from flask import g
    if g.user_role == "Guardian" and not _contract_owned_by_guardian(contract):
        raise errors.forbidden()


# -----------------------------------------------------------------------------
# Installment
# -----------------------------------------------------------------------------

@bp.get("/installments/<installment_id>")
@require_roles("BillingSpecialist", "ClinicAdmin", "Guardian")
def get_installment(installment_id):
    with lock:
        rec = get_or_404(db.installments, installment_id)
        _guardian_owns_installment(rec)
        return success(public(rec), 200)


@bp.get("/installments")
@require_roles("BillingSpecialist", "ClinicAdmin", "Guardian")
def list_installments():
    from flask import g
    with lock:
        limit, offset = parse_pagination()
        contract_id = request.args.get("contract_id")
        records = list(db.installments.values())
        if contract_id is not None:
            records = [r for r in records if r["contract_id"] == contract_id]
        if g.user_role == "Guardian":
            records = [r for r in records if _installment_owned_by_guardian(r)]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


def _installment_owned_by_guardian(inst):
    contract = db.contracts.get(inst["contract_id"])
    return contract is not None and _contract_owned_by_guardian(contract)


def _guardian_owns_installment(inst):
    from flask import g
    if g.user_role == "Guardian" and not _installment_owned_by_guardian(inst):
        raise errors.forbidden()


@bp.post("/installments/<installment_id>/charge")
@require_roles("BillingSpecialist")
def charge_installment(installment_id):
    body = get_json_body()
    outcome = body.get("outcome")
    if outcome is None or not isinstance(outcome, str):
        raise errors.invalid_request("outcome is required")
    norm = outcome.upper()
    if norm not in ("SUCCEEDED", "FAILED", "SUCCESS", "FAILURE"):
        raise errors.invalid_request("outcome must be SUCCEEDED or FAILED")
    succeeded = norm in ("SUCCEEDED", "SUCCESS")
    with lock:
        inst = get_or_404(db.installments, installment_id)
        contract = db.contracts.get(inst["contract_id"])
        if succeeded:
            # On-time/late charge success -> PAID + POSTED payment.
            if inst["status"] not in ("SCHEDULED", "MISSED"):
                raise errors.invalid_state()
            if contract["lifecycle_status"] != "ACTIVE":
                raise errors.invalid_state()
            _post_payment_and_settle(contract, inst, inst["amount_cents"], "AUTOPAY")
        else:
            # Failed charge -> MISSED, but only on/after due_at.
            if inst["status"] != "SCHEDULED":
                raise errors.invalid_state()
            if clock.now() < parse_iso8601(inst["due_at"]):
                raise errors.not_yet_due()
            inst["status"] = "MISSED"
            touch(inst)
            enter_delinquency(contract)
        return success(public(inst), 200)


def _post_payment_and_settle(contract, inst, amount, method):
    """Shared payment-posting path used by installment charge and POST /payments."""
    from services.domain import (
        recompute_contract_balance, cure_delinquency_if_resolved,
        close_contract_if_paid_off,
    )
    payment = {
        "contract_id": contract["id"],
        "installment_id": inst["id"] if inst is not None else None,
        "amount_cents": amount,
        "method": method,
        "status": "POSTED",
    }
    stamp_new(payment)
    db.payments[payment["id"]] = payment
    if inst is not None:
        inst["status"] = "PAID"
        touch(inst)
    recompute_contract_balance(contract)
    cure_delinquency_if_resolved(contract)
    close_contract_if_paid_off(contract)
    return payment
