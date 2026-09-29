"""High-risk clinical records: DA-CPR grading and medical-director sign-off.

PRD 3.6.  A cardiac-arrest case carries a second, clinical judgement alongside
the protocol score sheet, and the sentinel branch of the sign-off restricts the
dispatcher immediately rather than waiting for finalization.
"""
from flask import Blueprint, g, request

import calc
import cascades
import helpers
import validate
from auth import ALL_OPERATORS, require
from cascades import set_fields
from envelope import ok, public
from errors import fail
from store import base_row, clock, db

bp = Blueprint("highrisk", __name__)

OUTCOME_CATEGORIES = ("ROSC_FIELD", "ROSC_HOSPITAL", "NO_ROSC", "NOT_ARREST")
CLASSIFICATIONS = ("SENTINEL_EVENT", "COACHING_ONLY")


@bp.post("/reviews/<review_id>/high-risk-reviews")
@require("QaReviewer")
def open_record(review_id):
    payload = validate.body()
    outcome = validate.get_enum(payload, "outcome_category", OUTCOME_CATEGORIES)

    review = helpers.review(review_id)

    if cascades.hrcr_of_review(review["id"]) is not None:
        fail(
            "ERR_DUPLICATE_HIGH_RISK_REVIEW",
            "A clinical record already exists for this review.",
        )

    record = base_row()
    record.update(
        {
            "review_id": review["id"],
            "outcome_category": outcome,
            "cardiac_arrest_recognized": None,
            "recognition_time_sec": None,
            "time_to_first_compression_sec": None,
            "dacpr_instructions_delivered": None,
            "compressions_coached": None,
            "compression_compliant": None,
            "dacpr_index": None,
            "dacpr_pass": None,
            "classification": None,
            "director_notes": None,
            "signed_off_by_user_id": None,
            "signed_off_at": None,
            "status": "PENDING",
        }
    )
    db.high_risk_reviews[record["id"]] = record
    return ok(public(record), 201)


@bp.get("/reviews/<review_id>/high-risk-reviews")
@require(*ALL_OPERATORS)
def list_records(review_id):
    limit, offset = validate.pagination()
    review = helpers.review(review_id)
    filters = {"status": request.args.get("status")}
    rows = [
        r
        for r in db.high_risk_reviews.values()
        if r["review_id"] == review["id"] and helpers.matches(r, filters)
    ]
    return helpers.respond_list(rows, limit, offset)


@bp.post("/high-risk-reviews/<hrcr_id>/score-dacpr")
@require("QaReviewer")
def score_dacpr(hrcr_id):
    payload = validate.body()
    observations = {
        "cardiac_arrest_recognized": validate.get_bool(
            payload, "cardiac_arrest_recognized"
        ),
        "recognition_time_sec": validate.get_int(
            payload, "recognition_time_sec", minimum=0
        ),
        "time_to_first_compression_sec": validate.get_int(
            payload, "time_to_first_compression_sec", minimum=0
        ),
        "dacpr_instructions_delivered": validate.get_bool(
            payload, "dacpr_instructions_delivered"
        ),
        "compressions_coached": validate.get_bool(payload, "compressions_coached"),
    }

    record = helpers.high_risk_review(hrcr_id)

    if record["status"] != "PENDING":
        fail("ERR_HRCR_NOT_SCORABLE", "This clinical record is no longer gradable.")
    review = db.reviews.get(record["review_id"])
    if review is None or review["status"] not in ("SELECTED", "SCORED"):
        fail(
            "ERR_REVIEW_NOT_SCORABLE",
            "The parent review is not in a scorable state.",
        )

    call = db.call_records.get(review["call_record_id"])
    bystander = bool(call["bystander_cpr_in_progress"]) if call else False
    graded = calc.dacpr_index(observations, bystander)

    updates = dict(observations)
    updates.update(graded)
    updates["status"] = "DACPR_SCORED"
    set_fields(record, updates)
    return ok(public(record))


@bp.post("/high-risk-reviews/<hrcr_id>/sign-off")
@require("MedicalDirector")
def sign_off(hrcr_id):
    payload = validate.body()
    classification = validate.get_enum(payload, "classification", CLASSIFICATIONS)
    notes = validate.get_str(payload, "director_notes", required=False)

    record = helpers.high_risk_review(hrcr_id)

    if record["status"] != "DACPR_SCORED":
        fail("ERR_HRCR_NOT_SIGNABLE", "This clinical record cannot be signed off.")
    if (
        classification == "COACHING_ONLY"
        and record["dacpr_index"] < calc.SENTINEL_INDEX_FLOOR
    ):
        fail(
            "ERR_SENTINEL_CLASSIFICATION_REQUIRED",
            "An index below 50.0 must be classified as a sentinel event.",
        )

    set_fields(
        record,
        {
            "classification": classification,
            "director_notes": notes,
            "signed_off_by_user_id": g.user_id,
            "signed_off_at": clock(),
            "status": classification,
        },
    )

    review = db.reviews.get(record["review_id"])
    dispatcher = db.dispatchers.get(review["dispatcher_id"]) if review else None
    if dispatcher is None:
        return ok(public(record))

    # The plan ladder is consulted with the posture clauses disabled: no posture
    # is recomputed at sign-off, so only the sentinel and coaching-only clauses
    # may fire here (PRD 3.6).
    cascades.auto_plan_upsert(dispatcher, review, record, use_posture=False)

    if classification == "SENTINEL_EVENT":
        cascades.recompute_dispatcher_sentinel(dispatcher)
        cascades.recompute_program_sentinel(
            cascades.program_of_dispatcher(dispatcher)
        )
    # The owed-hours ledger is recomputed on both branches because a plan may
    # have been manufactured; on the coaching-only branch the classification
    # itself contributes nothing to the privilege derivation.
    cascades.recompute_hours_and_privilege(dispatcher)
    return ok(public(record))
