"""Teaching artist recruitment, roster standing, portfolio panels and screenings."""
from flask import Blueprint, request

import db
import middleware as mw
import response
from enums import (
    DISCIPLINES,
    GRADE_BANDS,
    ROSTER_STATUSES,
    ROSTER_TIERS,
    SCREENING_OUTCOMES,
    SCREENING_TYPES,
    VETTING_STATUSES,
)
from errors import ApiError
from services import calc, derive
from validators import Payload, bad

bp = Blueprint("artists", __name__)

VETTING_TRANSITIONS = {
    ("APPLIED", "PORTFOLIO_REVIEW"),
    ("PORTFOLIO_REVIEW", "DEMO_SCHEDULED"),
    ("DEMO_FAILED", "DEMO_SCHEDULED"),
    ("DEMO_SCHEDULED", "DEMO_PASSED"),
    ("DEMO_SCHEDULED", "DEMO_FAILED"),
    ("PORTFOLIO_REVIEW", "DECLINED"),
    ("DEMO_FAILED", "DECLINED"),
    ("DEMO_PASSED", "SCREENING_PENDING"),
    ("SCREENING_PENDING", "CLEARED"),
}

ROSTER_TRANSITIONS = {
    ("ACTIVE", "PROBATION"),
    ("PROBATION", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("PROBATION", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "RETIRED"),
    ("PROBATION", "RETIRED"),
    ("SUSPENDED", "RETIRED"),
}


def find_artist(artist_id):
    artist = db.teaching_artists.get(artist_id)
    if artist is None:
        raise ApiError("ERR_TEACHING_ARTIST_NOT_FOUND",
                       "teaching artist %s not found" % artist_id)
    return artist


def invalid_transition(message="the requested transition is not declared from the current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


# --- intake and reads -------------------------------------------------------
@bp.post("/teaching-artists")
def create_artist():
    mw.auth("RosterCoordinator")
    body = Payload(request.get_json(silent=True))
    full_name = body.string("full_name", required=True)
    email = body.string("email", required=True)
    primary = body.enum("primary_discipline", DISCIPLINES, required=True)
    secondary = body.array("secondary_disciplines", default=[], allowed=DISCIPLINES,
                           non_empty=False)
    grade_bands = body.array("grade_bands", required=True, allowed=GRADE_BANDS)
    languages = body.language_array("languages", required=True)
    tier = body.enum("roster_tier_assigned", ROSTER_TIERS, default="TEACHING_ARTIST")

    for existing in db.teaching_artists.values():
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL", "email %s already exists" % email)

    row = db.base_row()
    row.update({
        "full_name": full_name,
        "email": email,
        "primary_discipline": primary,
        "secondary_disciplines": secondary,
        "grade_bands": grade_bands,
        "languages": languages,
        "roster_tier_assigned": tier,
        "roster_tier_effective": tier,
        "vetting_status": "APPLIED",
        "roster_status": "NOT_LISTED",
        "demo_attempt_count": 0,
        "demo_rubric_score": None,
        "demo_evaluator_user_id": None,
        "reliability_bps_rolling": 10000,
        "reliability_bps_program_year": 10000,
    })
    db.teaching_artists[row["id"]] = row
    calc.recompute_tier(row)
    return response.ok(derive.artist_view(row), 201)


@bp.get("/teaching-artists/<artist_id>")
def read_artist(artist_id):
    mw.auth()
    return response.ok(derive.artist_view(find_artist(artist_id)))


@bp.get("/teaching-artists")
def list_artists():
    mw.auth()
    limit, offset = mw.pagination()
    discipline = mw.q_enum("discipline", DISCIPLINES)
    grade_band = mw.q_enum("grade_band", GRADE_BANDS)
    language = mw.q_str("language")
    vetting_status = mw.q_enum("vetting_status", VETTING_STATUSES)
    roster_status = mw.q_enum("roster_status", ROSTER_STATUSES)

    rows = db.ordered(list(db.teaching_artists.values()))
    if discipline:
        rows = [a for a in rows
                if a["primary_discipline"] == discipline
                or discipline in (a["secondary_disciplines"] or [])]
    if grade_band:
        rows = [a for a in rows if grade_band in (a["grade_bands"] or [])]
    if language:
        rows = [a for a in rows if language in (a["languages"] or [])]
    if vetting_status:
        rows = [a for a in rows if a["vetting_status"] == vetting_status]
    if roster_status:
        rows = [a for a in rows if a["roster_status"] == roster_status]
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.artist_view(a) for a in page], limit, offset, total)


# --- vetting axis -----------------------------------------------------------
@bp.post("/teaching-artists/<artist_id>/vetting")
def advance_vetting(artist_id):
    user_id, _role = mw.auth("RosterCoordinator")
    artist = find_artist(artist_id)
    body = Payload(request.get_json(silent=True))
    target = body.enum("to_vetting_status", VETTING_STATUSES, required=True)
    if target in ("DEMO_PASSED", "DEMO_FAILED"):
        score = body.number("demo_rubric_score", required=True, minimum=1.0, maximum=5.0)
    else:
        score = body.number("demo_rubric_score", default=None, minimum=1.0, maximum=5.0)
    body.string("decline_reason", default=None, min_len=0)

    current = artist["vetting_status"]
    if (current, target) not in VETTING_TRANSITIONS:
        raise invalid_transition()

    if target == "DEMO_PASSED":
        if calc.dec(score) < calc.DEMO_PASS_SCORE:
            raise invalid_transition("a demo score below %s cannot pass"
                                     % calc.DEMO_PASS_SCORE)
        _segregation_check(artist, user_id)
        artist["demo_rubric_score"] = score
        artist["demo_evaluator_user_id"] = user_id
    elif target == "DEMO_FAILED":
        if calc.dec(score) >= calc.DEMO_PASS_SCORE:
            raise invalid_transition("a demo score of %s or better cannot fail"
                                     % calc.DEMO_PASS_SCORE)
        _segregation_check(artist, user_id)
        artist["demo_rubric_score"] = score
        artist["demo_evaluator_user_id"] = user_id
    elif target == "CLEARED":
        if calc.clearance_status(artist) != "CLEARED":
            raise ApiError("ERR_ARTIST_NOT_CLEARED",
                           "the artist does not hold a complete, current clearance set")
    elif target == "DEMO_SCHEDULED":
        if current == "PORTFOLIO_REVIEW":
            count, mean = calc.portfolio_rollup(artist["id"])
            if count < calc.PORTFOLIO_MIN_REVIEWS:
                raise ApiError("ERR_INSUFFICIENT_PORTFOLIO_REVIEWS",
                               "at least %d distinct panelists must score the portfolio"
                               % calc.PORTFOLIO_MIN_REVIEWS)
            if mean is None or mean < calc.PORTFOLIO_ADVANCE_THRESHOLD:
                raise ApiError("ERR_PORTFOLIO_THRESHOLD_NOT_MET",
                               "portfolio_mean_composite is below %s"
                               % calc.PORTFOLIO_ADVANCE_THRESHOLD)
        if artist["demo_attempt_count"] >= calc.DEMO_ATTEMPT_LIMIT:
            raise ApiError("ERR_DEMO_ATTEMPT_LIMIT_REACHED",
                           "the demonstration attempt limit has been reached")
        artist["demo_attempt_count"] = artist["demo_attempt_count"] + 1
        if current == "DEMO_FAILED":
            artist["demo_rubric_score"] = None
            artist["demo_evaluator_user_id"] = None

    artist["vetting_status"] = target
    if target == "CLEARED" and artist["roster_status"] == "NOT_LISTED":
        artist["roster_status"] = "ACTIVE"
    calc.recompute_tier(artist)
    db.touch(artist)
    return response.ok(derive.artist_view(artist))


def _segregation_check(artist, user_id):
    for review in calc.reviews_of_artist(artist["id"]):
        if review["reviewer_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "a portfolio panelist may not record the demonstration outcome")


# --- roster axis ------------------------------------------------------------
@bp.post("/teaching-artists/<artist_id>/roster-status")
@mw.school_health_sync
def move_roster_status(artist_id):
    mw.auth("ProgramDirector")
    artist = find_artist(artist_id)
    body = Payload(request.get_json(silent=True))
    target = body.enum("to_roster_status", ROSTER_STATUSES, required=True)
    body.string("reason", default=None, min_len=0)

    current = artist["roster_status"]
    if (current, target) not in ROSTER_TRANSITIONS:
        raise invalid_transition()

    if target == "ACTIVE" and current == "SUSPENDED":
        if artist["vetting_status"] != "CLEARED":
            raise invalid_transition("reinstatement requires a CLEARED vetting status")
        if calc.clearance_status(artist) != "CLEARED":
            raise ApiError("ERR_ARTIST_NOT_CLEARED", "clearance does not currently hold")
        artist["roster_status"] = "ACTIVE"
        calc.recompute_tier(artist)
        db.touch(artist)
    elif target == "ACTIVE" and current == "PROBATION":
        if calc.clearance_status(artist) != "CLEARED":
            raise ApiError("ERR_ARTIST_NOT_CLEARED", "clearance does not currently hold")
        if artist["reliability_bps_rolling"] < calc.RELIABILITY_PROBATION_FLOOR_BPS:
            raise ApiError("ERR_RELIABILITY_BELOW_FLOOR",
                           "rolling reliability is below %d basis points"
                           % calc.RELIABILITY_PROBATION_FLOOR_BPS)
        artist["roster_status"] = "ACTIVE"
        calc.recompute_tier(artist)
        db.touch(artist)
        derive.reproject_open_residencies(artist)
    elif target == "PROBATION":
        derive.enter_probation(artist)
    elif target == "SUSPENDED":
        derive.suspend_artist(artist)
    elif target == "RETIRED":
        if current in ("ACTIVE", "PROBATION"):
            for session in db.sessions.values():
                if (session["assigned_artist_id"] == artist["id"]
                        and session["status"] in ("PLANNED", "CONFIRMED")):
                    raise ApiError("ERR_ARTIST_HAS_OPEN_SESSIONS",
                                   "the artist still holds open sessions")
        artist["roster_status"] = "RETIRED"
        calc.recompute_tier(artist)
        db.touch(artist)
    return response.ok(derive.artist_view(artist))


# --- portfolio reviews ------------------------------------------------------
@bp.post("/teaching-artists/<artist_id>/portfolio-reviews")
def create_portfolio_review(artist_id):
    mw.auth("RosterCoordinator", "CurriculumSpecialist")
    artist = find_artist(artist_id)
    body = Payload(request.get_json(silent=True))
    reviewer_user_id = body.string("reviewer_user_id", required=True)
    artistic = body.number("artistic_quality_score", required=True, minimum=1.0,
                           maximum=5.0, step="0.1")
    pedagogical = body.number("pedagogical_clarity_score", required=True, minimum=1.0,
                              maximum=5.0, step="0.1")
    cultural = body.number("cultural_responsiveness_score", required=True, minimum=1.0,
                           maximum=5.0, step="0.1")
    for existing in calc.reviews_of_artist(artist["id"]):
        if existing["reviewer_user_id"] == reviewer_user_id:
            raise ApiError("ERR_DUPLICATE_REVIEWER",
                           "%s has already scored this artist" % reviewer_user_id)

    row = db.base_row(versioned=False)
    row.update({
        "teaching_artist_id": artist["id"],
        "reviewer_user_id": reviewer_user_id,
        "artistic_quality_score": artistic,
        "pedagogical_clarity_score": pedagogical,
        "cultural_responsiveness_score": cultural,
    })
    db.portfolio_reviews[row["id"]] = row
    db.touch(artist)
    return response.ok(derive.portfolio_review_view(row), 201)


@bp.get("/teaching-artists/<artist_id>/portfolio-reviews")
def list_portfolio_reviews(artist_id):
    mw.auth()
    artist = find_artist(artist_id)
    limit, offset = mw.pagination()
    rows = calc.reviews_of_artist(artist["id"])
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.portfolio_review_view(r) for r in page],
                            limit, offset, total)


# --- screenings -------------------------------------------------------------
@bp.post("/teaching-artists/<artist_id>/screenings")
@mw.school_health_sync
def create_screening(artist_id):
    mw.auth("RosterCoordinator")
    artist = find_artist(artist_id)
    body = Payload(request.get_json(silent=True))
    screening_type = body.enum("screening_type", SCREENING_TYPES, required=True)
    outcome = body.enum("outcome", SCREENING_OUTCOMES, required=True)
    effective_on = body.date("effective_on", required=True)
    expires_on = body.date("expires_on", default=None)
    note = body.string("adjudication_note", default=None, min_len=0)
    if outcome == "CLEARED":
        if expires_on is None:
            bad("expires_on is required when the outcome is CLEARED")
        if expires_on <= effective_on:
            bad("expires_on must fall strictly after effective_on")
    else:
        if expires_on is not None:
            bad("expires_on must be null when the outcome is FAILED")

    row = db.base_row(versioned=False)
    row.update({
        "teaching_artist_id": artist["id"],
        "screening_type": screening_type,
        "outcome": outcome,
        "effective_on": effective_on,
        "expires_on": expires_on,
        "adjudication_note": note,
    })
    db.background_screenings[row["id"]] = row

    if outcome == "FAILED" and artist["vetting_status"] in ("SCREENING_PENDING", "CLEARED"):
        was_cleared = artist["vetting_status"] == "CLEARED"
        artist["vetting_status"] = "SCREEN_FAILED"
        if was_cleared:
            artist["_clearance_forced_none"] = True
        derive.suspend_artist(artist)
    db.touch(artist)
    return response.ok(derive.screening_view(row), 201)


@bp.get("/teaching-artists/<artist_id>/screenings")
def list_screenings(artist_id):
    mw.auth()
    artist = find_artist(artist_id)
    limit, offset = mw.pagination()
    rows = calc.screenings_of_artist(artist["id"])
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.screening_view(r) for r in page], limit, offset, total)
