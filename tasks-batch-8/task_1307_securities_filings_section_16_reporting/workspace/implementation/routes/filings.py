"""SecuritiesFiling pipeline: create, ready, reopen, discard, submit, record-edgar-result, amendments."""
from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_FILING_INVALID_STATE,
    ERR_PERSON_NOT_ACTIVE, ERR_AGENT_NOT_AUTHORIZED,
    ERR_SOD_PREPARER_SUBMITTER, ERR_EDGAR_CREDENTIAL_MISMATCH,
    ERR_AMENDMENT_TARGET_NOT_ACCEPTED, ERR_TRANSACTION_NOT_ATTACHABLE,
    ERR_STALE_VERSION, ApiError,
)
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import (
    FILING_FIELDS, serialize, stamp_created, bump_version,
    parse_pagination, paginate, now_stamp, logical_clock_date,
)
from datetime import date
from services.calculations import (
    compute_form4_deadline, compute_form3_deadline, compute_form5_deadline,
    recompute_open_obligation_count, recompute_balance_chain,
)

filings_bp = Blueprint("filings", __name__)


def _get_filing_or_404(fid):
    f = db.filings.get(fid)
    if not f:
        raise ApiError(ERR_NOT_FOUND, f"SecuritiesFiling {fid} not found.", 404)
    return f


def _active_authorization(issuer_id, agent_user_id):
    return any(
        a for a in db.filing_agent_authorizations.values()
        if a["issuer_id"] == issuer_id
        and a["agent_user_id"] == agent_user_id
        and a["status"] == "ACTIVE"
    )


@filings_bp.route("/filings", methods=["POST"])
def create_filing():
    user_id, role = require_role("FilingCoordinator")
    body = request.get_json(force=True) or {}

    for f in ["issuer_id", "reporting_person_id", "form_type"]:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    if body["issuer_id"] not in db.issuers:
        raise ApiError(ERR_INVALID_REQUEST, f"issuer_id {body['issuer_id']} not found.", 400)
    if body["reporting_person_id"] not in db.reporting_persons:
        raise ApiError(ERR_INVALID_REQUEST, f"reporting_person_id {body['reporting_person_id']} not found.", 400)

    person = db.reporting_persons[body["reporting_person_id"]]
    if person["status"] != "ACTIVE":
        raise ApiError(ERR_PERSON_NOT_ACTIVE, "Reporting person must be ACTIVE.", 409)

    form_type = body["form_type"]
    if form_type not in ("FORM_3", "FORM_4", "FORM_5"):
        raise ApiError(ERR_INVALID_REQUEST, f"Invalid form_type: {form_type}", 400)

    issuer = db.issuers[body["issuer_id"]]
    deadline = None
    txn_ids = body.get("transaction_ids") or []

    if form_type == "FORM_4":
        if not txn_ids:
            raise ApiError(ERR_INVALID_REQUEST, "transaction_ids required for FORM_4.", 400)
        txns = []
        for tid in txn_ids:
            t = db.transactions.get(tid)
            if not t:
                raise ApiError(ERR_INVALID_REQUEST, f"Transaction {tid} not found.", 400)
            txns.append(t)
        # All must be CONFIRMED, unfiled, same person
        for t in txns:
            if t["status"] != "CONFIRMED" or t.get("filing_id") is not None \
                    or t["reporting_person_id"] != body["reporting_person_id"]:
                raise ApiError(ERR_TRANSACTION_NOT_ATTACHABLE, f"Transaction {t['id']} is not attachable.", 422)
        earliest = min(t["transaction_date"] for t in txns)
        deadline = compute_form4_deadline(earliest, issuer)
    elif form_type == "FORM_3":
        if not person.get("designation_date"):
            raise ApiError(ERR_INVALID_REQUEST, "Person has no designation_date.", 400)
        deadline = compute_form3_deadline(person["designation_date"])
    elif form_type == "FORM_5":
        fiscal_year = body.get("fiscal_year")
        if fiscal_year is None:
            raise ApiError(ERR_INVALID_REQUEST, "fiscal_year required for FORM_5.", 400)
        # Resolve against issuer fiscal calendar
        fy_end_month = issuer["fiscal_year_end_month"]
        from calendar import monthrange
        fy_end = date(int(fiscal_year), fy_end_month, monthrange(int(fiscal_year), fy_end_month)[1])
        deadline = compute_form5_deadline(fy_end.isoformat())

    filing = {
        "issuer_id": body["issuer_id"],
        "reporting_person_id": body["reporting_person_id"],
        "form_type": form_type,
        "amends_filing_id": None,
        "filing_deadline": deadline,
        "is_late": False,
        "status": "DRAFT",
        "prepared_by_user_id": user_id,
        "submitted_by_user_id": None,
        "submitted_at": None,
        "accepted_at": None,
        "accession_number": None,
        "rejection_reason": None,
    }
    stamp_created(filing)
    db.filings[filing["id"]] = filing

    # Attach transactions for FORM_4
    if form_type == "FORM_4":
        for tid in txn_ids:
            t = db.transactions[tid]
            t["filing_id"] = filing["id"]
            bump_version(t)

    recompute_open_obligation_count(filing["reporting_person_id"])
    return success_object(serialize(filing, FILING_FIELDS), 201)


@filings_bp.route("/filings", methods=["GET"])
def list_filings():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.filings.values(), key=lambda x: x["created_at"])
    for param in ["issuer_id", "reporting_person_id", "status", "form_type", "amends_filing_id"]:
        val = request.args.get(param)
        if val:
            items = [f for f in items if str(f.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(f, FILING_FIELDS) for f in page], limit, offset, total)


@filings_bp.route("/filings/<filingId>", methods=["GET"])
def get_filing(filingId):
    get_auth()
    f = _get_filing_or_404(filingId)
    return success_object(serialize(f, FILING_FIELDS))


@filings_bp.route("/filings/<filingId>/ready", methods=["POST"])
def filing_ready(filingId):
    user_id, role = require_role("FilingCoordinator")
    f = _get_filing_or_404(filingId)
    if f["status"] != "DRAFT":
        raise ApiError(ERR_FILING_INVALID_STATE, "Ready requires DRAFT.", 409)
    f["status"] = "READY"
    bump_version(f)
    recompute_open_obligation_count(f["reporting_person_id"])
    return success_object(serialize(f, FILING_FIELDS))


@filings_bp.route("/filings/<filingId>/reopen", methods=["POST"])
def filing_reopen(filingId):
    user_id, role = require_role("FilingCoordinator")
    f = _get_filing_or_404(filingId)
    if f["status"] not in ("READY", "REJECTED"):
        raise ApiError(ERR_FILING_INVALID_STATE, "Reopen requires READY or REJECTED.", 409)
    f["status"] = "DRAFT"
    f["submitted_at"] = None
    f["submitted_by_user_id"] = None
    f["rejection_reason"] = None
    bump_version(f)
    recompute_open_obligation_count(f["reporting_person_id"])
    return success_object(serialize(f, FILING_FIELDS))


@filings_bp.route("/filings/<filingId>/discard", methods=["POST"])
def filing_discard(filingId):
    user_id, role = require_role("FilingCoordinator")
    f = _get_filing_or_404(filingId)
    if f["status"] != "DRAFT":
        raise ApiError(ERR_FILING_INVALID_STATE, "Discard requires DRAFT.", 409)
    f["status"] = "DISCARDED"
    bump_version(f)
    # Detach covered transactions
    for t in db.transactions.values():
        if t.get("filing_id") == f["id"]:
            t["filing_id"] = None
            bump_version(t)
    recompute_open_obligation_count(f["reporting_person_id"])
    return success_object(serialize(f, FILING_FIELDS))


@filings_bp.route("/filings/<filingId>/submit", methods=["POST"])
def filing_submit(filingId):
    user_id, role = require_role("FilingAgent")
    f = _get_filing_or_404(filingId)
    if f["status"] != "READY":
        raise ApiError(ERR_FILING_INVALID_STATE, "Submit requires READY.", 409)
    if not _active_authorization(f["issuer_id"], user_id):
        raise ApiError(ERR_AGENT_NOT_AUTHORIZED, "No ACTIVE authorization for this agent.", 403)
    if f.get("prepared_by_user_id") and f["prepared_by_user_id"] == user_id:
        raise ApiError(ERR_SOD_PREPARER_SUBMITTER, "Submitter must differ from preparer.", 403)
    body = request.get_json(force=True) or {}
    edgar_ccc = body.get("edgar_ccc")
    issuer = db.issuers[f["issuer_id"]]
    if edgar_ccc != issuer["edgar_ccc"]:
        raise ApiError(ERR_EDGAR_CREDENTIAL_MISMATCH, "edgar_ccc mismatch.", 422)
    f["status"] = "SUBMITTED"
    f["submitted_at"] = now_stamp()
    f["submitted_by_user_id"] = user_id
    bump_version(f)
    recompute_open_obligation_count(f["reporting_person_id"])
    return success_object(serialize(f, FILING_FIELDS))


@filings_bp.route("/filings/<filingId>/record-edgar-result", methods=["POST"])
def filing_record_edgar(filingId):
    user_id, role = require_role("FilingAgent")
    f = _get_filing_or_404(filingId)
    if f["status"] != "SUBMITTED":
        raise ApiError(ERR_FILING_INVALID_STATE, "Record-edgar-result requires SUBMITTED.", 409)
    if not _active_authorization(f["issuer_id"], user_id):
        raise ApiError(ERR_AGENT_NOT_AUTHORIZED, "No ACTIVE authorization for this agent.", 403)

    body = request.get_json(force=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("ACCEPTED", "REJECTED"):
        raise ApiError(ERR_INVALID_REQUEST, "outcome must be ACCEPTED or REJECTED.", 400)

    if outcome == "ACCEPTED":
        f["accepted_at"] = now_stamp()
        f["accession_number"] = body.get("accession_number")
        f["status"] = "ACCEPTED"
        # is_late
        accepted_date = f["accepted_at"][:10]
        f["is_late"] = accepted_date > f["filing_deadline"]
        if f["is_late"]:
            person = db.reporting_persons[f["reporting_person_id"]]
            person["late_filing_count"] += 1
            if person["late_filing_count"] >= 2:
                person["delinquent_flag"] = True
            bump_version(person)
        # Mark transactions REPORTED
        for t in db.transactions.values():
            if t.get("filing_id") == f["id"]:
                t["status"] = "REPORTED"
                bump_version(t)
        # Supersede amended filing
        if f.get("amends_filing_id"):
            amended = db.filings.get(f["amends_filing_id"])
            if amended and amended["status"] == "ACCEPTED":
                amended["status"] = "SUPERSEDED"
                bump_version(amended)
    else:
        f["rejection_reason"] = body.get("rejection_reason")
        f["status"] = "REJECTED"

    bump_version(f)
    recompute_open_obligation_count(f["reporting_person_id"])
    return success_object(serialize(f, FILING_FIELDS))


@filings_bp.route("/filings/<filingId>/amendments", methods=["POST"])
def filing_amendments(filingId):
    user_id, role = require_role("FilingCoordinator")
    amended = _get_filing_or_404(filingId)
    body = request.get_json(force=True) or {}

    expected = body.get("expected_filing_version")
    if expected is None:
        raise ApiError(ERR_INVALID_REQUEST, "expected_filing_version is required.", 400)
    if expected != amended["version"]:
        raise ApiError(ERR_STALE_VERSION, "Filing version mismatch.", 412)

    if amended["status"] != "ACCEPTED":
        raise ApiError(ERR_AMENDMENT_TARGET_NOT_ACCEPTED, "Amendment target must be ACCEPTED.", 409)

    bump_version(amended)

    amendment = {
        "issuer_id": amended["issuer_id"],
        "reporting_person_id": amended["reporting_person_id"],
        "form_type": amended["form_type"],
        "amends_filing_id": amended["id"],
        "filing_deadline": amended["filing_deadline"],
        "is_late": False,
        "status": "DRAFT",
        "prepared_by_user_id": user_id,
        "submitted_by_user_id": None,
        "submitted_at": None,
        "accepted_at": None,
        "accession_number": None,
        "rejection_reason": None,
    }
    stamp_created(amendment)
    db.filings[amendment["id"]] = amendment
    recompute_open_obligation_count(amendment["reporting_person_id"])
    return success_object(serialize(amendment, FILING_FIELDS), 201)
