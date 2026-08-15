"""Escheatment endpoints: dormancy scan, case pipeline (notice/report/remit/reactivate)."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import pagination_params, parse_dt
from middleware import auth, require_role
from response import success_list, success_object
from services import (stamp_new, touch, audit, sorted_recs, case_view, now_dt, now_iso,
                      add_years, DORMANCY_YEARS, DORMANCY_DEFAULT, positions_of_account,
                      payments_of_account, create_or_rearm_case, account_holds_property,
                      maybe_close_declaration)

bp = Blueprint("escheatment", __name__)

CASE_READ_ROLES = {"ComplianceOfficer", "ServiceAgent", "AgentAdmin"}
NOTICE_WINDOW_DAYS = 60


def get_case_or_404(case_id):
    case = STORE["escheatment_cases"].get(case_id)
    if case is None:
        fail("ERR_CASE_NOT_FOUND", "escheatment case %s does not exist" % case_id)
    return case


@bp.post("/escheatment/scan")
def dormancy_scan():
    user_id, role = auth()
    require_role(role, {"AgentAdmin"})
    now = now_dt()
    accounts_marked = 0
    cases_created = 0
    for account in sorted_recs("accounts"):
        if account["account_status"] != "ACTIVE":
            continue  # RESTRICTED accounts are never swept
        years = DORMANCY_YEARS.get(account["state_code"], DORMANCY_DEFAULT)
        horizon = add_years(parse_dt(account["last_qualifying_contact_date"],
                                     "last_qualifying_contact_date"), years)
        if now < horizon:
            continue  # one second short of the anniversary is not dormant
        account["account_status"] = "DORMANT"
        touch(account)
        accounts_marked += 1
        audit("ShareholderAccount", account["id"], role, user_id, "account.dormant",
              "ACTIVE", "DORMANT", "account crossed its dormancy horizon")
        if account_holds_property(account):
            result = create_or_rearm_case(account, role, user_id)
            if result == "created":
                cases_created += 1
    audit("EscheatmentScan", "sweep", role, user_id, "escheatment.scan", "", "",
          "dormancy sweep: %d accounts marked dormant, %d cases created"
          % (accounts_marked, cases_created))
    return success_object({
        "accounts_marked_dormant": accounts_marked,
        "cases_created": cases_created,
    })


@bp.get("/escheatment-cases")
def list_cases():
    user_id, role = auth()
    require_role(role, CASE_READ_ROLES)
    account_filter = request.args.get("account_id")
    status_filter = request.args.get("status")
    items = sorted_recs("escheatment_cases")
    if account_filter is not None:
        items = [c for c in items if c["account_id"] == account_filter]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([case_view(c) for c in page], limit, offset, total)


@bp.get("/escheatment-cases/<case_id>")
def read_case(case_id):
    user_id, role = auth()
    require_role(role, CASE_READ_ROLES)
    case = get_case_or_404(case_id)
    return success_object(case_view(case))


@bp.post("/escheatment-cases/<case_id>/send-notice")
def send_notice(case_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    case = get_case_or_404(case_id)
    if case["status"] != "IDENTIFIED":
        fail("ERR_INVALID_STATE", "only an IDENTIFIED case can send a notice")
    case["status"] = "NOTICE_SENT"
    case["notice_sent_at"] = now_iso()
    touch(case)
    audit("EscheatmentCase", case["id"], role, user_id, "case.send_notice",
          "IDENTIFIED", "NOTICE_SENT", "due-diligence notice sent")
    return success_object(case_view(case))


@bp.post("/escheatment-cases/<case_id>/report")
def report_case(case_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    case = get_case_or_404(case_id)
    if case["status"] != "NOTICE_SENT":
        fail("ERR_INVALID_STATE", "only a NOTICE_SENT case can be reported")
    # temporal gate: 60-day due-diligence window, inclusive boundary
    horizon = parse_dt(case["notice_sent_at"], "notice_sent_at") + timedelta(days=NOTICE_WINDOW_DAYS)
    if now_dt() < horizon:
        fail("ERR_NOTICE_WINDOW_NOT_ELAPSED",
             "60-day due-diligence window has not elapsed")
    account = STORE["accounts"].get(case["account_id"])
    # pinned valuation order: freeze price, then share leg, then cash leg, then total
    account_positions = positions_of_account(case["account_id"])
    report_price = None
    if account_positions:
        first_issuer = STORE["issuers"].get(account_positions[0]["issuer_id"])
        if first_issuer is not None:
            report_price = first_issuer["current_market_price_cents"]
    total_shares = sum(p["book_entry_shares"] + p["certificated_shares"]
                       for p in account_positions)
    share_value = total_shares * report_price if report_price is not None else 0
    cash_value = sum(p["gross_cents"] for p in payments_of_account(case["account_id"])
                     if p["status"] == "STALE_DATED")
    case["report_price_cents"] = report_price
    case["share_value_cents"] = share_value
    case["cash_value_cents"] = cash_value
    case["total_remit_cents"] = share_value + cash_value
    case["status"] = "REPORTED"
    touch(case)
    audit("EscheatmentCase", case["id"], role, user_id, "case.report",
          "NOTICE_SENT", "REPORTED", "state report filed; valuation frozen")
    return success_object(case_view(case))


@bp.post("/escheatment-cases/<case_id>/remit")
def remit_case(case_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    case = get_case_or_404(case_id)
    if case["status"] != "REPORTED":
        fail("ERR_INVALID_STATE", "only a REPORTED case can be remitted")
    # hop 1: the case itself
    case["status"] = "REMITTED"
    touch(case)
    audit("EscheatmentCase", case["id"], role, user_id, "case.remit",
          "REPORTED", "REMITTED", "property remitted to the state")
    # hop 2: account -> ESCHEATED; positions CLOSED and zeroed; stale payments ESCHEATED
    account = STORE["accounts"].get(case["account_id"])
    if account is not None:
        for position in positions_of_account(account["id"]):
            if position["status"] == "ACTIVE":
                position["book_entry_shares"] = 0
                position["restricted_shares"] = 0
                position["certificated_shares"] = 0
                position["status"] = "CLOSED"
                touch(position)
                audit("Position", position["id"], role, user_id, "position.escheat_closed",
                      "ACTIVE", "CLOSED", "position zeroed and closed by escheatment")
        relieved = 0
        for payment in payments_of_account(account["id"]):
            if payment["status"] == "STALE_DATED":
                payment["status"] = "ESCHEATED"
                touch(payment)
                relieved += payment["gross_cents"]
                audit("DividendPayment", payment["id"], role, user_id,
                      "payment.escheated", "STALE_DATED", "ESCHEATED",
                      "stale dividend escheated")
        account["stale_dividend_cents"] -= relieved
        account["account_status"] = "ESCHEATED"
        touch(account)
        audit("ShareholderAccount", account["id"], role, user_id, "account.escheated",
              "DORMANT", "ESCHEATED", "account escheated to the state")
        for payment in payments_of_account(account["id"]):
            if payment["status"] == "ESCHEATED":
                maybe_close_declaration(payment["declaration_id"], role, user_id)
    # hop 3: issuer totals are recomputed on read from positions (no stored drift)
    return success_object(case_view(case))


@bp.post("/escheatment-cases/<case_id>/reactivate")
def reactivate_case(case_id):
    user_id, role = auth()
    require_role(role, {"ServiceAgent"})
    case = get_case_or_404(case_id)
    if case["status"] not in ("IDENTIFIED", "NOTICE_SENT"):
        fail("ERR_INVALID_STATE", "case cannot be reactivated from %s" % case["status"])
    frm = case["status"]
    case["status"] = "REACTIVATED"
    touch(case)
    audit("EscheatmentCase", case["id"], role, user_id, "case.reactivate",
          frm, "REACTIVATED", "owner contacted; case reactivated")
    account = STORE["accounts"].get(case["account_id"])
    if account is not None:
        if account["account_status"] == "DORMANT":
            account["account_status"] = "ACTIVE"
            audit("ShareholderAccount", account["id"], role, user_id,
                  "account.reactivate", "DORMANT", "ACTIVE",
                  "reactivated via escheatment case")
        account["last_qualifying_contact_date"] = now_iso()
        touch(account)
    return success_object(case_view(case))
