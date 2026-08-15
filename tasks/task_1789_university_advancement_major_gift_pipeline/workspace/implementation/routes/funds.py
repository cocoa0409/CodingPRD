"""Restricted funds, valuations, disbursements, and stewardship reports."""

from datetime import timedelta

from flask import Blueprint, request

from core import (
    authenticate, authorize, body_json, check_unknown_fields, req_str, opt_str,
    req_money, parse_dt, now, new_entity, touch,
    success_object, success_list, paginate, ALL_ROLES,
)
from db import store
from errors import (
    fail, ERR_INVALID_REQUEST, ERR_FUND_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
    ERR_FUND_NOT_ACTIVE, ERR_FUND_SPENDING_FROZEN, ERR_SPENDING_ALLOWANCE_EXCEEDED,
    ERR_DUPLICATE_QUARTER_VALUATION, ERR_REPORT_PERIOD_OVERLAP,
    ERR_REPORT_TRANSITION_INVALID,
)
from services import ser_fund, ser_report, fund_allowances

bp = Blueprint("funds", __name__)


def _get_fund(fid):
    fund = store["funds"].get(fid)
    if fund is None:
        fail(ERR_FUND_NOT_FOUND, "Fund not found")
    return fund


@bp.get("/advancement/funds/<fid>")
def get_fund(fid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(ser_fund(_get_fund(fid)))


@bp.get("/advancement/funds")
def list_funds():
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store["funds"].values())
    for param in ("agreement_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [f for f in items if f.get(param) == value]
    page, limit, offset, total = paginate(items)
    return success_list([ser_fund(f) for f in page], limit, offset, total)


@bp.post("/advancement/funds/<fid>/valuations")
def append_valuation(fid):
    user_id, role = authenticate()
    authorize(role, ["FinanceSteward"])
    body = body_json()
    check_unknown_fields(body, {"quarter_end", "value_cents"})
    quarter_end = parse_dt(body.get("quarter_end"), "quarter_end")
    value_cents = req_money(body, "value_cents")
    fund = _get_fund(fid)
    if any(v["quarter_end"] == quarter_end for v in fund["trailing_market_values"]):
        fail(ERR_DUPLICATE_QUARTER_VALUATION, "A valuation for this quarter_end already exists on the fund")
    fund["trailing_market_values"].append({"quarter_end": quarter_end, "value_cents": value_cents})
    touch(fund)
    # Appending a valuation modifies the fund (valuations are not standalone
    # resources per §2.4); §4: modify -> 200 OK.
    return success_object(ser_fund(fund), 200)


@bp.post("/advancement/funds/<fid>/disburse")
def disburse_fund(fid):
    user_id, role = authenticate()
    authorize(role, ["FinanceSteward"])
    body = body_json()
    check_unknown_fields(body, {"amount_cents", "purpose_note"})
    amount_cents = req_money(body, "amount_cents")
    purpose_note = req_str(body, "purpose_note")
    fund = _get_fund(fid)
    # state (priority 8) then stewardship gate (priority 9)
    if fund["status"] == "CLOSED":
        fail(ERR_FUND_NOT_ACTIVE, "Cannot disburse from a CLOSED fund")
    if fund["status"] == "SPENDING_FROZEN":
        fail(ERR_FUND_SPENDING_FROZEN, "Cannot disburse from a SPENDING_FROZEN fund")
    # fiscal cap (priority 13)
    spendable, allowance_remaining = fund_allowances(fund)
    if fund["is_endowed"]:
        cap = min(allowance_remaining, fund["balance_cents"])
    else:
        cap = fund["balance_cents"]
    if amount_cents > cap:
        fail(ERR_SPENDING_ALLOWANCE_EXCEEDED, "Disbursement exceeds the spending allowance")
    fund["balance_cents"] -= amount_cents
    fund["disbursements"].append({
        "amount_cents": amount_cents,
        "purpose_note": purpose_note,
        "created_at": now(),
    })
    if fund["status"] == "ACTIVE" and fund["balance_cents"] < fund["minimum_activation_cents"]:
        fund["status"] = "PENDING_MINIMUM"
    touch(fund)
    return success_object(ser_fund(fund))


@bp.post("/advancement/funds/<fid>/reports")
def create_report(fid):
    user_id, role = authenticate()
    authorize(role, ["DonorRelationsOfficer"])
    body = body_json()
    check_unknown_fields(body, {"period_start", "period_end", "narrative"})
    period_start = parse_dt(body.get("period_start"), "period_start")
    period_end = parse_dt(body.get("period_end"), "period_end")
    narrative = opt_str(body, "narrative")
    if period_end <= period_start:
        fail(ERR_INVALID_REQUEST, "period_end must be later than period_start")
    fund = _get_fund(fid)
    # closed-interval overlap: sharing an endpoint date is a conflict
    for other in store["reports"].values():
        if other["fund_id"] != fid:
            continue
        if period_start <= other["period_end"] and other["period_start"] <= period_end:
            fail(ERR_REPORT_PERIOD_OVERLAP, "Report period overlaps an existing report")
    entity = new_entity()
    entity.update({
        "fund_id": fid,
        "period_start": period_start,
        "period_end": period_end,
        "due_date": period_end + timedelta(days=90),
        "narrative": narrative,
        "submitted_by": None,
        "status": "DRAFT",
    })
    store["reports"][entity["id"]] = entity
    return success_object(ser_report(entity), 201)


@bp.get("/advancement/funds/<fid>/reports")
def list_reports(fid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_fund(fid)
    items = [r for r in store["reports"].values() if r["fund_id"] == fid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([ser_report(r) for r in page], limit, offset, total)


@bp.post("/advancement/stewardship-reports/<rid>/submit")
def submit_report(rid):
    user_id, role = authenticate()
    authorize(role, ["DonorRelationsOfficer"])
    body_json()  # no documented inputs
    report = store["reports"].get(rid)
    if report is None:
        fail(ERR_RESOURCE_NOT_FOUND, "Stewardship report not found")
    if report["status"] not in ("DRAFT", "OVERDUE"):
        fail(ERR_REPORT_TRANSITION_INVALID, f"Report in {report['status']} cannot be submitted")
    report["status"] = "SUBMITTED"
    report["submitted_by"] = user_id
    touch(report)
    return success_object(ser_report(report))


@bp.post("/advancement/stewardship-reports/<rid>/deliver")
def deliver_report(rid):
    user_id, role = authenticate()
    authorize(role, ["DonorRelationsOfficer"])
    body_json()  # no documented inputs
    report = store["reports"].get(rid)
    if report is None:
        fail(ERR_RESOURCE_NOT_FOUND, "Stewardship report not found")
    if report["status"] != "SUBMITTED":
        fail(ERR_REPORT_TRANSITION_INVALID, "Only a SUBMITTED report can be delivered")
    report["status"] = "DELIVERED"
    touch(report)
    # recovery: unfreeze the fund and restore compliance when no other report
    # of the fund remains OVERDUE
    fund = store["funds"].get(report["fund_id"])
    if fund is not None:
        still_overdue = any(
            r["fund_id"] == fund["id"] and r["status"] == "OVERDUE"
            for r in store["reports"].values()
        )
        if not still_overdue:
            if fund["status"] == "SPENDING_FROZEN":
                fund["status"] = "ACTIVE"
                touch(fund)
            agreement = store["agreements"].get(fund["agreement_id"])
            if agreement is not None and agreement["compliance_status"] == "STEWARDSHIP_LAPSED":
                agreement["compliance_status"] = "COMPLIANT"
                touch(agreement)
    return success_object(ser_report(report))
