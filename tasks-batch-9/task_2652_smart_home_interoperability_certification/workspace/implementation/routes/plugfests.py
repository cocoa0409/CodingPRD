"""Plugfests and interoperability credits (PRD 3.7)."""

from flask import Blueprint

import cascade
import common as C
import enums as E
import middleware as M
import queries as Q
import shape as S
from db import new_row, now, ordered, set_fields, store
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("plugfests", __name__)

PARTICIPATION_READ_ROLES = M.NON_PUBLIC_READ


def _on_minute(value):
    return value.second == 0 and value.microsecond == 0


@bp.post("/plugfests")
def create_plugfest():
    M.auth([M.PROGRAM_ADMIN])
    body = S.body_obj()
    # rung 5
    lab = C.body_fk("laboratory", body, "host_laboratory_id")
    spec = C.body_fk("specification", body, "specification_id")
    # rung 6
    S.req_str(body, "host_laboratory_id")
    S.req_str(body, "specification_id")
    window_start = S.req_dt(body, "window_start")
    window_end = S.req_dt(body, "window_end")
    registration_deadline = S.req_dt(body, "registration_deadline")
    min_distinct_vendors = S.req_int(body, "min_distinct_vendors", 2, 8)
    # rung 8
    if not window_end > window_start or not _on_minute(window_start) or not _on_minute(window_end):
        raise ApiError("ERR_INVALID_WINDOW_BOUNDS",
                       "window_end must be after window_start and both must fall on a minute boundary")
    # rung 9
    if registration_deadline > window_start:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "registration_deadline must be at or before window_start")
    # rung 13
    if spec["status"] != "RATIFIED":
        raise ApiError("ERR_INVALID_SPECIFICATION_STATE",
                       "a plugfest requires a RATIFIED specification")
    # rung 15
    if lab["accreditation_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_LABORATORY_STATE",
                       "the host laboratory must be AUTHORIZED")

    plugfest = new_row(
        host_laboratory_id=lab["id"],
        specification_id=spec["id"],
        window_start=window_start,
        window_end=window_end,
        registration_deadline=registration_deadline,
        min_distinct_vendors=min_distinct_vendors,
        state="REGISTRATION_OPEN",
        distinct_vendor_count=0,
        locked_at=None,
    )
    store.plugfests[plugfest["id"]] = plugfest
    return object_response(public(plugfest), 201)


@bp.get("/plugfests/<plugfest_id>")
def get_plugfest(plugfest_id):
    M.auth(M.ALL_ROLES)
    return object_response(public(C.must("plugfest", plugfest_id)), 200)


@bp.get("/plugfests")
def list_plugfests():
    M.auth(M.ALL_ROLES)
    limit, offset = S.paging()
    host_laboratory_id = S.q_str("host_laboratory_id")
    specification_id = S.q_str("specification_id")
    state = S.q_str("state")
    rows = ordered(store.plugfests.values())
    if host_laboratory_id is not None:
        rows = [r for r in rows if r["host_laboratory_id"] == host_laboratory_id]
    if specification_id is not None:
        rows = [r for r in rows if r["specification_id"] == specification_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/plugfests/<plugfest_id>/lock")
def lock_plugfest(plugfest_id):
    M.auth([M.PROGRAM_ADMIN])
    plugfest = C.must("plugfest", plugfest_id)
    # rung 20
    if plugfest["state"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_INVALID_PLUGFEST_STATE", "locking requires REGISTRATION_OPEN")
    # rung 42
    if plugfest["distinct_vendor_count"] < plugfest["min_distinct_vendors"]:
        raise ApiError("ERR_INSUFFICIENT_DISTINCT_VENDORS", "the vendor quorum is not met")
    set_fields(plugfest, state="LOCKED", locked_at=now())
    return object_response(public(plugfest), 200)


@bp.post("/plugfests/<plugfest_id>/close")
def close_plugfest(plugfest_id):
    M.auth([M.PROGRAM_ADMIN])
    plugfest = C.must("plugfest", plugfest_id)
    # rung 20
    if plugfest["state"] != "LOCKED":
        raise ApiError("ERR_INVALID_PLUGFEST_STATE", "closing requires LOCKED")
    set_fields(plugfest, state="CLOSED")
    for participation in Q.participations_for_plugfest(plugfest["id"]):
        if participation["state"] == "REGISTERED":
            set_fields(participation, state="NO_SHOW")
    cascade.recompute_distinct_vendors(plugfest)
    return object_response(public(plugfest), 200)


# ------------------------------------------------------------- participations

def _date_range(plugfest):
    return plugfest["window_start"].date(), plugfest["window_end"].date()


@bp.post("/plugfest-participations")
def create_participation():
    user_id, _ = M.auth([M.MEMBER])
    body = S.body_obj()
    # rung 3
    raw_member_id = body.get("member_id")
    if isinstance(raw_member_id, str):
        M.own(user_id, raw_member_id)
    # rung 5
    plugfest = C.body_fk("plugfest", body, "plugfest_id")
    member = C.body_fk("member", body, "member_id")
    submission = C.body_fk("submission", body, "submission_id")
    # rung 6
    S.req_str(body, "plugfest_id")
    S.req_str(body, "member_id")
    S.req_str(body, "submission_id")
    device_model = S.req_str(body, "device_model", 1, 80)
    # rung 3 (continued) -- the submission must belong to the acting member
    M.own(user_id, submission["member_id"])
    # rung 20
    if plugfest["state"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_INVALID_PLUGFEST_STATE", "registration requires REGISTRATION_OPEN")
    # rung 25
    if not member["good_standing"]:
        raise ApiError("ERR_MEMBER_NOT_IN_GOOD_STANDING", "the member is not in good standing")
    # rung 34
    if submission["specification_id"] != plugfest["specification_id"]:
        raise ApiError("ERR_DEVICE_TYPE_MISMATCH",
                       "the submission is pinned to a different specification")
    # rung 39 -- inclusive UTC calendar-date overlap against other plugfests
    start, end = _date_range(plugfest)
    for other in Q.participations_for_submission(submission["id"]):
        if other["plugfest_id"] == plugfest["id"]:
            continue
        if other["state"] not in ("REGISTERED", "PASSED", "FAILED"):
            continue
        other_event = store.plugfests.get(other["plugfest_id"])
        if other_event is None:
            continue
        o_start, o_end = _date_range(other_event)
        if start <= o_end and end >= o_start:
            raise ApiError("ERR_PARTICIPATION_WINDOW_CONFLICT",
                           "the device is already booked on an overlapping calendar date")
    # rung 40
    for other in Q.participations_for_plugfest(plugfest["id"]):
        if other["submission_id"] == submission["id"]:
            raise ApiError("ERR_DUPLICATE_PARTICIPATION",
                           "this submission is already registered for the event")
    # rung 41
    if now() > plugfest["registration_deadline"]:
        raise ApiError("ERR_REGISTRATION_CLOSED", "the registration deadline has passed")

    participation = new_row(
        plugfest_id=plugfest["id"],
        member_id=member["id"],
        submission_id=submission["id"],
        device_model=device_model,
        state="REGISTERED",
        interop_pass_count=0,
        outcome_recorded_at=None,
    )
    store.participations[participation["id"]] = participation
    cascade.recompute_distinct_vendors(plugfest)
    return object_response(public(participation), 201)


@bp.get("/plugfest-participations/<participation_id>")
def get_participation(participation_id):
    M.auth(PARTICIPATION_READ_ROLES)
    return object_response(public(C.must("participation", participation_id)), 200)


@bp.get("/plugfest-participations")
def list_participations():
    M.auth(PARTICIPATION_READ_ROLES)
    limit, offset = S.paging()
    plugfest_id = S.q_str("plugfest_id")
    member_id = S.q_str("member_id")
    submission_id = S.q_str("submission_id")
    state = S.q_str("state")
    rows = ordered(store.participations.values())
    if plugfest_id is not None:
        rows = [r for r in rows if r["plugfest_id"] == plugfest_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if submission_id is not None:
        rows = [r for r in rows if r["submission_id"] == submission_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/plugfest-participations/<participation_id>/record-outcome")
def record_outcome(participation_id):
    user_id, _ = M.auth([M.TEST_LABORATORY])
    participation = C.must("participation", participation_id)
    plugfest = store.plugfests[participation["plugfest_id"]]
    M.own(user_id, plugfest["host_laboratory_id"])
    body = S.body_obj()
    # rung 6
    outcome = S.req_str(body, "outcome")
    interop_pass_count = S.req_int(body, "interop_pass_count", 0, 8)
    if outcome == "PASS" and interop_pass_count < 1:
        S.bad("interop_pass_count must be at least 1 when outcome is PASS")
    # rung 7
    S.check_enum(outcome, E.PARTICIPATION_OUTCOMES, "outcome")
    # rung 20
    if plugfest["state"] != "LOCKED":
        raise ApiError("ERR_INVALID_PLUGFEST_STATE", "outcomes are recorded only while LOCKED")
    # rung 21
    if participation["state"] != "REGISTERED":
        raise ApiError("ERR_INVALID_PARTICIPATION_STATE", "the outcome is already recorded")

    set_fields(participation,
               state="PASSED" if outcome == "PASS" else "FAILED",
               interop_pass_count=interop_pass_count,
               outcome_recorded_at=now())
    submission = store.submissions[participation["submission_id"]]
    if outcome == "PASS":
        cascade.apply_plugfest_pass(submission)
    cascade.recompute_distinct_vendors(plugfest)
    return object_response(public(participation), 200)
