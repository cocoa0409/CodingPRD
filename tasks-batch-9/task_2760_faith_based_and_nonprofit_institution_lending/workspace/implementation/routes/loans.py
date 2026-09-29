"""Origination, principal repayment and construction close-out
(PRD sections 3.6 and 3.7)."""

from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import LOAN_SERVICER, READ_ALL
from errors import ApiError

bp = Blueprint("loans", __name__)

DRAW_PHASE = ("PENDING_FIRST_DRAW", "CONSTRUCTION_DRAW")
OPEN_DRAW_STATES = ("SUBMITTED", "APPROVED", "SUSPENDED")


@bp.route("/loans", methods=["POST"])
def originate_loan():
    auth.authenticate((LOAN_SERVICER,))
    b = shapes.body()
    application = resolve.loan_application(b.get("loan_application_id"))
    if application is None:
        shapes.req_id_field(b, "loan_application_id")
    debt_service = shapes.req_int(b, "annual_debt_service_cents",
                                 exclusive_minimum=0)
    shortfall = shapes.req_int(b, "interest_reserve_shortfall_cents", minimum=0)

    existing = [l for l in store.loans.values()
                if l["loan_application_id"] == application["id"]]
    # ladder 19, with the ladder-26 carve-out for a repeat origination
    if application["status"] != "APPROVED":
        if application["status"] == "FUNDED" and existing:
            raise ApiError("ERR_LOAN_ALREADY_ORIGINATED")
        raise ApiError("ERR_APPLICATION_INVALID_STATE")
    # ladder 26
    if existing:
        raise ApiError("ERR_LOAN_ALREADY_ORIGINATED")

    principal = application["requested_amount_cents"]
    row = store.base_record()
    row.update({
        "loan_application_id": application["id"],
        "annual_debt_service_cents": debt_service,
        "interest_reserve_shortfall_cents": shortfall,
        "principal_cents": principal,
        "term_months": application["term_months"],
        "giving_basis": application.get("giving_basis"),
        "servicing_status": "PENDING_FIRST_DRAW",
        "risk_posture": "OPEN",
        "disbursed_principal_cents": 0,
        "undrawn_commitment_cents": principal,
        "cancelled_commitment_cents": 0,
        "reserved_draw_cents": 0,
        "retainage_held_cents": 0,
        "retainage_released_cents": 0,
        "outstanding_principal_cents": 0,
        "principal_repaid_cents": 0,
        "forgiven_principal_cents": 0,
        "deferred_payments_count": 0,
        "final_inspection_passed": None,
        "completion_note": None,
    })
    store.loans[row["id"]] = row
    store.mark_created(row)
    application["status"] = "FUNDED"
    store.touch(application)
    return envelope.created(serializers.loan(row))


@bp.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.loan(loan_id)
    auth.scope(ctx, auth.owner_of_loan(row))
    return envelope.ok(serializers.loan(row))


@bp.route("/loans", methods=["GET"])
def list_loans():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(list(store.loans.values()),
                                {"loan_application_id": "loan_application_id",
                                 "servicing_status": "servicing_status",
                                 "risk_posture": "risk_posture"})
    return envelope.listing(envelope.sort_created_desc(rows), serializers.loan)


@bp.route("/loans/<loan_id>/payments", methods=["POST"])
def loan_payment(loan_id):
    auth.authenticate((LOAN_SERVICER,))
    loan = resolve.loan(loan_id)
    b = shapes.body()
    amount = shapes.req_int(b, "amount_cents", minimum=0)
    shapes.req_dt(b, "payment_date")
    # ladder 27
    if loan["servicing_status"] == "PAID_OFF":
        raise ApiError("ERR_LOAN_TERMINAL")
    # ladder 52
    if amount > loan["outstanding_principal_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_OUTSTANDING")

    loan["principal_repaid_cents"] += amount
    loan["outstanding_principal_cents"] -= amount
    if loan["outstanding_principal_cents"] == 0 and \
            loan["servicing_status"] == "AMORTIZING":
        loan["servicing_status"] = "PAID_OFF"
    store.touch(loan)
    return envelope.ok(serializers.loan(loan))


@bp.route("/loans/<loan_id>/construction-completion", methods=["POST"])
def construction_completion(loan_id):
    auth.authenticate((LOAN_SERVICER,))
    loan = resolve.loan(loan_id)
    b = shapes.body()
    passed = shapes.req_bool(b, "final_inspection_passed")
    note = shapes.opt_str(b, "completion_note")
    if passed is not True:
        shapes.bad("final_inspection_passed", "must be true")
    # ladder 21 — no draw may still be open
    for draw in store.children(store.draw_requests, "loan_id", loan["id"]):
        if draw["status"] in OPEN_DRAW_STATES:
            raise ApiError("ERR_DRAW_INVALID_STATE")
    # ladder 27
    if loan["servicing_status"] == "PAID_OFF":
        raise ApiError("ERR_LOAN_TERMINAL")
    if loan["servicing_status"] not in DRAW_PHASE:
        raise ApiError("ERR_LOAN_NOT_IN_DRAW_PHASE")

    loan["cancelled_commitment_cents"] += loan["undrawn_commitment_cents"]
    loan["undrawn_commitment_cents"] = 0
    loan["retainage_released_cents"] += loan["retainage_held_cents"]
    loan["retainage_held_cents"] = 0
    loan["servicing_status"] = "AMORTIZING"
    loan["final_inspection_passed"] = True
    loan["completion_note"] = note
    store.touch(loan)
    return envelope.ok(serializers.loan(loan))
