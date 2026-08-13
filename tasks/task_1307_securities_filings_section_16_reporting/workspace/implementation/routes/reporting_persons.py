"""ReportingPerson CRUD + designation lifecycle + short-swing analysis."""
from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_PERSON_INVALID_STATE, ApiError,
)
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import (
    PERSON_FIELDS, serialize, stamp_created, bump_version,
    parse_pagination, paginate, today_stamp, parse_date,
)
from services.calculations import (
    compute_form3_deadline, short_swing_analysis, recompute_open_obligation_count,
)

persons_bp = Blueprint("reporting_persons", __name__)


def _get_person_or_404(person_id):
    p = db.reporting_persons.get(person_id)
    if not p:
        raise ApiError(ERR_NOT_FOUND, f"ReportingPerson {person_id} not found.", 404)
    return p


@persons_bp.route("/reporting-persons", methods=["POST"])
def create_person():
    user_id, role = require_role("ComplianceOfficer")
    body = request.get_json(force=True) or {}

    for f in ["issuer_id", "full_name", "person_cik"]:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    if body["issuer_id"] not in db.issuers:
        raise ApiError(ERR_INVALID_REQUEST, f"issuer_id {body['issuer_id']} not found.", 400)

    person = {
        "issuer_id": body["issuer_id"],
        "full_name": body["full_name"],
        "person_cik": body["person_cik"],
        "is_director": bool(body.get("is_director", False)),
        "is_officer": bool(body.get("is_officer", False)),
        "is_ten_pct_owner": bool(body.get("is_ten_pct_owner", False)),
        "status": "PROPOSED",
        "designation_date": None,
        "exit_date": None,
        "late_filing_count": 0,
        "delinquent_flag": False,
        "open_obligation_count": 0,
    }
    stamp_created(person)
    db.reporting_persons[person["id"]] = person
    return success_object(serialize(person, PERSON_FIELDS), 201)


@persons_bp.route("/reporting-persons", methods=["GET"])
def list_persons():
    get_auth()
    limit, offset = parse_pagination(request.args)
    issuer_id = request.args.get("issuer_id")
    status = request.args.get("status")
    items = sorted(db.reporting_persons.values(), key=lambda x: x["created_at"])
    if issuer_id:
        items = [p for p in items if p["issuer_id"] == issuer_id]
    if status:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(p, PERSON_FIELDS) for p in page], limit, offset, total)


@persons_bp.route("/reporting-persons/<personId>", methods=["GET"])
def get_person(personId):
    get_auth()
    p = _get_person_or_404(personId)
    return success_object(serialize(p, PERSON_FIELDS))


@persons_bp.route("/reporting-persons/<personId>/transitions", methods=["POST"])
def person_transition(personId):
    user_id, role = require_role("ComplianceOfficer")
    person = _get_person_or_404(personId)
    body = request.get_json(force=True) or {}
    action = body.get("action")
    if not action:
        raise ApiError(ERR_INVALID_REQUEST, "action is required.", 400)

    if action == "DESIGNATE":
        if person["status"] != "PROPOSED":
            raise ApiError(ERR_PERSON_INVALID_STATE, "DESIGNATE requires PROPOSED.", 409)
        person["designation_date"] = today_stamp()
        person["status"] = "ACTIVE"
        # Auto-create DRAFT FORM_3
        filing = {
            "issuer_id": person["issuer_id"],
            "reporting_person_id": person["id"],
            "form_type": "FORM_3",
            "amends_filing_id": None,
            "filing_deadline": compute_form3_deadline(person["designation_date"]),
            "is_late": False,
            "status": "DRAFT",
            "prepared_by_user_id": None,
            "submitted_by_user_id": None,
            "submitted_at": None,
            "accepted_at": None,
            "accession_number": None,
            "rejection_reason": None,
        }
        stamp_created(filing)
        db.filings[filing["id"]] = filing
        recompute_open_obligation_count(person["id"])
    elif action == "EXIT":
        if person["status"] != "ACTIVE":
            raise ApiError(ERR_PERSON_INVALID_STATE, "EXIT requires ACTIVE.", 409)
        person["exit_date"] = today_stamp()
        person["status"] = "EXITED"
    elif action == "REINSTATE":
        if person["status"] != "EXITED":
            raise ApiError(ERR_PERSON_INVALID_STATE, "REINSTATE requires EXITED.", 409)
        person["designation_date"] = today_stamp()
        person["exit_date"] = None
        person["status"] = "ACTIVE"
        filing = {
            "issuer_id": person["issuer_id"],
            "reporting_person_id": person["id"],
            "form_type": "FORM_3",
            "amends_filing_id": None,
            "filing_deadline": compute_form3_deadline(person["designation_date"]),
            "is_late": False,
            "status": "DRAFT",
            "prepared_by_user_id": None,
            "submitted_by_user_id": None,
            "submitted_at": None,
            "accepted_at": None,
            "accession_number": None,
            "rejection_reason": None,
        }
        stamp_created(filing)
        db.filings[filing["id"]] = filing
        recompute_open_obligation_count(person["id"])
    else:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown action: {action}", 400)

    bump_version(person)
    return success_object(serialize(person, PERSON_FIELDS))


@persons_bp.route("/reporting-persons/<personId>/short-swing-analysis", methods=["GET"])
def get_short_swing(personId):
    get_auth()
    _get_person_or_404(personId)
    result = short_swing_analysis(personId)
    return success_object(result)
