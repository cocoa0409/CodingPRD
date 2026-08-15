"""Impairment assessment routes — CECL and TDR_DCF (PRD §3.6)."""
from flask import Blueprint

import db
from auth import (
    ROLE_CREDIT_COMMITTEE, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SPECIAL_ASSETS_MANAGER, ROLE_SYSTEM_ADMIN, ROLE_WORKOUT_OFFICER,
    require_roles,
)
from db import STORE
from errors import (
    ApiError, ERR_CASE_NOT_IMPAIRABLE, ERR_DUPLICATE_CASH_FLOW_PERIOD,
    ERR_EMPTY_CASH_FLOWS, ERR_IMPAIRMENT_NOT_DRAFT, ERR_NOT_FOUND, ERR_SOD,
    ERR_TDR_METHOD_REQUIRES_TDR, invalid_request,
)
from response import ok, paginate
from services import (
    cecl_reserve, get_impairment, get_loan, impairment_out,
    impairments_of_case, sorted_rows, tdr_dcf_reserve,
)
from validate import as_enum, as_int, field, get_body, no_unknown

bp = Blueprint("impairments", __name__)

METHODS = ("CECL", "TDR_DCF")
IMPAIRMENT_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)


def resolve(loanId, caseId, assessmentId=None):
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    case = STORE["cases"].get(caseId)
    if case is None or case["loan_id"] != loanId:
        raise ApiError(ERR_NOT_FOUND, 404, "Workout case not found")
    assessment = None
    if assessmentId is not None:
        assessment = get_impairment(assessmentId)
        if assessment is None or assessment["case_id"] != caseId:
            raise ApiError(ERR_NOT_FOUND, 404, "Impairment assessment not found")
    return loan, case, assessment


def parse_cash_flows(raw):
    """Validate the expected_cash_flows array shape; return sorted entries."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise invalid_request("expected_cash_flows must be an array")
    flows = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise invalid_request("expected_cash_flows entries must be objects")
        unknown = [k for k in entry if k not in ("period_index", "amount_cents")]
        if unknown:
            raise invalid_request(
                f"Unknown cash-flow field(s): {', '.join(sorted(unknown))}"
            )
        period = as_int(
            field(entry, "period_index"), "period_index", minimum=1
        )
        amount = as_int(
            field(entry, "amount_cents"), "amount_cents", minimum=0
        )
        flows.append({"period_index": period, "amount_cents": amount})
    periods = [f["period_index"] for f in flows]
    if len(set(periods)) != len(periods):
        raise ApiError(
            ERR_DUPLICATE_CASH_FLOW_PERIOD, 422,
            "expected_cash_flows contains duplicate period_index entries",
        )
    return sorted(flows, key=lambda f: f["period_index"])


@bp.route("/loans/<loanId>/workout-cases/<caseId>/impairments", methods=["POST"])
def create_impairment(loanId, caseId):
    require_roles(ROLE_LOAN_ACCOUNTING)
    resolve(loanId, caseId)
    data = get_body()
    no_unknown(data, {
        "method", "probability_of_default_bps", "loss_given_default_bps",
        "expected_cash_flows",
    })
    method = as_enum(field(data, "method"), "method", METHODS)
    # PD/LGD are the CECL inputs; TDR_DCF discounts cash flows instead
    if method == "CECL":
        pd_bps = as_int(
            field(data, "probability_of_default_bps"),
            "probability_of_default_bps", 1, 10000,
        )
        lgd_bps = as_int(
            field(data, "loss_given_default_bps"), "loss_given_default_bps", 0, 10000
        )
    else:
        pd_bps = as_int(
            field(data, "probability_of_default_bps", 0),
            "probability_of_default_bps", 0, 10000,
        )
        lgd_bps = as_int(
            field(data, "loss_given_default_bps", 0), "loss_given_default_bps",
            0, 10000,
        )
    flows = parse_cash_flows(data.get("expected_cash_flows"))
    if method == "TDR_DCF" and not flows:
        raise ApiError(
            ERR_EMPTY_CASH_FLOWS, 422,
            "TDR_DCF requires a non-empty expected_cash_flows array",
        )
    assessment = db.stamp({
        "id": db.new_id(),
        "case_id": caseId,
        "method": method,
        "probability_of_default_bps": pd_bps,
        "loss_given_default_bps": lgd_bps,
        "expected_cash_flows": flows,
        "computed_reserve_cents": None,
        "is_active": False,
        "status": "DRAFT",
    })
    STORE["impairments"][assessment["id"]] = assessment
    return ok(impairment_out(assessment), 201)


@bp.route("/loans/<loanId>/workout-cases/<caseId>/impairments", methods=["GET"])
def list_impairments(loanId, caseId):
    require_roles(*IMPAIRMENT_READERS)
    resolve(loanId, caseId)
    rows = [impairment_out(a) for a in sorted_rows(impairments_of_case(caseId))]
    return paginate(rows)


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/impairments/<assessmentId>/finalize",
    methods=["POST"],
)
def finalize_impairment(loanId, caseId, assessmentId):
    user_id, _ = require_roles(ROLE_LOAN_ACCOUNTING)
    loan, case, assessment = resolve(loanId, caseId, assessmentId)
    # state (priority 4)
    if assessment["status"] != "DRAFT":
        raise ApiError(ERR_IMPAIRMENT_NOT_DRAFT, 409, "Assessment is not DRAFT")
    if case["status"] not in ("IMPAIRMENT_REVIEW", "LEGAL"):
        raise ApiError(
            ERR_CASE_NOT_IMPAIRABLE, 409,
            "Case must be IMPAIRMENT_REVIEW or LEGAL to finalize impairment",
        )
    # segregation of duties (priority 6): finalizer differs from case officer
    if user_id == case["case_officer_id"]:
        raise ApiError(
            ERR_SOD, 403, "Impairment finalizer must differ from the case officer"
        )
    # structural (priority 8): TDR method requires a confirmed TDR
    if assessment["method"] == "TDR_DCF" and case["tdr_status"] != "TDR_CONFIRMED":
        raise ApiError(
            ERR_TDR_METHOD_REQUIRES_TDR, 422,
            "TDR_DCF method requires tdr_status TDR_CONFIRMED",
        )

    if assessment["method"] == "CECL":
        reserve = cecl_reserve(
            loan["current_principal_cents"],
            assessment["probability_of_default_bps"],
            assessment["loss_given_default_bps"],
        )
    else:
        reserve = tdr_dcf_reserve(
            loan["current_principal_cents"],
            loan["contractual_rate_bps"],
            assessment["expected_cash_flows"],
        )

    # exactly one active assessment per case: supersede the prior FINALIZED
    for other in impairments_of_case(caseId):
        if other["id"] != assessment["id"] and other["status"] == "FINALIZED":
            other["status"] = "SUPERSEDED"
            other["is_active"] = False
            db.touch(other)
    assessment["computed_reserve_cents"] = reserve
    assessment["is_active"] = True
    assessment["status"] = "FINALIZED"
    db.touch(assessment)
    case["impairment_reserve_cents"] = reserve
    db.touch(case)
    return ok(impairment_out(assessment))
