"""Construction change orders, the supersedes chain and the cumulative exposure test (PRD 3.7)."""

from flask import Blueprint

import db
import errors
import middleware
import paging
import response
import validation
from errors import fail
from routes import API_PREFIX
from services import calc, domain, serializers
from services import constants as C

bp = Blueprint("change_orders", __name__)

READ_ROLES = middleware.STAFF_ROLES + (middleware.CONTRACTOR,)
SECURED_LOAN_STATUSES = ("LIEN_RECORDED", "DISBURSING")


@bp.post(API_PREFIX + "/change-orders")
@middleware.roles(middleware.REHAB_SPECIALIST)
def create_change_order():
    body = validation.json_body()
    loan = validation.body_fk(body, "loan_id", db.loans, errors.ERR_LOAN_NOT_FOUND)
    validation.field_id(body, "loan_id")
    supersedes = validation.body_fk(
        body, "supersedes_change_order_id", db.change_orders, errors.ERR_CHANGE_ORDER_NOT_FOUND
    )
    expected = validation.field_int(body, "expected_loan_version", minimum=0)
    amount_delta = validation.field_int(body, "amount_delta_cents")
    if amount_delta == 0:
        fail(errors.ERR_INVALID_REQUEST, "Field 'amount_delta_cents' may not be zero.")
    justification = validation.field_str(body, "justification")
    affects_lead = validation.field_bool(body, "affects_lead_hazard_work", default=False)

    validation.check_version(loan, expected)

    if not loan["lien_recorded_at"] or loan["status"] not in SECURED_LOAN_STATUSES:
        fail(errors.ERR_LIEN_NOT_RECORDED)

    row = db.new_row()
    row.update(
        {
            "loan_id": loan["id"],
            "supersedes_change_order_id": supersedes["id"] if supersedes else None,
            "amount_delta_cents": amount_delta,
            "justification": justification,
            "affects_lead_hazard_work": affects_lead,
            "cumulative_delta_pct": calc.round_half_up_2dp(0),
            "status": "SUBMITTED",
            "submitted_by_user_id": middleware.user_id(),
        }
    )
    db.change_orders[row["id"]] = row

    db.touch(loan)

    return response.object_response(serializers.change_order(row), 201)


@bp.post(API_PREFIX + "/change-orders/<change_order_id>/approve")
@middleware.roles(middleware.PROGRAM_MANAGER)
def approve_change_order(change_order_id):
    row = validation.path_row(
        db.change_orders, change_order_id, errors.ERR_CHANGE_ORDER_NOT_FOUND
    )
    loan = db.loans.get(row["loan_id"])

    if row["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_STATE, "Only a submitted change order may be decided.")
    if loan is None or loan["status"] not in SECURED_LOAN_STATUSES:
        fail(errors.ERR_INVALID_STATE, "The loan is not in a state that accepts scope changes.")

    application = db.applications.get(loan["application_id"])
    program_year = (
        db.program_years.get(application["program_year_id"]) if application else None
    )
    if program_year is None:
        fail(errors.ERR_PROGRAM_YEAR_NOT_FOUND)
    snapshot = domain.program_year_snapshot(program_year)

    cumulative, pct = calc.cumulative_delta(
        row, loan, domain.change_orders_of(loan["id"]), db.change_orders
    )

    # The superseded chain is backed out of the contract before the new delta lands.
    closure = calc.superseded_closure(row, db.change_orders)
    superseded_rows = []
    backed_out = 0
    for change_order_id_in_chain in closure:
        prior = db.change_orders.get(change_order_id_in_chain)
        if prior is not None and prior["status"] == "APPROVED":
            superseded_rows.append(prior)
            backed_out += prior["amount_delta_cents"]

    new_cost = loan["approved_project_cost_cents"] - backed_out + row["amount_delta_cents"]
    new_principal = calc.principal_for(
        new_cost, loan["lien_recording_fee_cents"], program_year["max_loan_amount_cents"]
    )
    principal_increase = new_principal - loan["principal_cents"]

    if row["amount_delta_cents"] > 0:
        uncommitted = domain.ledger(program_year)["uncommitted_amount_cents"]
        if principal_increase > uncommitted:
            fail(errors.ERR_ALLOCATION_INSUFFICIENT)

    if calc.exceeds_change_order_limit(pct):
        fail(errors.ERR_CHANGE_ORDER_EXCEEDS_LIMIT)

    for prior in db.ordered(superseded_rows):
        prior["status"] = "SUPERSEDED"
        db.touch(prior)

    row["cumulative_delta_pct"] = pct
    row["status"] = "APPROVED"
    db.touch(row)

    loan["approved_project_cost_cents"] = new_cost
    loan["principal_cents"] = new_principal
    loan["unforgiven_balance_cents"] = max(
        0,
        new_principal - loan["forgiven_cents"] - loan["principal_repaid_cents"],
    )
    db.touch(loan)

    domain.touch_program_year(program_year, snapshot)

    if row["affects_lead_hazard_work"] and application is not None:
        if application["lead_review_required"]:
            application["compliance_posture"] = "LEAD_HOLD"
            application["lead_hazard_control_method"] = "NONE"
            db.touch(application)

    return response.object_response(serializers.change_order(row))


@bp.post(API_PREFIX + "/change-orders/<change_order_id>/deny")
@middleware.roles(middleware.PROGRAM_MANAGER)
def deny_change_order(change_order_id):
    row = validation.path_row(
        db.change_orders, change_order_id, errors.ERR_CHANGE_ORDER_NOT_FOUND
    )
    body = validation.json_body()
    validation.field_str(body, "reason")

    if row["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_STATE, "Only a submitted change order may be decided.")

    row["status"] = "DENIED"
    db.touch(row)
    return response.object_response(serializers.change_order(row))


@bp.get(API_PREFIX + "/change-orders/<change_order_id>")
@middleware.roles(*READ_ROLES)
def read_change_order(change_order_id):
    row = validation.path_row(
        db.change_orders, change_order_id, errors.ERR_CHANGE_ORDER_NOT_FOUND
    )
    return response.object_response(serializers.change_order(row))


@bp.get(API_PREFIX + "/change-orders")
@middleware.roles(*READ_ROLES)
def list_change_orders():
    loan_id = validation.filter_str("loan_id")
    supersedes_id = validation.filter_str("supersedes_change_order_id")
    status = validation.filter_enum("status", C.CHANGE_ORDER_STATUSES)
    rows = []
    for row in db.change_orders.values():
        if loan_id is not None and row["loan_id"] != loan_id:
            continue
        if supersedes_id is not None and row["supersedes_change_order_id"] != supersedes_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.change_order)
