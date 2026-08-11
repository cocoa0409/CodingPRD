"""Grant, BudgetLine, and Fund endpoints."""

import services as S
import services_summary as SS
from db import store
from errors import (
    err_duplicate_award,
    err_invalid_state,
    err_validation,
)
from middleware import ALL_READ_ROLES, actor, body, require_roles
from response import ok, paginate
from util import get_dt, get_enum, get_int, get_num, get_str

FREQUENCIES = ("MONTHLY", "QUARTERLY", "SEMIANNUAL", "ANNUAL")
FUND_TYPES = ("RESTRICTED", "UNRESTRICTED")
GRANT_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSEOUT", "CLOSED")


# ---------------------------------------------------------------------------
# grants
# ---------------------------------------------------------------------------

def create_grant():
    uid, role = actor()
    require_roles(role, {"GrantsOfficer"})
    data = body()
    funder_id = get_str(data, "funder_id")
    award_number = get_str(data, "award_number")
    title = get_str(data, "title")
    award_amount_cents = get_int(data, "award_amount_cents", min_v=0)
    start_date = get_dt(data, "start_date")
    end_date = get_dt(data, "end_date")
    frequency = get_enum(data, "reporting_frequency", FREQUENCIES)
    if end_date < start_date:
        raise err_validation("end_date must be on or after start_date")
    if funder_id not in store["funders"]:
        raise err_validation("funder_id does not reference an existing Funder")
    for g in store["grants"].values():
        if g["funder_id"] == funder_id and g["award_number"] == award_number:
            raise err_duplicate_award()
    grant = S.stamp({
        "funder_id": funder_id,
        "award_number": award_number,
        "title": title,
        "award_amount_cents": award_amount_cents,
        "start_date": start_date,
        "end_date": end_date,
        "original_end_date": end_date,
        "reporting_frequency": frequency,
        "interim_report_due_days": get_int(data, "interim_report_due_days", required=False, default=30, min_v=0),
        "final_report_due_days": get_int(data, "final_report_due_days", required=False, default=90, min_v=0),
        "variance_threshold_pct": get_num(data, "variance_threshold_pct", required=False, default=10.0, min_v=0),
        "indirect_rate_pct": get_num(data, "indirect_rate_pct", required=False, default=0, min_v=0),
        "indirect_cap_cents": get_int(data, "indirect_cap_cents", required=False, default=None, min_v=0),
        "renewal_window_days": get_int(data, "renewal_window_days", required=False, default=60, min_v=0),
        "required_match_cents": get_int(data, "required_match_cents", required=False, default=0, min_v=0),
        "status": "DRAFT",
        "total_expended_cents": 0,
    })
    store["grants"][grant["id"]] = grant
    return ok(S.ser_grant(grant), code=201)


def list_grants():
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    from flask import request
    items = sorted(store["grants"].values(), key=lambda e: e["_order"])
    funder_id = request.args.get("funder_id")
    if funder_id is not None:
        items = [g for g in items if g["funder_id"] == funder_id]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, meta = paginate(items)
    return ok([S.ser_grant(g) for g in page], pagination=meta)


def get_grant(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    return ok(S.ser_grant(S.get_grant(grant_id)))


def grant_summary(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    grant = S.get_grant(grant_id)
    return ok(SS.compute_summary(grant))


def activate_grant(grant_id):
    _, role = actor()
    require_roles(role, {"ProgramDirector"})
    grant = S.get_grant(grant_id)
    if grant["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT grant can be activated")
    if not S.grant_lines(grant_id):
        raise err_invalid_state("Grant requires at least one BudgetLine to activate")
    if not S.grant_funds(grant_id):
        raise err_invalid_state("Grant requires at least one Fund to activate")
    n = S.generate_calendar(grant)
    for line in S.grant_lines(grant_id):
        S.recompute_proration(line, n)
        S.touch(line)
    grant["status"] = "ACTIVE"
    S.touch(grant)
    return ok(S.ser_grant(grant))


def closeout_grant(grant_id):
    _, role = actor()
    require_roles(role, {"ProgramDirector"})
    grant = S.get_grant(grant_id)
    if grant["status"] != "CLOSEOUT":
        raise err_invalid_state("Grant is not in CLOSEOUT")
    for rep in S.grant_reports(grant_id):
        if rep["status"] != "ACCEPTED":
            raise err_invalid_state("All reports of the grant must be ACCEPTED")
    for eng in S.grant_engagements(grant_id):
        for f in S.engagement_findings(eng["id"]):
            if f["status"] in ("OPEN", "RESPONSE_SUBMITTED"):
                raise err_invalid_state("Open audit findings remain on the grant")
    for m in S.grant_mods(grant_id):
        if m["status"] in ("DRAFT", "SUBMITTED"):
            raise err_invalid_state("Pending modification requests remain on the grant")
    grant["status"] = "CLOSED"
    S.touch(grant)
    return ok(S.ser_grant(grant))


# ---------------------------------------------------------------------------
# budget lines
# ---------------------------------------------------------------------------

def create_budget_line(grant_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    grant = S.get_grant(grant_id)
    if grant["status"] != "DRAFT":
        raise err_invalid_state("Budget lines can only be added while the grant is DRAFT")
    data = body()
    line = S.stamp({
        "grant_id": grant_id,
        "category": get_enum(data, "category", S.BUDGET_CATEGORIES),
        "budgeted_cents": get_int(data, "budgeted_cents", min_v=0),
        "adjusted_cents": 0,
        "expended_cents": 0,
        "period_budgets_cents": [],
    })
    line["adjusted_cents"] = line["budgeted_cents"]
    store["budget_lines"][line["id"]] = line
    return ok(S.ser_line(line), code=201)


def list_budget_lines(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_grant(grant_id)
    items = S.grant_lines(grant_id)
    page, meta = paginate(items)
    return ok([S.ser_line(l) for l in page], pagination=meta)


def get_budget_line(line_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    return ok(S.ser_line(S.get_line(line_id)))


def line_variance_explanations(line_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_line(line_id)
    items = sorted(
        (v for v in store["variance_explanations"].values() if v["budget_line_id"] == line_id),
        key=lambda e: e["_order"],
    )
    page, meta = paginate(items)
    return ok([S.ser_ve(v) for v in page], pagination=meta)


# ---------------------------------------------------------------------------
# funds
# ---------------------------------------------------------------------------

def create_fund(grant_id):
    _, role = actor()
    require_roles(role, {"FinanceManager"})
    grant = S.get_grant(grant_id)
    if grant["status"] != "DRAFT":
        raise err_invalid_state("Funds can only be created while the grant is DRAFT")
    data = body()
    allowed = data.get("allowed_categories", [])
    if not isinstance(allowed, list):
        raise err_validation("allowed_categories must be an array")
    for c in allowed:
        if c not in S.BUDGET_CATEGORIES:
            raise err_validation("allowed_categories entries must be budget categories")
    fund = S.stamp({
        "grant_id": grant_id,
        "fund_type": get_enum(data, "fund_type", FUND_TYPES),
        "purpose_restriction": data.get("purpose_restriction"),
        "allowed_categories": list(allowed),
        "allocated_cents": get_int(data, "allocated_cents", min_v=0),
        "expended_cents": 0,
    })
    if fund["purpose_restriction"] is not None and not isinstance(fund["purpose_restriction"], str):
        raise err_validation("purpose_restriction must be a string")
    store["funds"][fund["id"]] = fund
    return ok(S.ser_fund(fund), code=201)


def list_funds(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_grant(grant_id)
    items = S.grant_funds(grant_id)
    page, meta = paginate(items)
    return ok([S.ser_fund(f) for f in page], pagination=meta)


def register(app):
    app.add_url_rule("/grants", "grants_create", create_grant, methods=["POST"])
    app.add_url_rule("/grants", "grants_list", list_grants, methods=["GET"])
    app.add_url_rule("/grants/<grant_id>", "grants_get", get_grant, methods=["GET"])
    app.add_url_rule("/grants/<grant_id>/summary", "grants_summary", grant_summary, methods=["GET"])
    app.add_url_rule("/grants/<grant_id>/activate", "grants_activate", activate_grant, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/closeout", "grants_closeout", closeout_grant, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/budget-lines", "lines_create", create_budget_line, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/budget-lines", "lines_list", list_budget_lines, methods=["GET"])
    app.add_url_rule("/budget-lines/<line_id>", "lines_get", get_budget_line, methods=["GET"])
    app.add_url_rule("/budget-lines/<line_id>/variance-explanations", "lines_ves", line_variance_explanations, methods=["GET"])
    app.add_url_rule("/grants/<grant_id>/funds", "funds_create", create_fund, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/funds", "funds_list", list_funds, methods=["GET"])
