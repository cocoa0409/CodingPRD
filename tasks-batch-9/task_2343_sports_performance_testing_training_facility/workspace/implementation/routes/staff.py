"""Coaching staff, certifications, CEU credits and credential review (PRD 3.4)."""

from flask import Blueprint

import response
import serializers
from db import add_days, create, now_iso, ordered, parse_date, store, today, touch
from errors import ApiError
from middleware import (body_json, guard, pagination, query_enum, query_str,
                        resolve_acting_staff, slice_page, v_date, v_enum,
                        v_int, v_string)
from routes.common import get_certification, get_staff_member
from services import domain

bp = Blueprint("staff", __name__)

ROLE_TITLES = ("HEAD_COACH", "PERFORMANCE_COACH", "INTERN")
CREDENTIAL_STATUSES = ("COMPLIANT", "EXPIRING", "LAPSED")
CERT_CODES = ("CSCS", "USAW", "CPR_AED", "SCCC")
CERT_STATUSES = ("VALID", "EXPIRING", "LAPSED")
EXPIRING_WINDOW_DAYS = 30


# -------------------------------------------------------------- staff members ----
@bp.post("/staff-members")
def create_staff_member():
    guard("PerformanceDirector")
    body = body_json()
    full_name = v_string(body, "full_name", min_len=1, max_len=120)
    role_title = v_enum(body, "role_title", ROLE_TITLES)
    insurance = v_date(body, "liability_insurance_expires_on")

    record = create(
        store.staff_members,
        {
            "full_name": full_name,
            "role_title": role_title,
            "liability_insurance_expires_on": insurance.isoformat(),
            "credential_status": "COMPLIANT",
            "valid_certification_count": 0,
            "lapsed_certification_count": 0,
            "ceu_credits_earned_total": 0,
            "last_credential_review_at": None,
        },
    )
    return response.created(serializers.staff_member(record))


@bp.get("/staff-members/<staff_member_id>")
def read_staff_member(staff_member_id):
    ctx = guard("PerformanceDirector", "Coach", "FrontDesk")
    staff = get_staff_member(staff_member_id)
    resolve_acting_staff(ctx)
    return response.ok(serializers.staff_member(staff))


@bp.get("/staff-members")
def list_staff_members():
    ctx = guard("PerformanceDirector", "Coach", "FrontDesk")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    credential_status = query_enum("credential_status", CREDENTIAL_STATUSES)
    rows = ordered(store.staff_members)
    if credential_status:
        rows = [r for r in rows if r["credential_status"] == credential_status]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.staff_member(r) for r in page], limit, offset, total)


@bp.post("/staff-members/<staff_member_id>/credential-review")
def credential_review(staff_member_id):
    guard("PerformanceDirector")
    staff = get_staff_member(staff_member_id)
    body_json()

    reference = today()
    horizon = add_days(reference, EXPIRING_WINDOW_DAYS)
    for cert in domain.staff_certifications(staff["id"]):
        expires_on = parse_date(cert["expires_on"])
        if expires_on < reference:
            new_status = "LAPSED"
        elif expires_on <= horizon:
            new_status = "EXPIRING"
        else:
            new_status = "VALID"
        if cert["status"] != new_status:
            cert["status"] = new_status
            touch(cert)

    new_credential = domain.derive_credential_status(staff)
    staff["last_credential_review_at"] = now_iso()
    touch(staff)
    domain.apply_credential_status(staff, new_credential, remove_from_future_sessions=True)
    return response.ok(serializers.staff_member(staff))


# ------------------------------------------------------------- certifications ----
@bp.post("/certifications")
def create_certification():
    guard("PerformanceDirector")
    body = body_json()
    staff = get_staff_member(body.get("staff_member_id"))
    cert_code = v_enum(body, "cert_code", CERT_CODES)
    issued_on = v_date(body, "issued_on")
    expires_on = v_date(body, "expires_on")
    required = v_int(
        body, "ceu_credits_required", required=False, minimum=0, maximum=40, default=6
    )
    if expires_on <= issued_on:
        raise ApiError("ERR_INVALID_REQUEST", "expires_on must be strictly later than issued_on")

    record = create(
        store.certifications,
        {
            "staff_member_id": staff["id"],
            "cert_code": cert_code,
            "issued_on": issued_on.isoformat(),
            "expires_on": expires_on.isoformat(),
            "ceu_credits_required": required,
            "ceu_credits_earned": 0,
            "status": "VALID",
            "renewal_count": 0,
        },
    )
    new_credential = domain.derive_credential_status(staff)
    touch(staff)
    domain.apply_credential_status(staff, new_credential)
    return response.created(serializers.certification(record))


@bp.get("/certifications/<certification_id>")
def read_certification(certification_id):
    ctx = guard("PerformanceDirector", "Coach")
    cert = get_certification(certification_id)
    resolve_acting_staff(ctx)
    return response.ok(serializers.certification(cert))


@bp.get("/certifications")
def list_certifications():
    ctx = guard("PerformanceDirector", "Coach")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    staff_member_id = query_str("staff_member_id")
    status = query_enum("status", CERT_STATUSES)
    cert_code = query_enum("cert_code", CERT_CODES)

    rows = ordered(store.certifications)
    if staff_member_id:
        rows = [r for r in rows if r["staff_member_id"] == staff_member_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if cert_code:
        rows = [r for r in rows if r["cert_code"] == cert_code]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.certification(r) for r in page], limit, offset, total)


@bp.post("/certifications/<certification_id>/ceu-credits")
def log_ceu_credits(certification_id):
    ctx = guard("PerformanceDirector", "Coach")
    cert = get_certification(certification_id)
    resolve_acting_staff(ctx)
    body = body_json()
    credits = v_int(body, "credits", minimum=0)

    cert["ceu_credits_earned"] += credits
    touch(cert)
    staff = store.staff_members.get(cert["staff_member_id"])
    if staff is not None:
        domain.refresh_staff_counters(staff)
        touch(staff)
    return response.ok(serializers.certification(cert))


@bp.post("/certifications/<certification_id>/renew")
def renew_certification(certification_id):
    guard("PerformanceDirector")
    cert = get_certification(certification_id)
    body = body_json()
    new_expires_on = v_date(body, "new_expires_on")

    if cert["ceu_credits_earned"] < cert["ceu_credits_required"]:
        raise ApiError(
            "ERR_CEU_REQUIREMENT_NOT_MET",
            "The certification's continuing-education requirement has not been met",
        )

    reference = today()
    if cert["status"] == "LAPSED":
        if new_expires_on <= reference:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "new_expires_on must be later than the current logical date",
            )
    elif cert["status"] == "EXPIRING":
        if new_expires_on <= add_days(reference, EXPIRING_WINDOW_DAYS):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "new_expires_on must be more than 30 days beyond the current logical date",
            )

    cert["status"] = "VALID"
    cert["expires_on"] = new_expires_on.isoformat()
    cert["renewal_count"] += 1
    cert["ceu_credits_earned"] = 0
    touch(cert)

    staff = store.staff_members.get(cert["staff_member_id"])
    if staff is not None:
        new_credential = domain.derive_credential_status(staff)
        touch(staff)
        domain.apply_credential_status(staff, new_credential)
    return response.ok(serializers.certification(cert))
