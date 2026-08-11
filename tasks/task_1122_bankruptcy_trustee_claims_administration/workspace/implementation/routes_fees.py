"""Fee application endpoints: OCC-guarded filing (server-computed §326
commission for TRUSTEE applicants), court approval/denial, trustee payment."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_STALE_CASE_VERSION,
    ERR_APPROVAL_EXCEEDS_REQUEST, ERR_FEE_NOT_YET_EFFECTIVE,
    ERR_INSUFFICIENT_ESTATE_FUNDS, ERR_INVALID_REQUEST,
)
from logical_clock import CLOCK
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_calc import add_days, commission_326, disbursed_basis, proposed_basis
from services_common import (
    new_entity, touch, bump_case, get_case, get_or_404, ensure_case_open,
    ensure_trustee_binding, ser_fee, sorted_rows,
)
from util import require_enum, require_int, optional_enum

bp = Blueprint("fees", __name__)

APPLICANT_ROLES = ("TRUSTEE", "AUCTIONEER", "COUNSEL")
COMMISSION_BASES = ("DISBURSED", "PROPOSED")


def _get_fee_and_case(fee_id):
    fee = get_or_404(db.fees, fee_id, "fee application")
    return fee, db.cases[fee["case_id"]]


@bp.route("/trustee/cases/<id>/fee_applications", methods=["POST"])
def file_fee(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee", "Clerk"))
    case = get_case(id)
    ensure_case_open(case)
    if role == "Trustee":
        ensure_trustee_binding(case, uid)
    body = json_body()

    expected = body.get("expected_case_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_case_version is required and must be an integer.")
    if expected != case["version"]:
        raise ApiError(ERR_STALE_CASE_VERSION, 412,
                       "expected_case_version does not match the case's current version.")

    applicant_role = require_enum(body, "applicant_role", APPLICANT_ROLES)
    requested = require_int(body, "requested_amount_cents", minimum=0)
    basis = optional_enum(body, "commission_basis", COMMISSION_BASES)

    computed = None
    if applicant_role == "TRUSTEE":
        if basis is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "commission_basis is required when applicant_role is TRUSTEE.")
        basis_amount = disbursed_basis(id) if basis == "DISBURSED" else proposed_basis(id)
        computed = commission_326(basis_amount)
        disbursed_commission = commission_326(disbursed_basis(id))
        if requested != disbursed_commission:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "requested_amount_cents must equal the §326 commission on the "
                           "DISBURSED basis at filing time.")

    fee = new_entity({
        "case_id": id,
        "applicant_role": applicant_role,
        "requested_amount_cents": requested,
        "commission_basis": basis,
        "computed_commission_cents": computed,
        "status": "FILED",
        "approved_amount_cents": None,
        "effective_on": None,
    })
    db.fees[fee["id"]] = fee
    bump_case(case)
    return ok_object(ser_fee(fee), status=201)


@bp.route("/trustee/cases/<id>/fee_applications", methods=["GET"])
def list_case_fees(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    status = request.args.get("status")
    applicant_role = request.args.get("applicant_role")
    rows = [f for f in db.fees.values() if f["case_id"] == id]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    if applicant_role is not None:
        rows = [f for f in rows if f["applicant_role"] == applicant_role]
    return paginate([ser_fee(f) for f in sorted_rows(rows)])


@bp.route("/trustee/fee_applications/<id>", methods=["GET"])
def get_fee(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_fee(get_or_404(db.fees, id, "fee application")))


@bp.route("/trustee/fee_applications/<id>/approve", methods=["POST"])
def approve_fee(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    fee, case = _get_fee_and_case(id)
    ensure_case_open(case)
    if fee["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409, "Fee application must be FILED to approve.")
    body = json_body()
    approved = require_int(body, "approved_amount_cents", minimum=0)
    if approved > fee["requested_amount_cents"]:
        raise ApiError(ERR_APPROVAL_EXCEEDS_REQUEST, 422,
                       "approved_amount_cents may not exceed requested_amount_cents.")
    fee["approved_amount_cents"] = approved
    fee["effective_on"] = add_days(CLOCK.now(), case["objection_window_days"])
    fee["status"] = "APPROVED"
    touch(fee)
    bump_case(case)
    return ok_object(ser_fee(fee))


@bp.route("/trustee/fee_applications/<id>/deny", methods=["POST"])
def deny_fee(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    fee, case = _get_fee_and_case(id)
    ensure_case_open(case)
    if fee["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409, "Fee application must be FILED to deny.")
    fee["status"] = "DENIED"
    touch(fee)
    bump_case(case)
    return ok_object(ser_fee(fee))


@bp.route("/trustee/fee_applications/<id>/pay", methods=["POST"])
def pay_fee(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    fee, case = _get_fee_and_case(id)
    ensure_case_open(case)
    if fee["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Fee application must be APPROVED to pay.")
    ensure_trustee_binding(case, uid)
    if CLOCK.now() < fee["effective_on"]:
        raise ApiError(ERR_FEE_NOT_YET_EFFECTIVE, 409,
                       "The fee application is not yet effective.")
    if case["estate_cash_on_hand_cents"] < fee["approved_amount_cents"]:
        raise ApiError(ERR_INSUFFICIENT_ESTATE_FUNDS, 409,
                       "Estate cash does not cover the approved fee.")
    case["estate_cash_on_hand_cents"] -= fee["approved_amount_cents"]
    fee["status"] = "PAID"
    touch(fee)
    bump_case(case)
    return ok_object(ser_fee(fee))
