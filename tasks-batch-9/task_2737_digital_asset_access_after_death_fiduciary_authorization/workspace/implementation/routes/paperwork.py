"""Fiduciaries, court documents and authority directives
(PRD sections 3.2, 3.3).
"""
from flask import Blueprint, request

from authz import (ALL_ROLES, COURT_REGISTRAR, FIDUCIARY,
                   READ_ROLES_NO_PLATFORM, authenticate,
                   require_action_role, require_fiduciary_estate,
                   require_named_fiduciary_estate, require_role)
from clock import CLOCK
from db import DB, bump, sorted_records, stamp_new
from errors import ApiError
from response import public, single
from routes.common import paged
from services import authority, lookup
from services import estate as estate_svc
from validation import (bad, parse_body, v_date, v_enum, v_id, v_state_code,
                        v_str, v_text, validate)

bp = Blueprint("paperwork", __name__)

APPOINTMENT_TYPES = ("EXECUTOR", "ADMINISTRATOR", "TRUSTEE")
DOC_TYPES = ("DEATH_CERTIFICATE", "LETTERS_OF_AUTHORITY", "COURT_ORDER")
DIRECTIVE_TYPES = ("ONLINE_TOOL", "WILL_PROVISION", "TRUST_PROVISION")
DIRECTIVE_SCOPES = ("NONE", "CATALOG_ONLY", "CATALOG_AND_CONTENT")
ASSET_CATEGORIES = ("FINANCIAL_ACCOUNT", "EMAIL", "CLOUD_STORAGE",
                    "SUBSCRIPTION", "LOYALTY_PROGRAM", "SOCIAL_PROFILE")

DOCUMENT_ACTION_OWNERS = {"VERIFY": COURT_REGISTRAR, "REVOKE": COURT_REGISTRAR}


# ------------------------------------------------------------- Fiduciary

@bp.route("/estates/<estate_id>/fiduciaries", methods=["POST"])
def create_fiduciary(estate_id):
    _, role = authenticate(request)
    require_role(role, (COURT_REGISTRAR,))
    body = validate(parse_body(request), required={
        "full_name": v_str(200),
        "appointment_type": v_enum(APPOINTMENT_TYPES),
        "court_reference": v_str(80),
    })
    estate = lookup.get_estate(estate_id)
    estate_svc.require_open(estate)
    record = {
        "estate_id": estate_id,
        "full_name": body["full_name"],
        "appointment_type": body["appointment_type"],
        "court_reference": body["court_reference"],
        "letters_status": "PENDING",
    }
    stamp_new(record)
    DB.fiduciaries[record["id"]] = record
    return single(public(record), 201)


@bp.route("/fiduciaries/<fiduciary_id>", methods=["GET"])
def read_fiduciary(fiduciary_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_fiduciary(fiduciary_id)), 200)


@bp.route("/fiduciaries", methods=["GET"])
def list_fiduciaries():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.fiduciaries.values(), request.args, {
        "estate_id": "estate_id",
        "letters_status": "letters_status",
        "appointment_type": "appointment_type",
    })


# -------------------------------------------------------------- Document

@bp.route("/estates/<estate_id>/documents", methods=["POST"])
def create_document(estate_id):
    user_id, role = authenticate(request)
    require_role(role, (COURT_REGISTRAR, FIDUCIARY))
    payload = parse_body(request)
    body = validate(payload, required={
        "doc_type": v_enum(DOC_TYPES),
        "reference_number": v_str(60),
        "issued_on": v_date(),
        "jurisdiction": v_state_code(),
    }, optional={"fiduciary_id": v_id()})
    doc_type = body["doc_type"]
    has_fiduciary = "fiduciary_id" in body
    if doc_type == "LETTERS_OF_AUTHORITY" and not has_fiduciary:
        raise bad("fiduciary_id is required for a LETTERS_OF_AUTHORITY document.")
    if doc_type != "LETTERS_OF_AUTHORITY" and has_fiduciary:
        raise bad("fiduciary_id must be absent for a %s document." % doc_type)

    estate = lookup.get_estate(estate_id)
    named = lookup.get_fiduciary(body["fiduciary_id"]) if has_fiduciary else None
    require_fiduciary_estate(user_id, role, estate_id)
    if named is not None:
        require_named_fiduciary_estate(named, estate_id)
    estate_svc.require_open(estate)

    record = {
        "estate_id": estate_id,
        "fiduciary_id": body.get("fiduciary_id"),
        "doc_type": doc_type,
        "reference_number": body["reference_number"],
        "issued_on": body["issued_on"],
        "jurisdiction": body["jurisdiction"],
        "verification_status": "PENDING",
        "verified_by_user_id": None,
        "verified_at": None,
        "revocation_reason": None,
    }
    stamp_new(record)
    DB.documents[record["id"]] = record
    return single(public(record), 201)


@bp.route("/documents/<document_id>", methods=["GET"])
def read_document(document_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_document(document_id)), 200)


@bp.route("/documents", methods=["GET"])
def list_documents():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.documents.values(), request.args, {
        "estate_id": "estate_id",
        "fiduciary_id": "fiduciary_id",
        "doc_type": "doc_type",
        "verification_status": "verification_status",
    })


@bp.route("/documents/<document_id>/transitions", methods=["POST"])
def document_transition(document_id):
    user_id, role = authenticate(request)
    require_role(role, (COURT_REGISTRAR,))
    body = validate(parse_body(request),
                    required={"action": v_enum(("VERIFY", "REVOKE"))},
                    optional={"revocation_reason": v_text()})
    action = body["action"]
    require_action_role(role, action, DOCUMENT_ACTION_OWNERS)

    document = lookup.get_document(document_id)
    estate = DB.estates.get(document["estate_id"])
    estate_svc.require_open(estate)

    status = document["verification_status"]
    if action == "VERIFY":
        if status != "PENDING":
            raise ApiError("ERR_INVALID_DOCUMENT_STATE")
        document["verification_status"] = "VERIFIED"
        document["verified_by_user_id"] = user_id
        document["verified_at"] = CLOCK.iso()
        bump(document)
        if document["doc_type"] == "LETTERS_OF_AUTHORITY":
            fid = DB.fiduciaries.get(document["fiduciary_id"])
            if fid is not None and fid["letters_status"] != "ISSUED":
                fid["letters_status"] = "ISSUED"
                bump(fid)
        estate_svc.recompute(estate)
        return single(public(document), 200)

    # REVOKE
    if status not in ("PENDING", "VERIFIED"):
        raise ApiError("ERR_INVALID_DOCUMENT_STATE")
    was_verified = status == "VERIFIED"
    document["verification_status"] = "REVOKED"
    document["revocation_reason"] = body.get("revocation_reason")
    bump(document)

    if was_verified and document["doc_type"] == "LETTERS_OF_AUTHORITY":
        fid = DB.fiduciaries.get(document["fiduciary_id"])
        if fid is not None and fid["letters_status"] != "REVOKED":
            fid["letters_status"] = "REVOKED"
            bump(fid)
        # hop 2 is conditional on hop 1: it fires only when no fiduciary of the
        # estate still holds ISSUED letters.
        if not estate_svc.has_issued_letters(estate["id"]):
            for grant in sorted_records(lookup.estate_grants(estate["id"])):
                if grant["status"] != "ACTIVE":
                    continue
                grant["status"] = "REVOKED"
                grant["revocation_reason"] = "LETTERS_REVOKED"
                bump(grant)
            # hop 3 walks every account of the estate, across all providers,
            # resetting content_clamp_reason to NONE.
            authority.revoke_asset_access(lookup.estate_assets(estate["id"]), True)
    estate_svc.recompute(estate)
    return single(public(document), 200)


# ----------------------------------------------------- AuthorityDirective

@bp.route("/estates/<estate_id>/authority-directives", methods=["POST"])
def create_directive(estate_id):
    user_id, role = authenticate(request)
    require_role(role, (COURT_REGISTRAR, FIDUCIARY))
    body = validate(parse_body(request), required={
        "directive_type": v_enum(DIRECTIVE_TYPES),
        "scope": v_enum(DIRECTIVE_SCOPES),
        "instrument_reference": v_str(80),
        "executed_on": v_date(),
    }, optional={
        "platform_id": v_id(),
        "asset_category": v_enum(ASSET_CATEGORIES),
    })
    estate = lookup.get_estate(estate_id)
    platform = None
    if "platform_id" in body:
        platform = lookup.get_platform(body["platform_id"])
    require_fiduciary_estate(user_id, role, estate_id)
    estate_svc.require_open(estate)

    directive_type = body["directive_type"]
    if directive_type == "ONLINE_TOOL":
        if platform is None or not platform["supports_online_tool"]:
            raise ApiError("ERR_ONLINE_TOOL_UNSUPPORTED")

    platform_id = body.get("platform_id")
    asset_category = body.get("asset_category")
    record = {
        "estate_id": estate_id,
        "platform_id": platform_id,
        "directive_type": directive_type,
        "scope": body["scope"],
        "asset_category": asset_category,
        "instrument_reference": body["instrument_reference"],
        "executed_on": body["executed_on"],
        "status": "RECORDED",
        "precedence_rank": authority.precedence_rank(directive_type),
    }
    stamp_new(record)
    DB.directives[record["id"]] = record

    for other in sorted_records(lookup.estate_directives(estate_id)):
        if other["id"] == record["id"] or other["status"] != "RECORDED":
            continue
        if (other["directive_type"] == directive_type
                and other["platform_id"] == platform_id
                and other["asset_category"] == asset_category):
            other["status"] = "SUPERSEDED"
            bump(other)
    return single(public(record), 201)


@bp.route("/authority-directives/<directive_id>", methods=["GET"])
def read_directive(directive_id):
    _, role = authenticate(request)
    require_role(role, READ_ROLES_NO_PLATFORM)
    return single(public(lookup.get_directive(directive_id)), 200)


@bp.route("/authority-directives", methods=["GET"])
def list_directives():
    _, role = authenticate(request)
    require_role(role, READ_ROLES_NO_PLATFORM)
    return paged(DB.directives.values(), request.args, {
        "estate_id": "estate_id",
        "platform_id": "platform_id",
        "directive_type": "directive_type",
        "status": "status",
        "asset_category": "asset_category",
    })
