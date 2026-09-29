"""State registration filings, their documents and their extension requests.

PRD 3.3 (opening a filing), 3.4 (certification and adjudication), 3.5 (extensions).
"""
from flask import Blueprint, g, request

import clock
import response
import validate
from auth import endpoint, require_certifying_officer_of
from dates import fmt, parse_iso
from db import db, public, sorted_rows, stamp_new, touch_once
from errors import ApiError
from services import calc
from services.cascades import (LIVE_ENFORCEMENT_STATUSES, apply_review_approve,
                               supersede_extension_history)
from services.derive import recompute_organization

bp = Blueprint("registrations", __name__)

REGISTRATION_TYPES = ("INITIAL", "RENEWAL")
DOC_TYPES = ("GOVERNING_DOCUMENT", "IRS_DETERMINATION_LETTER", "FINANCIAL_STATEMENT",
             "OFFICER_DISCLOSURE_FORM", "REVIEW_REPORT", "AUDIT_OPINION")
EXTENSION_BASES = ("IRS_990_EXTENSION", "STATE_HARDSHIP")

# Statuses whose coverage intervals compete for the state's docket.
COVERAGE_COMPETING = ("SUBMITTED", "REGISTERED", "DELINQUENT", "CEASED")
# Only EXPIRED and WITHDRAWN filings free the (organization, state, fiscal_year) slot.
NON_TERMINAL_FOR_DOCKET = ("DRAFT", "SUBMITTED", "DEFICIENT", "REGISTERED", "DELINQUENT",
                           "CEASED")
SUPERSEDE_TARGET_STATUSES = ("REGISTERED", "DELINQUENT")
GRANTABLE_FILING_STATUSES = ("DRAFT", "SUBMITTED", "DEFICIENT", "REGISTERED")


def _check_supersede_target(organization_id, state_code, target_id):
    """Ladder rung 20 -- same organization, same state, REGISTERED or DELINQUENT."""
    target = db.state_registrations.get(target_id)
    if (target is None
            or target["organization_id"] != organization_id
            or target["state_code"] != state_code
            or target["status"] not in SUPERSEDE_TARGET_STATUSES):
        raise ApiError("ERR_SUPERSEDE_TARGET_INVALID")
    return target


def _check_statement_current(statement, organization_id):
    """Ladder rung 21 -- the supporting statement is CURRENT and belongs to the charity."""
    if statement["statement_status"] != "CURRENT" or statement["organization_id"] != organization_id:
        raise ApiError("ERR_FINANCIAL_STATEMENT_SUPERSEDED")


def _check_coverage_overlap(organization_id, state_code, start, end, exclude_id=None):
    """Ladder rung 22 -- half-open intervals; abutting years are consecutive, not conflicting."""
    for other in db.state_registrations.values():
        if other["id"] == exclude_id:
            continue
        if other["organization_id"] != organization_id or other["state_code"] != state_code:
            continue
        if other["status"] not in COVERAGE_COMPETING:
            continue
        other_start = parse_iso(other["coverage_start"])
        other_end = parse_iso(other["coverage_end"])
        if start < other_end and other_start < end:
            raise ApiError("ERR_COVERAGE_PERIOD_OVERLAP")


def _required_doc_types(registration):
    """The derived required document set (PRD 3.4)."""
    required = ["GOVERNING_DOCUMENT", "FINANCIAL_STATEMENT"]
    requirement = registration["required_financial_attestation"]
    if requirement == "REVIEW":
        required.append("REVIEW_REPORT")
    elif requirement == "AUDIT":
        required.append("AUDIT_OPINION")
    return required


def _documents_of(registration_id):
    return sorted_rows([d for d in db.registration_documents.values()
                        if d["registration_id"] == registration_id])


@bp.post("/state-registrations")
@endpoint(["ComplianceOfficer"])
def create_registration():
    body = validate.json_body()
    organization_id = validate.req_string(body, "organization_id")
    state_code = validate.req_state_code(body, "state_code")
    registration_type = validate.req_enum(body, "registration_type", REGISTRATION_TYPES)
    fiscal_year = validate.req_int(body, "fiscal_year", minimum=2000, maximum=2100)
    coverage_start = validate.req_datetime(body, "coverage_start")
    coverage_end = validate.req_datetime(body, "coverage_end")
    financial_statement_id = validate.req_string(body, "financial_statement_id")
    supersedes_registration_id = validate.opt_string(body, "supersedes_registration_id",
                                                     default=None, allow_blank=False)
    if not (coverage_end > coverage_start):
        raise ApiError("ERR_INVALID_REQUEST",
                       "coverage_end must be strictly after coverage_start.")
    if registration_type == "INITIAL" and supersedes_registration_id is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "supersedes_registration_id must be null on an INITIAL filing.")

    # Ladder rung 5 -- foreign keys in the order fixed by PRD 2.9.
    organization = validate.find_organization(organization_id)
    profile = validate.find_state_profile(state_code)
    statement = validate.find_financial_statement(financial_statement_id)
    if supersedes_registration_id is not None:
        validate.find_registration(supersedes_registration_id)

    # Ladder rung 14 -- solicitation not halted.
    if organization["solicitation_posture"] == "HALTED":
        raise ApiError("ERR_SOLICITATION_HALTED")
    # Ladder rung 18 -- the state requires registration at all.
    if not profile["registration_required"]:
        raise ApiError("ERR_STATE_REGISTRATION_NOT_REQUIRED")
    # Ladder rung 20.
    if supersedes_registration_id is not None:
        _check_supersede_target(organization_id, state_code, supersedes_registration_id)
    # Ladder rung 21.
    _check_statement_current(statement, organization_id)
    # Ladder rung 22.
    _check_coverage_overlap(organization_id, state_code, coverage_start, coverage_end)
    # Ladder rung 27 -- at most one non-terminal filing per organization/state/year.
    for other in db.state_registrations.values():
        if (other["organization_id"] == organization_id
                and other["state_code"] == state_code
                and other["fiscal_year"] == fiscal_year
                and other["status"] in NON_TERMINAL_FOR_DOCKET):
            raise ApiError("ERR_DUPLICATE_STATE_REGISTRATION")

    registration = {
        "organization_id": organization_id,
        "state_code": state_code,
        "registration_type": registration_type,
        "fiscal_year": fiscal_year,
        "coverage_start": fmt(coverage_start),
        "coverage_end": fmt(coverage_end),
        "financial_statement_id": financial_statement_id,
        "supersedes_registration_id": supersedes_registration_id,
        "certified_by_officer_id": None,
        "status": "DRAFT",
        "renewal_due_date": None,
        "extended_due_date": None,
        "effective_due_date": None,
        "required_financial_attestation": "NONE",
        "filing_fee_cents": 0,
        "deficiency_round_count": 0,
        "deficiency_reasons": [],
        "submitted_at": None,
        "registered_at": None,
    }
    stamp_new(registration)
    calc.recompute_deadlines(registration)
    calc.recompute_attestation(registration)
    calc.recompute_filing_fee(registration)
    db.state_registrations[registration["id"]] = registration
    return response.created(public(registration))


@bp.get("/state-registrations")
@endpoint(["ComplianceOfficer", "CertifyingOfficer", "StateRegulator", "SystemAdmin"])
def list_registrations():
    rows = list(db.state_registrations.values())
    for field in ("organization_id", "state_code", "status", "financial_statement_id",
                  "supersedes_registration_id", "certified_by_officer_id"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    fiscal_year = response.query_int("fiscal_year")
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/state-registrations/<registration_id>")
@endpoint(["ComplianceOfficer", "CertifyingOfficer", "StateRegulator", "SystemAdmin"])
def read_registration(registration_id):
    return response.ok(public(validate.find_registration(registration_id)))


@bp.post("/state-registrations/<registration_id>/submit")
@endpoint(["CertifyingOfficer"])
def submit_registration(registration_id):
    """Certification is the one operation reserved for a certifying officer personally."""
    body = validate.json_body()
    validate.opt_string(body, "certification_note", default=None)

    registration = validate.find_registration(registration_id)
    organization = db.organizations[registration["organization_id"]]

    # Ladder rung 6 -- an officer of THIS organization with is_certifying_officer true.
    officer = require_certifying_officer_of(registration["organization_id"])
    # Ladder rung 9.
    if registration["status"] not in ("DRAFT", "DEFICIENT"):
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")
    # Ladder rung 14.
    if organization["solicitation_posture"] == "HALTED":
        raise ApiError("ERR_SOLICITATION_HALTED")
    # Ladder rung 16 -- the certifier may not have prepared any document inside the packet.
    documents = _documents_of(registration_id)
    for document in documents:
        if document["prepared_by_officer_id"] == officer["id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Ladder rung 17 -- every officer disclosure of the organization is COMPLETE.
    for disclosure in db.officer_disclosures.values():
        if (disclosure["organization_id"] == registration["organization_id"]
                and disclosure["disclosure_status"] != "COMPLETE"):
            raise ApiError("ERR_OFFICER_DISCLOSURE_INCOMPLETE")
    # Ladder rung 18 -- the state profile still exists and still requires registration.
    profile = validate.find_state_profile(registration["state_code"])
    if not profile["registration_required"]:
        raise ApiError("ERR_STATE_REGISTRATION_NOT_REQUIRED")
    # Ladder rung 21.
    statement = db.financial_statements[registration["financial_statement_id"]]
    _check_statement_current(statement, registration["organization_id"])
    # Ladder rung 29 -- the required document set is complete.
    attached = {d["doc_type"] for d in documents}
    for doc_type in _required_doc_types(registration):
        if doc_type not in attached:
            raise ApiError("ERR_REQUIRED_DOCUMENT_MISSING")
    # Ladder rung 34 -- the statement's assurance level covers the requirement.
    if (calc.ASSURANCE_RANK[statement["assurance_level"]]
            < calc.ASSURANCE_RANK[registration["required_financial_attestation"]]):
        raise ApiError("ERR_ASSURANCE_LEVEL_INSUFFICIENT")

    was_deficient = registration["status"] == "DEFICIENT"
    registration["status"] = "SUBMITTED"
    registration["submitted_at"] = clock.now_iso()
    registration["certified_by_officer_id"] = officer["id"]
    calc.recompute_filing_fee(registration)
    calc.recompute_attestation(registration)
    if was_deficient:
        # The revision loop closes; deficiency_round_count deliberately survives.
        registration["deficiency_reasons"] = []
    touch_once(registration, "state_registration")
    return response.ok(public(registration))


@bp.post("/state-registrations/<registration_id>/review")
@endpoint(["StateRegulator"])
def review_registration(registration_id):
    """APPROVE and DEFICIENT have entirely disjoint effects."""
    body = validate.json_body()
    decision = validate.req_enum(body, "decision", ("APPROVE", "DEFICIENT"))
    deficiency_reasons = None
    if decision == "DEFICIENT":
        deficiency_reasons = validate.req_array(body, "deficiency_reasons", non_empty=True)

    registration = validate.find_registration(registration_id)

    # Ladder rung 9.
    if registration["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")

    if decision == "APPROVE":
        # Ladder rung 20 -- the supersede target is re-verified at approval time.
        if registration["supersedes_registration_id"]:
            _check_supersede_target(registration["organization_id"],
                                    registration["state_code"],
                                    registration["supersedes_registration_id"])
        # Ladder rung 22 -- a competing filing may have been approved in the interim.
        _check_coverage_overlap(registration["organization_id"], registration["state_code"],
                                parse_iso(registration["coverage_start"]),
                                parse_iso(registration["coverage_end"]),
                                exclude_id=registration["id"])
        apply_review_approve(registration)
    else:
        registration["status"] = "DEFICIENT"
        registration["deficiency_reasons"] = deficiency_reasons
        registration["deficiency_round_count"] += 1
        for document in _documents_of(registration_id):
            document["review_status"] = "REJECTED"
            touch_once(document, "registration_document")
        touch_once(registration, "state_registration")

    return response.ok(public(registration))


@bp.post("/state-registrations/<registration_id>/withdraw")
@endpoint(["ComplianceOfficer"])
def withdraw_registration(registration_id):
    """The compensating action for approval (registered_state_count_conservation)."""
    body = validate.json_body()
    validate.req_string(body, "withdraw_reason")

    registration = validate.find_registration(registration_id)

    # Ladder rung 9 -- withdrawal is available from exactly two statuses.
    if registration["status"] not in ("DRAFT", "REGISTERED"):
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")
    # A withdrawal is blocked while any enforcement action against the filing is live.
    for action in db.enforcement_actions.values():
        if (action["registration_id"] == registration_id
                and action["status"] in LIVE_ENFORCEMENT_STATUSES):
            raise ApiError(
                "ERR_INVALID_REGISTRATION_STATE",
                "A filing with a live enforcement action may not be withdrawn.",
            )

    was_registered = registration["status"] == "REGISTERED"
    registration["status"] = "WITHDRAWN"
    touch_once(registration, "state_registration")
    if was_registered:
        # A draft was never counted, so only this variant moves the counters.
        recompute_organization(db.organizations[registration["organization_id"]])
    return response.ok(public(registration))


@bp.get("/state-registrations/<registration_id>/extension-requests")
@endpoint(["ComplianceOfficer", "StateRegulator", "SystemAdmin"])
def list_registration_extensions(registration_id):
    validate.find_registration(registration_id)
    rows = [e for e in db.extension_requests.values()
            if e["registration_id"] == registration_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.post("/registration-documents")
@endpoint(["ComplianceOfficer"])
def create_registration_document():
    """prepared_by_officer_id is the input to the segregation-of-duties rule."""
    body = validate.json_body()
    registration_id = validate.req_string(body, "registration_id")
    doc_type = validate.req_enum(body, "doc_type", DOC_TYPES)
    prepared_by_officer_id = validate.req_string(body, "prepared_by_officer_id")
    page_count = validate.req_int(body, "page_count", minimum=1)

    registration = validate.find_registration(registration_id)
    validate.find_officer(prepared_by_officer_id)

    # Ladder rung 9 -- documents attach to a DRAFT or DEFICIENT filing only.
    if registration["status"] not in ("DRAFT", "DEFICIENT"):
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")

    document = {
        "registration_id": registration_id,
        "doc_type": doc_type,
        "prepared_by_officer_id": prepared_by_officer_id,
        "page_count": page_count,
        "review_status": "ATTACHED",
    }
    stamp_new(document)
    db.registration_documents[document["id"]] = document
    return response.created(public(document))


@bp.get("/registration-documents")
@endpoint(["ComplianceOfficer", "CertifyingOfficer", "StateRegulator", "SystemAdmin"])
def list_registration_documents():
    rows = list(db.registration_documents.values())
    for field in ("registration_id", "doc_type", "review_status", "prepared_by_officer_id"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/registration-documents/<document_id>")
@endpoint(["ComplianceOfficer", "CertifyingOfficer", "StateRegulator", "SystemAdmin"])
def read_registration_document(document_id):
    return response.ok(public(validate.find_registration_document(document_id)))


@bp.post("/extension-requests")
@endpoint(["ComplianceOfficer"])
def create_extension_request():
    """Guarded by the registration-version OCC rule, because the create can
    silently discard an already-granted extension and reset the deadline."""
    body = validate.json_body()
    registration_id = validate.req_string(body, "registration_id")
    basis = validate.req_enum(body, "basis", EXTENSION_BASES)
    requested_days = validate.req_int(body, "requested_days", minimum=1)
    expected_registration_version = validate.req_int(body, "expected_registration_version")

    registration = validate.find_registration(registration_id)

    # Ladder rung 7 -- the supersede OCC guard.
    if expected_registration_version != registration["version"]:
        raise ApiError("ERR_STALE_REGISTRATION_VERSION")

    profile = validate.find_state_profile(registration["state_code"])
    # Ladder rung 30 -- the state entertains extensions and grants at least one day.
    if not profile["extension_allowed"] or profile["extension_max_days"] < 1:
        raise ApiError("ERR_EXTENSION_NOT_ALLOWED")
    # Ladder rung 31 -- a charity already carrying a delinquent filing may not ask.
    organization = db.organizations[registration["organization_id"]]
    if organization["filing_posture"] != "CURRENT":
        raise ApiError("ERR_FILING_POSTURE_DELINQUENT")

    # Creating a request supersedes the filing's whole extension history.
    supersede_extension_history(registration)

    extension = {
        "registration_id": registration_id,
        "basis": basis,
        "requested_days": requested_days,
        "status": "PENDING",
        "granted_days": 0,
        "decided_at": None,
    }
    stamp_new(extension)
    db.extension_requests[extension["id"]] = extension
    return response.created(public(extension))


@bp.post("/extension-requests/<extension_request_id>/decide")
@endpoint(["StateRegulator"])
def decide_extension_request(extension_request_id):
    body = validate.json_body()
    decision = validate.req_enum(body, "decision", ("GRANT", "DENY"))

    extension = validate.find_extension_request(extension_request_id)

    # Ladder rung 13 -- GRANTED, DENIED and SUPERSEDED are all terminal.
    if extension["status"] != "PENDING":
        raise ApiError("ERR_EXTENSION_ALREADY_DECIDED")

    registration = db.state_registrations[extension["registration_id"]]

    if decision == "GRANT":
        # A filing already expired, delinquent, ceased or withdrawn is past extending.
        if registration["status"] not in GRANTABLE_FILING_STATUSES:
            raise ApiError("ERR_INVALID_REGISTRATION_STATE")
        profile = validate.find_state_profile(registration["state_code"])
        # Ladder rung 30 -- repeated here, so a corrected configuration cannot slip through.
        if not profile["extension_allowed"] or profile["extension_max_days"] < 1:
            raise ApiError("ERR_EXTENSION_NOT_ALLOWED")

        extension["granted_days"] = calc.extension_grant_length(
            extension["basis"], extension["requested_days"], profile)
        extension["status"] = "GRANTED"
        extension["decided_at"] = clock.now_iso()
        touch_once(extension, "extension_request")
        calc.recompute_deadlines(registration)
        touch_once(registration, "state_registration")
    else:
        # A denial never disturbs a deadline, extended or not.
        extension["status"] = "DENIED"
        extension["decided_at"] = clock.now_iso()
        touch_once(extension, "extension_request")

    return response.ok(public(extension))
