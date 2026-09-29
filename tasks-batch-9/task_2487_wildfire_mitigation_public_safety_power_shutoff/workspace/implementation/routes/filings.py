"""Wildfire mitigation plan filing endpoints."""

from flask import Blueprint, g

import db
import validation as v
from errors import ApiError
from middleware import (
    ASSET_INSPECTOR,
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import object_response
from services import calc

bp = Blueprint("filings", __name__)

REVIEW_TRACKS = ("SAFETY", "FISCAL")
DECISIONS = ("CLEAR", "DEFICIENT")

READ_ROLES = (
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    ASSET_INSPECTOR,
    TRANSMISSION_ENGINEER,
)

TRACK_FIELDS = {
    "SAFETY": ("safety_review_state", "safety_reviewer_user_id"),
    "FISCAL": ("fiscal_review_state", "fiscal_reviewer_user_id"),
}
OTHER_TRACK = {"SAFETY": "FISCAL", "FISCAL": "SAFETY"}


@bp.post("/plan-filings")
@roles(GRID_PLANNER)
def create_filing():
    body = v.Body()
    filing_code = body.string("filing_code", 3, 40)
    plan_year = body.integer("plan_year", minimum=2020, maximum=2100)

    v.unique_code(db.plan_filings, "filing_code", filing_code)
    v.unique_code(db.plan_filings, "plan_year", plan_year)

    row = db.new_row()
    row["filing_code"] = filing_code
    row["plan_year"] = plan_year
    row["status"] = "DRAFT"
    row["safety_review_state"] = "PENDING"
    row["fiscal_review_state"] = "PENDING"
    row["safety_reviewer_user_id"] = None
    row["fiscal_reviewer_user_id"] = None
    row["deficiency_round_count"] = 0
    row["last_deficiency_note"] = None
    row.update(calc.compute_filing_metrics(plan_year))
    db.plan_filings[row["id"]] = row
    return object_response(db.plan_filing_out(row), 201)


@bp.get("/plan-filings/<filing_id>")
@roles(*READ_ROLES)
def get_filing(filing_id):
    return object_response(db.plan_filing_out(v.plan_filing(filing_id)))


@bp.post("/plan-filings/<filing_id>/submit")
@roles(GRID_PLANNER)
def submit_filing(filing_id):
    filing = v.plan_filing(filing_id)

    # Priority 8 - the filing's own state.
    if filing["status"] not in ("DRAFT", "DEFICIENCY_ISSUED"):
        raise ApiError(
            "ERR_FILING_INVALID_STATE",
            "A %s filing cannot be submitted." % filing["status"],
        )

    metrics = calc.compute_filing_metrics(filing["plan_year"])

    # Priority 14 - there must be something to report.
    if int(metrics["qualifying_project_count"]) == 0:
        raise ApiError(
            "ERR_FILING_METRICS_INCOMPLETE",
            "No qualifying mitigation project exists for plan year %s."
            % filing["plan_year"],
        )

    filing.update(metrics)
    filing["status"] = "SUBMITTED"
    filing["safety_review_state"] = "PENDING"
    filing["fiscal_review_state"] = "PENDING"
    filing["safety_reviewer_user_id"] = None
    filing["fiscal_reviewer_user_id"] = None
    db.touch(filing)
    return object_response(db.plan_filing_out(filing))


@bp.post("/plan-filings/<filing_id>/reviews")
@roles(REGULATORY_REVIEWER)
def review_filing(filing_id):
    filing = v.plan_filing(filing_id)
    body = v.Body()
    track = body.enum("review_track", REVIEW_TRACKS)
    decision = body.enum("decision", DECISIONS)
    note = body.string("deficiency_note", required=False, default=None)

    state_field, reviewer_field = TRACK_FIELDS[track]
    other_state_field, other_reviewer_field = TRACK_FIELDS[OTHER_TRACK[track]]

    # Priority 8 - the filing, then the named track.
    if filing["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_FILING_INVALID_STATE",
            "Review decisions are admitted only while the filing is SUBMITTED.",
        )
    if filing[state_field] != "PENDING":
        raise ApiError(
            "ERR_REVIEW_TRACK_ALREADY_DECIDED",
            "The %s track is already %s in this round." % (track, filing[state_field]),
        )

    # Priority 12 - one reviewer may not decide both tracks of a round.
    other_reviewer = filing[other_reviewer_field]
    if other_reviewer is not None and other_reviewer == g.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewer who decided the other track may not decide this one.",
        )

    if decision == "CLEAR":
        filing[state_field] = "CLEARED"
        filing[reviewer_field] = g.user_id
        if filing[other_state_field] == "CLEARED":
            filing["status"] = "APPROVED"
    else:
        filing[state_field] = "DEFICIENT"
        filing[reviewer_field] = g.user_id
        filing["last_deficiency_note"] = note
        rounds = int(filing["deficiency_round_count"])
        if rounds >= 2:
            filing["deficiency_round_count"] = 3
            filing["status"] = "REJECTED"
        else:
            filing["deficiency_round_count"] = rounds + 1
            filing["status"] = "DEFICIENCY_ISSUED"

    db.touch(filing)
    return object_response(db.plan_filing_out(filing))
