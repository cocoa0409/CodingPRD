"""IndemnityAgreement (GIA) endpoints (PRD §3.2)."""

from flask import Blueprint

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_indemnity_agreement
from services.domain import touch
from flask import request

from helpers import (
    get_body, require_str, require_int,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("indemnity_agreements", __name__)

ROLES = ("Underwriter", "SeniorUnderwriter")


@bp.route("/surety/indemnity-agreements", methods=["POST"])
@require_roles(*ROLES)
def create_gia():
    body = get_body()
    principal_id = require_str(body, "principal_id")
    indemnitor_count = require_int(body, "indemnitor_count")
    required_signature_count = require_int(body, "required_signature_count")

    # Existence (priority 3) before body-shape business rules.
    if db.principals.get(principal_id) is None:
        raise errors.not_found("Principal not found")

    ts = now_ts()
    aid = new_id()
    record = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "principal_id": principal_id,
        "indemnitor_count": indemnitor_count,
        "required_signature_count": required_signature_count,
        "collected_signature_count": 0,
        "status": "PENDING",
    }
    db.indemnity_agreements[aid] = record
    return success(serialize_indemnity_agreement(record), status=201)


@bp.route("/surety/indemnity-agreements/<aid>", methods=["GET"])
@require_roles(*ROLES)
def get_gia(aid):
    record = db.indemnity_agreements.get(aid)
    if record is None:
        raise errors.not_found("Indemnity agreement not found")
    return success(serialize_indemnity_agreement(record), status=200)


@bp.route("/surety/indemnity-agreements", methods=["GET"])
@require_roles(*ROLES)
def list_gias():
    limit, offset = parse_pagination()
    items = list(db.indemnity_agreements.values())
    principal_id = request.args.get("principal_id")
    if principal_id is not None:
        items = [a for a in items if a["principal_id"] == principal_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success(
        [serialize_indemnity_agreement(a) for a in page], limit, offset, total)


@bp.route("/surety/indemnity-agreements/<aid>/sign", methods=["POST"])
@require_roles(*ROLES)
def sign_gia(aid):
    record = db.indemnity_agreements.get(aid)
    if record is None:
        raise errors.not_found("Indemnity agreement not found")
    if record["status"] != "PENDING":
        raise errors.invalid_state("Indemnity agreement is not PENDING")

    record["collected_signature_count"] += 1
    # The signature that brings the count up to exactly required executes the GIA.
    if record["collected_signature_count"] == record["required_signature_count"]:
        record["status"] = "EXECUTED"
        principal = db.principals.get(record["principal_id"])
        if principal is not None and not principal["indemnity_on_file"]:
            principal["indemnity_on_file"] = True
            touch(principal)
    touch(record)
    return success(serialize_indemnity_agreement(record), status=200)


@bp.route("/surety/indemnity-agreements/<aid>/void", methods=["POST"])
@require_roles(*ROLES)
def void_gia(aid):
    record = db.indemnity_agreements.get(aid)
    if record is None:
        raise errors.not_found("Indemnity agreement not found")
    if record["status"] != "PENDING":
        raise errors.invalid_state("Indemnity agreement is not PENDING")
    record["status"] = "VOIDED"
    touch(record)
    return success(serialize_indemnity_agreement(record), status=200)
