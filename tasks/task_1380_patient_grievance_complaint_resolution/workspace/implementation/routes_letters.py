"""Routes: response letters (draft, review loop, approve, issue)."""

from flask import Blueprint, g, request

import cascades
import db
import derived
import errors
import middleware
from clock import iso_ms
from helpers import (
    LETTER_BASE_REQUIRED,
    LETTER_SECTIONS,
    check_string,
    get_body,
    paginate,
    parse_pagination,
    require_present,
    serialize_letter,
    sorted_by_creation,
    stamp_new,
    touch,
)
from response import success_list, success_object
from routes_cases import get_case_or_404
from state import CLOCK

bp = Blueprint("letters", __name__)

NON_TERMINAL_LETTER_STATUSES = {"DRAFT", "IN_REVIEW", "RETURNED", "APPROVED"}
OPEN_ESCALATION_STATUSES = {"FILED", "IN_REVIEW", "REVIEWS_COMPLETE"}


def get_letter_or_404(letter_id):
    letter = db.response_letters.get(letter_id)
    if letter is None:
        raise errors.not_found(errors.ERR_LETTER_NOT_FOUND, "ResponseLetter not found")
    return letter


def case_investigation(case_id):
    for inv in db.investigations.values():
        if inv["case_id"] == case_id:
            return inv
    return None


@bp.route("/api/patient-cases/<case_id>/response-letters", methods=["POST"])
def create_letter(case_id):
    middleware.authenticate()
    middleware.require_roles("DepartmentInvestigator")
    body = get_body()
    require_present(body, "sections", "body_summary")
    case = get_case_or_404(case_id)
    # Drafting presupposes the case has reached RESPONSE_DRAFTING (PRD §3.4).
    if case["lifecycle_status"] != "RESPONSE_DRAFTING":
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE,
            409,
            "Drafting a letter requires the case in RESPONSE_DRAFTING",
        )
    # One non-terminal letter per case.
    for letter in db.response_letters.values():
        if (
            letter["case_id"] == case["id"]
            and letter["status"] in NON_TERMINAL_LETTER_STATUSES
        ):
            raise errors.api_error(
                errors.ERR_ACTIVE_LETTER_EXISTS,
                409,
                "Case already has a non-terminal ResponseLetter",
            )
    sections = body.get("sections")
    if not isinstance(sections, list):
        raise errors.invalid_request("sections must be an array")
    for entry in sections:
        if entry not in LETTER_SECTIONS:
            raise errors.invalid_enum(f"sections entry invalid: {entry}")
    body_summary = check_string(body, "body_summary", required=True)
    # A draft following an earlier superseded letter links to the most recent.
    superseded = [
        letter
        for letter in db.response_letters.values()
        if letter["case_id"] == case["id"] and letter["status"] == "SUPERSEDED"
    ]
    supersedes_id = None
    if superseded:
        superseded.sort(key=lambda letter: letter["_seq"])
        supersedes_id = superseded[-1]["id"]
    letter = stamp_new()
    letter.update(
        {
            "case_id": case["id"],
            "supersedes_letter_id": supersedes_id,
            "status": "DRAFT",
            "sections": sections,
            "body_summary": body_summary,
            "drafted_by_id": g.user_id,
            "approved_by_id": None,
            "issued_at": None,
            "return_reason": None,
        }
    )
    db.response_letters[letter["id"]] = letter
    return success_object(serialize_letter(letter), 201)


@bp.route("/api/response-letters", methods=["GET"])
def list_letters():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    supersedes = request.args.get("supersedes_letter_id")
    letters = list(db.response_letters.values())
    if case_id is not None:
        letters = [l for l in letters if l["case_id"] == case_id]
    if status is not None:
        letters = [l for l in letters if l["status"] == status]
    if supersedes is not None:
        letters = [l for l in letters if l["supersedes_letter_id"] == supersedes]
    letters = sorted_by_creation(letters)
    page, total = paginate(letters, limit, offset)
    return success_list([serialize_letter(l) for l in page], limit, offset, total)


@bp.route("/api/response-letters/<letter_id>", methods=["GET"])
def get_letter(letter_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    letter = get_letter_or_404(letter_id)
    return success_object(serialize_letter(letter))


@bp.route("/api/response-letters/<letter_id>/submit-review", methods=["POST"])
def submit_letter_review(letter_id):
    middleware.authenticate()
    middleware.require_roles("DepartmentInvestigator")
    get_body()
    letter = get_letter_or_404(letter_id)
    if letter["status"] not in ("DRAFT", "RETURNED"):
        raise errors.api_error(
            errors.ERR_LETTER_INVALID_STATE, 409, "Letter is not DRAFT or RETURNED"
        )
    case = get_case_or_404(letter["case_id"])
    # Content standard (PRD §3.4): five sections always required; two more
    # whenever requires_qro_cosign or any open/substantiated CARE_CONCERN
    # escalation exists for the case.
    required = set(LETTER_BASE_REQUIRED)
    extended = derived.requires_qro_cosign(case) or any(
        e["case_id"] == case["id"]
        and e["escalation_type"] == "CARE_CONCERN"
        and e["status"] in OPEN_ESCALATION_STATUSES | {"ADJUDICATED_SUBSTANTIATED"}
        for e in db.escalations.values()
    )
    if extended:
        required |= {"RISK_DISCLOSURE", "QAPI_REFERENCE"}
    if not required.issubset(set(letter["sections"])):
        missing = sorted(required - set(letter["sections"]))
        raise errors.api_error(
            errors.ERR_CONTENT_STANDARD_VIOLATION,
            422,
            f"Letter sections missing required entries: {missing}",
        )
    letter["status"] = "IN_REVIEW"
    touch(letter)
    if case["lifecycle_status"] == "RESPONSE_DRAFTING":
        case["lifecycle_status"] = "RESPONSE_REVIEW"
        touch(case)
    return success_object(serialize_letter(letter))


@bp.route("/api/response-letters/<letter_id>/return", methods=["POST"])
def return_letter(letter_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    body = get_body()
    require_present(body, "return_reason")
    letter = get_letter_or_404(letter_id)
    if letter["status"] != "IN_REVIEW":
        raise errors.api_error(
            errors.ERR_LETTER_INVALID_STATE, 409, "Letter is not IN_REVIEW"
        )
    reason = check_string(body, "return_reason", required=True)
    letter["status"] = "RETURNED"
    letter["return_reason"] = reason
    touch(letter)
    case = get_case_or_404(letter["case_id"])
    if case["lifecycle_status"] == "RESPONSE_REVIEW":
        case["lifecycle_status"] = "RESPONSE_DRAFTING"
        touch(case)
    return success_object(serialize_letter(letter))


@bp.route("/api/response-letters/<letter_id>/approve", methods=["POST"])
def approve_letter(letter_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector", "QualityRiskOfficer")
    get_body()
    letter = get_letter_or_404(letter_id)
    # Gates evaluated in order (PRD §3.4): letter state, case state, SoD,
    # QRO co-sign, then the open-escalation gate.
    if letter["status"] != "IN_REVIEW":
        raise errors.api_error(
            errors.ERR_LETTER_INVALID_STATE, 409, "Letter is not IN_REVIEW"
        )
    case = get_case_or_404(letter["case_id"])
    if case["lifecycle_status"] != "RESPONSE_REVIEW":
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE, 409, "Case is not RESPONSE_REVIEW"
        )
    investigation = case_investigation(case["id"])
    if (
        investigation is not None
        and investigation["submitted_by_id"] is not None
        and g.user_id == investigation["submitted_by_id"]
    ):
        raise errors.api_error(
            errors.ERR_SEGREGATION_OF_DUTIES,
            403,
            "Letter approver must differ from the investigation findings submitter",
        )
    if derived.requires_qro_cosign(case) and g.role != "QualityRiskOfficer":
        raise errors.api_error(
            errors.ERR_QRO_COSIGN_REQUIRED,
            403,
            "case.requires_qro_cosign is true; approval must be by QualityRiskOfficer",
        )
    for e in db.escalations.values():
        if e["case_id"] == case["id"] and e["status"] in OPEN_ESCALATION_STATUSES:
            raise errors.api_error(
                errors.ERR_OPEN_ESCALATION_BLOCKS_APPROVAL,
                409,
                "An open escalation for the case blocks letter approval",
            )
    letter["status"] = "APPROVED"
    letter["approved_by_id"] = g.user_id
    touch(letter)
    case["lifecycle_status"] = "PENDING_CLOSURE"
    touch(case)
    return success_object(serialize_letter(letter))


@bp.route("/api/response-letters/<letter_id>/issue", methods=["POST"])
def issue_letter(letter_id):
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    get_body()
    letter = get_letter_or_404(letter_id)
    if letter["status"] != "APPROVED":
        raise errors.api_error(
            errors.ERR_LETTER_INVALID_STATE, 409, "Letter is not APPROVED"
        )
    case = get_case_or_404(letter["case_id"])
    if case["lifecycle_status"] != "PENDING_CLOSURE":
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE, 409, "Case is not PENDING_CLOSURE"
        )
    now = CLOCK.now()
    letter["status"] = "ISSUED"
    letter["issued_at"] = iso_ms(now)
    touch(letter)
    # Issuance closes the case; closure_note is copied from the letter body.
    cascades.close_case(case, now, letter["body_summary"])
    return success_object(serialize_letter(letter))
