"""Enrollment records: reads, termination with retro-effective recoupment,
and the revalidation cycle."""
from flask import Blueprint, request

from db import store, touch
from errors import (
    ApiError,
    ERR_REVALIDATION_NOT_DUE,
    ERR_TERMINATION_DATE_INVALID,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, require_roles
from response import list_response, success_object
from serializers import pub
from services import (
    ACTIVE_RECORD_STATES,
    compute_revalidation_schedule,
    terminate_record,
)
from util import fmt_ts
from validate import body, req_date

bp = Blueprint("records", __name__)


def _get_record(rid):
    rec = store.records.get(rid)
    if rec is None:
        raise not_found("EnrollmentRecord")
    return rec


@bp.get("/api/enrollment-records/<rid>")
@require_roles(*ALL_ROLES)
def get_record(rid):
    return success_object(pub(_get_record(rid)))


@bp.get("/api/enrollment-records")
@require_roles(*ALL_ROLES)
def list_records():
    provider_id = request.args.get("provider_id")
    payer_id = request.args.get("payer_id")
    source_application_id = request.args.get("source_application_id")
    source_roster_line_id = request.args.get("source_roster_line_id")
    status = request.args.get("status")
    items = [
        r for r in store.records.values()
        if (provider_id is None or r["provider_id"] == provider_id)
        and (payer_id is None or r["payer_id"] == payer_id)
        and (source_application_id is None or r["source_application_id"] == source_application_id)
        and (source_roster_line_id is None or r["source_roster_line_id"] == source_roster_line_id)
        and (status is None or r["status"] == status)
    ]
    return list_response(items, pub)


@bp.post("/api/enrollment-records/<rid>/terminate")
@require_roles("ComplianceOfficer")
def terminate_record_endpoint(rid):
    rec = _get_record(rid)
    b = body()
    t = req_date(b, "termination_effective_date")
    if rec["status"] not in ACTIVE_RECORD_STATES:
        raise invalid_state("Only an ACTIVE or PENDING_REVALIDATION record can be terminated")
    if t < rec["effective_date"]:
        raise ApiError(
            ERR_TERMINATION_DATE_INVALID,
            422,
            "termination_effective_date is earlier than the record's effective_date",
        )
    terminate_record(rec, t)
    return success_object(pub(rec))


@bp.post("/api/enrollment-records/<rid>/revalidate")
@require_roles("EnrollmentSpecialist")
def revalidate_record(rid):
    rec = _get_record(rid)
    if rec["status"] == "PENDING_REVALIDATION":
        pass
    elif rec["status"] == "ACTIVE":
        raise ApiError(
            ERR_REVALIDATION_NOT_DUE,
            409,
            "The record's revalidation window has not opened",
        )
    else:
        raise invalid_state("A DEACTIVATED or TERMINATED record cannot be revalidated")
    rec["status"] = "ACTIVE"
    rec["last_revalidation_completed_at"] = fmt_ts(store.clock)
    compute_revalidation_schedule(rec, store.payers[rec["payer_id"]])
    touch(rec)
    return success_object(pub(rec))
