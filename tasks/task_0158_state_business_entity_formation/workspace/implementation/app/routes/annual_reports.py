"""Annual report routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_caller, require_auth
from ..envelope import object_response
from ..errors import (
    APIError,
    err_entity_not_active,
    err_invalid_input,
    err_invalid_state,
    err_not_found,
    err_segregation,
    err_version_conflict,
)
from ..store import store
from ..timeutil import anniversary_one_year_after, now as clock_now
from ..util import (
    get_json_body,
    new_uuid,
    optional_int,
    optional_str,
    require_int,
    require_str,
)
from ..services import serializers
from ..services.engine import emit_event, recompute_compliance_status, touch


bp = Blueprint("annual_reports", __name__, url_prefix="/business-registry")


def _report_or_404(report_id):
    row = store.annual_reports.get(report_id)
    if row is None:
        raise err_not_found(f"Annual report {report_id!r} not found")
    return row


@bp.post("/annual-reports")
@require_auth(["Filer"])
def create_annual_report():
    caller = current_caller()
    body = get_json_body()
    business_entity_id = require_str(body, "business_entity_id")
    report_year = require_int(body, "report_year", minimum=1900, maximum=9999)
    principal_office_address = require_str(body, "principal_office_address", min_len=1, max_len=500)
    officer_director_count = require_int(body, "officer_director_count", minimum=1)
    with store.lock:
        entity = store.business_entities.get(business_entity_id)
        if entity is None:
            raise err_not_found(f"business_entity_id {business_entity_id!r} not found")
        if entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != business_entity_id:
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)

        # report_year range: > formation_year and <= current_year(clock)
        formation_date = entity.get("formation_date")
        formation_year = formation_date.year if formation_date else None
        current_year = clock_now().year
        if formation_year is None or report_year <= formation_year or report_year > current_year:
            # The PRD doesn't designate a specific error for an out-of-range year other
            # than ERR_DUPLICATE_ANNUAL_REPORT being the one returned on collision.
            # Treat range violations as invalid input.
            raise err_invalid_input("report_year is outside the allowed range")

        # Duplicate (SUBMITTED or ACCEPTED) for same (entity, year)?
        for existing in store.annual_reports.values():
            if existing.get("business_entity_id") != business_entity_id:
                continue
            if existing.get("report_year") != report_year:
                continue
            if existing.get("status") in ("SUBMITTED", "ACCEPTED"):
                raise APIError("ERR_DUPLICATE_ANNUAL_REPORT",
                               f"Annual report for {report_year} already in SUBMITTED/ACCEPTED state", 409)

        now = clock_now()
        row = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "business_entity_id": business_entity_id,
            "report_year": report_year,
            "principal_office_address": principal_office_address,
            "officer_director_count": officer_director_count,
            "status": "DRAFT",
            "submitted_at": None,
            "accepted_at": None,
            "rejection_reason": None,
        }
        store.annual_reports[row["id"]] = row
        return jsonify(object_response(serializers.annual_report(row))), 201


@bp.patch("/annual-reports/<report_id>")
@require_auth(["Filer"])
def revise_annual_report(report_id):
    caller = current_caller()
    body = get_json_body()
    with store.lock:
        row = _report_or_404(report_id)
        if row.get("status") not in ("DRAFT", "REJECTED"):
            raise err_invalid_state("Annual report is not in DRAFT or REJECTED")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != row.get("business_entity_id"):
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)

        if "version" in body and body["version"] is not None:
            supplied = body["version"]
            if not isinstance(supplied, int) or isinstance(supplied, bool):
                raise err_invalid_input("version must be an integer")
            if supplied != int(row.get("version", 0)):
                raise err_version_conflict()
        new_addr = optional_str(body, "principal_office_address", min_len=1, max_len=500)
        new_count = optional_int(body, "officer_director_count", minimum=1)
        if new_addr is not None:
            row["principal_office_address"] = new_addr
        if new_count is not None:
            row["officer_director_count"] = new_count
        # REJECTED → DRAFT cycle
        if row.get("status") == "REJECTED":
            row["status"] = "DRAFT"
            row["rejection_reason"] = None
        touch(row)
        return jsonify(object_response(serializers.annual_report(row))), 200


@bp.post("/annual-reports/<report_id>/submit")
@require_auth(["Filer"])
def submit_annual_report(report_id):
    caller = current_caller()
    with store.lock:
        row = _report_or_404(report_id)
        if row.get("status") != "DRAFT":
            raise err_invalid_state("Annual report is not in DRAFT")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != row.get("business_entity_id"):
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        if int(row.get("officer_director_count") or 0) < 1:
            raise err_invalid_input("officer_director_count must be >= 1")
        for existing in store.annual_reports.values():
            if existing.get("id") == row.get("id"):
                continue
            if existing.get("business_entity_id") != row.get("business_entity_id"):
                continue
            if existing.get("report_year") != row.get("report_year"):
                continue
            if existing.get("status") in ("SUBMITTED", "ACCEPTED"):
                raise APIError("ERR_DUPLICATE_ANNUAL_REPORT",
                               "A peer SUBMITTED/ACCEPTED report already exists", 409)
        now = clock_now()
        row["status"] = "SUBMITTED"
        row["submitted_at"] = now
        row["rejection_reason"] = None
        touch(row, ts=now)
        return jsonify(object_response(serializers.annual_report(row))), 200


@bp.post("/annual-reports/<report_id>/accept")
@require_auth(["TaxOfficer"])
def accept_annual_report(report_id):
    caller = current_caller()
    with store.lock:
        row = _report_or_404(report_id)
        if row.get("status") != "SUBMITTED":
            raise err_invalid_state("Annual report is not in SUBMITTED")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        # Segregation of duties: TaxOfficer X-User-ID must not equal the entity id.
        if caller.user_id == row.get("business_entity_id"):
            raise err_segregation()
        now = clock_now()
        row["status"] = "ACCEPTED"
        row["accepted_at"] = now
        touch(row, ts=now)
        # Record the TaxOfficer who accepted so /pay segregation can be enforced.
        key = (row.get("business_entity_id"), row.get("report_year"))
        store.tax_accept_actor.setdefault(key, set()).add(caller.user_id)
        # Advance entity's next_annual_report_due_date to the formation-date anniversary in (report_year + 1).
        formation_date = entity.get("formation_date")
        if formation_date is not None:
            month = formation_date.month
            day = formation_date.day
            target_year = row.get("report_year") + 1
            try:
                next_due = formation_date.replace(year=target_year, month=month, day=day)
            except ValueError:
                next_due = formation_date.replace(year=target_year, month=month, day=28)
            entity["next_annual_report_due_date"] = next_due
            touch(entity, ts=now)
        # Recompute compliance posture in case acceptance closed the last delinquency.
        recompute_compliance_status(row.get("business_entity_id"), at=now)
        emit_event(row.get("business_entity_id"), "ANNUAL_REPORT_ACCEPTED",
                   {"report_id": row["id"], "accepted_by": caller.user_id}, occurred_at=now)
        return jsonify(object_response(serializers.annual_report(row))), 200


@bp.post("/annual-reports/<report_id>/reject")
@require_auth(["TaxOfficer"])
def reject_annual_report(report_id):
    body = get_json_body()
    reason = require_str(body, "rejection_reason", min_len=1, max_len=2000)
    with store.lock:
        row = _report_or_404(report_id)
        if row.get("status") != "SUBMITTED":
            raise err_invalid_state("Annual report is not in SUBMITTED")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        now = clock_now()
        row["status"] = "REJECTED"
        row["rejection_reason"] = reason
        touch(row, ts=now)
        emit_event(row.get("business_entity_id"), "ANNUAL_REPORT_REJECTED",
                   {"report_id": row["id"], "reason": reason}, occurred_at=now)
        return jsonify(object_response(serializers.annual_report(row))), 200
