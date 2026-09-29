"""Construction draw requests, approval and the four-hop payment cascade (PRD 3.7)."""

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

bp = Blueprint("draw_requests", __name__)

READ_ROLES = middleware.STAFF_ROLES + (middleware.CONTRACTOR,)
CLEARED_POSTURES = ("CLEAR", "CLEARED_WITH_PROTOCOL")
SECURED_LOAN_STATUSES = ("LIEN_RECORDED", "DISBURSING")


def _passing_inspector(draw):
    """The performer of the most recent DRAW visit that passed this draw."""
    performer = None
    for row in db.ordered(list(db.inspections.values())):
        if row["draw_request_id"] != draw["id"]:
            continue
        if row["inspection_type"] != "DRAW":
            continue
        if row["status"] != "COMPLETED" or row["result"] != "PASS":
            continue
        performer = row["performed_by_user_id"]
    return performer


@bp.post(API_PREFIX + "/draw-requests")
@middleware.roles(middleware.CONTRACTOR)
def create_draw_request():
    body = validation.json_body()
    middleware.scope_body_contractor(body)

    loan = validation.body_fk(body, "loan_id", db.loans, errors.ERR_LOAN_NOT_FOUND)
    validation.field_id(body, "loan_id")
    contractor = validation.body_fk(
        body, "contractor_id", db.contractors, errors.ERR_CONTRACTOR_NOT_FOUND
    )
    validation.field_id(body, "contractor_id")

    # The requesting firm must be the awarded contractor of the loan's case.
    application = db.applications.get(loan["application_id"])
    if application is None or application["awarded_contractor_id"] != contractor["id"]:
        fail(errors.ERR_OWNERSHIP_MISMATCH)

    requested_amount = validation.field_int(body, "requested_amount_cents", minimum=1)
    is_final_draw = validation.field_bool(body, "is_final_draw", default=False)

    if not loan["lien_recorded_at"] or loan["status"] not in SECURED_LOAN_STATUSES:
        fail(errors.ERR_LIEN_NOT_RECORDED)

    row = db.new_row()
    row.update(
        {
            "loan_id": loan["id"],
            "contractor_id": contractor["id"],
            "requested_amount_cents": requested_amount,
            "is_final_draw": is_final_draw,
            "approved_amount_cents": None,
            "retainage_cents": None,
            "net_payment_cents": None,
            "status": "SUBMITTED",
            "approved_by_user_id": None,
            "paid_at": None,
        }
    )
    db.draw_requests[row["id"]] = row
    return response.object_response(serializers.draw_request(row), 201)


@bp.post(API_PREFIX + "/draw-requests/<draw_request_id>/approve")
@middleware.roles(middleware.LOAN_OFFICER)
def approve_draw(draw_request_id):
    row = validation.path_row(db.draw_requests, draw_request_id, errors.ERR_DRAW_NOT_FOUND)
    loan = db.loans.get(row["loan_id"])
    application = db.applications.get(loan["application_id"]) if loan else None

    # Priority 11: an approved change order may have re-opened the lead hold.
    if application is not None and application["compliance_posture"] not in CLEARED_POSTURES:
        fail(errors.ERR_LEAD_CLEARANCE_REQUIRED)

    # Priority 13 replaces the generic state gate for this endpoint.
    if row["status"] != "INSPECTION_PASSED":
        fail(errors.ERR_DRAW_INSPECTION_NOT_PASSED)

    # Priority 15: the approver may not be the inspector who passed the draw.
    if _passing_inspector(row) == middleware.user_id():
        fail(errors.ERR_SEGREGATION_OF_DUTIES)

    # Priority 22: the draw must fit inside the construction contract.
    if loan is not None:
        remaining = loan["approved_project_cost_cents"] - loan["contract_earned_cents"]
        if row["requested_amount_cents"] > remaining:
            fail(errors.ERR_DRAW_EXCEEDS_CONTRACT_BALANCE)

    retainage_held = loan["retainage_held_cents"] if loan else 0
    approved, retainage, net_payment = calc.draw_amounts(
        row["requested_amount_cents"], row["is_final_draw"], retainage_held
    )
    row["approved_amount_cents"] = approved
    row["retainage_cents"] = retainage
    row["net_payment_cents"] = net_payment
    row["approved_by_user_id"] = middleware.user_id()
    row["status"] = "APPROVED"
    db.touch(row)

    return response.object_response(serializers.draw_request(row))


@bp.post(API_PREFIX + "/draw-requests/<draw_request_id>/pay")
@middleware.roles(middleware.LOAN_OFFICER)
def pay_draw(draw_request_id):
    row = validation.path_row(db.draw_requests, draw_request_id, errors.ERR_DRAW_NOT_FOUND)
    loan = db.loans.get(row["loan_id"])

    if row["status"] != "APPROVED":
        fail(errors.ERR_INVALID_STATE, "Only an approved draw may be paid.")
    if loan is None or loan["status"] not in SECURED_LOAN_STATUSES:
        fail(errors.ERR_INVALID_STATE, "The loan is not in a disbursing state.")

    application = db.applications.get(loan["application_id"])
    program_year = (
        db.program_years.get(application["program_year_id"]) if application else None
    )
    snapshot = domain.program_year_snapshot(program_year) if program_year else None

    # Hop one: the draw and the loan money.
    row["status"] = "PAID"
    row["paid_at"] = clock.now()
    db.touch(row)

    loan["contract_earned_cents"] += row["approved_amount_cents"]
    if row["is_final_draw"]:
        loan["retainage_held_cents"] = 0
    else:
        loan["retainage_held_cents"] += row["retainage_cents"]
    loan["disbursed_cents"] += row["net_payment_cents"]

    # Hop three: the loan lifecycle.
    if loan["status"] == "LIEN_RECORDED":
        loan["status"] = "DISBURSING"
    fully_disbursed = False
    if loan["status"] == "DISBURSING" and loan["disbursed_cents"] == loan["principal_cents"]:
        loan["status"] = "FULLY_DISBURSED"
        fully_disbursed = True
    loan["unforgiven_balance_cents"] = max(
        0,
        loan["principal_cents"] - loan["forgiven_cents"] - loan["principal_repaid_cents"],
    )
    db.touch(loan)

    # Hop two: the program-year ledger (derived from the loans of the year).
    domain.touch_program_year(program_year, snapshot)

    # Hop four: only the second loan transition drives the case.
    if fully_disbursed and application is not None:
        if application["workflow_state"] == "UNDER_CONSTRUCTION":
            application["workflow_state"] = "CONSTRUCTION_COMPLETE"
            db.touch(application)

    return response.object_response(serializers.draw_request(row))


@bp.get(API_PREFIX + "/draw-requests/<draw_request_id>")
@middleware.roles(*READ_ROLES)
def read_draw_request(draw_request_id):
    row = validation.path_row(db.draw_requests, draw_request_id, errors.ERR_DRAW_NOT_FOUND)
    return response.object_response(serializers.draw_request(row))


@bp.get(API_PREFIX + "/draw-requests")
@middleware.roles(*READ_ROLES)
def list_draw_requests():
    loan_id = validation.filter_str("loan_id")
    contractor_id = validation.filter_str("contractor_id")
    status = validation.filter_enum("status", C.DRAW_STATUSES)
    rows = []
    for row in db.draw_requests.values():
        if loan_id is not None and row["loan_id"] != loan_id:
            continue
        if contractor_id is not None and row["contractor_id"] != contractor_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.draw_request)
