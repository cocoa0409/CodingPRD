"""Legislative instruments, readings, vetoes, and the motion register."""
from flask import Blueprint, g

import calc
import domain
from core import (ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK, ROLE_PRESIDING,
                  STAFF_ROLES, ApiError, authorize, body_dict, db, fetch, fk,
                  invalid, listing, new_record, now_date, ok, opt_enum,
                  opt_str, q, req_enum, req_int, req_str, touch)

bp = Blueprint("instruments", __name__)

CATEGORIES = ("GENERAL", "ZONING", "CODE_AMENDMENT", "EMERGENCY")
MOTION_TYPES = ("ORDINANCE_ADOPTION", "RESOLUTION_ADOPTION", "MINUTES_APPROVAL",
                "MINUTES_CORRECTION", "VETO_OVERRIDE", "PROCEDURAL")
MAJORITY_RULES = ("SIMPLE", "TWO_THIRDS", "FOUR_FIFTHS", "UNANIMOUS_CONSENT")
INSTRUMENT_TARGETS = ("ORDINANCE_ADOPTION", "RESOLUTION_ADOPTION", "VETO_OVERRIDE")
MINUTES_TARGETS = ("MINUTES_APPROVAL", "MINUTES_CORRECTION")


# ----------------------------------------------------------- instruments
@bp.route("/clerk/instruments", methods=["POST"])
def create_instrument():
    authorize((ROLE_CITY_CLERK,))
    body = body_dict()
    series = fk(body, "number_series_id", db.number_series,
                "ERR_NUMBER_SERIES_NOT_FOUND")
    title_rec = fk(body, "code_title_id", db.code_titles, "ERR_CODE_TITLE_NOT_FOUND")
    instrument_class = req_enum(body, "instrument_class", ("ORDINANCE", "RESOLUTION"))
    title = req_str(body, "title")
    full_text_length = req_int(body, "full_text_length", minimum=1)
    if series is None:
        raise invalid("Field 'number_series_id' is required.")
    category = opt_enum(body, "ordinance_category", CATEGORIES)
    code_section_ref = opt_str(body, "code_section_ref", allow_empty=False)
    if instrument_class == "ORDINANCE" and category is None:
        raise invalid("ordinance_category is required for an ORDINANCE.")
    if instrument_class == "RESOLUTION" and category is not None:
        raise invalid("ordinance_category must be null for a RESOLUTION.")
    if category == "CODE_AMENDMENT":
        if title_rec is None or code_section_ref is None:
            raise invalid("code_title_id and code_section_ref are required for a "
                          "CODE_AMENDMENT ordinance.")
    else:
        if title_rec is not None or code_section_ref is not None:
            raise invalid("code_title_id and code_section_ref are only allowed on a "
                          "CODE_AMENDMENT ordinance.")
    if series["status"] != "OPEN":
        raise ApiError("ERR_NUMBER_SERIES_CLOSED", 409)
    if (series["instrument_class"] != instrument_class
            or series["series_year"] != now_date().year):
        raise ApiError("ERR_SERIES_CLASS_MISMATCH", 422)
    instrument = new_record()
    instrument.update({
        "instrument_class": instrument_class,
        "ordinance_category": category,
        "title": title,
        "full_text_length": full_text_length,
        "number_series_id": series["id"],
        "code_title_id": title_rec["id"] if title_rec is not None else None,
        "code_section_ref": code_section_ref,
        "status": "INTRODUCED",
        "assigned_number": None,
        "reading_count": 0,
        "voted_on": None,
        "adoption_date": None,
        "publication_completed_on": None,
        "requires_publication": instrument_class == "ORDINANCE",
        "effective_date_basis": None,
        "effective_date": None,
        "veto_reason": None,
    })
    db.instruments[instrument["id"]] = instrument
    return ok(instrument, 201)


@bp.route("/clerk/instruments/<instrument_id>", methods=["GET"])
def get_instrument(instrument_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.instruments, instrument_id, "ERR_INSTRUMENT_NOT_FOUND"))


@bp.route("/clerk/instruments", methods=["GET"])
def list_instruments():
    authorize(STAFF_ROLES)
    return listing(list(db.instruments.values()), {
        "number_series_id": q("number_series_id"),
        "code_title_id": q("code_title_id"),
        "status": q("status"),
    })


@bp.route("/clerk/instruments/<instrument_id>/advance-reading", methods=["POST"])
def advance_reading(instrument_id):
    authorize((ROLE_CITY_CLERK,))
    instrument = fetch(db.instruments, instrument_id, "ERR_INSTRUMENT_NOT_FOUND")
    body = body_dict()
    meeting = fk(body, "meeting_id", db.meetings, "ERR_MEETING_NOT_FOUND")
    if meeting is None:
        raise invalid("Field 'meeting_id' is required.")
    if (instrument["status"] != "INTRODUCED"
            or instrument["instrument_class"] != "ORDINANCE"):
        raise ApiError("ERR_INVALID_INSTRUMENT_STATE", 409)
    if meeting["status"] != "IN_SESSION":
        raise ApiError("ERR_MEETING_NOT_IN_SESSION", 409)
    instrument["status"] = "FIRST_READING_PASSED"
    instrument["reading_count"] = instrument["reading_count"] + 1
    touch(instrument)
    return ok(instrument)


@bp.route("/clerk/instruments/<instrument_id>/veto", methods=["POST"])
def veto_instrument(instrument_id):
    authorize((ROLE_PRESIDING,))
    instrument = fetch(db.instruments, instrument_id, "ERR_INSTRUMENT_NOT_FOUND")
    body = body_dict()
    reason = req_str(body, "veto_reason")
    if (instrument["status"] != "ADOPTED"
            or instrument["instrument_class"] != "ORDINANCE"):
        raise ApiError("ERR_INVALID_INSTRUMENT_STATE", 409)
    instrument["status"] = "VETOED"
    instrument["veto_reason"] = reason
    touch(instrument)
    domain.void_instrument_notices(instrument["id"])
    return ok(instrument)


# ---------------------------------------------------------------- motions
@bp.route("/clerk/motions", methods=["POST"])
def create_motion():
    authorize((ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK))
    body = body_dict()
    meeting = fk(body, "meeting_id", db.meetings, "ERR_MEETING_NOT_FOUND")
    item = fk(body, "agenda_item_id", db.agenda_items, "ERR_AGENDA_ITEM_NOT_FOUND")
    instrument = fk(body, "instrument_id", db.instruments, "ERR_INSTRUMENT_NOT_FOUND")
    minutes = fk(body, "target_minutes_id", db.minutes, "ERR_MINUTES_NOT_FOUND")
    motion_type = req_enum(body, "motion_type", MOTION_TYPES)
    majority_rule = req_enum(body, "majority_rule", MAJORITY_RULES)
    moved_by = req_str(body, "moved_by_member_id")
    seconded_by = req_str(body, "seconded_by_member_id")
    if meeting is None:
        raise invalid("Field 'meeting_id' is required.")
    if meeting["status"] != "IN_SESSION":
        raise ApiError("ERR_MEETING_NOT_IN_SESSION", 409)
    if motion_type in INSTRUMENT_TARGETS:
        if instrument is None or minutes is not None:
            raise ApiError("ERR_MOTION_TARGET_INVALID", 422)
    elif motion_type in MINUTES_TARGETS:
        if minutes is None or instrument is not None:
            raise ApiError("ERR_MOTION_TARGET_INVALID", 422)
        if minutes["meeting_id"] == meeting["id"]:
            raise ApiError("ERR_MOTION_TARGET_INVALID", 422)
    else:  # PROCEDURAL carries neither target
        if instrument is not None or minutes is not None:
            raise ApiError("ERR_MOTION_TARGET_INVALID", 422)
    motion = new_record()
    motion.update({
        "meeting_id": meeting["id"],
        "agenda_item_id": item["id"] if item is not None else None,
        "instrument_id": instrument["id"] if instrument is not None else None,
        "target_minutes_id": minutes["id"] if minutes is not None else None,
        "motion_type": motion_type,
        "majority_rule": majority_rule,
        "moved_by_member_id": moved_by,
        "seconded_by_member_id": seconded_by,
        "status": "SECONDED",
        "yes_count": 0,
        "no_count": 0,
        "abstain_count": 0,
        "recused_count": 0,
        "effective_base": None,
        "required_yes": None,
        "outcome": "PENDING",
        "tie_break_used": False,
        "result_official": False,
    })
    db.motions[motion["id"]] = motion
    return ok(motion, 201)


@bp.route("/clerk/motions/<motion_id>", methods=["GET"])
def get_motion(motion_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.motions, motion_id, "ERR_MOTION_NOT_FOUND"))


@bp.route("/clerk/motions", methods=["GET"])
def list_motions():
    authorize(STAFF_ROLES)
    return listing(list(db.motions.values()), {
        "meeting_id": q("meeting_id"),
        "agenda_item_id": q("agenda_item_id"),
        "instrument_id": q("instrument_id"),
        "target_minutes_id": q("target_minutes_id"),
        "status": q("status"),
    })


def _apply_tally_consequences(motion):
    """Everything a resolved motion reaches out and does."""
    passing = motion["outcome"] in calc.PASSING_OUTCOMES
    motion_type = motion["motion_type"]
    instrument = db.instruments.get(motion["instrument_id"])
    minutes = db.minutes.get(motion["target_minutes_id"])

    if motion_type == "ORDINANCE_ADOPTION" and instrument is not None:
        if passing and instrument["status"] == "FIRST_READING_PASSED":
            instrument["status"] = "ADOPTED_UNOFFICIAL"
            instrument["voted_on"] = now_date()
            touch(instrument)
        elif not passing and instrument["status"] == "FIRST_READING_PASSED":
            instrument["status"] = "FAILED"
            touch(instrument)
    elif motion_type == "RESOLUTION_ADOPTION" and instrument is not None:
        if passing and instrument["status"] == "INTRODUCED":
            instrument["status"] = "ADOPTED_UNOFFICIAL"
            instrument["voted_on"] = now_date()
            touch(instrument)
    elif motion_type == "MINUTES_APPROVAL" and minutes is not None:
        if passing and minutes["status"] == "SUBMITTED":
            domain.minutes_approval_cascade(minutes)
    elif motion_type == "MINUTES_CORRECTION" and minutes is not None:
        if minutes["status"] == "CORRECTION_PENDING":
            if passing:
                minutes["text_body"] = minutes["pending_correction_text"]
                minutes["revision_number"] = minutes["revision_number"] + 1
            minutes["pending_correction_text"] = None
            minutes["status"] = "APPROVED"
            minutes["approved_on"] = now_date()
            touch(minutes)
    elif motion_type == "VETO_OVERRIDE" and instrument is not None:
        if (passing and motion["majority_rule"] == "FOUR_FIFTHS"
                and instrument["status"] == "VETOED"):
            instrument["status"] = "VETO_OVERRIDDEN"
            touch(instrument)
            domain.create_instrument_notice(instrument)


@bp.route("/clerk/motions/<motion_id>/tally", methods=["POST"])
def tally_motion(motion_id):
    authorize((ROLE_CITY_CLERK,))
    motion = fetch(db.motions, motion_id, "ERR_MOTION_NOT_FOUND")
    body = body_dict()
    yes_count = req_int(body, "yes_count", minimum=0)
    no_count = req_int(body, "no_count", minimum=0)
    abstain_count = req_int(body, "abstain_count", minimum=0)
    recused_count = req_int(body, "recused_count", minimum=0)
    tie_break = opt_enum(body, "presiding_tie_break", ("YES", "NO"))
    if motion["status"] != "SECONDED":
        raise ApiError("ERR_INVALID_MOTION_STATE", 409)
    meeting = db.meetings.get(motion["meeting_id"])
    if meeting is None or meeting["status"] != "IN_SESSION":
        raise ApiError("ERR_MEETING_NOT_IN_SESSION", 409)
    present = meeting["present_member_count"]
    if yes_count + no_count + abstain_count + recused_count != present:
        raise ApiError("ERR_VOTE_TALLY_MISMATCH", 422)
    if present - recused_count < 1:
        raise ApiError("ERR_NO_VOTING_MEMBERS", 422)
    base, required_yes, outcome, tie_used = calc.motion_vote_outcome(
        present, yes_count, no_count, abstain_count, recused_count,
        motion["majority_rule"], tie_break)
    minutes = db.minutes.get(motion["target_minutes_id"])
    if (motion["motion_type"] == "MINUTES_APPROVAL" and minutes is not None
            and outcome in calc.PASSING_OUTCOMES
            and minutes["status"] == "SUBMITTED"):
        domain.precheck_minutes_cascade(minutes)
    motion["yes_count"] = yes_count
    motion["no_count"] = no_count
    motion["abstain_count"] = abstain_count
    motion["recused_count"] = recused_count
    motion["effective_base"] = base
    motion["required_yes"] = required_yes
    motion["outcome"] = outcome
    motion["tie_break_used"] = tie_used
    motion["status"] = "TALLIED"
    touch(motion)
    _apply_tally_consequences(motion)
    return ok(motion)
