"""TrustFund endpoints: create, get, run-ops (delinquency sweep)."""

from flask import Blueprint

import db
import errors
import middleware as mw
from response import success_object
from services import ledger

bp = Blueprint("trust_funds", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")


def fund_view(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "posture": f["posture"],
        "contributions_received_cents": f["contributions_received_cents"],
        "disbursed_cents": f["disbursed_cents"],
        "allocated_remaining_cents": f["allocated_remaining_cents"],
        "available_cents": f["available_cents"],
        "delinquent_employer_count": f["delinquent_employer_count"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def get_fund_or_404(fund_id):
    fund = db.trust_funds.get(fund_id)
    if fund is None:
        raise errors.err_fund_not_found()
    return fund


@bp.route("/trust-funds", methods=["POST"])
def create_fund():
    mw.require_roles("TrustAdmin")
    body = mw.get_body()
    mw.require_fields(body, ["name"])
    if not mw.is_str(body["name"]):
        raise errors.err_invalid_request("name must be a string")
    fid = db.new_id()
    now = db.now_iso()
    fund = {
        "id": fid,
        "name": body["name"],
        "posture": "OPERATING",
        "contributions_received_cents": 0,
        "disbursed_cents": 0,
        "allocated_remaining_cents": 0,
        "available_cents": 0,
        "delinquent_employer_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.trust_funds[fid] = fund
    return success_object(fund_view(fund), 201)


@bp.route("/trust-funds/<fund_id>", methods=["GET"])
def get_fund(fund_id):
    mw.require_roles(*ALL_ROLES)
    fund = get_fund_or_404(fund_id)
    ledger.recompute_fund(fund)
    return success_object(fund_view(fund), 200)


@bp.route("/trust-funds/<fund_id>/run-ops", methods=["POST"])
def run_ops(fund_id):
    mw.require_roles("TrustAdmin")
    fund = get_fund_or_404(fund_id)
    now = db.get_clock()

    # Delinquency sweep: non-terminal reports of this fund, ascending due_date,
    # tie-break created_at ASC. Overdue iff clock is STRICTLY greater than due_date.
    fund_employer_ids = {
        eid for eid, e in db.employers.items() if e["trust_fund_id"] == fund["id"]
    }
    candidates = [
        r for r in db.contribution_reports.values()
        if r["employer_id"] in fund_employer_ids and r["status"] in ("DRAFT", "SUBMITTED", "FLAGGED")
    ]
    candidates.sort(key=lambda r: (db._parse_iso(r["due_date"]), db._parse_iso(r["created_at"])))
    for r in candidates:
        if now > db._parse_iso(r["due_date"]):
            r["status"] = "DELINQUENT"
            ledger.touch(r)
            ledger.recompute_employer_outstanding(db.employers[r["employer_id"]])

    # Re-derive each employer's status, then fund count + posture.
    for eid in fund_employer_ids:
        ledger.recompute_employer_status(db.employers[eid])
    ledger.recompute_fund(fund)
    return success_object(fund_view(fund), 200)
