"""Regulatory filings and the four-eyes principle (PRD §3.9)."""

from flask import Blueprint, request

import db
import calculations as calc
import services
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_INVALID_DECISION,
    ERR_SEGREGATION_VIOLATION,
    ERR_FILING_TYPE_MISMATCH,
    ERR_NOT_APPROVABLE,
)
from middleware import authenticate, require_role
from response import object_response, array_response
from validation import (
    get_body,
    require_found,
    require_enum,
    require_field,
    require_string,
    parse_pagination,
    sort_and_paginate,
)

bp = Blueprint("filings", __name__)

READ_ROLES = {"Analyst", "ComplianceOfficer", "QualityReviewer", "PlatformAdmin"}


def _ctr_anchor_for_case(case):
    """Earliest posted_at among CTR_THRESHOLD transactions on this case's accounts,
    tie-broken by earliest created_at; None if none (PRD §3.9)."""
    # Accounts referenced by alerts linked (or formerly linked) to this case —
    # the PRD says "the case's accounts". Use accounts of alerts that reference
    # this case plus the case's customer's accounts that produced CTR alerts.
    # Concretely: gather accounts whose alerts have case_id==case.id, falling back
    # to alerts that fired CTR for the case's customer. We use the linked alerts'
    # originating accounts.
    account_ids = set()
    for al in db.alerts.values():
        if al.get("case_id") == case["id"]:
            account_ids.add(al["account_id"])
    candidates = [
        t
        for t in db.transactions.values()
        if t["account_id"] in account_ids and t["triggered_rule"] == "CTR_THRESHOLD"
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda t: (t["posted_at"], t["created_at"], t.get("_seq", 0)))
    return best["posted_at"]


# ---------------------------------------------------------------------------
# POST /cases/{id}/filings  (Analyst)
# ---------------------------------------------------------------------------
@bp.route("/cases/<cid>/filings", methods=["POST"])
def create_filing(cid):
    user_id, role = authenticate()
    require_role(role, {"Analyst"})
    case = require_found(db.cases.get(cid))
    body = get_body()

    filing_type = require_enum(body, "filing_type", {"SAR", "CTR"})

    # priority 12: filing_type must match case disposition (PRD §3.9)
    if filing_type == "SAR" and case["disposition"] != "SAR_RECOMMENDED":
        raise err(ERR_FILING_TYPE_MISMATCH, "SAR filing requires case in SAR_RECOMMENDED.")
    if filing_type == "CTR" and case["disposition"] != "CTR_REQUIRED":
        raise err(ERR_FILING_TYPE_MISMATCH, "CTR filing requires case in CTR_REQUIRED.")

    ctr_anchor = _ctr_anchor_for_case(case) if filing_type == "CTR" else None
    deadline = calc.filing_deadline(filing_type, case["created_at"], ctr_anchor)

    base = db.common_create_fields()
    filing = {
        **base,
        "case_id": cid,
        "filing_type": filing_type,
        "prepared_by_user_id": user_id,
        "approved_by_user_id": None,
        "deadline_at": deadline,
        "status": "DRAFT",
        "acknowledgement_code": None,
    }
    db.filings[filing["id"]] = filing
    services.audit("Filing", filing["id"], "FILING_CREATED", user_id, role)
    return object_response(db.public(filing), 201)


@bp.route("/cases/<cid>/filings", methods=["GET"])
def list_case_filings(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.cases.get(cid))
    limit, offset = parse_pagination(request.args)
    rows = [f for f in db.filings.values() if f["case_id"] == cid]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(f) for f in page], limit, offset, total)


@bp.route("/filings/<fid>", methods=["GET"])
def get_filing(fid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    filing = require_found(db.filings.get(fid))
    return object_response(db.public(filing))


# ---------------------------------------------------------------------------
# POST /filings/{id}/approve  (QualityReviewer; 4-eyes)
# ---------------------------------------------------------------------------
@bp.route("/filings/<fid>/approve", methods=["POST"])
def approve_filing(fid):
    user_id, role = authenticate()
    require_role(role, {"QualityReviewer"})
    filing = require_found(db.filings.get(fid))

    # priority 23: approve requires DRAFT
    if filing["status"] != "DRAFT":
        raise err(ERR_NOT_APPROVABLE, "approve requires filing in DRAFT.")
    # priority 11: 4-eyes — approver must differ from preparer (PRD §3.9)
    if user_id == filing["prepared_by_user_id"]:
        raise err(ERR_SEGREGATION_VIOLATION, "Approver must differ from preparer (4-eyes).")

    filing["approved_by_user_id"] = user_id
    db.touch(filing)
    services.audit("Filing", fid, "FILING_APPROVED", user_id, role)
    return object_response(db.public(filing))


# ---------------------------------------------------------------------------
# POST /filings/{id}/submit  (QualityReviewer)
# ---------------------------------------------------------------------------
@bp.route("/filings/<fid>/submit", methods=["POST"])
def submit_filing(fid):
    user_id, role = authenticate()
    require_role(role, {"QualityReviewer"})
    filing = require_found(db.filings.get(fid))

    # priority 23: submit requires DRAFT with approved_by_user_id set
    if filing["status"] != "DRAFT" or filing["approved_by_user_id"] is None:
        raise err(ERR_NOT_APPROVABLE, "submit requires an approved DRAFT filing.")
    # priority 11: re-assert 4-eyes (PRD §3.9)
    if filing["approved_by_user_id"] == filing["prepared_by_user_id"]:
        raise err(ERR_SEGREGATION_VIOLATION, "Approver must differ from preparer (4-eyes).")

    filing["status"] = "SUBMITTED"
    db.touch(filing)
    services.audit("Filing", fid, "FILING_SUBMITTED", user_id, role)
    return object_response(db.public(filing))


# ---------------------------------------------------------------------------
# POST /filings/{id}/acknowledge  (SystemFeed)
# ---------------------------------------------------------------------------
@bp.route("/filings/<fid>/acknowledge", methods=["POST"])
def acknowledge_filing(fid):
    user_id, role = authenticate()
    require_role(role, {"SystemFeed"})
    filing = require_found(db.filings.get(fid))
    body = get_body()

    # priority 21: decision must be ACCEPT or REJECT
    decision = require_field(body, "decision")
    if decision not in {"ACCEPT", "REJECT"}:
        raise err(ERR_INVALID_DECISION, "decision must be ACCEPT or REJECT.")

    # state legality (priority 7): acknowledge requires SUBMITTED
    if filing["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "acknowledge requires filing in SUBMITTED.")

    if decision == "ACCEPT":
        ack = require_string(body, "acknowledgement_code")
        filing["status"] = "ACCEPTED"
        filing["acknowledgement_code"] = ack
        db.touch(filing)
        services.audit("Filing", fid, "FILING_ACCEPTED", user_id, role)
        # bubble owning Case -> FILED (PRD §3.8, §3.9)
        case = db.cases.get(filing["case_id"])
        if case is not None:
            if (filing["filing_type"] == "SAR" and case["disposition"] == "SAR_RECOMMENDED") or (
                filing["filing_type"] == "CTR" and case["disposition"] == "CTR_REQUIRED"
            ):
                case["disposition"] = "FILED"
                db.touch(case)
                services.audit("Case", case["id"], "CASE_FILED", user_id, role)
        return object_response(db.public(filing))

    # REJECT
    filing["status"] = "REJECTED"
    db.touch(filing)
    services.audit("Filing", fid, "FILING_REJECTED", user_id, role)
    return object_response(db.public(filing))


# ---------------------------------------------------------------------------
# POST /filings/{id}/revise  (Analyst)
# ---------------------------------------------------------------------------
@bp.route("/filings/<fid>/revise", methods=["POST"])
def revise_filing(fid):
    user_id, role = authenticate()
    require_role(role, {"Analyst"})
    filing = require_found(db.filings.get(fid))

    if filing["status"] != "REJECTED":
        raise err(ERR_INVALID_STATE, "revise requires filing in REJECTED.")
    filing["status"] = "DRAFT"
    filing["approved_by_user_id"] = None
    db.touch(filing)
    services.audit("Filing", fid, "FILING_REVISED", user_id, role)
    return object_response(db.public(filing))
