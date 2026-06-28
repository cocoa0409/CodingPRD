"""Payment endpoints (PRD §3.8): record, reverse, payoff, cure."""

from flask import Blueprint, request

import errors
from db import db, lock
from helpers import (
    get_json_body, require_str, require_int, require_enum, stamp_new,
    parse_pagination, sort_and_paginate, touch,
)
from lookups import get_or_404, fk_or_404
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list
from clock import clock, parse_iso8601
from services.domain import (
    recompute_contract_balance, cure_delinquency_if_resolved,
    close_contract_if_paid_off, enter_delinquency,
)

bp = Blueprint("payments", __name__)

PAYMENT_METHODS = {"AUTOPAY", "CARD", "CASH", "CHECK"}


@bp.post("/payments")
@require_roles("BillingSpecialist", "Guardian")
def create_payment():
    body = get_json_body()
    contract_id = require_str(body, "contract_id")
    amount_cents = require_int(body, "amount_cents", non_negative=True)
    method = require_enum(body, "method", PAYMENT_METHODS)
    installment_id = body.get("installment_id")
    if installment_id is not None and not isinstance(installment_id, str):
        raise errors.invalid_request("installment_id must be a string")
    with lock:
        contract = fk_or_404(db.contracts, contract_id)
        _require_guardian_owns_contract(contract)
        inst = None
        if installment_id is not None:
            inst = fk_or_404(db.installments, installment_id)
            if inst["contract_id"] != contract_id:
                raise errors.not_found()
        # Priority 13: overpayment guard.
        if amount_cents > contract["balance_remaining_cents"]:
            raise errors.overpayment()

        payment = {
            "contract_id": contract_id,
            "installment_id": installment_id,
            "amount_cents": amount_cents,
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
        return success(public(payment), 201)


@bp.get("/payments/<payment_id>")
@require_roles("BillingSpecialist", "ClinicAdmin", "Guardian")
def get_payment(payment_id):
    with lock:
        rec = get_or_404(db.payments, payment_id)
        contract = db.contracts.get(rec["contract_id"])
        if contract is not None:
            _require_guardian_owns_contract(contract)
        return success(public(rec), 200)


@bp.get("/payments")
@require_roles("BillingSpecialist", "ClinicAdmin", "Guardian")
def list_payments():
    from flask import g
    with lock:
        limit, offset = parse_pagination()
        contract_id = request.args.get("contract_id")
        installment_id = request.args.get("installment_id")
        records = list(db.payments.values())
        if contract_id is not None:
            records = [r for r in records if r["contract_id"] == contract_id]
        if installment_id is not None:
            records = [r for r in records if r.get("installment_id") == installment_id]
        if g.user_role == "Guardian":
            records = [r for r in records if _payment_owned_by_guardian(r)]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


@bp.post("/payments/<payment_id>/reverse")
@require_roles("BillingSpecialist")
def reverse_payment(payment_id):
    with lock:
        payment = get_or_404(db.payments, payment_id)
        contract = db.contracts.get(payment["contract_id"])
        if payment["status"] != "POSTED":
            raise errors.invalid_state()
        if contract["lifecycle_status"] != "ACTIVE":
            raise errors.contract_closed()
        payment["status"] = "REVERSED"
        touch(payment)
        recompute_contract_balance(contract)
        # If the covered installment was PAID and is now past due, return it to
        # MISSED, possibly re-firing the delinquency cascade.
        inst_id = payment.get("installment_id")
        if inst_id is not None:
            inst = db.installments.get(inst_id)
            if (inst is not None and inst["status"] == "PAID"
                    and clock.now() >= parse_iso8601(inst["due_at"])):
                inst["status"] = "MISSED"
                touch(inst)
                enter_delinquency(contract)
        return success(public(payment), 200)


# -----------------------------------------------------------------------------
# Ownership helpers
# -----------------------------------------------------------------------------

def _contract_owned_by_guardian(contract):
    from lookups import family_of_patient, guardian_owns_family
    plan = db.treatment_plans.get(contract["plan_id"])
    if not plan:
        return False
    pat = db.patients.get(plan["patient_id"])
    return pat is not None and guardian_owns_family(family_of_patient(pat))


def _require_guardian_owns_contract(contract):
    from flask import g
    if g.user_role == "Guardian" and not _contract_owned_by_guardian(contract):
        raise errors.forbidden()


def _payment_owned_by_guardian(payment):
    contract = db.contracts.get(payment["contract_id"])
    return contract is not None and _contract_owned_by_guardian(contract)
