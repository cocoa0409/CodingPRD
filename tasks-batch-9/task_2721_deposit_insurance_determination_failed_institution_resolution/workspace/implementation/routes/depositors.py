"""The depositor register and the determination notice (PRD sections 3.2, 3.6)."""

from flask import Blueprint, g, request

import db as dbmod
import lookup
import response
import serializers
import shape
from auth import ALL_ROLES, CLAIMS_AGENT, DEPOSITOR, require
from db import db, new_row, touch
from errors import ApiError

bp = Blueprint("depositors", __name__)

DEPOSITOR_TYPES = ("NATURAL_PERSON", "BUSINESS", "GOVERNMENT", "BROKER")

INTEREST_ROLES = ("CO_OWNER", "BENEFICIARY", "PARTICIPANT")


@bp.post("/institutions/<institution_id>/depositor-records")
@require(CLAIMS_AGENT)
def create_depositor(institution_id):
    institution = lookup.institution(institution_id)
    payload = shape.body()
    tin_hash = shape.req_str(payload, "tin_hash", min_len=1, max_len=64)
    legal_name = shape.req_str(payload, "legal_name", min_len=1, max_len=160)
    depositor_type = shape.req_enum(payload, "depositor_type", DEPOSITOR_TYPES)
    contact_email = shape.req_str(payload, "contact_email", min_len=1, contains="@")

    # tin_hash is unique within the institution; the same hash at a different
    # institution is perfectly acceptable.
    for existing in lookup.depositors_of(institution_id):
        if existing["tin_hash"] == tin_hash:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")

    row = new_row(
        {
            "institution_id": institution_id,
            "tin_hash": tin_hash,
            "legal_name": legal_name,
            "depositor_type": depositor_type,
            "contact_email": contact_email,
            "notice_status": "PENDING",
            "notice_template_code": None,
            "notice_sent_at": None,
            "acknowledged_at": None,
            "attributed_total_cents": 0,
            "certified_insured_cents": 0,
            "certified_uninsured_cents": 0,
        }
    )
    db.depositors[row["id"]] = row
    touch(institution)
    return response.created(serializers.depositor(row))


@bp.get("/depositor-records")
@require(ALL_ROLES)
def list_depositors():
    rows = list(db.depositors.values())
    institution_id = request.args.get("institution_id")
    notice_status = request.args.get("notice_status")
    depositor_type = request.args.get("depositor_type")
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    if notice_status is not None:
        rows = [r for r in rows if r["notice_status"] == notice_status]
    if depositor_type is not None:
        rows = [r for r in rows if r["depositor_type"] == depositor_type]
    return response.paginated(dbmod.ordered(rows), serializers.depositor)


@bp.get("/depositor-records/<depositor_id>")
@require(ALL_ROLES)
def get_depositor(depositor_id):
    return response.ok(serializers.depositor(lookup.depositor(depositor_id)))


@bp.get("/depositor-records/<depositor_id>/ownership-interests")
@require(ALL_ROLES)
def list_depositor_interests(depositor_id):
    lookup.depositor(depositor_id)
    role = request.args.get("interest_role")
    rows = lookup.interests_of_depositor(depositor_id, role)
    return response.paginated(dbmod.ordered(rows), serializers.interest)


@bp.post("/depositor-records/<depositor_id>/acknowledge-notice")
@require(DEPOSITOR)
def acknowledge_notice(depositor_id):
    depositor = lookup.depositor(depositor_id)
    shape.body()

    # A depositor may acknowledge only the notice on its own record.
    if g.user_id != depositor["id"]:
        raise ApiError("ERR_DEPOSITOR_MISMATCH")

    if depositor["notice_status"] != "SENT":
        raise ApiError("ERR_NOTICE_NOT_SENT")

    depositor["notice_status"] = "ACKNOWLEDGED"
    depositor["acknowledged_at"] = db.now_iso()
    touch(depositor)
    return response.ok(serializers.depositor(depositor))
