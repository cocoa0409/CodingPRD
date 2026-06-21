"""OJT hours entry endpoints + approve/reject/reopen (PRD §3.4, §3.7)."""
from flask import Blueprint, request

import db
from common import (
    get_json_body,
    parse_pagination,
    require_int,
    require_number,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from errors import err
from lookups import get_agreement, get_ojt_entry
from middleware import require_roles
from response import success_array, success_object
from services.calc import recompute_agreement_derived

bp = Blueprint("ojt_entries", __name__)

SUPERVISION_BUFFER_MINUTES = 15


def _windows_overlap(a_start, a_end, b_start, b_end):
    """True if [a_start,a_end] and [b_start,b_end] truly overlap.

    Touching endpoints (a_end == b_start or b_end == a_start) are NOT an overlap.
    """
    return a_start < b_end and b_start < a_end


def _gap(a_start, a_end, b_start, b_end):
    """Minutes between two non-overlapping windows; negative if they overlap."""
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return -1  # overlap


@bp.route("/apprenticeship/ojt-entries", methods=["POST"])
@require_roles("Sponsor", "Apprentice")
def create_ojt_entry():
    body = get_json_body()
    agreement_id = require_str(body, "agreement_id")
    work_date = require_str(body, "work_date")
    start_time = require_int(body, "start_time")
    end_time = require_int(body, "end_time")
    credited_hours = require_number(body, "credited_hours")

    agreement = get_agreement(agreement_id)

    # Priority 10: work_date >= agreement.start_date.
    if work_date < agreement["start_date"]:
        raise err("ERR_DATE_BEFORE_AGREEMENT_START", "work_date is before the agreement start_date.")

    # Priority 11: well-formed window and positive credited_hours.
    if not (0 <= start_time <= 1440 and 0 <= end_time <= 1440):
        raise err("ERR_INVALID_TIME_RANGE", "start_time/end_time must be within 0..1440.")
    if not (start_time < end_time):
        raise err("ERR_INVALID_TIME_RANGE", "start_time must be strictly less than end_time.")
    if not (credited_hours > 0):
        raise err("ERR_INVALID_TIME_RANGE", "credited_hours must be greater than zero.")

    # Priority 12: apprentice session overlap (same apprentice, same work_date).
    apprentice_id = agreement["apprentice_id"]
    for other in db.ojt_entries.values():
        if other["work_date"] != work_date:
            continue
        other_ag = db.agreements.get(other["agreement_id"])
        if other_ag is None or other_ag["apprentice_id"] != apprentice_id:
            continue
        if _windows_overlap(start_time, end_time, other["start_time"], other["end_time"]):
            raise err(
                "ERR_APPRENTICE_SESSION_OVERLAP",
                "New OJT window overlaps another session for the same apprentice on this date.",
            )

    # Priority 13: journeyworker supervision buffer. The journeyworker "cannot be
    # in two places at once" — i.e. cannot supervise two DIFFERENT apprentices on
    # the same date within the buffer. The same apprentice's own consecutive
    # sessions are governed solely by the apprentice-overlap rule above (where
    # touching endpoints are permitted), so same-apprentice entries are excluded
    # here to avoid double-penalizing a permitted touching window.
    journeyworker_id = agreement["journeyworker_id"]
    for other in db.ojt_entries.values():
        if other["work_date"] != work_date:
            continue
        other_ag = db.agreements.get(other["agreement_id"])
        if other_ag is None or other_ag["journeyworker_id"] != journeyworker_id:
            continue
        if other_ag["apprentice_id"] == apprentice_id:
            continue  # same apprentice — governed by the apprentice-overlap rule
        gap = _gap(start_time, end_time, other["start_time"], other["end_time"])
        if gap < SUPERVISION_BUFFER_MINUTES:
            raise err(
                "ERR_JOURNEYWORKER_SUPERVISION_CONFLICT",
                "New OJT window violates the supervision buffer for the agreement's journeyworker.",
            )

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "agreement_id": agreement_id,
            "work_date": work_date,
            "start_time": start_time,
            "end_time": end_time,
            "credited_hours": credited_hours,
            "status": "PENDING",
        }
    )
    db.ojt_entries[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/ojt-entries", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_ojt_entries():
    limit, offset = parse_pagination()
    items = list(db.ojt_entries.values())
    for key in ("agreement_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/ojt-entries/<oid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_ojt_entry_route(oid):
    rec = get_ojt_entry(oid)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/ojt-entries/<oid>/approve", methods=["POST"])
@require_roles("TrainingCoordinator")
def approve_ojt_entry(oid):
    rec = get_ojt_entry(oid)
    if rec["status"] != "PENDING":
        raise err("ERR_OJT_ENTRY_NOT_PENDING", "OJT entry must be PENDING to approve.")
    agreement = db.agreements[rec["agreement_id"]]
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Parent agreement must be ACTIVE to approve OJT.")

    rec["status"] = "APPROVED"
    # Cascade: hours total first, then wage step -> wage snapshot -> eligibility.
    agreement["ojt_hours_completed"] += rec["credited_hours"]
    recompute_agreement_derived(agreement)

    db.touch(rec, bump_version=True)
    db.touch(agreement, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/ojt-entries/<oid>/reject", methods=["POST"])
@require_roles("TrainingCoordinator")
def reject_ojt_entry(oid):
    rec = get_ojt_entry(oid)
    if rec["status"] != "PENDING":
        raise err("ERR_OJT_ENTRY_NOT_PENDING", "OJT entry must be PENDING to reject.")
    rec["status"] = "REJECTED"
    db.touch(rec, bump_version=True)
    return success_object(serialize(rec))


@bp.route("/apprenticeship/ojt-entries/<oid>/reopen", methods=["POST"])
@require_roles("TrainingCoordinator")
def reopen_ojt_entry(oid):
    rec = get_ojt_entry(oid)
    if rec["status"] != "APPROVED":
        raise err("ERR_OJT_ENTRY_NOT_APPROVED", "OJT entry must be APPROVED to reopen.")
    agreement = db.agreements[rec["agreement_id"]]

    rec["status"] = "PENDING"
    # Compensating action: subtract credited hours, then re-run the cascade.
    agreement["ojt_hours_completed"] -= rec["credited_hours"]
    recompute_agreement_derived(agreement)

    db.touch(rec, bump_version=True)
    db.touch(agreement, bump_version=True)
    return success_object(serialize(rec))
