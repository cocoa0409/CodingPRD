"""Eligibility audit endpoints (PRD §3.8): open, issue findings, resolve with
segregation of duties and clawback side effects."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES
from middleware import authorized
from response import success_object
from routes.helpers import READ_AUDIT, get_one, list_response
from services.accumulation import recompute_specific_row, recompute_aggregate_row
from services.core import new_record, public, touch
from validate import get_body, req_str, req_int, require_path_resource, require_ref

bp = Blueprint("audits", __name__)


@bp.post("/stop-loss/audits")
def create_audit():
    authorized(["CarrierAuditor"])
    body = get_body()
    filing_id = req_str(body, "filing_id")
    reason = req_str(body, "reason")
    require_ref("filings", filing_id, "filing_id")
    rec = new_record("audits", {
        "filing_id": filing_id,
        "reason": reason,
        "adjustment_cents": None,
        "status": "OPENED",
    })
    return success_object(public(rec), status=201)


@bp.get("/stop-loss/audits/<rid>")
def get_audit(rid):
    return get_one("audits", rid, READ_AUDIT)


@bp.get("/stop-loss/audits")
def list_audits():
    return list_response("audits", READ_AUDIT,
                         {"filing_id": request.args.get("filing_id")})


@bp.post("/stop-loss/audits/<rid>/issue-findings")
def issue_findings(rid):
    authorized(["CarrierAuditor"])
    get_body()
    audit = require_path_resource("audits", rid)
    if audit["status"] != "OPENED":
        raise_error(ERR_INVALID_STATE,
                    f"audit in {audit['status']} cannot issue findings")
    touch(audit)
    audit["status"] = "FINDINGS_ISSUED"
    return success_object(public(audit))


@bp.post("/stop-loss/audits/<rid>/resolve")
def resolve_audit(rid):
    caller = authorized(["PlanAdministrator"])
    body = get_body()
    adjustment = req_int(body, "adjustment_cents")
    audit = require_path_resource("audits", rid)
    if audit["status"] != "FINDINGS_ISSUED":
        raise_error(ERR_INVALID_STATE,
                    f"audit in {audit['status']} cannot be resolved")
    filing = db["filings"].get(audit["filing_id"])
    # Segregation of duties (PRD §2.11): the resolving operator's X-User-ID must
    # differ from the identifier that submitted the underlying filing.
    if filing is not None and filing.get("_submitted_by") is not None \
            and caller.user_id == filing["_submitted_by"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the operator who submitted the filing cannot resolve its audit")

    audit["adjustment_cents"] = adjustment
    touch(audit)
    audit["status"] = "RESOLVED"

    # A negative adjustment is a clawback from the plan (PRD §3.8).
    if adjustment < 0 and filing is not None \
            and filing["approved_amount_cents"] is not None:
        filing["approved_amount_cents"] += adjustment
        touch(filing)
        contract = db["contracts"].get(filing["contract_id"])
        if contract is not None:
            if filing["filing_scope"] == "SPECIFIC" and filing["member_id"]:
                recompute_specific_row(contract, filing["member_id"])
            recompute_aggregate_row(contract)
    return success_object(public(audit))
