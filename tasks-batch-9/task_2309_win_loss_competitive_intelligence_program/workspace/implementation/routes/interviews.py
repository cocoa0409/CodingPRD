"""Interview scheduling, the staging battery, completion and the ledger."""
from datetime import timedelta

from flask import Blueprint, g

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from util import dec, floor_minutes
from validate import (INCENTIVE_STATUS, INTERVIEW_STATUS, QUESTION_KEYS, body,
                      fk_from_body, fk_from_query, opt_int, opt_str, paginate,
                      pagination, present, query_enum, req_dt, req_enum,
                      req_int, req_str, resolve)

from services import calc, cascade, serialize
from services.listing import by_created_at

bp = Blueprint("interviews", __name__)


def get_interview(interview_id):
    return resolve(db.interviews, interview_id, "ERR_INTERVIEW_NOT_FOUND")


def _duration_plus_buffer(interview):
    return floor_minutes(
        interview["scheduled_end_at"] - interview["scheduled_start_at"]
    ) + calc.DEBRIEF_BUFFER_MINUTES


def _same_person_interviews(contact):
    """Every interview of any buyer contact sharing this contact's email."""
    email = contact["email"]
    contact_ids = {c["id"] for c in db.buyer_contacts.values()
                   if c["email"] == email}
    return [i for i in db.interviews.values()
            if i["buyer_contact_id"] in contact_ids]


def _cooling_off_blocked(contact, start_at, exclude_id=None):
    window_start = start_at - timedelta(days=calc.COOLING_OFF_DAYS)
    for other in _same_person_interviews(contact):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] == "COMPLETED":
            instant = other.get("actual_end_at")
        elif other["status"] == "SCHEDULED":
            instant = other["scheduled_start_at"]
        else:
            continue
        if instant is None:
            continue
        if window_start <= instant <= start_at:
            return True
    return False


def _slot_conflict(analyst, start_at, end_at, exclude_id=None):
    buffer_delta = timedelta(minutes=calc.DEBRIEF_BUFFER_MINUTES)
    new_end = end_at + buffer_delta
    for other in calc.interviews_of_analyst(analyst["id"]):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        other_start = other["scheduled_start_at"]
        other_end = other["scheduled_end_at"] + buffer_delta
        if start_at < other_end and other_start < new_end:
            return True
    return False


def _staging_battery(deal, contact, analyst, program, start_at, end_at,
                     interview=None):
    """Precedence 16 -> 20, 22 and 33: the shared scheduling battery."""
    # 16. independence, skipped entirely under ADVISORY mode
    if program["independence_mode"] == "STRICT":
        if analyst["sales_org_member"] or \
                analyst["linked_user_ref"] == deal["sales_rep_user_ref"]:
            fail("ERR_INDEPENDENCE_VIOLATION",
                 "STRICT independence forbids this analyst on this deal.")
    # 17. certification
    if not db.clock < analyst["certified_until"]:
        fail("ERR_ANALYST_NOT_CERTIFIED",
             "The analyst's certification has lapsed.")
    # 18. consent
    if contact["consent_status"] != "GRANTED":
        fail("ERR_CONSENT_NOT_GRANTED",
             "The buyer contact has not granted interview consent.")
    exclude_id = interview["id"] if interview is not None else None
    # 19. buyer cooling-off window
    if _cooling_off_blocked(contact, start_at, exclude_id):
        fail("ERR_CONTACT_COOLING_OFF_ACTIVE",
             "This buyer person is inside the ninety-day cooling-off window.")
    # 20. buffered analyst slot conflict
    if _slot_conflict(analyst, start_at, end_at, exclude_id):
        fail("ERR_ANALYST_SLOT_CONFLICT",
             "The requested interval collides with another interview.")
    # 22. open workload cap
    if not calc.open_interview_count(analyst) < \
            program["max_open_interviews_per_analyst"]:
        fail("ERR_ANALYST_CAPACITY_EXCEEDED",
             "The analyst already holds the maximum open interviews.")
    # 33. incentive budget ceiling
    provisional = calc.incentive_amount(contact, analyst, program, start_at, end_at)
    total = calc.incentive_committed(program) + calc.incentive_paid(program) \
        + provisional
    if total > dec(program["incentive_budget_usd"]):
        fail("ERR_INCENTIVE_BUDGET_EXCEEDED",
             "The interview would push the program past its incentive budget.")
    return provisional


@bp.post("/interviews")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def schedule_interview():
    payload = body()
    deal = fk_from_body(payload, "deal_id", db.deals, "ERR_DEAL_NOT_FOUND")
    contact = fk_from_body(payload, "buyer_contact_id", db.buyer_contacts,
                           "ERR_BUYER_CONTACT_NOT_FOUND")
    analyst = fk_from_body(payload, "analyst_id", db.analysts,
                           "ERR_ANALYST_NOT_FOUND")
    req_str(payload, "deal_id")
    req_str(payload, "buyer_contact_id")
    req_str(payload, "analyst_id")
    start_at = req_dt(payload, "scheduled_start_at")
    end_at = req_dt(payload, "scheduled_end_at")

    # 9. interval well-formedness
    if not start_at < end_at:
        fail("ERR_INVALID_TIME_WINDOW",
             "scheduled_start_at must be strictly before scheduled_end_at.")

    # 10. tenancy
    if contact["deal_id"] != deal["id"]:
        fail("ERR_CROSS_PROGRAM_REFERENCE",
             "The buyer contact does not belong to the named deal.")
    if analyst["program_id"] != deal["program_id"]:
        fail("ERR_CROSS_PROGRAM_REFERENCE",
             "The analyst belongs to a different program.")

    # 13. staging states
    if deal["research_status"] != "SELECTED":
        fail("ERR_DEAL_STATE_INVALID",
             "Only a SELECTED deal can have an interview scheduled.")
    frame = db.sampling_frames.get(deal.get("sampling_frame_id"))
    if frame is None or frame["status"] != "SEALED":
        fail("ERR_FRAME_STATE_INVALID", "The deal's sampling frame must be SEALED.")

    program = db.programs[deal["program_id"]]
    # 14. posture
    if calc.posture(program) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN", "The program's posture is FROZEN.")
    if analyst["status"] != "ACTIVE":
        fail("ERR_ANALYST_IDENTITY_INVALID", "The named analyst is not ACTIVE.")

    provisional = _staging_battery(deal, contact, analyst, program,
                                   start_at, end_at)

    interview = new_row({
        "deal_id": deal["id"],
        "buyer_contact_id": contact["id"],
        "analyst_id": analyst["id"],
        "scheduled_start_at": start_at,
        "scheduled_end_at": end_at,
        "actual_start_at": None,
        "actual_end_at": None,
        "status": "SCHEDULED",
        "incentive_status": "COMMITTED",
        "incentive_provisional_usd": provisional,
        "incentive_final_usd": None,
        "guide_version_pinned": program["guide_version"],
        "required_question_keys_pinned": list(program["required_question_keys"]),
        "coverage_complete": False,
        "reschedule_count": 0,
    })
    db.interviews[interview["id"]] = interview
    touch(program)
    cascade.apply_posture_cascade(program)
    touch(analyst)
    return object_response(serialize.interview(interview), 201)


@bp.get("/interviews/<interview_id>")
@endpoint(ANY_ROLE)
def read_interview(interview_id):
    return object_response(serialize.interview(get_interview(interview_id)))


@bp.get("/interviews")
@endpoint(ANY_ROLE)
def list_interviews():
    deal_id = fk_from_query("deal_id", db.deals, "ERR_DEAL_NOT_FOUND")
    contact_id = fk_from_query("buyer_contact_id", db.buyer_contacts,
                               "ERR_BUYER_CONTACT_NOT_FOUND")
    analyst_id = fk_from_query("analyst_id", db.analysts, "ERR_ANALYST_NOT_FOUND")
    status = query_enum("status", INTERVIEW_STATUS)
    incentive_status = query_enum("incentive_status", INCENTIVE_STATUS)
    limit, offset = pagination()
    rows = list(db.interviews.values())
    if deal_id:
        rows = [i for i in rows if i["deal_id"] == deal_id]
    if contact_id:
        rows = [i for i in rows if i["buyer_contact_id"] == contact_id]
    if analyst_id:
        rows = [i for i in rows if i["analyst_id"] == analyst_id]
    if status:
        rows = [i for i in rows if i["status"] == status]
    if incentive_status:
        rows = [i for i in rows if i["incentive_status"] == incentive_status]
    rows = sorted(by_created_at(rows),
                  key=lambda i: i["scheduled_start_at"].timestamp())
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.interview(r) for r in page],
                         limit, offset, total)


@bp.post("/interviews/<interview_id>/complete")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def complete_interview(interview_id):
    interview = get_interview(interview_id)
    payload = body()
    actual_start_at = req_dt(payload, "actual_start_at")
    actual_end_at = req_dt(payload, "actual_end_at")
    if not actual_start_at < actual_end_at:
        fail("ERR_INVALID_TIME_WINDOW",
             "actual_end_at must be strictly after actual_start_at.")
    if interview["status"] != "SCHEDULED":
        fail("ERR_INTERVIEW_STATE_INVALID",
             "Only a SCHEDULED interview can be completed.")

    deal = db.deals[interview["deal_id"]]
    program = db.programs[deal["program_id"]]
    analyst = db.analysts[interview["analyst_id"]]
    contact = db.buyer_contacts[interview["buyer_contact_id"]]

    # 17. certification
    if not db.clock < analyst["certified_until"]:
        fail("ERR_ANALYST_NOT_CERTIFIED",
             "The analyst's certification has lapsed.")
    # 25. guide coverage against the pinned array
    recorded = {r["question_key"] for r in calc.responses_of_interview(interview["id"])}
    if not set(interview["required_question_keys_pinned"]).issubset(recorded):
        fail("ERR_GUIDE_COVERAGE_INCOMPLETE",
             "The recorded question keys do not cover the pinned guide.")

    final = calc.incentive_amount(contact, analyst, program,
                                  actual_start_at, actual_end_at)
    interview["actual_start_at"] = actual_start_at
    interview["actual_end_at"] = actual_end_at
    interview["coverage_complete"] = True
    interview["incentive_final_usd"] = final
    interview["incentive_status"] = "PAID"
    interview["status"] = "COMPLETED"
    touch(interview)

    touch(program)
    cascade.apply_posture_cascade(program)
    touch(contact)
    deal["research_status"] = "INTERVIEWED"
    touch(deal)
    touch(analyst)
    return object_response(serialize.interview(interview))


@bp.post("/interviews/<interview_id>/no-show")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def no_show_interview(interview_id):
    interview = get_interview(interview_id)
    body()
    if interview["status"] != "SCHEDULED":
        fail("ERR_INTERVIEW_STATE_INVALID",
             "Only a SCHEDULED interview can be marked a no-show.")
    threshold = interview["scheduled_start_at"] + \
        timedelta(minutes=calc.NO_SHOW_GRACE_MINUTES)
    if db.clock < threshold:
        fail("ERR_INTERVIEW_STATE_INVALID",
             "The fifteen-minute grace period has not yet elapsed.")

    deal = db.deals[interview["deal_id"]]
    program = db.programs[deal["program_id"]]
    analyst = db.analysts[interview["analyst_id"]]

    interview["status"] = "NO_SHOW"
    interview["incentive_status"] = "FORFEITED"
    touch(interview)
    touch(program)
    cascade.apply_posture_cascade(program)
    touch(analyst)
    return object_response(serialize.interview(interview))


@bp.post("/interviews/<interview_id>/reschedule")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def reschedule_interview(interview_id):
    interview = get_interview(interview_id)
    payload = body()
    start_at = req_dt(payload, "scheduled_start_at")
    end_at = req_dt(payload, "scheduled_end_at")
    if not start_at < end_at:
        fail("ERR_INVALID_TIME_WINDOW",
             "scheduled_start_at must be strictly before scheduled_end_at.")
    if interview["status"] != "NO_SHOW":
        fail("ERR_INTERVIEW_STATE_INVALID",
             "Only a NO_SHOW interview can be rescheduled.")

    deal = db.deals[interview["deal_id"]]
    program = db.programs[deal["program_id"]]
    analyst = db.analysts[interview["analyst_id"]]
    contact = db.buyer_contacts[interview["buyer_contact_id"]]

    if calc.posture(program) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN", "The program's posture is FROZEN.")

    provisional = _staging_battery(deal, contact, analyst, program,
                                   start_at, end_at, interview=interview)

    # 36. the reschedule ceiling is the last gate on the cycle
    if not interview["reschedule_count"] < calc.MAX_RESCHEDULES:
        fail("ERR_RESCHEDULE_LIMIT_REACHED",
             "This interview has already been rescheduled twice.")

    interview["scheduled_start_at"] = start_at
    interview["scheduled_end_at"] = end_at
    interview["reschedule_count"] = interview["reschedule_count"] + 1
    interview["incentive_provisional_usd"] = provisional
    interview["incentive_status"] = "COMMITTED"
    interview["status"] = "SCHEDULED"
    touch(interview)
    touch(program)
    cascade.apply_posture_cascade(program)
    touch(analyst)
    return object_response(serialize.interview(interview))


@bp.post("/interviews/<interview_id>/cancel")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def cancel_interview(interview_id):
    interview = get_interview(interview_id)
    payload = body()
    opt_str(payload, "cancel_reason", allow_empty=True)
    if interview["status"] not in ("SCHEDULED", "NO_SHOW"):
        fail("ERR_INTERVIEW_STATE_INVALID",
             "Only a SCHEDULED or NO_SHOW interview can be cancelled.")

    was_scheduled = interview["status"] == "SCHEDULED"
    deal = db.deals[interview["deal_id"]]
    program = db.programs[deal["program_id"]]
    analyst = db.analysts[interview["analyst_id"]]

    interview["status"] = "CANCELLED"
    if was_scheduled:
        interview["incentive_status"] = "RELEASED"
    touch(interview)
    if was_scheduled:
        # compensating transition: the ledger returns to its pre-scheduling value
        touch(program)
        cascade.apply_posture_cascade(program)
        touch(analyst)
    return object_response(serialize.interview(interview))


# ------------------------------------------------------------------- responses
@bp.post("/interviews/<interview_id>/responses")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def record_response(interview_id):
    interview = get_interview(interview_id)
    payload = body()
    question_key = req_enum(payload, "question_key", QUESTION_KEYS)
    verbatim_text = req_str(payload, "verbatim_text")
    recorded_at = req_dt(payload, "recorded_at")
    rating = None
    if present(payload, "rating"):
        rating = req_int(payload, "rating")
    competitor_name = opt_str(payload, "competitor_name_verbatim", allow_empty=True)

    if rating is not None and (rating < 1 or rating > 5):
        fail("ERR_VALUE_OUT_OF_RANGE", "rating must be an integer from 1 through 5.")
    if interview["status"] != "SCHEDULED":
        fail("ERR_INTERVIEW_STATE_INVALID",
             "Answers may only be recorded while the interview is SCHEDULED.")

    response = new_row({
        "interview_id": interview["id"],
        "question_key": question_key,
        "verbatim_text": verbatim_text,
        "rating": rating,
        "competitor_name_verbatim": competitor_name,
        "recorded_at": recorded_at,
    })
    db.interview_responses[response["id"]] = response
    return object_response(serialize.interview_response(response), 201)


@bp.get("/interviews/<interview_id>/responses")
@endpoint(ANY_ROLE)
def list_interview_responses(interview_id):
    interview = get_interview(interview_id)
    question_key = query_enum("question_key", QUESTION_KEYS)
    limit, offset = pagination()
    rows = calc.responses_of_interview(interview["id"])
    if question_key:
        rows = [r for r in rows if r["question_key"] == question_key]
    rows = sorted(by_created_at(rows), key=lambda r: r["recorded_at"].timestamp())
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.interview_response(r) for r in page],
                         limit, offset, total)


@bp.get("/interview-responses/<response_id>")
@endpoint(ANY_ROLE)
def read_response(response_id):
    response = resolve(db.interview_responses, response_id,
                       "ERR_INTERVIEW_RESPONSE_NOT_FOUND")
    return object_response(serialize.interview_response(response))


@bp.get("/interview-responses")
@endpoint(ANY_ROLE)
def list_responses():
    interview_id = fk_from_query("interview_id", db.interviews,
                                 "ERR_INTERVIEW_NOT_FOUND")
    question_key = query_enum("question_key", QUESTION_KEYS)
    limit, offset = pagination()
    rows = list(db.interview_responses.values())
    if interview_id:
        rows = [r for r in rows if r["interview_id"] == interview_id]
    if question_key:
        rows = [r for r in rows if r["question_key"] == question_key]
    rows = sorted(by_created_at(rows), key=lambda r: r["recorded_at"].timestamp())
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.interview_response(r) for r in page],
                         limit, offset, total)
