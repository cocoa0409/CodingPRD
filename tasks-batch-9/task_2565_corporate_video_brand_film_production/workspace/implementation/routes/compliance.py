"""Film permits and certificates of insurance (PRD 3.5)."""

from flask import Blueprint, request

import derive
from auth import authenticate
from envelope import respond_created, respond_list, respond_object
from errors import ApiError
from lookups import find_compliance_cert, find_project, find_shoot_day
from store import clock_now, db, iso, new_row, touch
from validation import (field_enum, field_identifier, field_instant, field_integer,
                        field_string, json_body, paginate, pagination, require_interval)

bp = Blueprint("compliance", __name__)

CERT_TYPES = ("FILM_PERMIT", "LIABILITY_COI")
CERT_DECISIONS = ("ISSUE", "DENY")
READ_ROLES = ("ProductionCoordinator", "LineProducer", "ComplianceOfficer")


@bp.get("/compliance-certs/<cert_id>")
def read_cert(cert_id):
    authenticate(READ_ROLES)
    cert = find_compliance_cert(cert_id)
    return respond_object(derive.compliance_cert_out(cert))


@bp.get("/compliance-certs")
def list_certs():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = list(db["compliance_certs"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    shoot_day_id = request.args.get("shoot_day_id")
    if shoot_day_id is not None:
        rows = [r for r in rows if r["shoot_day_id"] == shoot_day_id]
    cert_type = request.args.get("cert_type")
    if cert_type is not None:
        rows = [r for r in rows if r["cert_type"] == cert_type]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.compliance_cert_out(r) for r in page], limit, offset, total)


@bp.post("/compliance-certs")
def file_cert():
    caller = authenticate(("ComplianceOfficer",))
    body = json_body()
    project_id = field_identifier(body, "project_id")
    cert_type = field_enum(body, "cert_type", CERT_TYPES)
    carrier_or_authority = field_string(body, "carrier_or_authority", 1, 120)
    reference_code = field_string(body, "reference_code", 1, 64)
    effective_from = field_instant(body, "effective_from")
    effective_to = field_instant(body, "effective_to")
    require_interval(effective_from, effective_to, "effective_from", "effective_to")
    shoot_day_id = field_identifier(body, "shoot_day_id", required=False, default=None)
    coverage_amount_cents = field_integer(body, "coverage_amount_cents", minimum=0,
                                          required=False, default=0)
    fee_cents = field_integer(body, "fee_cents", minimum=0, required=False, default=0)
    # A certificate of insurance with zero or absent coverage is malformed, not
    # a scope violation (PRD 3.5).
    if cert_type == "LIABILITY_COI" and coverage_amount_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "A LIABILITY_COI must declare coverage_amount_cents greater than 0.")

    project = find_project(project_id)
    shoot_day = find_shoot_day(shoot_day_id) if shoot_day_id is not None else None

    if cert_type == "FILM_PERMIT":
        if shoot_day is None:
            raise ApiError("ERR_CERT_SCOPE_MISMATCH",
                           "A FILM_PERMIT must name the single shoot day it covers.")
        if shoot_day["project_id"] != project["id"]:
            raise ApiError("ERR_CERT_SCOPE_MISMATCH",
                           "The named shoot day belongs to a different project.")
    elif shoot_day_id is not None:
        raise ApiError("ERR_CERT_SCOPE_MISMATCH",
                       "A LIABILITY_COI covers the whole project and must omit shoot_day_id.")

    row = new_row(
        project_id=project["id"],
        shoot_day_id=shoot_day["id"] if shoot_day is not None else None,
        cert_type=cert_type,
        carrier_or_authority=carrier_or_authority,
        reference_code=reference_code,
        coverage_amount_cents=coverage_amount_cents,
        fee_cents=fee_cents,
        effective_from=iso(effective_from),
        effective_to=iso(effective_to),
        status="SUBMITTED",
        decision_note=None,
        decided_at=None,
        _filed_by_user_id=caller.user_id,
    )
    db["compliance_certs"][row["id"]] = row
    return respond_created(derive.compliance_cert_out(row))


@bp.post("/compliance-certs/<cert_id>/decision")
def decide_cert(cert_id):
    caller = authenticate(("ComplianceOfficer",))
    body = json_body()
    decision = field_enum(body, "decision", CERT_DECISIONS)
    decision_note = field_string(body, "decision_note", 1, 2000, required=False, default=None)
    cert = find_compliance_cert(cert_id)
    if cert["status"] != "SUBMITTED":
        raise ApiError("ERR_COMPLIANCE_CERT_STATE_INVALID",
                       "A certificate in %s is terminal and accepts no further decision."
                       % cert["status"])
    if caller.user_id == cert["_filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who filed this certificate may not record its decision.")
    cert["status"] = "ISSUED" if decision == "ISSUE" else "DENIED"
    cert["decision_note"] = decision_note
    cert["decided_at"] = iso(clock_now())
    touch(cert)
    # The posture of the linked day (FILM_PERMIT) or of every day of the
    # project (LIABILITY_COI) is a derived column and is recomputed on read.
    return respond_object(derive.compliance_cert_out(cert))
