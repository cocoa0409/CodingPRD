from datetime import timedelta

from flask import Blueprint

import clock
import store
from auth import ALL_ROLES, authenticate, authorize
from errors import (
    ERR_DUAL_TRACKING_BLOCKED,
    ERR_FORECLOSURE_CASE_ACTIVE,
    ERR_FORECLOSURE_CASE_NOT_FOUND,
    ERR_FORECLOSURE_STATE_INVALID,
    ERR_LOAN_NOT_FOUND,
    ERR_REFERRAL_TOO_EARLY,
    ERR_SALE_MIN_NOTICE,
    ERR_SALE_WITHIN_APPEAL_WINDOW,
    raise_err,
)
from services import (
    BLOCKING_APP_STATES,
    MIN_SALE_NOTICE_DAYS,
    REFERRAL_MIN_DELINQUENCY_DAYS,
    SALE_BLOCK_MIN_DAYS,
    case_out,
)
from util import body_json, bump, get_or_404, list_response, new_record, req_date, req_str, success_object

bp = Blueprint("foreclosures", __name__)

NON_TERMINAL_CASE_STATES = {"REFERRED", "SALE_SCHEDULED", "SALE_HOLD"}


def _blocking_applications(loan_id):
    return [a for a in store.applications.values()
            if a["loan_id"] == loan_id and a["status"] in BLOCKING_APP_STATES]


@bp.route("/loans/<rid>/foreclosure-cases", methods=["POST"])
def create_foreclosure_case(rid):
    _, role = authenticate()
    authorize(role, ["ForeclosureCounsel"])
    body = body_json()
    county = req_str(body, "county")
    docket_number = req_str(body, "docket_number")

    loan = get_or_404(store.loans, rid, ERR_LOAN_NOT_FOUND, "Loan")

    # compliance gates (priority 8)
    if loan["delinquency_days"] <= REFERRAL_MIN_DELINQUENCY_DAYS:
        raise_err(ERR_REFERRAL_TOO_EARLY,
                  "Referral requires delinquency_days > 120")
    if _blocking_applications(loan["id"]):
        raise_err(ERR_DUAL_TRACKING_BLOCKED,
                  "A blocking-state loss-mitigation application is pending")

    # structural (priority 10): one non-terminal case per loan
    for c in store.cases.values():
        if c["loan_id"] == loan["id"] and c["status"] in NON_TERMINAL_CASE_STATES:
            raise_err(ERR_FORECLOSURE_CASE_ACTIVE,
                      "A non-terminal foreclosure case already exists for this loan")

    rec = new_record()
    rec.update({
        "loan_id": loan["id"],
        "county": county,
        "docket_number": docket_number,
        "referred_at": clock.now(),
        "sale_date": None,
        "status": "REFERRED",
    })
    store.cases[rec["id"]] = rec
    bump(loan)
    return success_object(case_out(rec), 201)


@bp.route("/foreclosure-cases/<rid>", methods=["GET"])
def get_foreclosure_case(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.cases, rid, ERR_FORECLOSURE_CASE_NOT_FOUND, "ForeclosureCase")
    return success_object(case_out(rec))


@bp.route("/loans/<rid>/foreclosure-cases", methods=["GET"])
def list_loan_foreclosure_cases(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    loan = get_or_404(store.loans, rid, ERR_LOAN_NOT_FOUND, "Loan")
    records = [c for c in store.cases.values() if c["loan_id"] == loan["id"]]
    return list_response(records, case_out)


@bp.route("/foreclosure-cases/<rid>/schedule-sale", methods=["POST"])
def schedule_sale(rid):
    _, role = authenticate()
    authorize(role, ["ForeclosureCounsel"])
    body = body_json()
    sale_date = req_date(body, "sale_date")

    case = get_or_404(store.cases, rid, ERR_FORECLOSURE_CASE_NOT_FOUND, "ForeclosureCase")
    if case["status"] not in ("REFERRED", "SALE_HOLD"):
        raise_err(ERR_FORECLOSURE_STATE_INVALID,
                  "Case in %s cannot schedule a sale" % case["status"])

    loan = store.loans[case["loan_id"]]

    # compliance gates (priority 8)
    # appeal-window exclusion: closed interval [issued_at date, appeal_deadline date]
    for n in store.notices.values():
        if n["status"] not in ("ISSUED", "APPEALED"):
            continue
        n_app = store.applications.get(n["application_id"])
        if n_app is None or n_app["loan_id"] != loan["id"]:
            continue
        if n["issued_at"].date() <= sale_date <= n["appeal_deadline"].date():
            raise_err(ERR_SALE_WITHIN_APPEAL_WINDOW,
                      "sale_date falls within a denial notice appeal window")

    # 37-day dual-tracking block
    for a in _blocking_applications(loan["id"]):
        if a.get("completed_at") is not None:
            if (sale_date - a["completed_at"].date()).days >= SALE_BLOCK_MIN_DAYS:
                raise_err(ERR_DUAL_TRACKING_BLOCKED,
                          "Blocking application completed at least 37 days before sale_date")

    # temporal gate (priority 9): minimum notice
    if sale_date < case["referred_at"].date() + timedelta(days=MIN_SALE_NOTICE_DAYS):
        raise_err(ERR_SALE_MIN_NOTICE,
                  "sale_date must be at least 14 days after referral")

    case["sale_date"] = sale_date
    case["status"] = "SALE_SCHEDULED"
    bump(case)
    return success_object(case_out(case))


@bp.route("/foreclosure-cases/<rid>/cancel", methods=["POST"])
def cancel_case(rid):
    _, role = authenticate()
    authorize(role, ["ForeclosureCounsel"])
    case = get_or_404(store.cases, rid, ERR_FORECLOSURE_CASE_NOT_FOUND, "ForeclosureCase")
    if case["status"] not in NON_TERMINAL_CASE_STATES:
        raise_err(ERR_FORECLOSURE_STATE_INVALID,
                  "Case in %s cannot be cancelled" % case["status"])
    case["status"] = "CANCELLED"
    bump(case)
    return success_object(case_out(case))


@bp.route("/foreclosure-cases/<rid>/complete-sale", methods=["POST"])
def complete_sale(rid):
    _, role = authenticate()
    authorize(role, ["ForeclosureCounsel"])
    case = get_or_404(store.cases, rid, ERR_FORECLOSURE_CASE_NOT_FOUND, "ForeclosureCase")
    if case["status"] != "SALE_SCHEDULED":
        raise_err(ERR_FORECLOSURE_STATE_INVALID,
                  "Case in %s cannot complete a sale" % case["status"])
    case["status"] = "SALE_COMPLETED"
    bump(case)
    return success_object(case_out(case))
