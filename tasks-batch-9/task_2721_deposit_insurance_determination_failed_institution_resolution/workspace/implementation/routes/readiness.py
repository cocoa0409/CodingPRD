"""Pre-failure readiness collection and deposit-file standardization (PRD 3.1).

Both figures a package earns are written before either gate is applied, so a
rejected package still carries its diagnostics, and the gates are evaluated in a
fixed order that makes ``rejection_reason`` deterministic when both would fail.
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
from services import aggregates
from util import floor_div

bp = Blueprint("readiness", __name__)

FILE_FORMATS = ("FDIC_STANDARD_V2", "LEGACY_FIXED_WIDTH", "VENDOR_CSV")

READINESS_SCORE_FLOOR_BPS = 9800
READINESS_VARIANCE_CEILING_BPS = 25


@bp.post("/institutions/<institution_id>/readiness-submissions")
@require(CLOSING_MANAGER)
def create_submission(institution_id):
    institution = lookup.institution(institution_id)
    payload = shape.body()
    file_format = shape.req_enum(payload, "file_format", FILE_FORMATS)
    record_count = shape.req_int(payload, "record_count", minimum=1)
    malformed = shape.req_int(
        payload, "malformed_record_count", minimum=0, maximum=record_count
    )
    reported_total = shape.req_int(payload, "reported_deposit_total_cents", minimum=0)

    row = new_row(
        {
            "institution_id": institution_id,
            "file_format": file_format,
            "record_count": record_count,
            "malformed_record_count": malformed,
            "reported_deposit_total_cents": reported_total,
            "standardization_score_bps": None,
            "deposit_total_variance_bps": None,
            "status": "RECEIVED",
            "rejection_reason": None,
        }
    )
    db.submissions[row["id"]] = row

    # The first package opens readiness collection; a package arriving after
    # readiness was already achieved is a revert, because readiness is only as
    # good as the newest delivered file.  A package arriving while collection is
    # already open changes nothing on the institution, so its version does not
    # move either.
    if institution["status"] == "PRE_FAILURE_MONITORING":
        institution["status"] = "READINESS_COLLECTION"
        touch(institution)
    elif institution["status"] == "RESOLUTION_READY":
        institution["status"] = "READINESS_COLLECTION"
        institution["readiness_standardized"] = False
        touch(institution)

    return response.created(serializers.submission(row))


@bp.get("/institutions/<institution_id>/readiness-submissions")
@require(ALL_ROLES)
def list_submissions(institution_id):
    lookup.institution(institution_id)
    rows = lookup.submissions_of(institution_id)
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginated(dbmod.ordered(rows), serializers.submission)


@bp.post("/readiness-submissions/<submission_id>/standardize")
@require(CLOSING_MANAGER)
def standardize(submission_id):
    submission = lookup.submission(submission_id)
    shape.body()

    if submission["status"] != "RECEIVED":
        raise ApiError("ERR_SUBMISSION_NOT_PENDING")

    institution = db.institutions.get(submission["institution_id"])

    # Part one: the clean-record score, truncated downward.
    clean = submission["record_count"] - submission["malformed_record_count"]
    score_bps = floor_div(clean * 10000, submission["record_count"])

    # Part two: what the institution asserted against what has been booked.
    booked = aggregates.total_deposit_balance_cents(submission["institution_id"])
    reported = submission["reported_deposit_total_cents"]
    if booked == 0:
        variance_bps = 0 if reported == 0 else 10000
    else:
        variance_bps = floor_div(abs(reported - booked) * 10000, booked)

    submission["standardization_score_bps"] = score_bps
    submission["deposit_total_variance_bps"] = variance_bps

    if score_bps < READINESS_SCORE_FLOOR_BPS:
        submission["status"] = "REJECTED"
        submission["rejection_reason"] = "SCORE_BELOW_FLOOR"
    elif variance_bps > READINESS_VARIANCE_CEILING_BPS:
        submission["status"] = "REJECTED"
        submission["rejection_reason"] = "TOTAL_VARIANCE_EXCEEDED"
    else:
        submission["status"] = "STANDARDIZED"
        if institution is not None:
            institution["readiness_standardized"] = True
            if institution["status"] == "READINESS_COLLECTION":
                institution["status"] = "RESOLUTION_READY"
            touch(institution)
    touch(submission)
    return response.ok(serializers.submission(submission))
