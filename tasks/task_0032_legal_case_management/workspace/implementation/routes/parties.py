"""Party endpoints (multi-role binding, identity verification)."""

import re

from flask import Blueprint, request

import db
import errors
import helpers
import response
import serializers
from middleware import auth_required


bp = Blueprint("parties", __name__)


VALID_PARTY_ROLES = {"PLAINTIFF", "DEFENDANT", "THIRD_PARTY", "WITNESS"}
VALID_ACCESS_LEVELS = {"STANDARD", "RESTRICTED", "NONE"}

# Simple RFC5322-flavoured email regex (strict enough for tests; not full RFC).
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _ensure_not_archived(case):
    if case["status"] == "ARCHIVED":
        errors.raise_error(errors.ERR_CASE_ARCHIVED, "Case is archived.")


@bp.route("/cases/<cid>/parties", methods=["POST"])
@auth_required("IntakeClerk", "PartnerLawyer", "SeniorLawyer")
def add_party(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    _ensure_not_archived(case)

    body = helpers.get_json_body()
    party_role = helpers.require_enum(body, "party_role", VALID_PARTY_ROLES)
    full_name = helpers.require_str(body, "full_name", min_len=1)
    id_document_number = helpers.require_str(body, "id_document_number", min_len=1)
    contact_email = helpers.require_str(body, "contact_email", min_len=1)
    contact_phone = helpers.require_str(body, "contact_phone", min_len=7, max_len=20)

    if not _EMAIL_RE.match(contact_email):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "contact_email is not a valid email.")

    agency_lawyer_id = body.get("agency_lawyer_id")
    if agency_lawyer_id is not None:
        if not isinstance(agency_lawyer_id, str):
            errors.raise_error(errors.ERR_VALIDATION_FAILED, "agency_lawyer_id must be a string.")
        if agency_lawyer_id not in db.lawyers:
            errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Lawyer {agency_lawyer_id} not found.")

    access_level = body.get("access_level", "STANDARD") or "STANDARD"
    if access_level not in VALID_ACCESS_LEVELS:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "Invalid access_level.")

    pid = db.new_id()
    common = helpers.common_create()
    party = {
        "id": pid,
        "case_id": cid,
        "party_role": party_role,
        "full_name": full_name,
        "id_document_number": id_document_number,
        "identity_verified": False,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "agency_lawyer_id": agency_lawyer_id,
        "access_level": access_level,
        **common,
    }
    db.parties[pid] = party
    return response.created(serializers.party_dict(party))


@bp.route("/parties/<pid>/verify-identity", methods=["POST"])
@auth_required("IntakeClerk", "PartnerLawyer")
def verify_party(pid):
    party = db.parties.get(pid)
    if party is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Party {pid} not found.")
    case = db.cases.get(party["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(party, body.get("version"))

    party["identity_verified"] = True
    helpers.bump(party)
    return response.ok(serializers.party_dict(party))


@bp.route("/cases/<cid>/parties", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer", "IntakeClerk")
def list_parties(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    limit, offset = helpers.parse_pagination()

    items = [p for p in db.parties.values() if p["case_id"] == cid]
    pr = request.args.get("party_role")
    if pr:
        items = [p for p in items if p["party_role"] == pr]
    items.sort(key=lambda p: p["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok(
        [serializers.party_dict(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )
