"""AnnualStatement routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import now
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    adjust_governance,
    body,
    compute_statement_fields,
    get_captive,
    get_statement,
    req_int,
    req_num,
    stamp_new,
    statement_uncertified_reserves,
    touch,
    touch_captive,
)
from clock import parse_ts

bp = Blueprint("statements", __name__)

READ_ROLES = ("CaptiveManager", "Actuary", "BoardDirector")


@bp.post("/api/captives/<captiveId>/annual-statements")
def create_statement(captiveId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    data = body()
    year = req_int(data, "statement_year")
    investment = req_num(data, "investment_income_cents")

    stmt = stamp_new()
    stmt.update({
        "captive_id": captiveId,
        "statement_year": year,
        "filing_deadline": None,
        "total_assets_cents": 0,
        "total_liabilities_cents": 0,
        "policyholder_surplus_cents": 0,
        "net_premium_written_cents": 0,
        "net_losses_incurred_cents": 0,
        "combined_ratio": 0.0,
        "expense_ratio": 0.0,
        "underwriting_result_cents": 0,
        "investment_income_cents": int(investment),
        "rbc_ratio": 0.0,
        "rbc_action_level": "NONE",
        "status": "DRAFT",
    })
    compute_statement_fields(captive, stmt)
    db.statements[stmt["id"]] = stmt
    log(captiveId, "STATE_CHANGE", "AnnualStatement", stmt["id"], role,
        user_id, f"Annual statement for {year} created in DRAFT", None, "DRAFT")
    return ok(stmt, 201)


@bp.get("/api/captives/<captiveId>/annual-statements")
def list_statements(captiveId):
    require_roles(*READ_ROLES)
    get_captive(captiveId)
    items = sorted(
        [s for s in db.statements.values() if s["captive_id"] == captiveId],
        key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/annual-statements/<statementId>")
def get_statement_route(captiveId, statementId):
    require_roles(*READ_ROLES)
    captive = get_captive(captiveId)
    return ok(get_statement(captive, statementId), 200)


@bp.post("/api/captives/<captiveId>/annual-statements/<statementId>/submit-for-review")
def submit_for_review(captiveId, statementId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    stmt = get_statement(captive, statementId)
    if stmt["status"] != "DRAFT":
        raise ApiError("ERR_STATEMENT_NOT_DRAFT",
                       "Annual statement must be in DRAFT state")
    prev = stmt["status"]
    compute_statement_fields(captive, stmt)
    stmt["status"] = "ACTUARIAL_REVIEW"
    touch(stmt)
    log(captiveId, "STATE_CHANGE", "AnnualStatement", statementId, role,
        user_id, "Statement submitted for actuarial review", prev,
        "ACTUARIAL_REVIEW")
    return ok(stmt, 200)


@bp.post("/api/captives/<captiveId>/annual-statements/<statementId>/board-approve")
def board_approve(captiveId, statementId):
    user_id, role = require_roles("BoardDirector")
    captive = get_captive(captiveId)
    stmt = get_statement(captive, statementId)
    if stmt["status"] != "ACTUARIAL_REVIEW":
        raise ApiError("ERR_STATEMENT_NOT_UNDER_REVIEW",
                       "Annual statement must be in ACTUARIAL_REVIEW state")
    uncertified = statement_uncertified_reserves(captive, stmt)
    if uncertified:
        raise ApiError("ERR_UNCERTIFIED_RESERVES",
                       "Uncertified reserves exist for the statement year")
    has_meeting = any(
        m["captive_id"] == captiveId and m["status"] == "MINUTES_APPROVED"
        for m in db.meetings.values())
    if not has_meeting:
        raise ApiError("ERR_NO_BOARD_APPROVAL_MEETING",
                       "No approved board meeting exists for annual statement approval")
    prev = stmt["status"]
    stmt["status"] = "BOARD_APPROVED"
    touch(stmt)
    adjust_governance(captive, +5)
    touch_captive(captive)
    log(captiveId, "GOVERNANCE_ACTION", "AnnualStatement", statementId, role,
        user_id, "Statement board-approved; governance score +5", prev,
        "BOARD_APPROVED")
    return ok(stmt, 200)


@bp.post("/api/captives/<captiveId>/annual-statements/<statementId>/file")
def file_statement(captiveId, statementId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    stmt = get_statement(captive, statementId)
    if stmt["status"] != "BOARD_APPROVED":
        raise ApiError("ERR_STATEMENT_NOT_BOARD_APPROVED",
                       "Annual statement must be in BOARD_APPROVED state")
    deadline = parse_ts(stmt.get("filing_deadline"))
    if deadline is not None and now() > deadline:
        raise ApiError("ERR_FILING_DEADLINE_PASSED",
                       "Annual statement filing deadline has passed")
    prev = stmt["status"]
    stmt["status"] = "FILED"
    touch(stmt)
    log(captiveId, "FILING_SUBMITTED", "AnnualStatement", statementId, role,
        user_id, "Annual statement filed with regulator", prev, "FILED")
    return ok(stmt, 200)


@bp.post("/api/captives/<captiveId>/annual-statements/<statementId>/amend")
def amend_statement(captiveId, statementId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    stmt = get_statement(captive, statementId)
    if stmt["status"] != "FILED":
        raise ApiError("ERR_STATEMENT_NOT_FILED",
                       "Annual statement must be in FILED state")
    prev = stmt["status"]
    stmt["status"] = "AMENDED"
    touch(stmt)
    # Spawn a fresh DRAFT statement for the same year.
    new_stmt = stamp_new()
    new_stmt.update({
        "captive_id": captiveId,
        "statement_year": stmt["statement_year"],
        "filing_deadline": None,
        "total_assets_cents": 0,
        "total_liabilities_cents": 0,
        "policyholder_surplus_cents": 0,
        "net_premium_written_cents": 0,
        "net_losses_incurred_cents": 0,
        "combined_ratio": 0.0,
        "expense_ratio": 0.0,
        "underwriting_result_cents": 0,
        "investment_income_cents": stmt.get("investment_income_cents", 0),
        "rbc_ratio": 0.0,
        "rbc_action_level": "NONE",
        "status": "DRAFT",
    })
    compute_statement_fields(captive, new_stmt)
    db.statements[new_stmt["id"]] = new_stmt
    adjust_governance(captive, -5)
    touch_captive(captive)
    log(captiveId, "GOVERNANCE_ACTION", "AnnualStatement", statementId, role,
        user_id,
        "Statement amended; new DRAFT spawned; governance score -5", prev,
        "AMENDED")
    return ok(stmt, 200)
