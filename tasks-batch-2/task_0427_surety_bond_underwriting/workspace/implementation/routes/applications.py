"""BondApplication endpoints (PRD §3.3): create, submit (quote), the underwriting
fork (approve/refer/decline), with indemnity, referral, single-limit, and
program-suspended gates."""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_application
from services.calculations import premium_rating
from services.domain import touch
from helpers import (
    get_body, require_str, require_int, require_enum,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("applications", __name__)

ROLES = ("Underwriter", "SeniorUnderwriter")
BOND_TYPES = {"BID", "PERFORMANCE", "PAYMENT", "LICENSE_PERMIT", "FIDELITY"}
DECLINE_REASONS = {"OBLIGEE_INELIGIBLE", "CREDIT", "CAPACITY", "OTHER"}


@bp.route("/surety/applications", methods=["POST"])
@require_roles(*ROLES)
def create_application():
    body = get_body()
    principal_id = require_str(body, "principal_id")
    program_id = require_str(body, "program_id")
    # Existence checked left-to-right (PRD §2.11) before body-shape validation.
    if db.principals.get(principal_id) is None:
        raise errors.not_found("Principal not found")
    if db.programs.get(program_id) is None:
        raise errors.not_found("Program not found")
    bond_type = require_enum(body, "bond_type", BOND_TYPES)
    requested_penal_sum_cents = require_int(body, "requested_penal_sum_cents")
    term_months = require_int(body, "term_months")

    ts = now_ts()
    aid = new_id()
    record = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "principal_id": principal_id,
        "program_id": program_id,
        "bond_type": bond_type,
        "requested_penal_sum_cents": requested_penal_sum_cents,
        "term_months": term_months,
        "quoted_premium_rate_bps": None,
        "quoted_premium_cents": None,
        "status": "DRAFT",
        "decline_reason": None,
    }
    db.applications[aid] = record
    return success(serialize_application(record), status=201)


@bp.route("/surety/applications/<aid>", methods=["GET"])
@require_roles(*ROLES)
def get_application(aid):
    record = db.applications.get(aid)
    if record is None:
        raise errors.not_found("Application not found")
    return success(serialize_application(record), status=200)


@bp.route("/surety/applications", methods=["GET"])
@require_roles(*ROLES)
def list_applications():
    limit, offset = parse_pagination()
    items = list(db.applications.values())
    principal_id = request.args.get("principal_id")
    program_id = request.args.get("program_id")
    if principal_id is not None:
        items = [a for a in items if a["principal_id"] == principal_id]
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_application(a) for a in page], limit, offset, total)


@bp.route("/surety/applications/<aid>/submit", methods=["POST"])
@require_roles(*ROLES)
def submit_application(aid):
    record = db.applications.get(aid)
    if record is None:
        raise errors.not_found("Application not found")
    # State (priority 5) first.
    if record["status"] != "DRAFT":
        raise errors.invalid_state("Application is not DRAFT")
    # Business gates (PRD §3.3): indemnity on file, then program OPEN.
    principal = db.principals.get(record["principal_id"])
    if principal is None or not principal["indemnity_on_file"]:
        raise errors.ApiError(errors.ERR_INDEMNITY_REQUIRED, 409,
                              "No EXECUTED indemnity agreement on file for the principal")
    program = db.programs.get(record["program_id"])
    if program is None or program["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_PROGRAM_SUSPENDED, 409,
                              "Program is SUSPENDED")

    rate_bps, premium_cents = premium_rating(
        principal["credit_tier"], record["bond_type"],
        record["requested_penal_sum_cents"], program["single_limit_cents"])
    record["quoted_premium_rate_bps"] = rate_bps
    record["quoted_premium_cents"] = premium_cents
    record["status"] = "SUBMITTED"
    touch(record)
    return success(serialize_application(record), status=200)


@bp.route("/surety/applications/<aid>/approve", methods=["POST"])
@require_roles(*ROLES)
def approve_application(aid):
    record = db.applications.get(aid)
    if record is None:
        raise errors.not_found("Application not found")

    program = db.programs.get(record["program_id"])
    status = record["status"]

    if status == "SUBMITTED":
        # Front-line approval path (Underwriter or Senior may act).
        # Referral threshold: a request at/above threshold cannot approve directly.
        if record["requested_penal_sum_cents"] >= program["referral_threshold_cents"]:
            raise errors.ApiError(errors.ERR_REFERRAL_REQUIRED, 409,
                                  "Application must be referred before approval")
        if record["requested_penal_sum_cents"] > program["single_limit_cents"]:
            raise errors.ApiError(errors.ERR_SINGLE_LIMIT_EXCEEDED, 409,
                                  "Requested penal sum exceeds single limit")
    elif status == "REFERRED":
        # Referred approval is senior-only (segregation of duties).
        if g.user_role != "SeniorUnderwriter":
            raise errors.forbidden("Only a SeniorUnderwriter may approve a REFERRED application")
        if record["requested_penal_sum_cents"] > program["single_limit_cents"]:
            raise errors.ApiError(errors.ERR_SINGLE_LIMIT_EXCEEDED, 409,
                                  "Requested penal sum exceeds single limit")
    else:
        raise errors.invalid_state("Application is not in an approvable state")

    record["status"] = "APPROVED"
    touch(record)
    return success(serialize_application(record), status=200)


@bp.route("/surety/applications/<aid>/refer", methods=["POST"])
@require_roles(*ROLES)
def refer_application(aid):
    record = db.applications.get(aid)
    if record is None:
        raise errors.not_found("Application not found")
    if record["status"] != "SUBMITTED":
        raise errors.invalid_state("Application is not SUBMITTED")
    record["status"] = "REFERRED"
    touch(record)
    return success(serialize_application(record), status=200)


@bp.route("/surety/applications/<aid>/decline", methods=["POST"])
@require_roles(*ROLES)
def decline_application(aid):
    body = get_body()
    record = db.applications.get(aid)
    if record is None:
        raise errors.not_found("Application not found")
    decline_reason = require_enum(body, "decline_reason", DECLINE_REASONS)
    if record["status"] not in ("SUBMITTED", "REFERRED"):
        raise errors.invalid_state("Application is not SUBMITTED or REFERRED")
    record["status"] = "DECLINED"
    record["decline_reason"] = decline_reason
    touch(record)
    return success(serialize_application(record), status=200)
