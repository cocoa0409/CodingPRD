"""Payment plan and receipt reads plus the compensating reversal (PRD section 3.7)."""

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import ROLE_FINANCE_CONTROLLER, ROLE_PROGRAM_MANAGER, authorize
from validate import apply_filters, body_of, pagination, req_str

bp = Blueprint("finance", __name__)

READ_ROLES = (ROLE_FINANCE_CONTROLLER, ROLE_PROGRAM_MANAGER)


@bp.route("/payment-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    authorize(READ_ROLES)
    with lock:
        row = db.payment_plans.get(plan_id)
        if row is None:
            err("ERR_PAYMENT_PLAN_NOT_FOUND", "Payment plan %s does not exist." % plan_id)
        return response.ok(core.serialize(row))


@bp.route("/payment-plans", methods=["GET"])
def list_plans():
    authorize(READ_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.payment_plans.values()))
        rows = apply_filters(rows, {
            "pilgrim_id": "pilgrim_id",
            "superseded_by_plan_id": "superseded_by_plan_id",
            "status": "status",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize(r) for r in page], limit, offset, total)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    authorize(READ_ROLES)
    with lock:
        row = db.payments.get(payment_id)
        if row is None:
            err("ERR_PAYMENT_NOT_FOUND", "Payment %s does not exist." % payment_id)
        return response.ok(core.serialize(row))


@bp.route("/payments", methods=["GET"])
def list_payments():
    authorize(READ_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.payments.values()))
        rows = apply_filters(rows, {
            "pilgrim_id": "pilgrim_id",
            "status": "status",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize(r) for r in page], limit, offset, total)


def _rederive_installment_status(installment):
    if installment["status"] == "WAIVED":
        return
    if installment["amount_paid_cents"] >= installment["amount_due_cents"]:
        installment["status"] = "PAID"
    elif installment["amount_paid_cents"] > 0:
        installment["status"] = "PARTIALLY_PAID"
    else:
        installment["status"] = "SCHEDULED"


@bp.route("/payments/<payment_id>/reverse", methods=["POST"])
def reverse_payment(payment_id):
    authorize((ROLE_FINANCE_CONTROLLER,))
    body = body_of()
    with lock:
        payment = db.payments.get(payment_id)
        if payment is None:
            err("ERR_PAYMENT_NOT_FOUND", "Payment %s does not exist." % payment_id)
        req_str(body, "reversal_reason", 1, None)

        if payment["status"] != "APPLIED":
            err("ERR_PAYMENT_ALREADY_REVERSED", "This receipt has already been reversed.")
        pilgrim = db.pilgrims[payment["pilgrim_id"]]
        if pilgrim["booking_status"] == "CANCELLED":
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler's receipt cannot be reversed.")

        entries = list(zip(payment["allocation"], payment.get("_alloc_plan_ids", [])))
        touched_plans = []
        # Reverse list order: the CREDIT entries appended last unwind first, then
        # the installment entries in descending sequence_no.
        for entry, plan_id in reversed(entries):
            if entry["target"] == "CREDIT":
                pilgrim["credit_balance_cents"] = \
                    pilgrim["credit_balance_cents"] - entry["amount_cents"]
                continue
            plan = db.payment_plans.get(plan_id)
            if plan is None:
                continue
            if plan["id"] not in [p["id"] for p in touched_plans]:
                touched_plans.append(plan)
            for installment in plan["installments"]:
                if installment["sequence_no"] != entry["sequence_no"]:
                    continue
                installment["amount_paid_cents"] = \
                    installment["amount_paid_cents"] - entry["amount_cents"]
                _rederive_installment_status(installment)

        payment["status"] = "REVERSED"
        payment["reversed_at"] = response.iso_ms(core.clock_now())
        pilgrim["cash_applied_cents"] = pilgrim["cash_applied_cents"] - payment["amount_cents"]

        for plan in touched_plans:
            before = core.snap(plan)
            if plan["status"] == "COMPLETED":
                plan["status"] = "ACTIVE"
            core.refresh_past_due_count(plan)
            core.touch_if_changed(plan, before)

        core.rederive_payment_status_after_reversal(pilgrim)

        departure = core.departure_of(pilgrim)
        if pilgrim["booking_status"] == "DEPOSITED" and \
                pilgrim["cash_applied_cents"] < departure["provisional_deposit_cents"]:
            pilgrim["booking_status"] = "INQUIRY"
            core.touch(pilgrim)
            departure_before = core.snap(departure)
            core.recompute_provisional_tier(departure)
            core.touch_if_changed(departure, departure_before)
            core.refresh_recruiting_agreement(pilgrim, "snapshot")
        else:
            core.touch(pilgrim)

        return response.ok(core.serialize(payment))
