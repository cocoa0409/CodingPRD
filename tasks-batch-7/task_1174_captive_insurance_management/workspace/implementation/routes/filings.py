"""DomicileFiling routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from clock import fmt_ts, now
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    adjust_governance,
    body,
    get_captive,
    get_filing,
    new_id,
    recompute_captive_ledger,
    req_enum,
    stamp_new,
    touch,
    touch_captive,
)

bp = Blueprint("filings", __name__)

ROLES = ("CaptiveManager", "DomicileRegulator")


def _documents(data):
    docs = data.get("supporting_documents")
    if docs is None:
        return []
    if not isinstance(docs, list):
        raise ApiError("ERR_INVALID_REQUEST",
                       "supporting_documents must be an array")
    for doc in docs:
        if not isinstance(doc, dict):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Each supporting document must be an object")
    return docs


@bp.post("/api/captives/<captiveId>/domicile-filings")
def create_filing(captiveId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    data = body()
    filing_type = req_enum(data, "filing_type", C.FILING_TYPES)
    jurisdiction = req_enum(data, "jurisdiction", C.DOMICILES)
    docs = _documents(data)

    filing = stamp_new()
    filing.update({
        "captive_id": captiveId,
        "filing_type": filing_type,
        "jurisdiction": jurisdiction,
        "filing_fee_cents": C.filing_fee_cents(jurisdiction, filing_type),
        "supporting_documents": docs,
        "regulator_reference": None,
        "review_deadline": None,
        "status": "DRAFT",
        "rejection_reason": None,
        "filed_at": None,
    })
    db.filings[filing["id"]] = filing
    log(captiveId, "STATE_CHANGE", "DomicileFiling", filing["id"], role,
        user_id, "Domicile filing created in DRAFT", None, "DRAFT")
    return ok(filing, 201)


@bp.get("/api/captives/<captiveId>/domicile-filings")
def list_filings(captiveId):
    require_roles(*ROLES)
    get_captive(captiveId)
    items = sorted(
        [f for f in db.filings.values() if f["captive_id"] == captiveId],
        key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/domicile-filings/<filingId>")
def get_filing_route(captiveId, filingId):
    require_roles(*ROLES)
    captive = get_captive(captiveId)
    return ok(get_filing(captive, filingId), 200)


@bp.post("/api/captives/<captiveId>/domicile-filings/<filingId>/submit")
def submit_filing(captiveId, filingId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    filing = get_filing(captive, filingId)
    if captive["status"] != "FORMATION_PENDING":
        raise ApiError("ERR_CAPTIVE_NOT_IN_FORMATION",
                       "Captive entity must be in FORMATION_PENDING state")
    if filing["status"] != "DRAFT":
        raise ApiError("ERR_FILING_NOT_DRAFT",
                       "Domicile filing must be in DRAFT state")
    if not filing.get("supporting_documents"):
        raise ApiError("ERR_NO_SUPPORTING_DOCUMENTS",
                       "At least one supporting document is required for filing submission")
    prev = filing["status"]
    filed_at = now()
    filing["status"] = "SUBMITTED"
    filing["filed_at"] = fmt_ts(filed_at)
    days = C.JURISDICTION_REVIEW_DAYS.get(filing["jurisdiction"], 30)
    filing["review_deadline"] = fmt_ts(filed_at + timedelta(days=days))
    touch(filing)
    captive["status"] = "DOMICILE_FILED"
    touch_captive(captive)
    log(captiveId, "FILING_SUBMITTED", "DomicileFiling", filing["id"], role,
        user_id, "Domicile filing submitted; captive moved to DOMICILE_FILED",
        prev, "SUBMITTED")
    return ok(filing, 200)


@bp.post("/api/captives/<captiveId>/domicile-filings/<filingId>/acknowledge")
def acknowledge_filing(captiveId, filingId):
    user_id, role = require_roles("DomicileRegulator")
    captive = get_captive(captiveId)
    filing = get_filing(captive, filingId)
    if filing["status"] != "SUBMITTED":
        raise ApiError("ERR_FILING_NOT_SUBMITTED",
                       "Domicile filing must be in SUBMITTED state")
    prev = filing["status"]
    filing["status"] = "UNDER_REVIEW"
    filing["regulator_reference"] = f"REG-{new_id()[:12].upper()}"
    touch(filing)
    log(captiveId, "STATE_CHANGE", "DomicileFiling", filing["id"], role,
        user_id, "Filing acknowledged; under review", prev, "UNDER_REVIEW")
    return ok(filing, 200)


@bp.post("/api/captives/<captiveId>/domicile-filings/<filingId>/approve")
def approve_filing(captiveId, filingId):
    user_id, role = require_roles("DomicileRegulator")
    captive = get_captive(captiveId)
    filing = get_filing(captive, filingId)
    if captive["status"] != "DOMICILE_FILED":
        raise ApiError("ERR_CAPTIVE_NOT_DOMICILE_FILED",
                       "Captive entity must be in DOMICILE_FILED state")
    if filing["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_FILING_NOT_UNDER_REVIEW",
                       "Domicile filing must be in UNDER_REVIEW state")
    if int(captive.get("capitalization_amount") or 0) < int(
            captive.get("capital_minimum_required") or 0):
        raise ApiError("ERR_CAPITALIZATION_BELOW_MINIMUM",
                       "Capitalization amount is below the domicile minimum requirement")
    prev = filing["status"]
    filing["status"] = "APPROVED"
    if not filing.get("regulator_reference"):
        filing["regulator_reference"] = f"REG-{new_id()[:12].upper()}"
    touch(filing)
    captive["status"] = "CAPITALIZED"
    recompute_captive_ledger(captive)
    touch_captive(captive)
    log(captiveId, "STATE_CHANGE", "DomicileFiling", filing["id"], role,
        user_id, "Filing approved; captive CAPITALIZED", prev, "APPROVED")
    return ok(filing, 200)


@bp.post("/api/captives/<captiveId>/domicile-filings/<filingId>/reject")
def reject_filing(captiveId, filingId):
    user_id, role = require_roles("DomicileRegulator")
    captive = get_captive(captiveId)
    filing = get_filing(captive, filingId)
    if filing["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_FILING_NOT_UNDER_REVIEW",
                       "Domicile filing must be in UNDER_REVIEW state")
    data = body()
    prev = filing["status"]
    filing["status"] = "REJECTED"
    filing["rejection_reason"] = data.get("rejection_reason")
    touch(filing)
    adjust_governance(captive, -10)
    touch_captive(captive)
    log(captiveId, "GOVERNANCE_ACTION", "DomicileFiling", filing["id"], role,
        user_id, "Filing rejected; governance score reduced by 10", prev,
        "REJECTED")
    return ok(filing, 200)


@bp.post("/api/captives/<captiveId>/domicile-filings/<filingId>/withdraw")
def withdraw_filing(captiveId, filingId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    filing = get_filing(captive, filingId)
    if filing["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_FILING_NOT_WITHDRAWABLE",
                       "Domicile filing must be in DRAFT or SUBMITTED state")
    prev = filing["status"]
    filing["status"] = "WITHDRAWN"
    touch(filing)
    if prev == "SUBMITTED":
        adjust_governance(captive, -5)
        touch_captive(captive)
    log(captiveId, "STATE_CHANGE", "DomicileFiling", filing["id"], role,
        user_id, "Filing withdrawn", prev, "WITHDRAWN")
    return ok(filing, 200)
