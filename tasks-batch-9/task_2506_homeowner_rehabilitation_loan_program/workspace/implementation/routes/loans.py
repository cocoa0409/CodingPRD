"""Loan structuring, lien recording, close-out, servicing and recapture (PRD 3.6, 3.7, 3.8)."""

from flask import Blueprint

import clock
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

bp = Blueprint("loans", __name__)

READ_ROLES = middleware.STAFF_ROLES
READ_ONE_ROLES = middleware.STAFF_ROLES + (middleware.APPLICANT,)


def _awarded_bid_of(application):
    for solicitation in domain.solicitations_of(application["id"]):
        if solicitation["status"] == "AWARDED" and solicitation["award_bid_id"]:
            bid = db.bids.get(solicitation["award_bid_id"])
            if bid is not None:
                return bid
    return None


def _unforgiven(loan):
    balance = loan["principal_cents"] - (loan["forgiven_cents"] or 0) - loan["principal_repaid_cents"]
    return balance if balance > 0 else 0


@bp.post(API_PREFIX + "/loans")
@middleware.roles(middleware.LOAN_OFFICER)
def create_loan():
    body = validation.json_body()
    application = validation.body_fk(
        body, "application_id", db.applications, errors.ERR_APPLICATION_NOT_FOUND
    )
    validation.field_id(body, "application_id")
    structure_type = validation.field_enum(body, "structure_type", C.STRUCTURE_TYPES)
    interest_rate_bps = validation.field_int(
        body, "interest_rate_bps", required=False, default=0, minimum=0
    )
    term_months = validation.field_int(
        body, "term_months", required=False, default=0, minimum=0
    )
    forgiveness_term_months = validation.field_int(
        body, "forgiveness_term_months", required=False, default=0, minimum=0
    )

    if structure_type == "AMORTIZING":
        if term_months < 1:
            fail(
                errors.ERR_INVALID_REQUEST,
                "Field 'term_months' must be at least 1 for an AMORTIZING note.",
            )
        if forgiveness_term_months != 0:
            fail(
                errors.ERR_INVALID_REQUEST,
                "Field 'forgiveness_term_months' must be 0 for an AMORTIZING note.",
            )
    else:
        if interest_rate_bps != 0:
            fail(
                errors.ERR_INVALID_REQUEST,
                "Field 'interest_rate_bps' must be 0 for a %s note." % structure_type,
            )
        if term_months != 0:
            fail(
                errors.ERR_INVALID_REQUEST,
                "Field 'term_months' must be 0 for a %s note." % structure_type,
            )
        if forgiveness_term_months <= 0:
            fail(
                errors.ERR_INVALID_REQUEST,
                "Field 'forgiveness_term_months' must be greater than 0 for a %s note."
                % structure_type,
            )

    if domain.loan_of_application(application["id"]) is not None:
        fail(errors.ERR_INVALID_STATE, "The case already carries a structured note.")
    bid = _awarded_bid_of(application)
    if bid is None:
        fail(errors.ERR_INVALID_STATE, "The case has no awarded construction contract.")

    program_year = db.program_years.get(application["program_year_id"])
    if program_year is None:
        fail(errors.ERR_PROGRAM_YEAR_NOT_FOUND)

    awarded_amount = bid["amount_cents"]
    if awarded_amount > program_year["max_loan_amount_cents"]:
        fail(errors.ERR_LOAN_LIMIT_EXCEEDED)

    fee = calc.lien_recording_fee(awarded_amount)
    principal = calc.principal_for(awarded_amount, fee, program_year["max_loan_amount_cents"])
    monthly_payment = calc.monthly_payment(
        structure_type, principal, interest_rate_bps, term_months
    )

    row = db.new_row()
    row.update(
        {
            "application_id": application["id"],
            "structure_type": structure_type,
            "awarded_bid_amount_cents": awarded_amount,
            "approved_project_cost_cents": awarded_amount,
            "lien_recording_fee_cents": fee,
            "principal_cents": principal,
            "interest_rate_bps": interest_rate_bps,
            "term_months": term_months,
            "forgiveness_term_months": forgiveness_term_months,
            "monthly_payment_cents": monthly_payment,
            "lien_position": None,
            "lien_recorded_at": None,
            "forgiveness_start_date": None,
            "status": "STRUCTURED",
            "contract_earned_cents": 0,
            "disbursed_cents": 0,
            "retainage_held_cents": 0,
            "forgiven_cents": 0,
            "principal_repaid_cents": 0,
            "unforgiven_balance_cents": principal,
            "recapture_event_type": None,
            "recapture_event_date": None,
            "net_proceeds_cents": None,
            "recapture_amount_cents": None,
            "shortfall_forgiven_cents": None,
            "program_income_posted_cents": None,
        }
    )
    db.loans[row["id"]] = row
    return response.object_response(serializers.loan(row), 201)


@bp.post(API_PREFIX + "/loans/<loan_id>/record-lien")
@middleware.roles(middleware.LOAN_OFFICER)
def record_lien(loan_id):
    row = validation.path_row(db.loans, loan_id, errors.ERR_LOAN_NOT_FOUND)
    body = validation.json_body()
    lien_position = validation.field_int(body, "lien_position", minimum=1)
    validation.field_str(body, "recorded_instrument_number")

    if row["status"] != "STRUCTURED":
        fail(errors.ERR_INVALID_STATE, "The lien has already been recorded.")

    application = db.applications.get(row["application_id"])
    posture = application["compliance_posture"] if application else "CLEAR"
    if application is not None and application["lead_review_required"]:
        if posture in ("LEAD_HOLD", "DUAL_HOLD"):
            fail(errors.ERR_LEAD_CLEARANCE_REQUIRED)
    if application is not None and application["historic_review_required"]:
        if posture in ("HISTORIC_HOLD", "DUAL_HOLD", "ADVERSE_EFFECT_BLOCKED"):
            fail(errors.ERR_HISTORIC_CLEARANCE_REQUIRED)

    program_year = db.program_years.get(application["program_year_id"]) if application else None
    if program_year is None:
        fail(errors.ERR_PROGRAM_YEAR_NOT_FOUND)
    snapshot = domain.program_year_snapshot(program_year)
    if domain.ledger(program_year)["uncommitted_amount_cents"] < row["principal_cents"]:
        fail(errors.ERR_ALLOCATION_INSUFFICIENT)

    row["lien_position"] = lien_position
    row["lien_recorded_at"] = clock.now()
    row["status"] = "LIEN_RECORDED"
    # The recording fee passes straight through the committed bucket.
    row["disbursed_cents"] += row["lien_recording_fee_cents"]
    row["unforgiven_balance_cents"] = _unforgiven(row)
    db.touch(row)

    if application["workflow_state"] == "AWARDED":
        application["workflow_state"] = "UNDER_CONSTRUCTION"
        db.touch(application)

    domain.touch_program_year(program_year, snapshot)

    return response.object_response(serializers.loan(row))


@bp.post(API_PREFIX + "/loans/<loan_id>/close-out")
@middleware.roles(middleware.LOAN_OFFICER)
def close_out(loan_id):
    row = validation.path_row(db.loans, loan_id, errors.ERR_LOAN_NOT_FOUND)
    body = validation.json_body()
    completion_date = validation.field_datetime(body, "completion_date")

    if row["status"] not in ("DISBURSING", "FULLY_DISBURSED"):
        fail(errors.ERR_INVALID_STATE, "The loan is not in construction.")
    if row["retainage_held_cents"] != 0:
        fail(errors.ERR_INVALID_STATE, "Retainage is still held on this loan.")
    if row["lien_recorded_at"] is not None and completion_date < row["lien_recorded_at"]:
        fail(
            errors.ERR_INVALID_STATE,
            "The completion date may not precede the lien recording instant.",
        )

    application = db.applications.get(row["application_id"])
    program_year = db.program_years.get(application["program_year_id"]) if application else None
    snapshot = domain.program_year_snapshot(program_year) if program_year else None

    row["principal_cents"] = row["disbursed_cents"]
    row["unforgiven_balance_cents"] = _unforgiven(row)
    row["monthly_payment_cents"] = calc.monthly_payment(
        row["structure_type"], row["principal_cents"], row["interest_rate_bps"], row["term_months"]
    )
    row["forgiveness_start_date"] = completion_date
    row["status"] = "SERVICING"
    db.touch(row)

    if application is not None:
        application["workflow_state"] = "CLOSED"
        application["warranty_expires_at"] = clock.add_months(
            completion_date, C.WARRANTY_MONTHS
        )
        db.touch(application)

        contractor = db.contractors.get(application.get("awarded_contractor_id"))
        if contractor is not None:
            contractor["on_time_completion_count"] += 1
            db.touch(contractor)

    if program_year is not None:
        domain.touch_program_year(program_year, snapshot)

    return response.object_response(serializers.loan(row))


@bp.post(API_PREFIX + "/loans/<loan_id>/payments")
@middleware.roles(middleware.LOAN_OFFICER)
def post_payment(loan_id):
    row = validation.path_row(db.loans, loan_id, errors.ERR_LOAN_NOT_FOUND)
    body = validation.json_body()
    amount = validation.field_int(body, "amount_cents", minimum=0)
    validation.field_datetime(body, "payment_date")

    if row["status"] != "SERVICING":
        fail(errors.ERR_INVALID_STATE, "Only a servicing note accepts homeowner payments.")

    application = db.applications.get(row["application_id"])
    program_year = db.program_years.get(application["program_year_id"]) if application else None
    snapshot = domain.program_year_snapshot(program_year) if program_year else None

    row["principal_repaid_cents"] += amount
    row["unforgiven_balance_cents"] = _unforgiven(row)
    db.touch(row)

    if program_year is not None:
        program_year["program_income_balance_cents"] += amount
        domain.touch_program_year(program_year, snapshot)

    return response.object_response(serializers.loan(row))


@bp.post(API_PREFIX + "/loans/<loan_id>/recapture")
@middleware.roles(middleware.PROGRAM_MANAGER)
def recapture(loan_id):
    row = validation.path_row(db.loans, loan_id, errors.ERR_LOAN_NOT_FOUND)
    body = validation.json_body()
    event_type = validation.field_enum(body, "recapture_event_type", C.RECAPTURE_EVENT_TYPES)
    event_date = validation.field_datetime(body, "recapture_event_date")
    sale_price = validation.field_int(
        body, "sale_price_cents", required=False, default=0, minimum=0
    )
    closing_costs = validation.field_int(
        body, "closing_costs_cents", required=False, default=0, minimum=0
    )
    homeowner_investment = validation.field_int(
        body, "homeowner_investment_cents", required=False, default=0, minimum=0
    )

    if row["status"] != "SERVICING":
        fail(errors.ERR_INVALID_STATE, "Only a servicing note may be settled.")

    application = db.applications.get(row["application_id"])
    program_year = db.program_years.get(application["program_year_id"]) if application else None
    snapshot = domain.program_year_snapshot(program_year) if program_year else None

    figures = calc.recapture_figures(
        row,
        application if application else {"senior_lien_balance_cents": 0},
        event_type,
        event_date,
        sale_price,
        closing_costs,
        homeowner_investment,
    )
    row["recapture_event_type"] = event_type
    row["recapture_event_date"] = event_date
    row.update(figures)
    row["status"] = "RECAPTURED" if figures["recapture_amount_cents"] > 0 else "FORGIVEN"
    db.touch(row)

    if program_year is not None and figures["program_income_posted_cents"]:
        program_year["program_income_balance_cents"] += figures["program_income_posted_cents"]
        domain.touch_program_year(program_year, snapshot)

    return response.object_response(serializers.loan(row))


@bp.get(API_PREFIX + "/loans/<loan_id>")
@middleware.roles(*READ_ONE_ROLES)
def read_loan(loan_id):
    middleware.scope_loan(loan_id)
    row = validation.path_row(db.loans, loan_id, errors.ERR_LOAN_NOT_FOUND)
    return response.object_response(serializers.loan(row))


@bp.get(API_PREFIX + "/loans")
@middleware.roles(*READ_ROLES)
def list_loans():
    application_id = validation.filter_str("application_id")
    status = validation.filter_enum("status", C.LOAN_STATUSES)
    structure_type = validation.filter_enum("structure_type", C.STRUCTURE_TYPES)
    rows = []
    for row in db.loans.values():
        if application_id is not None and row["application_id"] != application_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if structure_type is not None and row["structure_type"] != structure_type:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.loan)
