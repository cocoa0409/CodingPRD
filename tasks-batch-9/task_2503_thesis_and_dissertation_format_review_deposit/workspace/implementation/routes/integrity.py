"""Plagiarism screening, referral and the termination cascade (PRD section 3.6)."""

import lookup
import serializers
import validate
from db import db, new_row, write
from errors import fail
from flask import Blueprint
from logical_clock import clock
from middleware import endpoint
from response import object_response
from routes import common
from routes.common import PREFIX
from services import calc
from services.clearance import recompute_for_thesis

bp = Blueprint("integrity", __name__, url_prefix=PREFIX)

ACTIONS = ("REFER", "DISMISS", "UPHOLD")

ALLOWED_THESIS_STATES = (
    "UNDER_FORMAT_REVIEW",
    "FORMAT_REVISIONS_REQUIRED",
    "FORMAT_ACCEPTED",
    "DEPOSITED",
)

INTEGRITY_STATE_FOR = {"CLEARED": "SCREEN_CLEARED", "FLAGGED": "SCREEN_FLAGGED"}


@bp.post("/integrity-screenings")
@endpoint(["GradSchoolAnalyst"])
def create_screening(user_id, role):
    body = validate.get_body()
    thesis_id = validate.req_str(body, "thesis_id")
    similarity_pct = validate.req_num(body, "similarity_pct", minimum=0, maximum=100)
    excluded_pct = validate.opt_num(
        body, "excluded_quoted_pct", default=0, minimum=0, maximum=100
    )

    thesis = lookup.get_thesis(thesis_id)
    common.require_term_open(thesis)

    if thesis["workflow_state"] not in ALLOWED_THESIS_STATES:
        fail(
            "ERR_THESIS_STATE_INVALID",
            "A screening cannot be recorded while the document is '%s'"
            % thesis["workflow_state"],
        )

    existing_rows = lookup.screenings_of_thesis(thesis["id"])
    if any(row["status"] in ("REFERRED", "UPHELD") for row in existing_rows):
        fail(
            "ERR_SCREENING_STATE_INVALID",
            "An open or concluded referral must be resolved by the integrity office",
        )

    adjusted = calc.adjusted_similarity_pct(similarity_pct, excluded_pct)
    resolved = calc.screening_status_for(adjusted)

    row = new_row(
        thesis_id=thesis["id"],
        similarity_pct=calc.round_half_up(str(similarity_pct), 2),
        excluded_quoted_pct=calc.round_half_up(str(excluded_pct), 2),
        adjusted_similarity_pct=adjusted,
        status=resolved,
        screened_at=clock.now(),
        referred_at=None,
        referred_by_user_id=None,
        resolved_by_user_id=None,
        resolution_note=None,
    )

    for previous in existing_rows:
        if previous["status"] in ("CLEARED", "FLAGGED"):
            write(previous, status="SUPERSEDED")

    db.integrity_screenings[row["id"]] = row

    write(thesis, integrity_state=INTEGRITY_STATE_FOR[resolved])
    recompute_for_thesis(thesis)

    return object_response(serializers.integrity_screening(row), 201)


@bp.post("/integrity-screenings/<screening_id>/action")
@endpoint(["IntegrityOfficer"])
def act_on_screening(user_id, role, screening_id):
    screening = lookup.get_screening(screening_id)
    body = validate.get_body()
    action = validate.req_enum(body, "action", ACTIONS)
    resolution_note = validate.opt_str(body, "resolution_note")

    thesis = db.theses.get(screening["thesis_id"])

    # Integrity office action is deliberately NOT gated on the deposit window.
    if action == "UPHOLD":
        if thesis is not None and thesis["workflow_state"] in common.TERMINAL_WORKFLOW_STATES:
            fail(
                "ERR_THESIS_STATE_INVALID",
                "The document has already reached the terminal state '%s'"
                % thesis["workflow_state"],
            )
        if screening["status"] != "REFERRED":
            fail(
                "ERR_SCREENING_STATE_INVALID",
                "Only a REFERRED screening may be upheld",
            )
        common.integrity_upheld_cascade(
            screening, thesis, user_id, resolution_note=resolution_note
        )
        return object_response(serializers.integrity_screening(screening))

    if action == "REFER":
        if screening["status"] != "FLAGGED" or (
            thesis is not None and thesis["integrity_state"] != "SCREEN_FLAGGED"
        ):
            fail(
                "ERR_SCREENING_STATE_INVALID",
                "Only a FLAGGED screening on a flagged document may be referred",
            )
        write(
            screening,
            status="REFERRED",
            referred_at=clock.now(),
            referred_by_user_id=user_id,
            resolution_note=resolution_note,
        )
        if thesis is not None:
            write(thesis, integrity_state="UNDER_INTEGRITY_REVIEW")
    else:
        if screening["status"] != "REFERRED":
            fail(
                "ERR_SCREENING_STATE_INVALID",
                "Only a REFERRED screening may be dismissed",
            )
        write(
            screening,
            status="DISMISSED",
            resolved_by_user_id=user_id,
            resolution_note=resolution_note,
        )
        if thesis is not None:
            write(thesis, integrity_state="INTEGRITY_CLEARED")

    if thesis is not None:
        recompute_for_thesis(thesis)
    return object_response(serializers.integrity_screening(screening))
