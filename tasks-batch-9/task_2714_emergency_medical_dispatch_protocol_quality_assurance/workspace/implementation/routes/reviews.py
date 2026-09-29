"""Reviews: scoring, disputes, adjudication, finalization and voiding.

PRD 3.5 (score sheets), 3.7 (disputes, finalization, Cascades A and D).
"""
from datetime import timedelta

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

bp = Blueprint("reviews", __name__)

GROUNDS = (
    "SCORING_DISPUTE",
    "DETERMINANT_DISPUTE",
    "PROTOCOL_AMBIGUITY",
    "AUDIO_QUALITY",
)
# PERIOD_LOCKED is stamped only by the lock cascade and is not a supervisor's
# to supply (PRD 3.7).
VOID_REASONS = ("AUDIO_UNAVAILABLE", "WRONG_DISPATCHER", "DUPLICATE_CASE")


def period_of(review):
    return db.sampling_periods.get(review["sampling_period_id"])


def program_of(review):
    return cascades.program_of_review(review)


@bp.get("/reviews/<review_id>")
@require(*(ALL_OPERATORS + ("Dispatcher",)))
def read_review(review_id):
    return ok(public(helpers.review(review_id)))


@bp.get("/reviews")
@require(*ALL_OPERATORS)
def list_reviews():
    limit, offset = validate.pagination()
    filters = {
        "sampling_period_id": request.args.get("sampling_period_id"),
        "call_record_id": request.args.get("call_record_id"),
        "dispatcher_id": request.args.get("dispatcher_id"),
        "protocol_version_id": request.args.get("protocol_version_id"),
        "status": request.args.get("status"),
        "high_risk": validate.query_bool("high_risk"),
    }
    rows = [r for r in db.reviews.values() if helpers.matches(r, filters)]
    return helpers.respond_list(rows, limit, offset)


@bp.post("/reviews/<review_id>/scores")
@require("QaReviewer")
def submit_score(review_id):
    payload = validate.body()
    expected_version = validate.get_int(payload, "expected_review_version", minimum=0)
    points = {}
    for section in calc.SECTIONS:
        earned = validate.get_int(payload, section + "_points_earned", minimum=0)
        possible = validate.get_int(payload, section + "_points_possible", minimum=0)
        if earned > possible:
            fail(
                "ERR_INVALID_REQUEST",
                "%s_points_earned may not exceed %s_points_possible."
                % (section, section),
            )
        points[section + "_points_earned"] = earned
        points[section + "_points_possible"] = possible
    code = validate.get_str(payload, "reviewer_determinant_code")
    notes = validate.get_str(payload, "reviewer_notes", required=False)

    if not calc.valid_determinant_code(code):
        fail(
            "ERR_INVALID_DETERMINANT_CODE",
            "reviewer_determinant_code is not a valid determinant code.",
        )

    review = helpers.review(review_id)

    if expected_version != review["version"]:
        fail(
            "ERR_STALE_REVIEW_VERSION",
            "expected_review_version does not match the review's current version.",
        )

    period = period_of(review)
    if period is not None and period["status"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "The sampling period is locked.")
    if review["status"] not in ("SELECTED", "SCORED"):
        fail("ERR_REVIEW_NOT_SCORABLE", "This review cannot be scored in its state.")
    for rebuttal in cascades.rebuttals_of_review(review["id"]):
        if rebuttal["status"] == "SUBMITTED":
            fail(
                "ERR_REVIEW_NOT_SCORABLE",
                "An undecided rebuttal is open on this review.",
            )

    pcts = {}
    for section in calc.SECTIONS:
        pcts[section + "_pct"] = calc.section_percentage(
            points[section + "_points_earned"], points[section + "_points_possible"]
        )
    provisional = calc.provisional_composite(pcts)

    call = db.call_records.get(review["call_record_id"])
    graded = calc.classify_determinant_accuracy(
        call["dispatched_determinant_code"], code
    )

    # Sheets are append-only audit artefacts: no updated_at and no version.
    sheet = base_row(with_version=False)
    sheet.update(
        {
            "review_id": review["id"],
            "sheet_round": review["current_sheet_round"] + 1,
            "provisional_composite_score": provisional,
            "reviewer_determinant_code": code,
            "reviewer_notes": notes,
            "submitted_by_user_id": g.user_id,
        }
    )
    sheet.update(points)
    sheet.update(pcts)
    sheet.update(graded)
    db.score_sheets[sheet["id"]] = sheet

    set_fields(
        review,
        {
            "current_sheet_round": sheet["sheet_round"],
            "provisional_composite_score": provisional,
            "scored_at": clock(),
            "status": "SCORED",
        },
    )
    return ok(public(sheet), 201)


@bp.get("/reviews/<review_id>/score-sheets")
@require("ProgramAdmin", "QaSupervisor", "QaReviewer", "MedicalDirector", "Dispatcher")
def list_score_sheets(review_id):
    limit, offset = validate.pagination()
    review = helpers.review(review_id)
    rows = cascades.sheets_of_review(review["id"])
    return helpers.respond_list(rows, limit, offset)


@bp.post("/reviews/<review_id>/rebuttals")
@require("Dispatcher")
def file_rebuttal(review_id):
    payload = validate.body()
    grounds = validate.get_enum(payload, "grounds_category", GROUNDS)
    narrative = validate.get_str(payload, "narrative")

    review = helpers.review(review_id)

    if review["dispatcher_id"] != g.user_id:
        fail("ERR_NOT_CASE_OWNER", "Only the reviewed dispatcher may dispute this case.")

    if review["status"] != "SCORED":
        fail("ERR_REVIEW_NOT_DISPUTABLE", "Only a SCORED review may be disputed.")

    program = program_of(review)
    deadline = review["scored_at"] + timedelta(days=program["rebuttal_window_days"])
    if clock() > deadline:
        fail("ERR_REBUTTAL_WINDOW_CLOSED", "The rebuttal window has closed.")

    if review["rebuttal_round_count"] >= program["max_rebuttal_rounds"]:
        fail("ERR_REBUTTAL_ROUNDS_EXHAUSTED", "This case has exhausted its rounds.")

    rebuttal = base_row()
    rebuttal.update(
        {
            "review_id": review["id"],
            "round_index": review["rebuttal_round_count"] + 1,
            "grounds_category": grounds,
            "narrative": narrative,
            "status": "SUBMITTED",
            "submitted_by_user_id": g.user_id,
            "decided_by_user_id": None,
            "decision_notes": None,
        }
    )
    db.rebuttals[rebuttal["id"]] = rebuttal

    set_fields(
        review,
        {"rebuttal_round_count": rebuttal["round_index"], "status": "DISPUTED"},
    )
    return ok(public(rebuttal), 201)


@bp.get("/reviews/<review_id>/rebuttals")
@require("ProgramAdmin", "QaSupervisor", "QaReviewer", "MedicalDirector", "Dispatcher")
def list_rebuttals(review_id):
    limit, offset = validate.pagination()
    review = helpers.review(review_id)
    filters = {"status": request.args.get("status")}
    rows = [
        r
        for r in cascades.rebuttals_of_review(review["id"])
        if helpers.matches(r, filters)
    ]
    return helpers.respond_list(rows, limit, offset)


@bp.post("/rebuttals/<rebuttal_id>/decide")
@require("QaSupervisor")
def decide_rebuttal(rebuttal_id):
    payload = validate.body()
    decision = validate.get_enum(payload, "decision", ("UPHELD", "REJECTED"))
    notes = validate.get_str(payload, "decision_notes", required=False)

    rebuttal = helpers.rebuttal(rebuttal_id)

    if rebuttal["status"] != "SUBMITTED":
        fail("ERR_REBUTTAL_ALREADY_DECIDED", "This rebuttal has already been decided.")
    review = db.reviews.get(rebuttal["review_id"])
    if review is None or review["status"] == "VOIDED":
        fail("ERR_REVIEW_ALREADY_VOIDED", "The disputed review has been voided.")
    if review["status"] != "DISPUTED":
        fail("ERR_REVIEW_NOT_DISPUTABLE", "The review is not under dispute.")

    set_fields(
        rebuttal,
        {"status": decision, "decided_by_user_id": g.user_id, "decision_notes": notes},
    )
    if decision == "UPHELD":
        # The case must be scored again from scratch; the invalidated sheet
        # stays in the append-only log and current_sheet_round is not rewound.
        set_fields(
            review,
            {"status": "SELECTED", "provisional_composite_score": None, "scored_at": None},
        )
    else:
        set_fields(review, {"status": "SCORED"})
    return ok(public(rebuttal))


@bp.post("/reviews/<review_id>/finalize")
@require("QaSupervisor")
def finalize_review(review_id):
    payload = validate.body()
    validate.get_str(payload, "finalization_note", required=False)
    review = helpers.review(review_id)

    sheet = cascades.current_sheet(review)
    if sheet is not None and sheet["submitted_by_user_id"] == g.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who scored this case may not finalize it.",
        )

    if review["status"] != "SCORED":
        fail("ERR_REVIEW_NOT_FINALIZABLE", "Only a SCORED review may be finalized.")

    period = period_of(review)
    if period is not None and period["status"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "The sampling period is locked.")

    if review["high_risk"]:
        hrcr = cascades.hrcr_of_review(review["id"])
        if hrcr is None or hrcr["status"] not in ("SENTINEL_EVENT", "COACHING_ONLY"):
            fail(
                "ERR_HIGH_RISK_SIGN_OFF_REQUIRED",
                "The clinical record must be signed off first.",
            )

    program = program_of(review)
    deadline = review["created_at"] + timedelta(days=program["review_deadline_days"])
    if clock() > deadline:
        fail("ERR_REVIEW_DEADLINE_PASSED", "The review deadline has passed.")

    version = db.protocol_versions.get(review["protocol_version_id"])
    pre_penalty = calc.weighted_composite(sheet, version)
    accuracy = sheet["determinant_accuracy"]
    penalty, final = calc.determinant_penalty(pre_penalty, accuracy)

    set_fields(
        review,
        {
            "pre_penalty_composite_score": pre_penalty,
            "determinant_accuracy": accuracy,
            "penalty_points": penalty,
            "final_composite_score": final,
            "compliant": bool(final >= program["target_compliance_pct"]),
            "status": "FINALIZED",
            "finalized_at": clock(),
        },
    )
    cascades.cascade_a_finalize(review)
    return ok(public(review))


@bp.post("/reviews/<review_id>/void")
@require("QaSupervisor")
def void_review_endpoint(review_id):
    payload = validate.body()
    reason = validate.get_enum(payload, "void_reason", VOID_REASONS)
    review = helpers.review(review_id)

    if review["status"] == "VOIDED":
        fail("ERR_REVIEW_ALREADY_VOIDED", "This review is already voided.")

    period = period_of(review)
    if (
        review["status"] == "FINALIZED"
        and period is not None
        and period["status"] == "LOCKED"
    ):
        fail("ERR_PERIOD_LOCKED", "A finalized review in a locked period is frozen.")

    cascades.void_review(review, reason)
    return ok(public(review))
