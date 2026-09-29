"""Complaints, consent agreements and hearings."""
from datetime import timedelta

from flask import Blueprint

import cascades
import computed
import envelope
import serialize
import shape
import store
from authz import guard
from errors import fail, invalid

bp = Blueprint("discipline", __name__)


# ----------------------------------------------------------------- complaints
@bp.post("/commission/complaints")
def file_complaint():
    guard(["Public", "LicensingAnalyst", "CommissionCounsel"])
    data = shape.body()
    complainant_name = shape.req_str(data, "complainant_name")
    respondent_licensee_id = shape.req_id(data, "respondent_licensee_id")
    allegation_type = shape.req_enum(data, "allegation_type", computed.ALLEGATION_TYPES)
    alleged_loss_cents = shape.req_int(data, "alleged_loss_cents", minimum=0)
    shape.opt_str(data, "narrative")

    respondent = computed.must("licensee", respondent_licensee_id)
    brokerage_id = respondent.get("sponsoring_brokerage_id")
    snap = cascades.posture_snapshot(brokerage_id)
    moment = store.now()
    row = store.insert("complaint", {
        "case_number": store.next_case_number(),
        "complainant_name": complainant_name,
        "respondent_licensee_id": respondent["id"],
        "respondent_brokerage_id": brokerage_id,
        "source_audit_id": None,
        "allegation_type": allegation_type,
        "alleged_loss_cents": alleged_loss_cents,
        "filed_at": store.fmt_dt(moment),
        "statute_deadline_at": store.fmt_dt(
            moment + timedelta(seconds=computed.STATUTE_DAYS * 86400)),
        "status": "SUBMITTED",
        "screener_user_id": None,
        "investigator_user_id": None,
        "amendment_count": 0,
    })
    cascades.settle(snap)
    return envelope.created(serialize.complaint(row))


DISPOSITIONS = {"INVESTIGATE", "DISMISS", "REQUEST_AMENDMENT", "PROBABLE_CAUSE",
                "CLOSE_NO_ACTION"}


@bp.post("/commission/complaints/<cid>/disposition")
def dispose_complaint(cid):
    user_id, _ = guard(["CommissionCounsel"])
    data = shape.body()
    disposition = shape.req_enum(data, "disposition", DISPOSITIONS)
    shape.opt_str(data, "investigator_user_id")
    shape.opt_str(data, "note")

    complaint = computed.must("complaint", cid)
    respondent = store.get("licensee", complaint["respondent_licensee_id"])
    snap = cascades.posture_snapshot(complaint.get("respondent_brokerage_id"))
    if respondent is not None:
        cascades.add_snapshot(snap, respondent.get("sponsoring_brokerage_id"))
    status = complaint["status"]

    if disposition == "INVESTIGATE":
        if status != "SUBMITTED":
            fail("ERR_INVALID_STATE", "Only a SUBMITTED complaint may be investigated.")
        if respondent is not None and respondent["license_status"] == "DENIED":
            fail("ERR_INVALID_STATE",
                 "A complaint against a DENIED applicant cannot be investigated.")
        complaint["status"] = "INVESTIGATION"
        complaint["screener_user_id"] = user_id
        complaint["investigator_user_id"] = user_id
        store.touch(complaint)
        cascades.open_investigation(respondent)
    elif disposition == "DISMISS":
        if status != "SUBMITTED":
            fail("ERR_INVALID_STATE", "Only a SUBMITTED complaint may be dismissed.")
        complaint["status"] = "DISMISSED"
        complaint["screener_user_id"] = user_id
        store.touch(complaint)
        cascades.clear_discipline(respondent, from_states=("UNDER_INVESTIGATION",))
    elif disposition == "REQUEST_AMENDMENT":
        if status != "INVESTIGATION":
            fail("ERR_INVALID_STATE",
                 "An amendment may only be requested from INVESTIGATION.")
        if complaint["amendment_count"] >= computed.MAX_AMENDMENTS:
            fail("ERR_AMENDMENT_LIMIT", "Two amendment rounds are already used.")
        complaint["status"] = "AMENDMENT_REQUESTED"
        store.touch(complaint)
    elif disposition == "PROBABLE_CAUSE":
        if status != "INVESTIGATION":
            fail("ERR_INVALID_STATE",
                 "Probable cause may only be found from INVESTIGATION.")
        if computed.priority_score(complaint) < computed.PROBABLE_CAUSE_MIN_SCORE:
            fail("ERR_PROBABLE_CAUSE_SCORE_TOO_LOW",
                 "The investigation priority score is below %d."
                 % computed.PROBABLE_CAUSE_MIN_SCORE)
        if store.now() >= store.dt_of(complaint["statute_deadline_at"]):
            fail("ERR_STATUTE_DEADLINE_PASSED", "The 180-day deadline has passed.")
        complaint["status"] = "PROBABLE_CAUSE"
        store.touch(complaint)
    else:
        if status != "INVESTIGATION":
            fail("ERR_INVALID_STATE",
                 "A complaint may only be closed without action from INVESTIGATION.")
        complaint["status"] = "CLOSED_NO_ACTION"
        store.touch(complaint)
        cascades.clear_discipline(respondent)

    cascades.settle(snap)
    return envelope.ok(serialize.complaint(complaint))


@bp.post("/commission/complaints/<cid>/amendments")
def amend_complaint(cid):
    guard(["Public", "LicensingAnalyst"])
    data = shape.body()
    shape.req_str(data, "amendment_note")
    amended_loss = shape.opt_int(data, "amended_alleged_loss_cents", minimum=0)

    complaint = computed.must("complaint", cid)
    if complaint["status"] != "AMENDMENT_REQUESTED":
        fail("ERR_INVALID_STATE",
             "Only a complaint in AMENDMENT_REQUESTED may be amended.")
    if store.now() >= store.dt_of(complaint["statute_deadline_at"]):
        fail("ERR_STATUTE_DEADLINE_PASSED", "The 180-day deadline has passed.")

    complaint["status"] = "INVESTIGATION"
    complaint["amendment_count"] = complaint["amendment_count"] + 1
    if amended_loss is not None:
        complaint["alleged_loss_cents"] = amended_loss
    store.touch(complaint)
    return envelope.ok(serialize.complaint(complaint))


# ---------------------------------------------------------- consent agreements
def _live_channel_exists(complaint_id):
    for row in computed.rows_where("consent_agreement", complaint_id=complaint_id):
        if row["status"] in ("OFFERED", "COUNTERED", "ACCEPTED"):
            return True
    for row in computed.rows_where("hearing", complaint_id=complaint_id):
        if row["status"] in computed.LIVE_HEARING_STATUSES:
            return True
    return False


@bp.post("/commission/complaints/<cid>/consent-agreements")
def open_consent(cid):
    user_id, _ = guard(["CommissionCounsel"])
    data = shape.body()
    sanction_type = shape.req_enum(data, "proposed_sanction_type", computed.SANCTION_TYPES)
    fine_cents = shape.req_int(data, "proposed_fine_cents", minimum=0)
    suspension_days = shape.req_int(data, "proposed_suspension_days", minimum=0)

    complaint = computed.must("complaint", cid)
    status = complaint["status"]
    if status not in ("PROBABLE_CAUSE", "CONSENT_PENDING", "HEARING_SCHEDULED"):
        fail("ERR_INVALID_STATE",
             "A consent agreement requires a complaint in PROBABLE_CAUSE.")
    if _live_channel_exists(complaint["id"]):
        fail("ERR_CONSENT_ALREADY_OPEN",
             "A consent agreement or hearing is already open on this complaint.")
    if status != "PROBABLE_CAUSE":
        fail("ERR_INVALID_STATE",
             "A consent agreement requires a complaint in PROBABLE_CAUSE.")

    row = store.insert("consent_agreement", {
        "complaint_id": complaint["id"],
        "offered_by_user_id": user_id,
        "round_number": 1,
        "status": "OFFERED",
        "proposed_sanction_type": sanction_type,
        "proposed_fine_cents": fine_cents,
        "proposed_suspension_days": suspension_days,
        "counter_fine_cents": None,
        "counter_suspension_days": None,
        "responded_by_user_id": None,
        "executed_by_user_id": None,
    })
    complaint["status"] = "CONSENT_PENDING"
    store.touch(complaint)
    return envelope.created(serialize.consent_agreement(row))


@bp.post("/commission/consent-agreements/<aid>/respondent-response")
def respond_to_consent(aid):
    user_id, _ = guard(["Respondent"])
    data = shape.body()
    action = shape.req_enum(data, "action", {"ACCEPT", "COUNTER"})
    counter_fine = shape.opt_int(data, "counter_fine_cents", minimum=0)
    counter_days = shape.opt_int(data, "counter_suspension_days", minimum=0)

    agreement = computed.must("consent_agreement", aid)
    complaint = store.get("complaint", agreement["complaint_id"])
    if complaint is None or user_id != complaint["respondent_licensee_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the named respondent may answer this offer.")
    if agreement["status"] != "OFFERED":
        fail("ERR_INVALID_STATE", "Only an OFFERED agreement may be answered.")

    agreement["responded_by_user_id"] = user_id
    if action == "ACCEPT":
        agreement["status"] = "ACCEPTED"
    else:
        agreement["status"] = "COUNTERED"
        agreement["counter_fine_cents"] = counter_fine
        agreement["counter_suspension_days"] = counter_days
    store.touch(agreement)
    return envelope.ok(serialize.consent_agreement(agreement))


@bp.post("/commission/consent-agreements/<aid>/commission-action")
def act_on_consent(aid):
    user_id, _ = guard(["CommissionCounsel"])
    data = shape.body()
    action = shape.req_enum(data, "action", {"REVISE", "WITHDRAW", "EXECUTE"})
    revised_fine = None
    revised_days = None
    revised_type = None
    if action == "REVISE":
        revised_fine = shape.req_int(data, "proposed_fine_cents", minimum=0)
        revised_days = shape.req_int(data, "proposed_suspension_days", minimum=0)
        revised_type = shape.opt_enum(data, "proposed_sanction_type",
                                      computed.SANCTION_TYPES)

    agreement = computed.must("consent_agreement", aid)
    complaint = store.get("complaint", agreement["complaint_id"])

    if action == "EXECUTE":
        if agreement["status"] != "ACCEPTED":
            fail("ERR_INVALID_STATE", "Only an ACCEPTED agreement may be executed.")
        if user_id == agreement["offered_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The counsel who offered the agreement may not execute it.")
        agreement["status"] = "EXECUTED"
        agreement["executed_by_user_id"] = user_id
        store.touch(agreement)
        cascades.issue_sanction_order(
            complaint, "CONSENT", agreement["proposed_sanction_type"],
            agreement["proposed_fine_cents"], agreement["proposed_suspension_days"],
            consent_agreement_id=agreement["id"])
        return envelope.ok(serialize.consent_agreement(agreement))

    if agreement["status"] != "COUNTERED":
        fail("ERR_INVALID_STATE",
             "Only a COUNTERED agreement may be revised or withdrawn.")

    if action == "REVISE":
        if agreement["round_number"] >= computed.MAX_CONSENT_ROUNDS:
            fail("ERR_CONSENT_ROUND_LIMIT",
                 "Three negotiation rounds are already used.")
        agreement["status"] = "OFFERED"
        agreement["round_number"] = agreement["round_number"] + 1
        if revised_type is not None:
            agreement["proposed_sanction_type"] = revised_type
        agreement["proposed_fine_cents"] = revised_fine
        agreement["proposed_suspension_days"] = revised_days
        agreement["counter_fine_cents"] = None
        agreement["counter_suspension_days"] = None
        store.touch(agreement)
        return envelope.ok(serialize.consent_agreement(agreement))

    agreement["status"] = "REJECTED"
    store.touch(agreement)
    if complaint is not None and complaint["status"] == "CONSENT_PENDING":
        complaint["status"] = "PROBABLE_CAUSE"
        store.touch(complaint)
    return envelope.ok(serialize.consent_agreement(agreement))


# ------------------------------------------------------------------- hearings
def _check_occupancy(room, chair, start, end, exclude_id):
    buffer = timedelta(seconds=computed.HEARING_ROOM_BUFFER_SECONDS)
    live = [h for h in store.all_rows("hearing")
            if h["id"] != exclude_id and h["status"] in computed.LIVE_HEARING_STATUSES]
    for other in live:
        if other["hearing_room"] != room:
            continue
        o_start = store.dt_of(other["scheduled_start_at"])
        o_end = store.dt_of(other["scheduled_end_at"])
        if not (start >= o_end + buffer or end + buffer <= o_start):
            fail("ERR_HEARING_ROOM_CONFLICT",
                 "Room %s is not free for that slot." % room)
    for other in live:
        if other["panel_chair_user_id"] != chair:
            continue
        o_start = store.dt_of(other["scheduled_start_at"])
        o_end = store.dt_of(other["scheduled_end_at"])
        if start < o_end and o_start < end:
            fail("ERR_PANEL_CHAIR_DOUBLE_BOOKED",
                 "The panel chair already sits in that slot.")


@bp.post("/commission/complaints/<cid>/hearings")
def schedule_hearing(cid):
    guard(["CommissionCounsel"])
    data = shape.body()
    chair = shape.req_str(data, "panel_chair_user_id")
    room = shape.req_str(data, "hearing_room")
    start = shape.req_dt(data, "scheduled_start_at")
    end = shape.req_dt(data, "scheduled_end_at")
    if end <= start:
        invalid("scheduled_end_at must be strictly after scheduled_start_at.")

    complaint = computed.must("complaint", cid)
    status = complaint["status"]
    if status not in ("PROBABLE_CAUSE", "CONSENT_PENDING", "HEARING_SCHEDULED"):
        fail("ERR_INVALID_STATE",
             "A hearing requires a complaint in PROBABLE_CAUSE.")
    if chair == complaint.get("investigator_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The investigator may not chair the panel.")
    if _live_channel_exists(complaint["id"]):
        fail("ERR_CONSENT_ALREADY_OPEN",
             "A consent agreement or hearing is already open on this complaint.")
    if status != "PROBABLE_CAUSE":
        fail("ERR_INVALID_STATE",
             "A hearing requires a complaint in PROBABLE_CAUSE.")
    _check_occupancy(room, chair, start, end, None)

    respondent = store.get("licensee", complaint["respondent_licensee_id"])
    snap = cascades.posture_snapshot(complaint.get("respondent_brokerage_id"))
    if respondent is not None:
        cascades.add_snapshot(snap, respondent.get("sponsoring_brokerage_id"))
    row = store.insert("hearing", {
        "complaint_id": complaint["id"],
        "panel_chair_user_id": chair,
        "hearing_room": room,
        "scheduled_start_at": store.fmt_dt(start),
        "scheduled_end_at": store.fmt_dt(end),
        "status": "SCHEDULED",
        "continuance_count": 0,
        "convened_at": None,
        "decided_at": None,
        "finding": None,
    })
    complaint["status"] = "HEARING_SCHEDULED"
    store.touch(complaint)
    if respondent is not None and respondent["discipline_status"] == "UNDER_INVESTIGATION":
        respondent["discipline_status"] = "PENDING_HEARING"
        store.touch(respondent)
    cascades.settle(snap)
    return envelope.created(serialize.hearing(row))


@bp.post("/commission/hearings/<hid>/disposition")
def dispose_hearing(hid):
    user_id, _ = guard(["HearingPanelChair"])
    data = shape.body()
    action = shape.req_enum(data, "action", {"CONVENE", "CONTINUE", "DECIDE"})
    finding = None
    sanction_type = None
    fine_cents = 0
    suspension_days = 0
    new_start = None
    new_end = None
    new_room = None
    if action == "DECIDE":
        finding = shape.req_enum(data, "finding", computed.FINDINGS)
        sanction_type = shape.opt_enum(data, "sanction_type", computed.SANCTION_TYPES)
        fine_cents = shape.opt_int(data, "fine_cents", 0, minimum=0)
        suspension_days = shape.opt_int(data, "suspension_days", 0, minimum=0)
        if finding == "VIOLATION_FOUND" and sanction_type is None:
            invalid("sanction_type is required when the finding is VIOLATION_FOUND.")
    elif action == "CONTINUE":
        new_start = shape.req_dt(data, "rescheduled_start_at")
        new_end = shape.req_dt(data, "rescheduled_end_at")
        new_room = shape.opt_str(data, "hearing_room")
        if new_end <= new_start:
            invalid("rescheduled_end_at must be strictly after rescheduled_start_at.")

    hearing = computed.must("hearing", hid)
    if user_id != hearing["panel_chair_user_id"]:
        fail("ERR_PANEL_CHAIR_MISMATCH",
             "Only the recorded panel chair may dispose of this hearing.")
    complaint = store.get("complaint", hearing["complaint_id"])

    if action == "CONVENE":
        if hearing["status"] != "SCHEDULED":
            fail("ERR_INVALID_STATE", "Only a SCHEDULED hearing may convene.")
        if store.now() < store.dt_of(hearing["scheduled_start_at"]):
            fail("ERR_HEARING_NOT_STARTED", "The hearing slot has not started.")
        hearing["status"] = "CONVENED"
        hearing["convened_at"] = store.fmt_dt(store.now())
        store.touch(hearing)
        return envelope.ok(serialize.hearing(hearing))

    if action == "CONTINUE":
        if hearing["status"] != "CONVENED":
            fail("ERR_INVALID_STATE", "Only a CONVENED hearing may be continued.")
        if hearing["continuance_count"] >= computed.MAX_CONTINUANCES:
            fail("ERR_CONTINUANCE_LIMIT", "Two continuances are already used.")
        room = new_room if new_room is not None else hearing["hearing_room"]
        _check_occupancy(room, hearing["panel_chair_user_id"], new_start, new_end,
                         hearing["id"])
        hearing["status"] = "SCHEDULED"
        hearing["continuance_count"] = hearing["continuance_count"] + 1
        hearing["scheduled_start_at"] = store.fmt_dt(new_start)
        hearing["scheduled_end_at"] = store.fmt_dt(new_end)
        hearing["hearing_room"] = room
        hearing["convened_at"] = None
        store.touch(hearing)
        return envelope.ok(serialize.hearing(hearing))

    if hearing["status"] != "CONVENED":
        fail("ERR_INVALID_STATE", "Only a CONVENED hearing may be decided.")
    hearing["status"] = "DECIDED"
    hearing["decided_at"] = store.fmt_dt(store.now())
    hearing["finding"] = finding
    store.touch(hearing)

    if finding == "VIOLATION_FOUND":
        cascades.issue_sanction_order(
            complaint, "HEARING", sanction_type, fine_cents, suspension_days,
            hearing_id=hearing["id"])
    else:
        snap = cascades.posture_snapshot(complaint.get("respondent_brokerage_id"))
        respondent = store.get("licensee", complaint["respondent_licensee_id"])
        if respondent is not None:
            cascades.add_snapshot(snap, respondent.get("sponsoring_brokerage_id"))
        complaint["status"] = "CLOSED_NO_ACTION"
        store.touch(complaint)
        cascades.clear_discipline(respondent)
        cascades.settle(snap)
    return envelope.ok(serialize.hearing(hearing))
