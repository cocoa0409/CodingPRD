"""Routes: payee change requests."""

from flask import Blueprint, request

from db import DB, base_entity, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_STATE_PROFILE_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_CHANGE_REQUEST_INVALID_STATE,
    ERR_SOD_VIOLATION,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_caller, require_roles, get_json_body, check_unknown_fields,
    require_field, opt_field, as_string, as_enum, parse_pagination,
)
from response import success_object, success_list
from services import pub, list_view, find_profile_by_state

bp = Blueprint("changes", __name__)

CHANGE_FIELDS = {
    "payee_id", "change_type",
    "new_address_line1", "new_address_city", "new_address_state_code",
    "new_address_postal_code", "new_full_name",
    "new_bank_routing_number", "new_bank_account_number",
}


def request_view(r):
    return pub(r)


def _has_open_returned_case(payee_id):
    for c in DB.returned_payment_cases.values():
        if c["status"] not in ("OPEN", "ESCHEAT_PENDING"):
            continue
        p = DB.scheduled_payments.get(c["scheduled_payment_id"])
        if p is not None and p["payee_id"] == payee_id:
            return True
    return False


def _apply_change(r):
    payee = DB.payees.get(r["payee_id"])
    if payee is None:
        return
    if r["change_type"] == "ADDRESS":
        payee["address_line1"] = r.get("new_address_line1")
        payee["address_city"] = r.get("new_address_city")
        payee["address_state_code"] = r.get("new_address_state_code")
        payee["address_postal_code"] = r.get("new_address_postal_code")
        touch(payee)
    elif r["change_type"] == "NAME":
        payee["full_name"] = r.get("new_full_name")
        touch(payee)
    elif r["change_type"] == "BANK_ACCOUNT":
        # recorded on request only, but payee version still increments
        touch(payee)


@bp.route("/annuity/payee-change-requests", methods=["POST"])
def create_change_request():
    caller = get_caller()
    require_roles(caller, {"Payee", "CaseManager"})
    body = get_json_body()
    pid = body.get("payee_id")
    # Payee self-service ownership (priority 2)
    if caller.role == "Payee":
        if pid is not None and isinstance(pid, str) and pid != caller.user_id:
            raise ApiError(ERR_FORBIDDEN_ROLE, "Payee may only submit change requests for themselves", 403)
    # existence
    payee = None
    if pid is not None and isinstance(pid, str):
        payee = DB.payees.get(pid)
        if payee is None:
            raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    nasc = body.get("new_address_state_code")
    if nasc is not None and isinstance(nasc, str):
        if find_profile_by_state(nasc) is None:
            raise ApiError(ERR_STATE_PROFILE_NOT_FOUND, "No StateStatuteProfile for new_address_state_code", 404)
    # shape
    check_unknown_fields(body, CHANGE_FIELDS)
    pid = as_string(require_field(body, "payee_id"), "payee_id")
    if caller.role == "Payee" and pid != caller.user_id:
        raise ApiError(ERR_FORBIDDEN_ROLE, "Payee may only submit change requests for themselves", 403)
    payee = DB.payees.get(pid)
    if payee is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    ctype = as_enum(require_field(body, "change_type"), "change_type",
                    {"ADDRESS", "NAME", "BANK_ACCOUNT"})
    new_al1 = opt_field(body, "new_address_line1")
    new_city = opt_field(body, "new_address_city")
    new_st = opt_field(body, "new_address_state_code")
    new_postal = opt_field(body, "new_address_postal_code")
    new_name = opt_field(body, "new_full_name")
    new_routing = opt_field(body, "new_bank_routing_number")
    new_account = opt_field(body, "new_bank_account_number")

    if ctype == "ADDRESS":
        new_al1 = as_string(new_al1, "new_address_line1") if new_al1 is not None else None
        new_city = as_string(new_city, "new_address_city") if new_city is not None else None
        new_st = as_string(new_st, "new_address_state_code") if new_st is not None else None
        new_postal = as_string(new_postal, "new_address_postal_code") if new_postal is not None else None
        if new_st is not None and find_profile_by_state(new_st) is None:
            raise ApiError(ERR_STATE_PROFILE_NOT_FOUND, "No StateStatuteProfile for new_address_state_code", 404)
    elif ctype == "NAME":
        new_name = as_string(new_name, "new_full_name") if new_name is not None else None
    elif ctype == "BANK_ACCOUNT":
        new_routing = as_string(new_routing, "new_bank_routing_number") if new_routing is not None else None
        new_account = as_string(new_account, "new_bank_account_number") if new_account is not None else None

    e = base_entity()
    e.update({
        "payee_id": pid,
        "change_type": ctype,
        "new_address_line1": new_al1,
        "new_address_city": new_city,
        "new_address_state_code": new_st,
        "new_address_postal_code": new_postal,
        "new_full_name": new_name,
        "new_bank_routing_number": new_routing,
        "new_bank_account_number": new_account,
        "submitted_by_user_id": caller.user_id,
        "status": "SUBMITTED",
    })
    DB.payee_change_requests[e["id"]] = e

    # auto-approve path: ADDRESS and no OPEN/ESCHEAT_PENDING returned case
    if ctype == "ADDRESS" and not _has_open_returned_case(pid):
        e["status"] = "APPROVED"
        touch(e)
        _apply_change(e)
    else:
        e["status"] = "UNDER_REVIEW"
        touch(e)
    return success_object(request_view(e), status=201)


@bp.route("/annuity/payee-change-requests", methods=["GET"])
def list_change_requests():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.payee_change_requests.values())
    pid = request.args.get("payee_id")
    if pid is not None:
        items = [r for r in items if r["payee_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/payee-change-requests/<requestId>", methods=["GET"])
def get_change_request(requestId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    r = DB.payee_change_requests.get(requestId)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, "PayeeChangeRequest not found", 404)
    return success_object(request_view(r))


@bp.route("/annuity/payee-change-requests/<requestId>/approve", methods=["POST"])
def approve_change_request(requestId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    r = DB.payee_change_requests.get(requestId)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, "PayeeChangeRequest not found", 404)
    if r["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_CHANGE_REQUEST_INVALID_STATE, "Change request not UNDER_REVIEW", 409)
    if caller.user_id == r["submitted_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, "Approver must differ from submitter", 403)
    get_json_body()
    r["status"] = "APPROVED"
    touch(r)
    _apply_change(r)
    return success_object(request_view(r))


@bp.route("/annuity/payee-change-requests/<requestId>/reject", methods=["POST"])
def reject_change_request(requestId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    r = DB.payee_change_requests.get(requestId)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, "PayeeChangeRequest not found", 404)
    if r["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_CHANGE_REQUEST_INVALID_STATE, "Change request not UNDER_REVIEW", 409)
    get_json_body()
    r["status"] = "REJECTED"
    touch(r)
    return success_object(request_view(r))
