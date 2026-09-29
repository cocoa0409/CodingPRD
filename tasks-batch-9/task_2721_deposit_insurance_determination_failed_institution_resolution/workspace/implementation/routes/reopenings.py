"""Branch reopening planning, rescheduling and reopening (PRD section 3.8).

Branch windows are **half-open** -- the start instant belongs to the window and
the end instant does not -- and unlike data-room reservations they carry no
buffer, so a window beginning at exactly the instant an existing one ends is
allowed.
"""

from flask import Blueprint, request

import db as dbmod
import lookup
import response
import serializers
import shape
from auth import ALL_ROLES, CLOSING_MANAGER, require
from db import db, new_row, touch
from errors import ApiError
from util import format_iso, parse_iso

bp = Blueprint("reopenings", __name__)

BLOCKING_REOPENING_STATUSES = ("PLANNED", "READY")


def _assert_no_overlap(institution_id, branch_code, start, end, ignore_id=None):
    for existing in dbmod.ordered(lookup.reopenings_of(institution_id)):
        if existing["id"] == ignore_id:
            continue
        if existing["branch_code"] != branch_code:
            continue
        if existing["status"] not in BLOCKING_REOPENING_STATUSES:
            continue
        existing_start = parse_iso(existing["reopen_window_start"])
        existing_end = parse_iso(existing["reopen_window_end"])
        if start < existing_end and existing_start < end:
            raise ApiError("ERR_BRANCH_WINDOW_OVERLAP")


@bp.post("/institutions/<institution_id>/branch-reopenings")
@require(CLOSING_MANAGER)
def create_reopening(institution_id):
    lookup.institution(institution_id)
    payload = shape.body()
    branch_code = shape.req_str(payload, "branch_code", min_len=1, max_len=16)
    start = shape.req_datetime(payload, "reopen_window_start")
    end = shape.req_datetime(payload, "reopen_window_end")
    staffing_headcount = shape.req_int(payload, "staffing_headcount", minimum=1)
    if end <= start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "reopen_window_end must be strictly after reopen_window_start",
        )

    _assert_no_overlap(institution_id, branch_code, start, end)

    row = new_row(
        {
            "institution_id": institution_id,
            "branch_code": branch_code,
            "reopen_window_start": format_iso(start),
            "reopen_window_end": format_iso(end),
            "staffing_headcount": staffing_headcount,
            # READY is reachable only through the award cascade.
            "status": "PLANNED",
            "reschedule_count": 0,
            "reopened_at": None,
        }
    )
    db.reopenings[row["id"]] = row
    return response.created(serializers.reopening(row))


@bp.get("/institutions/<institution_id>/branch-reopenings")
@require(ALL_ROLES)
def list_reopenings(institution_id):
    lookup.institution(institution_id)
    rows = lookup.reopenings_of(institution_id)
    status = request.args.get("status")
    branch_code = request.args.get("branch_code")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if branch_code is not None:
        rows = [r for r in rows if r["branch_code"] == branch_code]
    return response.paginated(dbmod.ordered(rows), serializers.reopening)


@bp.get("/branch-reopenings/<reopening_id>")
@require(ALL_ROLES)
def get_reopening(reopening_id):
    return response.ok(serializers.reopening(lookup.reopening(reopening_id)))


@bp.post("/branch-reopenings/<reopening_id>/reschedule")
@require(CLOSING_MANAGER)
def reschedule_reopening(reopening_id):
    reopening = lookup.reopening(reopening_id)
    payload = shape.body()
    start = shape.req_datetime(payload, "reopen_window_start")
    end = shape.req_datetime(payload, "reopen_window_end")
    if end <= start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "reopen_window_end must be strictly after reopen_window_start",
        )

    if reopening["status"] not in ("PLANNED", "READY"):
        raise ApiError("ERR_BRANCH_NOT_RESCHEDULABLE")
    _assert_no_overlap(
        reopening["institution_id"],
        reopening["branch_code"],
        start,
        end,
        ignore_id=reopening["id"],
    )

    reopening["reopen_window_start"] = format_iso(start)
    reopening["reopen_window_end"] = format_iso(end)
    reopening["reschedule_count"] = reopening["reschedule_count"] + 1
    # The cycle PLANNED -> READY -> PLANNED: a rescheduled branch must be
    # re-readied by a later award cascade, which cannot fire twice.
    reopening["status"] = "PLANNED"
    touch(reopening)
    return response.ok(serializers.reopening(reopening))


@bp.post("/branch-reopenings/<reopening_id>/reopen")
@require(CLOSING_MANAGER)
def reopen_branch(reopening_id):
    reopening = lookup.reopening(reopening_id)
    shape.body()
    institution = db.institutions.get(reopening["institution_id"])

    if reopening["status"] != "READY":
        raise ApiError("ERR_BRANCH_NOT_READY")
    if institution is None or institution["least_cost_status"] not in (
        "AWARDED",
        "FAILED_ALL_BIDS",
    ):
        raise ApiError("ERR_BRANCH_NOT_READY")
    start = parse_iso(reopening["reopen_window_start"])
    end = parse_iso(reopening["reopen_window_end"])
    if not (start <= db.clock < end):
        raise ApiError("ERR_OUTSIDE_REOPEN_WINDOW")

    reopening["status"] = "REOPENED"
    reopening["reopened_at"] = db.now_iso()
    touch(reopening)
    return response.ok(serializers.reopening(reopening))
