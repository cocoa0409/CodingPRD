"""Error resolution cases (RESPA Reg X)."""

from flask import Blueprint, request

from auth import any_role, check_borrower_owner, require_roles
from domain import account_of_loan, post_ledger, replay, void_notices_of_analysis
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_DUP_CASE,
    ERR_EXTENSION_PASSED,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SOD,
    not_found,
)
from routes_core import get_loan_or_404
from serializers import error_case_out
from store import store
from util import (
    add_business_days,
    bump,
    fmt_date,
    new_record,
    now_ts,
    ok,
    ok_list,
    parse_date,
    today,
)
from validate import body, opt_int, req_enum, req_str

bp = Blueprint("error_cases", __name__)

ERROR_TYPES = (
    "DISBURSEMENT_FAILURE", "DISBURSEMENT_AMOUNT_ERROR", "UNTIMELY_DISBURSEMENT",
    "FORCE_PLACEMENT_ERROR", "ANALYSIS_ERROR", "PAYMENT_APPLICATION_ERROR",
    "OTHER_COVERED",
)
OPEN_STATES = ("RECEIVED", "ACKNOWLEDGED", "INVESTIGATING", "EXTENDED")
TERMINAL = ("RESOLVED_CORRECTED", "RESOLVED_NO_ERROR", "DISMISSED_NOT_COVERED")


def get_case_or_404(cid):
    c = store.error_cases.get(cid)
    if c is None:
        raise not_found("ErrorResolutionCase not found")
    return c


@bp.post("/servicing/loans/<lid>/error-cases")
def create_case(lid):
    uid, role = require_roles("Borrower")
    check_borrower_owner(uid, lid)
    loan = get_loan_or_404(lid)
    data = body()
    error_type = req_enum(data, "error_type", ERROR_TYPES)
    description = req_str(data, "description")
    asserted = opt_int(data, "asserted_amount_cents", None)
    for c in store.error_cases.values():
        if (c["loan_id"] == lid and c["error_type"] == error_type
                and c["status"] in OPEN_STATES):
            raise ApiError(ERR_DUP_CASE, 409,
                           "A non-terminal case with this error_type already exists")
    received_date = today()
    case = new_record({
        "loan_id": lid,
        "error_type": error_type,
        "description": description,
        "asserted_amount_cents": asserted,
        "status": "RECEIVED",
        "received_at": now_ts(),
        "acknowledged_at": None,
        "ack_deadline": fmt_date(add_business_days(received_date, 5)),
        "ack_timeliness": None,
        "assigned_to_user_id": None,
        "resolution_deadline": fmt_date(add_business_days(received_date, 30)),
        "resolved_at": None,
        "resolution_timeliness": None,
        "resolved_by_user_id": None,
        "outcome": None,
        "correction_amount_cents": None,
        "resolution_note": "",
    })
    store.error_cases[case["id"]] = case
    return ok(error_case_out(case), 201)


@bp.get("/servicing/loans/<lid>/error-cases")
def list_cases(lid):
    any_role()
    get_loan_or_404(lid)
    rows = [c for c in sorted(store.error_cases.values(), key=lambda r: r["_seq"])
            if c["loan_id"] == lid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([error_case_out(r) for r in rows])


@bp.get("/servicing/error-cases/<cid>")
def get_case(cid):
    any_role()
    return ok(error_case_out(get_case_or_404(cid)))


@bp.post("/servicing/error-cases/<cid>/acknowledge")
def acknowledge_case(cid):
    require_roles("ComplianceOfficer")
    c = get_case_or_404(cid)
    if c["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is terminal")
    if c["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Case is not RECEIVED")
    ack_date = today()
    c["acknowledged_at"] = now_ts()
    c["ack_timeliness"] = (
        "ON_TIME" if ack_date <= parse_date(c["ack_deadline"]) else "LATE")
    c["status"] = "ACKNOWLEDGED"
    bump(c)
    return ok(error_case_out(c))


@bp.post("/servicing/error-cases/<cid>/assign")
def assign_case(cid):
    require_roles("ComplianceOfficer")
    c = get_case_or_404(cid)
    data = body()
    assignee = req_str(data, "assigned_to_user_id")
    if c["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is terminal")
    if c["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE, 409, "Case is not ACKNOWLEDGED")
    c["assigned_to_user_id"] = assignee
    c["status"] = "INVESTIGATING"
    bump(c)
    return ok(error_case_out(c))


@bp.post("/servicing/error-cases/<cid>/extend")
def extend_case(cid):
    require_roles("ComplianceOfficer")
    c = get_case_or_404(cid)
    if c["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is terminal")
    if c["status"] != "INVESTIGATING":
        raise ApiError(ERR_INVALID_STATE, 409, "Case is not INVESTIGATING")
    received_date = parse_date(c["received_at"][:10])
    original_deadline = add_business_days(received_date, 30)
    if today() > original_deadline:
        raise ApiError(ERR_EXTENSION_PASSED, 409,
                       "Extension window has passed")
    c["resolution_deadline"] = fmt_date(add_business_days(received_date, 45))
    c["status"] = "EXTENDED"
    bump(c)
    return ok(error_case_out(c))


@bp.post("/servicing/error-cases/<cid>/resolve")
def resolve_case(cid):
    uid, _ = require_roles("ComplianceOfficer")
    c = get_case_or_404(cid)
    data = body()
    outcome = data.get("outcome")
    if outcome not in ("CORRECTED", "NO_ERROR"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "outcome must be CORRECTED or NO_ERROR")
    correction = data.get("correction_amount_cents")
    if correction is not None and (not isinstance(correction, int)
                                   or isinstance(correction, bool)):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "correction_amount_cents must be an integer")
    note = data.get("resolution_note", "")
    if note is None:
        note = ""
    if not isinstance(note, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "resolution_note must be a string")
    if c["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is terminal")
    if c["status"] not in ("INVESTIGATING", "EXTENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case is not INVESTIGATING or EXTENDED")
    account = account_of_loan(c["loan_id"])
    if outcome == "CORRECTED":
        if account is None or account["account_status"] == "CLOSED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Escrow account missing or CLOSED")
    if c["assigned_to_user_id"] is not None and uid == c["assigned_to_user_id"]:
        raise ApiError(ERR_SOD, 409, "Resolver must differ from investigator")
    if outcome == "CORRECTED":
        if not isinstance(correction, int) or correction <= 0:
            raise ApiError(ERR_INVALID_AMOUNT, 422,
                           "correction_amount_cents is required and must be positive")
    resolved_date = today()
    c["resolved_at"] = now_ts()
    c["resolved_by_user_id"] = uid
    c["resolution_timeliness"] = (
        "ON_TIME" if resolved_date <= parse_date(c["resolution_deadline"]) else "LATE")
    c["resolution_note"] = note
    c["outcome"] = outcome
    if outcome == "CORRECTED":
        c["correction_amount_cents"] = correction
        c["status"] = "RESOLVED_CORRECTED"
        post_ledger(account, "ERROR_CORRECTION", correction, fmt_date(resolved_date),
                    "ErrorResolutionCase", c["id"])
        replay(account)
        bump(account)
        # Correction cascade: EFFECTIVE analysis -> REOPENED; its pending notices voided
        for cycle in sorted(store.analyses.values(), key=lambda r: r["_seq"]):
            if (cycle["escrow_account_id"] == account["id"]
                    and cycle["status"] == "EFFECTIVE"):
                cycle["status"] = "REOPENED"
                bump(cycle)
                void_notices_of_analysis(cycle["id"], include_acknowledged=True)
    else:
        c["status"] = "RESOLVED_NO_ERROR"
    bump(c)
    return ok(error_case_out(c))


@bp.post("/servicing/error-cases/<cid>/dismiss")
def dismiss_case(cid):
    require_roles("ComplianceOfficer")
    c = get_case_or_404(cid)
    data = body()
    reason = req_str(data, "dismissal_reason")
    if c["status"] in TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is terminal")
    if c["status"] not in ("RECEIVED", "ACKNOWLEDGED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only RECEIVED or ACKNOWLEDGED cases can be dismissed")
    c["status"] = "DISMISSED_NOT_COVERED"
    c["outcome"] = "DISMISSED"
    c["resolution_note"] = reason
    bump(c)
    return ok(error_case_out(c))
