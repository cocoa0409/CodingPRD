"""Stop-loss filing endpoints (PRD §3.5-3.6): OCC-guarded assembly, submission
gates, carrier review cycle (dispute/resolve/approve/deny), line-item reads."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_CROSS_PLAN_REFERENCE,
    ERR_STALE_VERSION, ERR_NOTICE_OUTSTANDING, ERR_AMOUNT_OUT_OF_RANGE,
    ERR_FILING_DEADLINE_PASSED,
)
from middleware import authorized
from response import success_object, success_list
from routes.helpers import READ_FILING, get_one, list_response, get_pagination
from services.accumulation import recompute_filing
from services.core import new_record, public, touch
from util import CLOCK, parse_dt
from validate import (
    get_body, req_str, req_enum, req_int, req_str_list,
    require_path_resource, require_ref,
)

bp = Blueprint("filings", __name__)

FILING_SCOPES = {"SPECIFIC", "AGGREGATE"}


@bp.post("/stop-loss/filings")
def create_filing():
    authorized(["StopLossAnalyst"])
    body = get_body()
    contract_id = req_str(body, "contract_id")
    filing_scope = req_enum(body, "filing_scope", FILING_SCOPES)
    if filing_scope == "SPECIFIC":
        member_id = req_str(body, "member_id")
    else:
        member_id = body.get("member_id")
        if member_id is not None:
            raise_error(ERR_INVALID_REQUEST,
                        "member_id must be null on an AGGREGATE filing")
    claim_ids = req_str_list(body, "claim_ids")
    expected_version = req_int(body, "expected_contract_version")

    contract = require_ref("contracts", contract_id, "contract_id")
    member = None
    if filing_scope == "SPECIFIC":
        member = require_ref("members", member_id, "member_id")
    claims = [require_ref("claims", cid, "claim_ids") for cid in claim_ids]

    # The cross-plan check runs before the stale-version check (PRD §3.5).
    if member is not None and member["plan_id"] != contract["plan_id"]:
        raise_error(ERR_CROSS_PLAN_REFERENCE,
                    "filing member_id does not belong to the plan the contract insures")
    if expected_version != contract["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_contract_version does not match the contract's current version")

    filing = new_record("filings", {
        "contract_id": contract_id,
        "filing_scope": filing_scope,
        "member_id": member_id if filing_scope == "SPECIFIC" else None,
        "requested_amount_cents": 0,
        "approved_amount_cents": None,
        "submitted_at": None,
        "status": "DRAFT",
        "_submitted_by": None,
    })
    for cid in claim_ids:
        # Line items carry only id and created_at (PRD §2.4).
        new_record("line_items", {
            "filing_id": filing["id"],
            "claim_id": cid,
            "eligible_excess_cents": 0,
            "disputed": False,
        }, with_version=False)
    recompute_filing(filing)
    touch(contract)  # filing creation advances the contract version (PRD §2.8)
    return success_object(public(filing), status=201)


@bp.get("/stop-loss/filings/<rid>")
def get_filing(rid):
    return get_one("filings", rid, READ_FILING)


@bp.get("/stop-loss/filings")
def list_filings():
    return list_response("filings", READ_FILING, {
        "contract_id": request.args.get("contract_id"),
        "member_id": request.args.get("member_id"),
        "status": request.args.get("status"),
    })


@bp.get("/stop-loss/filings/<rid>/line-items")
def list_filing_line_items(rid):
    authorized(READ_FILING)
    filing = require_path_resource("filings", rid)
    items = [l for l in db["line_items"].values() if l["filing_id"] == filing["id"]]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/stop-loss/filing-line-items/<rid>")
def get_line_item(rid):
    return get_one("line_items", rid, READ_FILING)


@bp.get("/stop-loss/filing-line-items")
def list_line_items():
    return list_response("line_items", READ_FILING, {
        "filing_id": request.args.get("filing_id"),
        "claim_id": request.args.get("claim_id"),
    })


@bp.post("/stop-loss/filings/<rid>/submit")
def submit_filing(rid):
    caller = authorized(["StopLossAnalyst"])
    get_body()
    filing = require_path_resource("filings", rid)

    # Gates evaluate in a fixed order (PRD §3.5) — an earlier gate is never
    # masked by a later one.
    lines = [l for l in db["line_items"].values() if l["filing_id"] == filing["id"]]
    if filing["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"filing in {filing['status']} cannot be submitted")
    if not lines:
        raise_error(ERR_INVALID_STATE, "filing has no line items")
    for line in lines:
        claim = db["claims"].get(line["claim_id"])
        if claim is None or claim["status"] != "PAID":
            raise_error(ERR_INVALID_STATE,
                        "every line item's claim must be in PAID status at submission")

    if filing["filing_scope"] == "SPECIFIC":
        member = db["members"].get(filing["member_id"])
        if member is not None and member["notice_status"] == "NOTICE_PENDING":
            raise_error(ERR_NOTICE_OUTSTANDING,
                        "the member's 50% notice must be filed before any specific "
                        "reimbursement filing")

    if filing["requested_amount_cents"] <= 0:
        raise_error(ERR_AMOUNT_OUT_OF_RANGE,
                    "requested_amount_cents must be greater than zero")

    contract = db["contracts"].get(filing["contract_id"])
    deadline = parse_dt(contract["policy_year_end"]) + timedelta(
        days=contract["filing_deadline_days"])
    if CLOCK.now() > deadline:
        raise_error(ERR_FILING_DEADLINE_PASSED,
                        "submission is past policy_year_end + filing_deadline_days")

    filing["submitted_at"] = CLOCK.now_iso()
    filing["_submitted_by"] = caller.user_id
    touch(filing)
    filing["status"] = "SUBMITTED"
    return success_object(public(filing))


@bp.post("/stop-loss/filings/<rid>/begin-review")
def begin_review(rid):
    authorized(["CarrierReviewer"])
    get_body()
    filing = require_path_resource("filings", rid)
    if filing["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"filing in {filing['status']} cannot enter review")
    touch(filing)
    filing["status"] = "UNDER_REVIEW"
    return success_object(public(filing))


@bp.post("/stop-loss/filings/<rid>/dispute")
def dispute_filing(rid):
    authorized(["CarrierReviewer"])
    body = get_body()
    line_ids = req_str_list(body, "disputed_line_item_ids")
    filing = require_path_resource("filings", rid)
    lines = []
    for lid in line_ids:
        line = db["line_items"].get(lid)
        if line is None or line["filing_id"] != filing["id"]:
            from errors import ERR_NOT_FOUND
            raise_error(ERR_NOT_FOUND,
                        f"disputed_line_item_ids id does not resolve on this filing: {lid}")
        lines.append(line)
    if filing["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"filing in {filing['status']} cannot be disputed")
    for line in lines:
        line["disputed"] = True
    touch(filing)
    filing["status"] = "DISPUTED"
    return success_object(public(filing))


@bp.post("/stop-loss/filings/<rid>/resolve-dispute")
def resolve_dispute(rid):
    authorized(["StopLossAnalyst"])
    get_body()
    filing = require_path_resource("filings", rid)
    if filing["status"] != "DISPUTED":
        raise_error(ERR_INVALID_STATE,
                    f"filing in {filing['status']} has no dispute to resolve")
    for line in db["line_items"].values():
        if line["filing_id"] == filing["id"] and line["disputed"]:
            line["disputed"] = False
    recompute_filing(filing)
    touch(filing)
    filing["status"] = "UNDER_REVIEW"
    return success_object(public(filing))


@bp.post("/stop-loss/filings/<rid>/approve")
def approve_filing(rid):
    authorized(["CarrierReviewer"])
    body = get_body()
    approved = req_int(body, "approved_amount_cents")
    filing = require_path_resource("filings", rid)
    if filing["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"filing in {filing['status']} cannot be approved")
    if any(l["disputed"] for l in db["line_items"].values()
           if l["filing_id"] == filing["id"]):
        raise_error(ERR_INVALID_STATE,
                    "disputed line items block approval")
    if approved < 0 or approved > filing["requested_amount_cents"]:
        raise_error(ERR_AMOUNT_OUT_OF_RANGE,
                    "approved_amount_cents may not exceed requested_amount_cents")
    filing["approved_amount_cents"] = approved
    touch(filing)
    filing["status"] = "APPROVED"
    return success_object(public(filing))


@bp.post("/stop-loss/filings/<rid>/deny")
def deny_filing(rid):
    authorized(["CarrierReviewer"])
    get_body()
    filing = require_path_resource("filings", rid)
    if filing["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"filing in {filing['status']} cannot be denied")
    touch(filing)
    filing["status"] = "DENIED"
    return success_object(public(filing))
