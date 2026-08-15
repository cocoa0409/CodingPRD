"""Investor, KycCase, AccreditationAttestation, CapitalAccount, SeriesLot,
InvestorStatement nested endpoints (PRD 3.2, 3.3, 3.8)."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_SANCTIONS_HIT, ERR_STALE_ATTESTATION,
)
from middleware import require_roles, check_investor_owns
from response import success_object, success_list
from services.core import (
    stamp_new, touch, serialize, paginate, filter_by,
    get_investor, get_kyc_case, get_attestation, get_capital_account,
    get_statement, child_of, open_kyc_case, documents_complete,
    set_kyc_status, cascade_kyc_approved, cascade_kyc_rejected, _TIER_RANK,
)
from util import CLOCK, parse_datetime, fmt_datetime
from validate import get_body, req_str, req_enum, req_bool, req_datetime, opt_str

bp = Blueprint("investors", __name__)

INVESTOR_TYPES = {"INDIVIDUAL", "JOINT", "CORPORATION", "TRUST", "PARTNERSHIP",
                  "LLC", "EMPLOYEE_BENEFIT_PLAN"}
RISK_RATINGS = {"LOW", "MEDIUM", "HIGH", "PROHIBITED"}
ATTESTATION_TIERS = {"ACCREDITED", "QUALIFIED_PURCHASER"}
EVIDENCE_TYPES = {"INCOME_STATEMENT", "NET_WORTH_CERT", "CPA_LETTER",
                  "LICENSED_PROFESSIONAL", "ENTITY_ASSETS"}
ALL_READ = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager", "Investor")


def _load_investor_scoped(caller, investor_id):
    """Investor callers may only touch their own record (403 before 404)."""
    check_investor_owns(caller, investor_id)
    return get_investor(investor_id)


# ---------------------------------------------------------------------------
# Investor
# ---------------------------------------------------------------------------


@bp.post("/investors")
def create_investor():
    require_roles("FundAdmin", "TransferAgent")
    body = get_body()
    investor = stamp_new({
        "legal_name": req_str(body, "legal_name"),
        "investor_type": req_enum(body, "investor_type", INVESTOR_TYPES),
        "tax_id": req_str(body, "tax_id"),
        "email": req_str(body, "email"),
        "residence_country": req_str(body, "residence_country"),
        "is_us_person": req_bool(body, "is_us_person"),
        "kyc_status": "NOT_STARTED",
        "accreditation_status": "UNVERIFIED",
        "aggregate_unfunded_commitment_cents": 0,
    })
    db["investors"][investor["id"]] = investor
    return success_object(serialize(investor), 201)


@bp.get("/investors")
def list_investors():
    require_roles("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager")
    items, total, limit, offset = paginate(list(db["investors"].values()))
    return success_list(items, total, limit, offset)


@bp.get("/investors/<investor_id>")
def get_investor_route(investor_id):
    caller = require_roles(*ALL_READ)
    investor = _load_investor_scoped(caller, investor_id)
    return success_object(serialize(investor))


# ---------------------------------------------------------------------------
# KycCase
# ---------------------------------------------------------------------------


@bp.post("/investors/<investor_id>/kyc-cases")
def create_kyc_case(investor_id):
    require_roles("ComplianceOfficer", "FundAdmin")
    investor = get_investor(investor_id)
    body = get_body()
    case = open_kyc_case(
        investor,
        risk_rating=req_enum(body, "risk_rating", RISK_RATINGS),
        pep_hit=req_bool(body, "pep_hit"),
        sanctions_hit=req_bool(body, "sanctions_hit"),
        adverse_media_hit=req_bool(body, "adverse_media_hit"),
    )
    return success_object(serialize(case), 201)


@bp.get("/investors/<investor_id>/kyc-cases")
def list_kyc_cases(investor_id):
    require_roles("FundAdmin", "ComplianceOfficer")
    investor = get_investor(investor_id)
    items, total, limit, offset = paginate(filter_by(
        db["kyc_cases"].values(), investor_id=investor["id"]))
    return success_list(items, total, limit, offset)


@bp.get("/investors/<investor_id>/kyc-cases/<case_id>")
def get_kyc_case_route(investor_id, case_id):
    caller = require_roles("FundAdmin", "ComplianceOfficer", "Investor")
    investor = _load_investor_scoped(caller, investor_id)
    case = get_kyc_case(case_id)
    child_of(case, "investor_id", investor["id"])
    return success_object(serialize(case))


@bp.post("/investors/<investor_id>/kyc-cases/<case_id>/documents")
def submit_kyc_document(investor_id, case_id):
    caller = require_roles("Investor", "TransferAgent")
    investor = _load_investor_scoped(caller, investor_id)
    case = get_kyc_case(case_id)
    child_of(case, "investor_id", investor["id"])
    body = get_body()
    document_type = req_str(body, "document_type")
    req_str(body, "document_reference")
    if case["status"] not in ("AWAITING_DOCUMENTS", "IN_REVIEW"):
        raise_error(ERR_INVALID_STATE, "case does not accept documents in its state")
    case["submitted_documents"].append(document_type)
    if case["status"] == "AWAITING_DOCUMENTS" and documents_complete(case):
        # Last required document arrived; entering review auto-escalates cases
        # with sanctions hits or PEP hits at non-LOW risk.
        if case["sanctions_hit"] or (case["pep_hit"] and case["risk_rating"] != "LOW"):
            case["status"] = "ESCALATED"
        else:
            case["status"] = "IN_REVIEW"
        set_kyc_status(investor, "UNDER_REVIEW")
    touch(case)
    return success_object(serialize(case))


@bp.post("/investors/<investor_id>/kyc-cases/<case_id>/approve")
def approve_kyc_case(investor_id, case_id):
    require_roles("ComplianceOfficer")
    investor = get_investor(investor_id)
    case = get_kyc_case(case_id)
    child_of(case, "investor_id", investor["id"])
    body = get_body()

    if case["status"] == "ESCALATED":
        if body.get("senior_override") is True:
            case["status"] = "APPROVED"
            touch(case)
            cascade_kyc_approved(investor)
            return success_object(serialize(case))
        if case["sanctions_hit"]:
            raise_error(ERR_SANCTIONS_HIT, "sanctions hit requires senior override")
        raise_error(ERR_INVALID_STATE, "ESCALATED case requires senior_override=true")
    if case["status"] == "IN_REVIEW":
        pass  # valid state; safety checks below
    elif case["status"] == "AWAITING_DOCUMENTS" and documents_complete(case):
        pass  # required set vacuously/fully satisfied; treat as reviewable
    else:
        raise_error(ERR_INVALID_STATE, "case is not in a reviewable state")

    # Business safety: sanctions block outright (and auto-escalate); PEP at
    # non-LOW risk belongs on the escalated path.
    if case["sanctions_hit"]:
        case["status"] = "ESCALATED"
        touch(case)
        set_kyc_status(investor, "UNDER_REVIEW")
        raise_error(ERR_SANCTIONS_HIT, "sanctions_hit blocks approval")
    if case["pep_hit"] and case["risk_rating"] != "LOW":
        case["status"] = "ESCALATED"
        touch(case)
        set_kyc_status(investor, "UNDER_REVIEW")
        raise_error(ERR_INVALID_STATE, "PEP hit at non-LOW risk requires escalation")

    case["status"] = "APPROVED"
    touch(case)
    cascade_kyc_approved(investor)
    return success_object(serialize(case))


@bp.post("/investors/<investor_id>/kyc-cases/<case_id>/reject")
def reject_kyc_case(investor_id, case_id):
    require_roles("ComplianceOfficer")
    investor = get_investor(investor_id)
    case = get_kyc_case(case_id)
    child_of(case, "investor_id", investor["id"])
    body = get_body()
    if case["status"] not in ("OPEN", "AWAITING_DOCUMENTS", "IN_REVIEW", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "case is already resolved")
    case["status"] = "REJECTED"
    case["rejection_reason"] = opt_str(body, "rejection_reason")
    touch(case)
    cascade_kyc_rejected(investor)
    return success_object(serialize(case))


# ---------------------------------------------------------------------------
# AccreditationAttestation
# ---------------------------------------------------------------------------


@bp.post("/investors/<investor_id>/accreditations")
def create_attestation(investor_id):
    caller = require_roles("Investor", "TransferAgent")
    investor = _load_investor_scoped(caller, investor_id)
    body = get_body()
    attested_at = req_datetime(body, "attested_at_utc")
    expires = parse_datetime(attested_at) + timedelta(days=365)
    attestation = stamp_new({
        "investor_id": investor["id"],
        "attestation_tier": req_enum(body, "attestation_tier", ATTESTATION_TIERS),
        "evidence_type": req_enum(body, "evidence_type", EVIDENCE_TYPES),
        "evidence_document_id": req_str(body, "evidence_document_id"),
        "attested_at_utc": attested_at,
        "expires_at_utc": fmt_datetime(expires),
        "status": "PENDING_REVIEW",
        "_rejection_reason": None,
    })
    db["accreditations"][attestation["id"]] = attestation
    return success_object(serialize(attestation), 201)


@bp.get("/investors/<investor_id>/accreditations")
def list_attestations(investor_id):
    caller = require_roles("FundAdmin", "ComplianceOfficer", "Investor")
    investor = _load_investor_scoped(caller, investor_id)
    items, total, limit, offset = paginate(filter_by(
        db["accreditations"].values(), investor_id=investor["id"]))
    return success_list(items, total, limit, offset)


@bp.get("/investors/<investor_id>/accreditations/<att_id>")
def get_attestation_route(investor_id, att_id):
    caller = require_roles("FundAdmin", "ComplianceOfficer", "Investor")
    investor = _load_investor_scoped(caller, investor_id)
    attestation = get_attestation(att_id)
    child_of(attestation, "investor_id", investor["id"])
    return success_object(serialize(attestation))


@bp.post("/investors/<investor_id>/accreditations/<att_id>/verify")
def verify_attestation(investor_id, att_id):
    require_roles("ComplianceOfficer")
    investor = get_investor(investor_id)
    attestation = get_attestation(att_id)
    child_of(attestation, "investor_id", investor["id"])
    get_body()
    if attestation["status"] != "PENDING_REVIEW":
        raise_error(ERR_INVALID_STATE, "attestation is not PENDING_REVIEW")
    attested = parse_datetime(attestation["attested_at_utc"])
    if CLOCK.now() - attested > timedelta(days=90):
        raise_error(ERR_STALE_ATTESTATION, "attestation signed more than 90 days ago")
    attestation["status"] = "VERIFIED"
    touch(attestation)
    if _TIER_RANK[attestation["attestation_tier"]] > _TIER_RANK.get(
            investor["accreditation_status"], 0):
        investor["accreditation_status"] = attestation["attestation_tier"]
        touch(investor)
    return success_object(serialize(attestation))


@bp.post("/investors/<investor_id>/accreditations/<att_id>/reject")
def reject_attestation(investor_id, att_id):
    require_roles("ComplianceOfficer")
    investor = get_investor(investor_id)
    attestation = get_attestation(att_id)
    child_of(attestation, "investor_id", investor["id"])
    body = get_body()
    if attestation["status"] != "PENDING_REVIEW":
        raise_error(ERR_INVALID_STATE, "attestation is not PENDING_REVIEW")
    attestation["status"] = "REJECTED"
    attestation["_rejection_reason"] = opt_str(body, "rejection_reason")
    touch(attestation)
    return success_object(serialize(attestation))


# ---------------------------------------------------------------------------
# CapitalAccount / SeriesLot / InvestorStatement nested reads
# ---------------------------------------------------------------------------


@bp.get("/investors/<investor_id>/capital-accounts")
def list_capital_accounts(investor_id):
    caller = require_roles(*ALL_READ)
    investor = _load_investor_scoped(caller, investor_id)
    from flask import request
    items = filter_by(db["capital_accounts"].values(),
                      investor_id=investor["id"],
                      share_class_id=request.args.get("share_class_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/investors/<investor_id>/capital-accounts/<account_id>")
def get_capital_account_route(investor_id, account_id):
    caller = require_roles(*ALL_READ)
    investor = _load_investor_scoped(caller, investor_id)
    account = get_capital_account(account_id)
    child_of(account, "investor_id", investor["id"])
    return success_object(serialize(account))


@bp.get("/investors/<investor_id>/capital-accounts/<account_id>/lots")
def list_series_lots(investor_id, account_id):
    caller = require_roles(*ALL_READ)
    investor = _load_investor_scoped(caller, investor_id)
    account = get_capital_account(account_id)
    child_of(account, "investor_id", investor["id"])
    items, total, limit, offset = paginate(filter_by(
        db["series_lots"].values(), capital_account_id=account["id"]))
    return success_list(items, total, limit, offset)


@bp.get("/investors/<investor_id>/capital-accounts/<account_id>/statements")
def list_statements(investor_id, account_id):
    caller = require_roles(*ALL_READ)
    investor = _load_investor_scoped(caller, investor_id)
    account = get_capital_account(account_id)
    child_of(account, "investor_id", investor["id"])
    from flask import request
    items = filter_by(db["statements"].values(),
                      capital_account_id=account["id"],
                      nav_period_id=request.args.get("nav_period_id"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/investors/<investor_id>/capital-accounts/<account_id>/statements/<stmt_id>")
def get_statement_route(investor_id, account_id, stmt_id):
    caller = require_roles(*ALL_READ)
    investor = _load_investor_scoped(caller, investor_id)
    account = get_capital_account(account_id)
    child_of(account, "investor_id", investor["id"])
    statement = get_statement(stmt_id)
    child_of(statement, "capital_account_id", account["id"])
    return success_object(serialize(statement))


@bp.post("/investors/<investor_id>/capital-accounts/<account_id>/statements/<stmt_id>/deliver")
def deliver_statement(investor_id, account_id, stmt_id):
    require_roles("TransferAgent", "FundAdmin")
    investor = get_investor(investor_id)
    account = get_capital_account(account_id)
    child_of(account, "investor_id", investor["id"])
    statement = get_statement(stmt_id)
    child_of(statement, "capital_account_id", account["id"])
    get_body()
    if statement["status"] not in ("DRAFT", "FINALIZED"):
        raise_error(ERR_INVALID_STATE, "statement already delivered")
    statement["status"] = "DELIVERED"
    statement["delivered_at_utc"] = CLOCK.now_iso()
    touch(statement)
    return success_object(serialize(statement))
