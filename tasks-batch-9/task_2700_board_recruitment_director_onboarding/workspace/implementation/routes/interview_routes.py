"""Interview sessions: the interviewer's calendar and the interview rollups."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    SEATED_DIRECTOR,
    require,
)
from derive import (
    _apply,
    recompute_candidate_interviews,
    recompute_readiness,
)
from errors import fail
from payload import (
    body,
    check_enum,
    check_interval_after,
    check_range,
    optional,
    parse_dt,
    required,
)
from store import clock_instant, db, new_row, touch
from vocab import INTERVIEW_MODALITY, INTERVIEW_RECOMMENDATION, INTERVIEW_RESOLUTION

from routes.common import apply_filters, by_field, emit, emit_list, need

bp = Blueprint("interview", __name__)

READ_ROLES = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER,
              SEATED_DIRECTOR)
STAFF = (GOVERNANCE_STAFF, CORPORATE_SECRETARY)

OCCUPYING = ("SCHEDULED", "COMPLETED")
INTERVIEWABLE = ("SCREEN_PASSED", "INTERVIEWING")
LIVE_NOMINEE = ("PROPOSED", "CONFIRMED", "ELECTED")


def _ballot_conflict(director_id, candidate_id):
    """True when this director already balloted on a slate carrying this candidate."""
    slate_ids = set()
    for nominee in db.nominees.values():
        if nominee.get("candidate_id") == candidate_id and nominee["status"] != "VOIDED":
            slate_ids.add(nominee["slate_id"])
    if not slate_ids:
        return False
    for vote in db.votes.values():
        if vote["status"] == "CAST" and vote["voting_director_id"] == director_id \
                and vote["slate_id"] in slate_ids:
            return True
    return False


@bp.post("/interviews")
def schedule_interview():
    require(*STAFF)
    b = body()
    candidate_id = required(b, "candidate_id", "string")
    interviewer_id = required(b, "interviewer_director_id", "string")
    start_at = required(b, "start_at", "string")
    end_at = required(b, "end_at", "string")
    modality = check_enum("modality", optional(b, "modality", "string", "VIDEO"),
                          INTERVIEW_MODALITY)
    start_dt = parse_dt(start_at, "start_at")
    end_dt = parse_dt(end_at, "end_at")
    check_interval_after(end_dt, start_dt, "end_at must be strictly after start_at.")
    candidate = need("candidate", candidate_id)
    need("director", interviewer_id)
    if candidate["status"] not in INTERVIEWABLE:
        fail("ERR_CANDIDATE_STATE_INVALID",
             "Interviews may only be scheduled from SCREEN_PASSED or INTERVIEWING; this "
             "candidate is %s." % candidate["status"])
    if candidate.get("referring_director_id") == interviewer_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A director may not interview a candidate whose nomination they proposed.")
    if _ballot_conflict(interviewer_id, candidate_id):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "This director has already balloted on a slate carrying this candidate.")
    for session in db.interviews.values():
        if session["interviewer_director_id"] != interviewer_id:
            continue
        if session["status"] not in OCCUPYING:
            continue
        other_start = parse_dt(session["start_at"], "start_at")
        other_end = parse_dt(session["end_at"], "end_at")
        if start_dt < other_end and other_start < end_dt:
            fail("ERR_INTERVIEWER_DOUBLE_BOOKED",
                 "The interviewer already holds a session overlapping that window.")

    if candidate["status"] == "SCREEN_PASSED":
        round_number = candidate["interview_round"] + 1
    else:
        round_number = candidate["interview_round"]
    row = new_row({
        "candidate_id": candidate_id,
        "interviewer_director_id": interviewer_id,
        "start_at": start_at,
        "end_at": end_at,
        "modality": modality,
        "interview_round": round_number,
        "score": None,
        "recommendation": None,
        "status": "SCHEDULED",
        "completed_at": None,
    })
    db.interviews[row["id"]] = row
    if candidate["status"] == "SCREEN_PASSED":
        # The first session of a round opens that round on the candidate too, so a
        # later session "inside the same round" reads the candidate's current
        # interview_round and lands on the same number.
        _apply(candidate, {"status": "INTERVIEWING", "interview_round": round_number})
    return emit(row, 201)


@bp.get("/interviews/<interview_id>")
def read_interview(interview_id):
    require(*READ_ROLES)
    return emit(need("interview", interview_id))


@bp.get("/interviews")
def list_interviews():
    require(*READ_ROLES)
    rows = apply_filters(list(db.interviews.values()), {
        "candidate_id": ("candidate_id", "str"),
        "interviewer_director_id": ("interviewer_director_id", "str"),
        "status": ("status", "str"),
    })
    return emit_list(by_field(rows, "start_at"))


@bp.post("/interviews/<interview_id>/complete")
def complete_interview(interview_id):
    require(GOVERNANCE_STAFF, CORPORATE_SECRETARY, SEATED_DIRECTOR)
    b = body()
    score = required(b, "score", "integer")
    recommendation = required(b, "recommendation", "string")
    check_enum("recommendation", recommendation, INTERVIEW_RECOMMENDATION)
    check_range("score", score, 1, 5)
    session = need("interview", interview_id)
    if session["status"] != "SCHEDULED":
        fail("ERR_INTERVIEW_STATE_INVALID",
             "Only a SCHEDULED session may be completed; this one is %s." % session["status"])
    session["score"] = score
    session["recommendation"] = recommendation
    session["status"] = "COMPLETED"
    session["completed_at"] = clock_instant()
    touch(session)
    candidate = db.candidates.get(session["candidate_id"])
    if candidate is not None:
        recompute_candidate_interviews(candidate)
        recompute_readiness(candidate)
    return emit(session)


@bp.post("/interviews/<interview_id>/cancel")
def cancel_interview(interview_id):
    require(*STAFF)
    b = body()
    resolution = required(b, "resolution", "string")
    check_enum("resolution", resolution, INTERVIEW_RESOLUTION)
    session = need("interview", interview_id)
    if session["status"] != "SCHEDULED":
        fail("ERR_INTERVIEW_STATE_INVALID",
             "Only a SCHEDULED session may be closed; this one is %s." % session["status"])
    session["status"] = resolution
    touch(session)
    return emit(session)
