"""Subgrantee capability endpoints (PRD section 3.4)."""

from flask import Blueprint, request

from db import db, new_record, serialize
from errors import ApiError
from middleware import (authenticate, get_bool, get_cents, get_int, get_number,
                        get_str, json_body, pagination)
from records import assign, touch
from response import object_response
from routes.listing import paginated
from services import calculations as calc
from services import domain

bp = Blueprint("subgrantees", __name__)

READ_ROLES = ("ProgramAdmin", "CapabilityReviewer", "ScoringOfficer", "AuditOfficer", "Subgrantee")
LIST_ROLES = ("ProgramAdmin", "CapabilityReviewer", "ScoringOfficer", "AuditOfficer")
REGISTRATION_PROGRAM_STATES = ("CHALLENGE_OPEN", "CHALLENGE_CLOSED", "SCORING")
REVIEW_PROGRAM_STATES = ("DRAFT", "CHALLENGE_OPEN", "CHALLENGE_CLOSED", "SCORING")


@bp.post("/broadband/subgrantees")
def create_subgrantee():
    authenticate("ProgramAdmin")
    body = json_body()

    program_id = get_str(body, "program_id")
    legal_name = get_str(body, "legal_name")
    ein = get_str(body, "ein")
    net_assets = get_cents(body, "net_assets_cents")
    requested = get_int(body, "requested_amount_cents", minimum=1)
    personnel = get_int(body, "key_personnel_count", minimum=0)
    prior_award = get_bool(body, "has_prior_federal_award", required=False, default=False)

    program = domain.require_program(program_id)                      # priority 20
    if program["program_state"] not in REGISTRATION_PROGRAM_STATES:    # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")

    subgrantee = new_record({
        "program_id": program["id"],
        "legal_name": legal_name,
        "ein": ein,
        "net_assets_cents": net_assets,
        "requested_amount_cents": requested,
        "key_personnel_count": personnel,
        "has_prior_federal_award": prior_award,
        "audited_net_assets_cents": None,
        "withdrawn_personnel_count": 0,
        "technical_raw_score": None,
        "review_variant": "INITIAL",
        "technical_component": None,
        "financial_component": None,
        "managerial_component": None,
        "capability_index": None,
        "capability_state": "REGISTERED",
        "capability_reviewer_user_id": None,
        "remediation_count": 0,
        "open_noncompliance_count": 0,
    })
    db.subgrantees[subgrantee["id"]] = subgrantee
    return object_response(serialize(subgrantee), 201)


@bp.get("/broadband/subgrantees/<subgrantee_id>")
def get_subgrantee(subgrantee_id):
    authenticate(*READ_ROLES)
    subgrantee = domain.require_subgrantee(subgrantee_id)
    return object_response(serialize(subgrantee))


@bp.get("/broadband/subgrantees")
def list_subgrantees():
    authenticate(*LIST_ROLES)
    limit, offset = pagination()
    rows = list(db.subgrantees.values())
    for field in ("program_id", "capability_state"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    return paginated(rows, limit, offset)


@bp.post("/broadband/subgrantees/<subgrantee_id>/begin-capability-review")
def begin_capability_review(subgrantee_id):
    user_id, _role = authenticate("CapabilityReviewer")
    subgrantee = domain.require_subgrantee(subgrantee_id)              # priority 23
    program = db.programs.get(subgrantee["program_id"])
    if program is not None and program["program_state"] not in REVIEW_PROGRAM_STATES:
        raise ApiError("ERR_PROGRAM_STATE_INVALID")                    # priority 40
    if subgrantee["capability_state"] not in ("REGISTERED", "REMEDIATION_REQUIRED"):
        raise ApiError("ERR_SUBGRANTEE_STATE_INVALID")                 # priority 42

    variant = "REMEDIATION" if int(subgrantee["remediation_count"]) > 0 else "INITIAL"
    assign(subgrantee, "capability_state", "UNDER_CAPABILITY_REVIEW")
    assign(subgrantee, "capability_reviewer_user_id", user_id)
    assign(subgrantee, "review_variant", variant)
    touch(subgrantee)
    return object_response(serialize(subgrantee))


@bp.post("/broadband/subgrantees/<subgrantee_id>/record-capability-determination")
def record_capability_determination(subgrantee_id):
    user_id, _role = authenticate("CapabilityReviewer")
    body = json_body()
    raw_score = get_number(body, "technical_raw_score", minimum=0)
    get_str(body, "determination_note", required=False)

    subgrantee = domain.require_subgrantee(subgrantee_id)              # priority 23
    program = db.programs.get(subgrantee["program_id"])
    if program is not None and program["program_state"] not in REVIEW_PROGRAM_STATES:
        raise ApiError("ERR_PROGRAM_STATE_INVALID")                    # priority 40
    if subgrantee["capability_state"] != "UNDER_CAPABILITY_REVIEW":    # priority 42
        raise ApiError("ERR_SUBGRANTEE_STATE_INVALID")
    # "The same reviewer who opened the review — the check compares `X-User-ID`
    # to `capability_reviewer_user_id`".  §2.1 restricts ERR_NOT_RESOURCE_OWNER
    # (priority 30) to three enumerated situations, none of which is this one,
    # so this check cannot pre-empt the state ladder above; it only has meaning
    # once a review has actually been opened.
    if subgrantee.get("capability_reviewer_user_id") != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the reviewer that opened the review may record its determination.")

    assign(subgrantee, "technical_raw_score", raw_score)
    variant = subgrantee.get("review_variant") or "INITIAL"
    technical, financial, managerial, index = calc.capability_components(subgrantee, variant)
    outcome = calc.capability_outcome(index, technical, financial, variant)

    assign(subgrantee, "technical_component", float(technical))
    assign(subgrantee, "financial_component", float(financial))
    assign(subgrantee, "managerial_component", float(managerial))
    assign(subgrantee, "capability_index", float(index))
    assign(subgrantee, "capability_state", outcome)
    touch(subgrantee)

    if outcome == "DISQUALIFIED":
        for application in db.applications.values():
            if application["subgrantee_id"] != subgrantee["id"]:
                continue
            if application["application_state"] in ("DRAFT", "SUBMITTED", "RETURNED_FOR_CURE"):
                assign(application, "application_state", "NOT_SELECTED")
                touch(application)
    return object_response(serialize(subgrantee))


@bp.post("/broadband/subgrantees/<subgrantee_id>/submit-remediation")
def submit_remediation(subgrantee_id):
    user_id, role = authenticate("Subgrantee", "ProgramAdmin")
    body = json_body()
    audited = get_cents(body, "audited_net_assets_cents")
    withdrawn = get_int(body, "withdrawn_personnel_count", minimum=0)

    subgrantee = domain.require_subgrantee(subgrantee_id)              # priority 23
    program = db.programs.get(subgrantee["program_id"])
    if role == "Subgrantee" and user_id != subgrantee["id"]:           # priority 30
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if program is not None and program["program_state"] not in REVIEW_PROGRAM_STATES:
        raise ApiError("ERR_PROGRAM_STATE_INVALID")                    # priority 40
    if subgrantee["capability_state"] != "REMEDIATION_REQUIRED":       # priority 42
        raise ApiError("ERR_SUBGRANTEE_STATE_INVALID")
    if int(subgrantee["remediation_count"]) >= 1:                     # priority 79
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED")

    assign(subgrantee, "audited_net_assets_cents", audited)
    assign(subgrantee, "withdrawn_personnel_count", withdrawn)
    assign(subgrantee, "capability_state", "UNDER_CAPABILITY_REVIEW")
    assign(subgrantee, "remediation_count", int(subgrantee["remediation_count"]) + 1)
    assign(subgrantee, "review_variant", "REMEDIATION")
    touch(subgrantee)
    return object_response(serialize(subgrantee))
