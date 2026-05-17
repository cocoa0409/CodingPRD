"""StateLicense routes (mounted under /practice/therapists/{tid}/licenses)."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, request

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_invalid_state,
    err_not_found,
    err_validation,
)
from ..helpers import (
    assert_string,
    new_uuid,
    occ_check,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.cascades import (
    bump,
    hold_future_for_therapist_lacking_coverage,
    unhold_appointments_for_therapist_license_gap,
)
from ..services.serialize import serialize_state_license
from ..store import store

bp = Blueprint("licenses", __name__, url_prefix="/practice/therapists")

LICENSE_STATUSES = ["PENDING", "ACTIVE", "EXPIRED", "REVOKED"]


@bp.post("/<tid>/licenses")
@require_roles("PracticeAdmin")
def create_license(tid: str, **_):
    body = require_json_object()
    s = store()
    if tid not in s.therapists:
        raise err_not_found("Therapist not found")
    state_code = assert_string(body.get("state_code"), "state_code", pattern=r"^[A-Z]{2}$")
    license_number = assert_string(body.get("license_number"), "license_number")
    issued_on = parse_iso8601(body.get("issued_on"), "issued_on")
    expires_on = parse_iso8601(body.get("expires_on"), "expires_on")
    if expires_on <= issued_on:
        raise err_validation("expires_on must be strictly after issued_on")

    with s.lock:
        lid = new_uuid()
        ts = now()
        row: dict[str, Any] = {
            "id": lid,
            "therapist_id": tid,
            "state_code": state_code,
            "license_number": license_number,
            "status": "PENDING",
            "issued_on": issued_on,
            "expires_on": expires_on,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.state_licenses[lid] = row
        return created(serialize_state_license(row))


@bp.post("/<tid>/licenses/<lid>/verify")
@require_roles("PracticeAdmin")
def verify_license(tid: str, lid: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        if tid not in s.therapists:
            raise err_not_found("Therapist not found")
        lic = s.state_licenses.get(lid)
        if lic is None or lic["therapist_id"] != tid:
            raise err_not_found("License not found")
        occ_check(body.get("version"), lic["version"])
        if lic["status"] != "PENDING":
            raise err_invalid_state("License is not PENDING")
        current = now()
        if lic["issued_on"] > current:
            raise err_invalid_state("License issued_on is in the future")
        if lic["expires_on"] <= current:
            raise err_invalid_state("License expires_on is on/before current clock")
        lic["status"] = "ACTIVE"
        bump(lic)
        # Cascade: appointments held due to LICENSE_GAP for this therapist may be eligible to unhold.
        unhold_appointments_for_therapist_license_gap(s, tid)
        return ok(serialize_state_license(lic))


@bp.post("/<tid>/licenses/<lid>/revoke")
@require_roles("PracticeAdmin")
def revoke_license(tid: str, lid: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        if tid not in s.therapists:
            raise err_not_found("Therapist not found")
        lic = s.state_licenses.get(lid)
        if lic is None or lic["therapist_id"] != tid:
            raise err_not_found("License not found")
        occ_check(body.get("version"), lic["version"])
        if lic["status"] != "ACTIVE":
            raise err_invalid_state("Only ACTIVE licenses may be revoked")
        lic["status"] = "REVOKED"
        bump(lic)
        # Cascade: re-evaluate coverage; any future SCHEDULED appointment lacking coverage → HELD/LICENSE_GAP.
        hold_future_for_therapist_lacking_coverage(s, tid)
        return ok(serialize_state_license(lic))


@bp.get("/<tid>/licenses")
@require_roles("PracticeAdmin", "Therapist", "BillingClerk")
def list_licenses(tid: str, **_):
    s = store()
    if tid not in s.therapists:
        raise err_not_found("Therapist not found")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in LICENSE_STATUSES:
        raise err_validation("status filter invalid")
    rows = [r for r in s.state_licenses.values()
            if r["therapist_id"] == tid
            and (status_filter is None or r["status"] == status_filter)]
    rows.sort(key=lambda r: r["created_at"])
    return listing([serialize_state_license(r) for r in paginate(rows, limit, offset)],
                   total_count=len(rows), limit=limit, offset=offset)
