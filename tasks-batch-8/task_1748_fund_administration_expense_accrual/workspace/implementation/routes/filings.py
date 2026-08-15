"""Regulatory filing endpoints: create, get, list, submit-review, approve,
file, amend (the amendment cycle)."""
from datetime import timedelta

from flask import Blueprint, g

import db
from db import store
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from services import navmath
from validation import parse_body, require_fk, require_path_entity

bp = Blueprint("filings", __name__)

FILING_SCHEMA = {
    "fund_id": ("string", True, None),
    "filing_type": ("enum", True, ["N_PORT", "N_CEN", "ANNUAL_REPORT", "SEMI_ANNUAL_REPORT"]),
    "period_end": ("date", True, None),
}

DEADLINE_DAYS = {"N_CEN": 75}  # everything else: 60


def _has_escalated_break(fund_id):
    return any(b["fund_id"] == fund_id and b["status"] == "ESCALATED"
               for b in store.reconciliation_breaks.values())


@bp.post("/regulatory-filings")
def create_filing():
    get_context()
    require_roles(["ComplianceOfficer"])
    body = parse_body(FILING_SCHEMA)
    fund = require_fk(store.funds, body["fund_id"], "fund_id")
    days = DEADLINE_DAYS.get(body["filing_type"], 60)
    deadline = (navmath.date_of(body["period_end"]) + timedelta(days=days)).isoformat()
    filing = {
        "id": db.new_id(),
        "fund_id": fund["id"],
        "filing_type": body["filing_type"],
        "period_end": body["period_end"],
        "filing_deadline": deadline,
        "status": "DRAFT",
        "filed_at": None,
        "filed_after_deadline": False,
        "prepared_by_user_id": g.user_id,
        "approved_by_user_id": None,
    }
    db.new_common(filing)
    store.regulatory_filings[filing["id"]] = filing
    return created(filing)


@bp.get("/regulatory-filings/<regulatory_filing_id>")
def get_filing(regulatory_filing_id):
    get_context()
    filing = require_path_entity(store.regulatory_filings, regulatory_filing_id)
    require_roles(ALL_ROLES)
    return ok(filing)


@bp.get("/regulatory-filings")
def list_filings():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.regulatory_filings.values())
    rows = filter_arg(rows, "fund_id")
    rows = filter_arg(rows, "filing_type")
    rows = filter_arg(rows, "status")
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)


@bp.post("/regulatory-filings/<regulatory_filing_id>/submit-review")
def submit_review(regulatory_filing_id):
    get_context()
    filing = require_path_entity(store.regulatory_filings, regulatory_filing_id)
    require_roles(["ComplianceOfficer"])
    parse_body({})
    if filing["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT or AMENDED filing can be submitted for review")
    filing["status"] = "PENDING_REVIEW"
    db.touch(filing)
    return ok(filing)


@bp.post("/regulatory-filings/<regulatory_filing_id>/approve")
def approve_filing(regulatory_filing_id):
    get_context()
    filing = require_path_entity(store.regulatory_filings, regulatory_filing_id)
    require_roles(["FundController"])
    parse_body({})
    if filing["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PENDING_REVIEW filing can be approved")
    # SoD (priority 6) -> compliance gate (7) -> temporal (8).
    if g.user_id == filing["prepared_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "The filing's preparer cannot approve it")
    if _has_escalated_break(filing["fund_id"]):
        raise ApiError("ERR_BREAK_ESCALATED_BLOCKS", 409,
                       "An ESCALATED reconciliation break of the fund blocks approval")
    if navmath.date_of(filing["period_end"]) >= db.clock_today():
        raise ApiError("ERR_PERIOD_NOT_ENDED", 422,
                       "period_end is not strictly before the logical clock date")
    filing["status"] = "APPROVED"
    filing["approved_by_user_id"] = g.user_id
    db.touch(filing)
    return ok(filing)


@bp.post("/regulatory-filings/<regulatory_filing_id>/file")
def file_filing(regulatory_filing_id):
    get_context()
    filing = require_path_entity(store.regulatory_filings, regulatory_filing_id)
    require_roles(["ComplianceOfficer"])
    parse_body({})
    if filing["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED filing can be filed")
    if _has_escalated_break(filing["fund_id"]):
        raise ApiError("ERR_BREAK_ESCALATED_BLOCKS", 409,
                       "An ESCALATED reconciliation break of the fund blocks filing")
    filing["status"] = "FILED"
    filing["filed_at"] = db.logical_now()
    filing["filed_after_deadline"] = \
        db.clock_today() > navmath.date_of(filing["filing_deadline"])
    db.touch(filing)
    return ok(filing)


@bp.post("/regulatory-filings/<regulatory_filing_id>/amend")
def amend_filing(regulatory_filing_id):
    get_context()
    filing = require_path_entity(store.regulatory_filings, regulatory_filing_id)
    require_roles(["ComplianceOfficer"])
    parse_body({})
    if filing["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a FILED filing can be amended")
    filing["status"] = "AMENDED"
    filing["approved_by_user_id"] = None
    db.touch(filing)
    return ok(filing)
