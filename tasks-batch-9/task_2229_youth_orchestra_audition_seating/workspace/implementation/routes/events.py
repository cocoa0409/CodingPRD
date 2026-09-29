"""The rehearsal calendar, attendance, eligibility, programming and tours."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import services as svc
from auth import ALL_ROLES, acting, endpoint, require_guardian_owns
from envelope import ok, ok_list
from errors import ApiError
from store import clock_now, db
from validate import Body, bad, pagination

bp = Blueprint("events", __name__)

EVENT_KINDS = ("REHEARSAL", "CONCERT", "TOUR_PERFORMANCE", "FESTIVAL")
PERFORMANCE_KINDS = ("CONCERT", "TOUR_PERFORMANCE", "FESTIVAL")
TOUR_KINDS = ("TOUR_PERFORMANCE", "FESTIVAL")
RECORDABLE = ("PRESENT", "TARDY", "ABSENCE_UNVERIFIED", "UNEXCUSED_ABSENT")
EXCUSE_REASONS = ("NONE", "ILLNESS", "ACADEMIC_CONFLICT", "FAMILY", "TRANSPORT")


# --------------------------------------------------------------- ensemble events
@bp.route("/ensemble-events", methods=["POST"])
@endpoint("ArtisticDirector")
def create_event():
    body = Body()
    ensemble_id = body.string("ensemble_id", required=True)
    kind = body.enum("kind", EVENT_KINDS, required=True)
    start_at = body.datetime("start_at", required=True)
    end_at = body.datetime("end_at", required=True)
    venue_code = body.string("venue_code", required=True, min_len=1, max_len=64)
    is_dress = body.boolean("is_dress_rehearsal", default=False)
    dress_required = body.boolean("dress_rehearsal_required", default=False)
    window_start = body.datetime("eligibility_window_start", required=False)
    mode = body.enum("soloist_selection_mode", ("AUTO_SELECT", "MANUAL", "NONE"),
                     required=False, default="AUTO_SELECT")
    cost_share = body.integer("tour_cost_share_cents", required=False, default=0,
                              minimum=0)
    chaperone_required = body.boolean("chaperone_required", default=False)
    if end_at <= start_at:
        bad("end_at must be strictly later than start_at.")
    if kind in PERFORMANCE_KINDS and window_start is None:
        bad("eligibility_window_start is required for performance events.")

    ensemble = svc.ensemble_or_404(ensemble_id)

    row = svc.new_row()
    row.update({
        "ensemble_id": ensemble["id"],
        "kind": kind,
        "start_at": start_at,
        "end_at": end_at,
        "venue_code": venue_code,
        "is_dress_rehearsal": is_dress,
        "dress_rehearsal_required": dress_required,
        "eligibility_window_start": window_start,
        "soloist_selection_mode": mode,
        "soloist_member_id": None,
        "guest_artist_name": None,
        "guest_artist_fee_cents": 0,
        "programming_state": "DRAFT",
        "tour_cost_share_cents": cost_share,
        "chaperone_required": chaperone_required,
    })
    db.ensemble_events[row["id"]] = row
    return ok(svc.event_json(row), 201)


@bp.route("/ensemble-events", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_events():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.ensemble_events.values())),
                             request.args,
                             ["ensemble_id", "soloist_member_id", "kind",
                              "programming_state"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.event_json(r) for r in page], limit, offset, len(rows))


@bp.route("/ensemble-events/<event_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_event(event_id):
    return ok(svc.event_json(svc.event_or_404(event_id)))


@bp.route("/ensemble-events/<event_id>/programming", methods=["POST"])
@endpoint("ArtisticDirector")
def programming(event_id):
    event = svc.event_or_404(event_id)
    body = Body()
    soloist_id = body.string("soloist_member_id", required=False)
    guest_name = body.string("guest_artist_name", required=False)
    guest_fee = body.integer("guest_artist_fee_cents", required=False, minimum=0)
    soloist = svc.member_or_404(soloist_id) if soloist_id is not None else None

    if event["kind"] == "REHEARSAL" or event["programming_state"] == "PROGRAMMED":
        raise ApiError("ERR_EVENT_NOT_PROGRAMMABLE",
                       "This event cannot be programmed.")

    chosen_id = None
    mode = event["soloist_selection_mode"]
    if mode == "MANUAL":
        if soloist is None or not _manual_soloist_ok(event, soloist):
            raise ApiError("ERR_SOLOIST_NOT_ELIGIBLE",
                           "The named soloist is not eligible for this event.")
        chosen_id = soloist["id"]
    elif mode == "AUTO_SELECT":
        pool = svc.soloist_candidates(event)
        if not pool:
            raise ApiError("ERR_NO_ELIGIBLE_SOLOIST",
                           "No eligible soloist could be selected.")
        chosen_id = pool[0][1]["id"]

    if guest_fee is not None:
        if guest_fee > calc.GUEST_ARTIST_FEE_CAP_CENTS:
            raise ApiError("ERR_GUEST_ARTIST_FEE_CAP_EXCEEDED",
                           "The guest-artist fee exceeds the cap.")
        if guest_fee > 0 and not guest_name:
            raise ApiError("ERR_GUEST_ARTIST_FEE_CAP_EXCEEDED",
                           "A guest-artist fee requires a guest_artist_name.")

    event["soloist_member_id"] = chosen_id
    if guest_name is not None:
        event["guest_artist_name"] = guest_name
    if guest_fee is not None:
        event["guest_artist_fee_cents"] = guest_fee
    event["programming_state"] = "PROGRAMMED"
    svc.touch(event)
    return ok(svc.event_json(event))


def _manual_soloist_ok(event, member):
    if member["standing_status"] != "CLEAR":
        return False
    quota_ids = set(q["id"] for q in svc.quotas_of_ensemble(event["ensemble_id"]))
    seated = any(s["section_quota_id"] in quota_ids
                 for s in svc.active_seats_of_member(member["id"]))
    if not seated:
        return False
    for row in svc.participations_of_event(event["id"]):
        if row["member_id"] == member["id"]:
            return row["performance_eligibility"] == "ELIGIBLE"
    return False


# ----------------------------------------------------------- event participations
@bp.route("/event-participations", methods=["POST"])
@endpoint("RegistrarStaff")
def create_participation():
    body = Body()
    event_id = body.string("event_id", required=True)
    member_id = body.string("member_id", required=True)
    event = svc.event_or_404(event_id)
    member = svc.member_or_404(member_id)

    for other in db.event_participations.values():
        if other["event_id"] == event["id"] and other["member_id"] == member["id"]:
            raise ApiError("ERR_DUPLICATE_PARTICIPATION",
                           "This musician is already rostered onto the event.")

    for other in svc.participations_of_member(member["id"]):
        other_event = db.ensemble_events[other["event_id"]]
        if other_event["id"] == event["id"]:
            continue
        if (event["start_at"] < other_event["end_at"]
                and other_event["start_at"] < event["end_at"]):
            raise ApiError("ERR_MEMBER_EVENT_CONFLICT",
                           "The musician is already booked over that interval.")

    quota_ids = set(q["id"] for q in svc.quotas_of_ensemble(event["ensemble_id"]))
    seated = any(s["section_quota_id"] in quota_ids
                 for s in svc.active_seats_of_member(member["id"]))
    if not seated:
        raise ApiError("ERR_MEMBER_NOT_IN_ENSEMBLE",
                       "The musician holds no chair in this ensemble.")

    row = svc.new_row()
    row.update({
        "event_id": event["id"],
        "member_id": member["id"],
        "attendance_status": "NOT_RECORDED",
        "excuse_reason_code": "NONE",
        "excuse_documentation_ref": None,
        "excuse_decided_by_user_id": None,
        "performance_eligibility": "UNREVIEWED",
        "ineligibility_reason": "NONE",
        "attendance_index": None,
        "fundraising_credited_cents": 0,
        "fundraising_shortfall_cents": 0,
        "chaperone_name": None,
        "chaperone_background_check_ref": None,
        "chaperone_confirmed": False,
        "tour_status": "PENDING" if event["kind"] in TOUR_KINDS else "NOT_APPLICABLE",
        "_attendance_recorded_by_user_id": None,
    })
    db.event_participations[row["id"]] = row
    svc.touch(event)
    return ok(svc.participation_json(row), 201)


@bp.route("/event-participations", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_participations():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.event_participations.values())),
                             request.args,
                             ["event_id", "member_id", "attendance_status",
                              "performance_eligibility", "tour_status"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.participation_json(r) for r in page], limit, offset, len(rows))


@bp.route("/event-participations/<participation_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_participation(participation_id):
    return ok(svc.participation_json(svc.participation_or_404(participation_id)))


@bp.route("/event-participations/<participation_id>/attendance", methods=["POST"])
@endpoint("RegistrarStaff")
def record_attendance(participation_id):
    row = svc.participation_or_404(participation_id)
    body = Body()
    status = body.enum("attendance_status", RECORDABLE, required=True)

    if row["attendance_status"] != "NOT_RECORDED":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "Attendance has already been recorded on this row.")
    event = db.ensemble_events[row["event_id"]]
    if clock_now() < event["start_at"]:
        raise ApiError("ERR_EVENT_NOT_STARTED",
                       "The event has not started yet.")

    user_id, _role = acting()
    row["attendance_status"] = status
    row["_attendance_recorded_by_user_id"] = user_id
    svc.touch(row)

    if status in ("TARDY", "UNEXCUSED_ABSENT"):
        svc.attendance_cascade(db.members[row["member_id"]])
    return ok(svc.participation_json(row))


@bp.route("/event-participations/<participation_id>/excuse-request", methods=["POST"])
@endpoint("Guardian")
def excuse_request(participation_id):
    row = svc.participation_or_404(participation_id)
    require_guardian_owns(row["member_id"])
    body = Body()
    reason = body.enum("excuse_reason_code", EXCUSE_REASONS, required=True)
    doc_ref = body.string("excuse_documentation_ref", required=False, max_len=200)

    if row["attendance_status"] != "ABSENCE_UNVERIFIED":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "Only an unverified absence may be excused.")
    event = db.ensemble_events[row["event_id"]]
    deadline = event["end_at"] + timedelta(hours=calc.EXCUSE_REQUEST_WINDOW_HOURS)
    if not clock_now() < deadline:
        raise ApiError("ERR_EXCUSE_WINDOW_CLOSED",
                       "The excuse window has closed.")

    row["attendance_status"] = "EXCUSE_PENDING"
    row["excuse_reason_code"] = reason
    if doc_ref is not None:
        row["excuse_documentation_ref"] = doc_ref
    svc.touch(row)
    return ok(svc.participation_json(row))


@bp.route("/event-participations/<participation_id>/excuse-decision", methods=["POST"])
@endpoint("RegistrarStaff")
def excuse_decision(participation_id):
    row = svc.participation_or_404(participation_id)
    body = Body()
    decision = body.enum("decision", ("APPROVED", "DENIED"), required=True)

    if row["attendance_status"] != "EXCUSE_PENDING":
        raise ApiError("ERR_INVALID_STATE_FOR_OPERATION",
                       "No excuse is pending on this row.")

    user_id, _role = acting()
    if (user_id == row.get("_attendance_recorded_by_user_id")
            or user_id == row.get("excuse_decided_by_user_id")):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The registrar who recorded the absence may not decide it.")

    row["excuse_decided_by_user_id"] = user_id
    if decision == "APPROVED":
        row["attendance_status"] = "EXCUSED_ABSENT"
        svc.touch(row)
    else:
        row["attendance_status"] = "UNEXCUSED_ABSENT"
        svc.touch(row)
        svc.attendance_cascade(db.members[row["member_id"]])
    return ok(svc.participation_json(row))


@bp.route("/event-participations/<participation_id>/eligibility-review",
          methods=["POST"])
@endpoint("ArtisticDirector")
def eligibility_review(participation_id):
    row = svc.participation_or_404(participation_id)
    event = db.ensemble_events[row["event_id"]]
    if event["kind"] not in PERFORMANCE_KINDS:
        raise ApiError("ERR_EVENT_KIND_NOT_ELIGIBLE",
                       "A rehearsal carries no performance eligibility.")

    index, dress_ok = svc.compute_attendance_index(row, event)
    member = db.members[row["member_id"]]
    row["attendance_index"] = index

    reason = None
    if index < calc.ATTENDANCE_ELIGIBILITY_THRESHOLD:
        reason = "ATTENDANCE_INDEX_BELOW_THRESHOLD"
    elif event["dress_rehearsal_required"] and not dress_ok:
        reason = "DRESS_REHEARSAL_MISSED"
    elif member["standing_status"] == "ATTENDANCE_PROBATION":
        reason = "MEMBER_ON_PROBATION"

    if reason is None:
        row["performance_eligibility"] = "ELIGIBLE"
        row["ineligibility_reason"] = "NONE"
    else:
        row["performance_eligibility"] = "INELIGIBLE"
        row["ineligibility_reason"] = reason
        if row["tour_status"] == "READY":
            row["tour_status"] = "PENDING"
    svc.touch(row)
    return ok(svc.participation_json(row))


@bp.route("/event-participations/<participation_id>/tour-requirements",
          methods=["POST"])
@endpoint("Guardian")
def tour_requirements(participation_id):
    row = svc.participation_or_404(participation_id)
    require_guardian_owns(row["member_id"])
    body = Body()
    amount = body.integer("fundraising_amount_cents", required=False, minimum=0)
    chaperone_name = body.string("chaperone_name", required=False, max_len=200)
    check_ref = body.string("chaperone_background_check_ref", required=False,
                            max_len=200)

    event = db.ensemble_events[row["event_id"]]
    if event["kind"] not in TOUR_KINDS:
        raise ApiError("ERR_EVENT_KIND_NOT_ELIGIBLE",
                       "Only a tour performance or festival carries tour readiness.")

    credited = row["fundraising_credited_cents"] + (amount or 0)
    shortfall = max(0, event["tour_cost_share_cents"] - credited)
    name = chaperone_name if chaperone_name is not None else row["chaperone_name"]
    ref = check_ref if check_ref is not None else row["chaperone_background_check_ref"]
    confirmed = bool(name) and bool(ref)

    if (shortfall != 0
            or (event["chaperone_required"] and not confirmed)
            or row["performance_eligibility"] != "ELIGIBLE"):
        raise ApiError("ERR_TOUR_REQUIREMENTS_UNMET",
                       "The tour readiness requirements are not satisfied.")

    row["fundraising_credited_cents"] = credited
    row["fundraising_shortfall_cents"] = shortfall
    row["chaperone_name"] = name
    row["chaperone_background_check_ref"] = ref
    row["chaperone_confirmed"] = confirmed
    row["tour_status"] = "READY"
    svc.touch(row)
    return ok(svc.participation_json(row))
