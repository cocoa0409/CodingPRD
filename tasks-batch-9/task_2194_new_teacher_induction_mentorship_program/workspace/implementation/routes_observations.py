"""Observation cycles: booking, phase advance, feedback and feedback review."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import domain
from auth import (ADMIN, LEAD, MENTOR, NOVICE, guard, own_match, own_mentor,
                  own_site, role, scope_rows)
from envelope import list_response, pagination, row_response
from errors import ApiError
from store import db, iso, new_row, now, parse_iso, sorted_rows, touch
from validators import (apply_filters, body, bool_field, datetime_field,
                        dict_field, enum_field, enum_list_field, fk, int_field,
                        invalid, path_row, str_field)

bp = Blueprint("observations", __name__)

ACTIVE_PHASES = ("PRE_CONFERENCE", "OBSERVED", "POST_CONFERENCE")


def _match_of(cycle):
    return db.matches.get(cycle.get("match_id"))


@bp.post("/observation-cycles")
@guard([MENTOR, LEAD])
def create_cycle():
    data = body()
    match = fk("matches", data, "match_id")
    str_field(data, "match_id", 1, None)
    cycle_index = int_field(data, "cycle_index", 1, 8)
    window_start = datetime_field(data, "window_start")
    window_end = datetime_field(data, "window_end")
    novice = domain.novice_of_match(match)
    mentor = domain.mentor_of_match(match)
    if role() == MENTOR:
        own_mentor(match.get("mentor_id"))
    elif novice is not None:
        own_site(novice.get("site_id"))

    if match.get("match_status") != "ACTIVE":
        raise ApiError("ERR_MATCH_STATE_INVALID")
    if novice is None or novice.get("program_status") != "ACTIVE":
        raise ApiError("ERR_NOVICE_PROGRAM_STATE_INVALID")
    if mentor is None or mentor.get("certification_status") != "CERTIFIED":
        raise ApiError("ERR_MENTOR_NOT_CERTIFIED")

    for other in sorted_rows(list(db.cycles.values())):
        other_match = _match_of(other)
        if other_match is None or other_match.get("mentor_id") != match.get("mentor_id"):
            continue
        if other.get("phase") not in ACTIVE_PHASES:
            continue
        other_start = parse_iso(other.get("window_start"))
        other_end = parse_iso(other.get("window_end"))
        if other_start is None or other_end is None:
            continue
        if calc.observation_conflict(window_start, window_end, other_start, other_end):
            raise ApiError("ERR_OBSERVATION_WINDOW_CONFLICT")

    if not calc.window_ok(window_start, window_end):
        raise ApiError("ERR_INVALID_WINDOW")

    for other in domain.cycles_of_match(match["id"]):
        if other.get("cycle_index") == cycle_index:
            raise ApiError("ERR_DUPLICATE_CYCLE_INDEX")

    row = new_row({
        "match_id": match["id"],
        "cycle_index": cycle_index,
        "window_start": iso(window_start),
        "window_end": iso(window_end),
        "phase": "PRE_CONFERENCE",
        "feedback_review_status": "NONE",
        "narrative": None,
        "growth_area_codes": None,
        "rubric_scores": None,
        "composite_rubric_score": None,
        "return_reason": None,
        "return_count": 0,
        "observed_at": None,
        "post_conference_at": None,
        "documented_at": None,
        "abandoned_at": None,
    })
    db.cycles[row["id"]] = row
    return row_response(row, 201)


@bp.get("/observation-cycles")
@guard([ADMIN, LEAD, MENTOR])
def list_cycles():
    rows = sorted_rows(list(db.cycles.values()))
    rows = scope_rows(rows, match_getter=_match_of)
    rows = apply_filters(rows, {
        "match_id": ("match_id", "str"),
        "phase": ("phase", "str"),
        "feedback_review_status": ("feedback_review_status", "str"),
    })
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/observation-cycles/<row_id>")
@guard([ADMIN, LEAD, MENTOR, NOVICE])
def get_cycle(row_id):
    row = path_row("cycles", row_id)
    own_match(_match_of(row))
    return row_response(row)


def _feedback_complete(cycle):
    narrative = cycle.get("narrative") or ""
    if len(narrative) < 120:
        return False
    codes = cycle.get("growth_area_codes") or []
    if not (1 <= len(codes) <= 4):
        return False
    scores = cycle.get("rubric_scores") or {}
    return all(key in scores for key in calc.RUBRIC_KEYS)


@bp.post("/observation-cycles/<row_id>/advance")
@guard([MENTOR, LEAD])
def advance_cycle(row_id):
    cycle = path_row("cycles", row_id)
    data = body()
    to_phase = enum_field(data, "to_phase",
                          ("OBSERVED", "POST_CONFERENCE", "DOCUMENTED", "ABANDONED"))
    str_field(data, "reason", 1, 1000, required=False)
    match = _match_of(cycle)
    novice = domain.novice_of_match(match)
    if role() == MENTOR:
        own_mentor(match.get("mentor_id") if match else None)
    elif novice is not None:
        own_site(novice.get("site_id"))

    phase = cycle.get("phase")
    if to_phase != "ABANDONED" and match.get("match_status") != "ACTIVE":
        raise ApiError("ERR_MATCH_STATE_INVALID")

    if to_phase == "ABANDONED":
        if phase not in ACTIVE_PHASES:
            raise ApiError("ERR_OBSERVATION_PHASE_INVALID")
        cycle["phase"] = "ABANDONED"
        cycle["abandoned_at"] = iso(now())
        if cycle.get("feedback_review_status") in ("DRAFT", "SUBMITTED"):
            cycle["feedback_review_status"] = "RETURNED"
            cycle["return_reason"] = "CYCLE_ABANDONED"
            cycle["return_count"] = int(cycle.get("return_count") or 0) + 1
        touch(cycle)
        return row_response(cycle)

    expected_from = {"OBSERVED": "PRE_CONFERENCE",
                     "POST_CONFERENCE": "OBSERVED",
                     "DOCUMENTED": "POST_CONFERENCE"}[to_phase]
    if phase != expected_from:
        raise ApiError("ERR_OBSERVATION_PHASE_INVALID")

    if to_phase == "OBSERVED":
        window_end = parse_iso(cycle.get("window_end"))
        if window_end is None or now() < window_end:
            raise ApiError("ERR_OBSERVATION_PHASE_INVALID")
        cycle["phase"] = "OBSERVED"
        cycle["observed_at"] = iso(now())
        touch(cycle)
        return row_response(cycle)

    if to_phase == "POST_CONFERENCE":
        cycle["phase"] = "POST_CONFERENCE"
        cycle["post_conference_at"] = iso(now())
        touch(cycle)
        return row_response(cycle)

    if cycle.get("feedback_review_status") != "ACCEPTED":
        raise ApiError("ERR_FEEDBACK_STATE_INVALID")
    if not _feedback_complete(cycle):
        raise ApiError("ERR_FEEDBACK_INCOMPLETE")
    cycle["phase"] = "DOCUMENTED"
    cycle["documented_at"] = iso(now())
    touch(cycle)
    domain.refresh_novice(novice)
    return row_response(cycle)


@bp.post("/observation-cycles/<row_id>/feedback")
@guard([MENTOR])
def write_feedback(row_id):
    cycle = path_row("cycles", row_id)
    data = body()
    narrative = str_field(data, "narrative", None, 4000)
    codes = enum_list_field(data, "growth_area_codes", calc.GROWTH_CODES,
                            min_items=1, max_items=4, unique=False)
    scores = dict_field(data, "rubric_scores")
    submit = bool_field(data, "submit")
    for key, value in scores.items():
        if key not in calc.RUBRIC_KEYS:
            invalid("rubric_scores contains an unknown key.")
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
            invalid("rubric_scores values must be integers between 1 and 4.")
    match = _match_of(cycle)
    own_mentor(match.get("mentor_id") if match else None)

    phase = cycle.get("phase")
    if submit:
        if phase != "POST_CONFERENCE":
            raise ApiError("ERR_OBSERVATION_PHASE_INVALID")
    elif phase not in ("OBSERVED", "POST_CONFERENCE"):
        raise ApiError("ERR_OBSERVATION_PHASE_INVALID")

    if cycle.get("feedback_review_status") not in ("NONE", "DRAFT", "RETURNED"):
        raise ApiError("ERR_FEEDBACK_STATE_INVALID")

    cycle["narrative"] = narrative
    cycle["growth_area_codes"] = list(codes)
    cycle["rubric_scores"] = dict(scores)
    if all(key in scores for key in calc.RUBRIC_KEYS):
        total = sum(int(scores[key]) for key in calc.RUBRIC_KEYS)
        cycle["composite_rubric_score"] = float(
            calc.round_half_up(Decimal(total) / Decimal(4), 2))
    else:
        cycle["composite_rubric_score"] = None

    if submit:
        if not _feedback_complete(cycle):
            raise ApiError("ERR_FEEDBACK_INCOMPLETE")
        cycle["feedback_review_status"] = "SUBMITTED"
        cycle["return_reason"] = None
    else:
        cycle["feedback_review_status"] = "DRAFT"
    touch(cycle)
    return row_response(cycle)


@bp.post("/observation-cycles/<row_id>/feedback-review")
@guard([ADMIN, LEAD])
def review_feedback(row_id):
    cycle = path_row("cycles", row_id)
    data = body()
    decision = enum_field(data, "decision", ("RETURN", "ACCEPT"))
    return_reason = str_field(data, "return_reason", 1, 1000,
                              required=decision == "RETURN")
    match = _match_of(cycle)
    novice = domain.novice_of_match(match)
    if role() == LEAD and novice is not None:
        own_site(novice.get("site_id"))

    if decision == "ACCEPT" and cycle.get("phase") != "POST_CONFERENCE":
        raise ApiError("ERR_OBSERVATION_PHASE_INVALID")
    if cycle.get("feedback_review_status") != "SUBMITTED":
        raise ApiError("ERR_FEEDBACK_STATE_INVALID")

    if decision == "RETURN":
        if int(cycle.get("return_count") or 0) >= 3:
            raise ApiError("ERR_FEEDBACK_RETURN_LIMIT_REACHED")
        cycle["feedback_review_status"] = "RETURNED"
        cycle["return_reason"] = return_reason
        cycle["return_count"] = int(cycle.get("return_count") or 0) + 1
    else:
        cycle["feedback_review_status"] = "ACCEPTED"
        cycle["return_reason"] = None
    touch(cycle)
    return row_response(cycle)
