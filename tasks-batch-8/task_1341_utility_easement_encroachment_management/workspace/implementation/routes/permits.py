"""ThirdPartyPermit endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import (
    CASE_MONITORING,
    INSPECTION_RESULTS,
    PERMIT_TYPES,
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
    ROLE_VEGETATION_INSPECTOR as VI,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services import calculations, domain
from services.serializers import serialize_permit, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_bool,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_number,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("permits", __name__)

READERS = (RoWA, VI, DD)


@bp.route("/easement-cases/<case_id>/permits", methods=["POST"])
@require_roles(RoWA)
def create_permit(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    permittee_name = require_string(body, "permittee_name")
    permit_type = require_enum(body, "permit_type", PERMIT_TYPES)
    requested_area_sqft = require_number(body, "requested_area_sqft")
    start_dt = require_ts(body, "requested_start_date")
    end_dt = require_ts(body, "requested_end_date")
    encroachment_id = optional_field(body, "encroachment_id", None)
    insurance = optional_bool(body, "insurance_certificate_on_file", False)

    # Cross-case referential integrity (priority 6) before temporal (9).
    if encroachment_id is not None:
        enc = db.encroachments.get(encroachment_id)
        if enc is None:
            raise_err("ERR_ENCROACHMENT_NOT_FOUND", "encroachment_id does not exist")
        if enc["case_id"] != case_id:
            raise_err("ERR_CROSS_CASE_REFERENCE", "Referenced encroachment belongs to a different case")

    if end_dt <= start_dt:
        raise_err("ERR_INVALID_DATE_RANGE", "requested_end_date must be after requested_start_date")

    permit = {
        "case_id": case_id,
        "encroachment_id": encroachment_id,
        "permittee_name": permittee_name,
        "permit_type": permit_type,
        "requested_area_sqft": float(requested_area_sqft) if requested_area_sqft % 1 else int(requested_area_sqft),
        "requested_start_date": db.fmt_dt(start_dt),
        "requested_end_date": db.fmt_dt(end_dt),
        "annual_fee_cents": None,
        "approval_status": "PENDING",
        "field_inspection_status": "NOT_SCHEDULED",
        "insurance_certificate_on_file": insurance,
    }
    db.stamp_new(permit)
    db.permits[permit["id"]] = permit
    return success_object(serialize_permit(permit), 201)


@bp.route("/easement-cases/<case_id>/permits", methods=["GET"])
@require_roles(*READERS)
def list_permits(case_id: str, _user_id: str, _role: str):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = [p for p in db.permits.values() if p["case_id"] == case_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["approval_status", "permit_type"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_permit), limit, offset, total)


@bp.route("/easement-cases/<case_id>/permits/<permit_id>", methods=["GET"])
@require_roles(*READERS)
def get_permit(case_id: str, permit_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    permit = domain.get_permit_or_404(case, permit_id)
    return success_object(serialize_permit(permit))


@bp.route("/easement-cases/<case_id>/permits/<permit_id>/schedule-inspection", methods=["POST"])
@require_roles(VI)
def schedule_inspection(case_id: str, permit_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    permit = domain.get_permit_or_404(case, permit_id)
    domain.ensure_case_not_closed(case)
    if permit["approval_status"] != "PENDING":
        raise_err("ERR_PERMIT_NOT_PENDING", "Permit approval_status must be PENDING to schedule inspection")
    if permit["field_inspection_status"] != "NOT_SCHEDULED":
        raise_err("ERR_INVALID_STATE", "field_inspection_status must be NOT_SCHEDULED")
    permit["field_inspection_status"] = "SCHEDULED"
    db.touch(permit)
    return success_object(serialize_permit(permit))


def _apply_failed_inspection(case: dict, permit: dict) -> None:
    """A FAILED inspection on an APPROVED permit tears the approval down."""
    if permit["approval_status"] == "APPROVED":
        permit["approval_status"] = "REVOKED"
        _revert_linked_encroachment(case, permit)


def _revert_linked_encroachment(case: dict, permit: dict) -> None:
    enc_id = permit.get("encroachment_id")
    if not enc_id:
        return
    enc = db.encroachments.get(enc_id)
    if enc is not None and enc["status"] == "PERMITTED_RETROACTIVELY":
        enc["status"] = "NEGOTIATING"
        db.touch(enc)


@bp.route("/easement-cases/<case_id>/permits/<permit_id>/record-inspection", methods=["POST"])
@require_roles(VI)
def record_inspection(case_id: str, permit_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    permit = domain.get_permit_or_404(case, permit_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    result = require_enum(body, "result", INSPECTION_RESULTS)
    # Re-inspection of an already-PASSED (possibly APPROVED) permit is allowed:
    # a FAILED result then tears the approval down (PRD 3.4).
    if permit["field_inspection_status"] not in ("SCHEDULED", "PASSED"):
        raise_err("ERR_INVALID_STATE", "record-inspection requires field_inspection_status SCHEDULED")
    permit["field_inspection_status"] = result
    if result == "FAILED":
        _apply_failed_inspection(case, permit)
    db.touch(permit)
    domain.reconcile_case(case)
    return success_object(serialize_permit(permit))


@bp.route("/easement-cases/<case_id>/permits/<permit_id>/approve", methods=["POST"])
@require_roles(RoWA)
def approve_permit(case_id: str, permit_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    permit = domain.get_permit_or_404(case, permit_id)
    domain.ensure_case_not_closed(case)
    if case["status"] not in CASE_MONITORING:
        raise_err("ERR_CASE_NOT_MONITORING", "Case status not in {ACTIVE_MONITORING, RESOLUTION_PENDING}")
    body = get_json_body()
    domain.check_expected_case_version(case, body)
    if permit["approval_status"] != "PENDING":
        raise_err("ERR_PERMIT_NOT_PENDING", "Permit approval_status must be PENDING to approve")
    if permit["field_inspection_status"] != "PASSED":
        raise_err("ERR_INSPECTION_NOT_PASSED", "Permit field_inspection_status must be PASSED to approve")
    if not permit["insurance_certificate_on_file"]:
        raise_err("ERR_INSURANCE_REQUIRED", "insurance_certificate_on_file must be true to approve a permit")
    for other in db.permits.values():
        if other["id"] == permit_id or other["case_id"] != case_id:
            continue
        if calculations.permit_conflicts(permit, other):
            raise_err("ERR_PERMIT_OVERLAP", "Another APPROVED permit covers an overlapping window")
    enc = None
    if permit.get("encroachment_id"):
        enc = db.encroachments.get(permit["encroachment_id"])
        if enc is not None and enc["status"] not in ("NEGOTIATING", "COUNTERED"):
            raise_err("ERR_ENCROACHMENT_NOT_NEGOTIATING", "Linked encroachment must be NEGOTIATING or COUNTERED")

    permit["approval_status"] = "APPROVED"
    permit["annual_fee_cents"] = calculations.annual_fee_cents(
        permit["permit_type"], _dec(permit["requested_area_sqft"])
    )
    db.touch(permit)
    if enc is not None:
        enc["status"] = "PERMITTED_RETROACTIVELY"
        db.touch(enc)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_permit(permit))


def _dec(value):
    from decimal import Decimal
    return Decimal(str(value))


@bp.route("/easement-cases/<case_id>/permits/<permit_id>/deny", methods=["POST"])
@require_roles(RoWA)
def deny_permit(case_id: str, permit_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    permit = domain.get_permit_or_404(case, permit_id)
    domain.ensure_case_not_closed(case)
    if permit["approval_status"] != "PENDING":
        raise_err("ERR_PERMIT_NOT_PENDING", "Permit approval_status must be PENDING to deny")
    permit["approval_status"] = "DENIED"
    db.touch(permit)
    return success_object(serialize_permit(permit))


@bp.route("/easement-cases/<case_id>/permits/<permit_id>/revoke", methods=["POST"])
@require_roles(DD)
def revoke_permit(case_id: str, permit_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    permit = domain.get_permit_or_404(case, permit_id)
    domain.ensure_case_not_closed(case)
    if permit["approval_status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "revoke requires approval_status APPROVED")
    if permit["field_inspection_status"] != "FAILED":
        raise_err("ERR_ONLY_FAILED_INSPECTION_REVOKABLE", "Only a permit with field_inspection_status=FAILED can be revoked")
    permit["approval_status"] = "REVOKED"
    db.touch(permit)
    _revert_linked_encroachment(case, permit)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_permit(permit))
