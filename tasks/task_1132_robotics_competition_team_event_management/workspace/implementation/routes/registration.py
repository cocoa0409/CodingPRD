"""Team registration, Person registry, ScreeningRecord pipeline (PRD 3.2)."""
import re
from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles
from db import store, stamp_new, touch, now
from envelope import success, paginated
from errors import (
    ApiError,
    ERR_DUPLICATE_TEAM_NUMBER,
    ERR_EVENT_FULL,
    ERR_EVENT_WRONG_STATUS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MENTOR_NOT_CLEARED,
    ERR_NO_GROUNDS,
    ERR_RECORD_NOT_PENDING,
    ERR_SEGREGATION_VIOLATION,
    ERR_STALE_VERSION,
    ERR_TEAM_NOT_FOUND,
)
from services import (
    persons_of_team,
    recompute_counts,
    recompute_posture,
)
from util import (
    TERMINAL,
    check_from_state,
    gate_posture,
    get_body,
    public,
    req_enum,
    req_int,
    req_str,
    opt_str,
    req_dt,
    resolve_event,
    resolve_team,
    resolve_person,
    resolve_record,
)

bp = Blueprint("registration", __name__)

ALL_GET_ROLES = (
    "EventDirector", "RegistrationOfficer", "ScreeningOfficer", "TeamLead",
    "JudgeAdvisor", "Scorekeeper", "QueueManager", "HeadReferee", "Inspector",
    "LeadInspector", "FieldResetCrew", "TravelOfficer", "ProcurementOfficer", "Judge",
)
PERSON_GET_ROLES = ("EventDirector", "RegistrationOfficer", "ScreeningOfficer", "TeamLead", "JudgeAdvisor")
ROLE_KINDS = {"MENTOR", "VOLUNTEER", "JUDGE", "STUDENT"}
SUBMISSION_CHANNELS = {"FIRST_YPP", "VENDOR_API", "MANUAL_UPLOAD"}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _team_memberships_on_forming_alliance(team):
    for a in store.alliances.values():
        if a["event_id"] != team["event_id"]:
            continue
        if a.get("_ephemeral"):
            continue
        if a["status"] == "FORMING" and team["id"] in (
            a.get("captain_team_id"), a.get("pick1_team_id"), a.get("pick2_team_id")
        ):
            yield a


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

@bp.route("/frc-events/<eventId>/teams", methods=["POST"])
def create_team(eventId):
    require_roles("RegistrationOfficer")
    event = resolve_event(eventId)
    gate_posture(event)
    body = get_body()
    team_number = req_int(body, "team_number", minimum=1)
    nickname = req_str(body, "nickname")
    for t in store.teams.values():
        if t["event_id"] == eventId and t["team_number"] == team_number:
            raise ApiError(ERR_DUPLICATE_TEAM_NUMBER, 409, "team_number %s already registered for this event" % team_number)
    team = {
        "event_id": eventId,
        "team_number": team_number,
        "nickname": nickname,
        "registration_status": "PENDING_PAYMENT",
        "robot_inspection_status": "NOT_SUBMITTED",
        "ranking_score": 0.0,
        "ranking_tie_break": 0.0,
        "matches_played": 0,
        "is_alliance_captain": False,
        "qualified_for_championship": False,
    }
    if body.get("is_rookie") is not None:
        if not isinstance(body.get("is_rookie"), bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "is_rookie must be a boolean")
        team["is_rookie"] = body["is_rookie"]
    stamp_new(team)
    store.teams[team["id"]] = team
    return success(public(team), code=201)


@bp.route("/frc-events/<eventId>/teams", methods=["GET"])
def list_teams(eventId):
    require_roles(*ALL_GET_ROLES)
    event = resolve_event(eventId)
    items = [t for t in store.teams.values() if t["event_id"] == event["id"]]
    status = request.args.get("registration_status")
    if status is not None:
        items = [t for t in items if t["registration_status"] == status]
    number = request.args.get("team_number")
    if number is not None:
        try:
            tn = int(number)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "team_number must be an integer")
        items = [t for t in items if t["team_number"] == tn]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/teams/<teamId>", methods=["GET"])
def get_team(eventId, teamId):
    require_roles(*ALL_GET_ROLES)
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    return success(public(team))


@bp.route("/frc-events/<eventId>/teams/<teamId>/mark-payment-cleared", methods=["POST"])
def mark_payment_cleared(eventId, teamId):
    require_roles("RegistrationOfficer")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    if event["status"] != "REGISTRATION_OPEN":
        raise ApiError(ERR_EVENT_WRONG_STATUS, 409, "Payment can only be cleared while REGISTRATION_OPEN")
    gate_posture(event)
    check_from_state(team, "registration_status", "PENDING_PAYMENT", TERMINAL["Team"], "Team")
    team["registration_status"] = "PAYMENT_CLEARED"
    touch(team)
    return success(public(team))


@bp.route("/frc-events/<eventId>/teams/<teamId>/submit-roster", methods=["POST"])
def submit_roster(eventId, teamId):
    require_roles("TeamLead")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    gate_posture(event)
    check_from_state(team, "registration_status", "PAYMENT_CLEARED", TERMINAL["Team"], "Team")
    members = persons_of_team(teamId)
    has_cleared_mentor = any(
        p["role_kind"] == "MENTOR" and p["screening_status"] == "CLEARED" for p in members
    )
    if not has_cleared_mentor:
        raise ApiError(ERR_MENTOR_NOT_CLEARED, 422, "Team lacks a CLEARED MENTOR")
    has_student = any(p["role_kind"] == "STUDENT" for p in members)
    if not has_student:
        raise ApiError(ERR_INVALID_REQUEST, 422, "Team must have at least one STUDENT member")
    team["registration_status"] = "ROSTER_SUBMITTED"
    touch(team)
    return success(public(team))


@bp.route("/frc-events/<eventId>/teams/<teamId>/confirm", methods=["POST"])
def confirm_team(eventId, teamId):
    require_roles("RegistrationOfficer")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    gate_posture(event, require_open=True)
    check_from_state(team, "registration_status", "ROSTER_SUBMITTED", TERMINAL["Team"], "Team")
    recompute_counts(event)
    if not (event["registered_team_count"] < event["team_capacity"]):
        raise ApiError(ERR_EVENT_FULL, 409, "Event is at team capacity")
    team["registration_status"] = "CONFIRMED"
    touch(team)
    recompute_counts(event)
    touch(event)
    return success(public(team))


@bp.route("/frc-events/<eventId>/teams/<teamId>/withdraw", methods=["POST"])
def withdraw_team(eventId, teamId):
    user_id, _ = require_roles("TeamLead")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    if team["registration_status"] == "CONFIRMED" and event["status"] in ("AWARDS", "CLOSED"):
        raise ApiError(ERR_EVENT_WRONG_STATUS, 409, "Cannot withdraw during AWARDS or CLOSED")
    gate_posture(event)
    check_from_state(team, "registration_status", {"PENDING_PAYMENT", "CONFIRMED"}, TERMINAL["Team"], "Team")
    was_confirmed = team["registration_status"] == "CONFIRMED"
    team["registration_status"] = "WITHDRAWN"
    touch(team)
    if was_confirmed:
        for s in store.queue_slots.values():
            if s["team_id"] == teamId and s["status"] in ("STAGED", "AT_FIELD"):
                s["status"] = "NO_SHOW"
                touch(s)
        for s in store.interview_slots.values():
            if s["team_id"] == teamId and s["status"] in ("PROPOSED", "CONFIRMED"):
                s["status"] = "CANCELLED"
                touch(s)
        recompute_posture(event)
    return success(public(team))


@bp.route("/frc-events/<eventId>/teams/<teamId>/disqualify", methods=["POST"])
def disqualify_team(eventId, teamId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    gate_posture(event)
    check_from_state(team, "registration_status", "CONFIRMED", TERMINAL["Team"], "Team")
    grounds = any(
        v["team_id"] == teamId and v["severity"] == "CRITICAL" and v["resolution_status"] != "RESOLVED"
        for v in store.violations.values()
    )
    if not grounds:
        raise ApiError(ERR_NO_GROUNDS, 409, "Disqualify requires an unresolved CRITICAL violation")
    team["registration_status"] = "DISQUALIFIED"
    touch(team)
    # Cancel every still-SCHEDULED match this team appears in.
    for m in store.matches.values():
        if m["event_id"] == eventId and m["status"] == "SCHEDULED" and (
            teamId in m.get("_red_teams", []) or teamId in m.get("_blue_teams", [])
        ):
            m["status"] = "CANCELLED"
            touch(m)
    for s in store.interview_slots.values():
        if s["team_id"] == teamId and s["status"] in ("PROPOSED", "CONFIRMED"):
            s["status"] = "CANCELLED"
            touch(s)
    # Remove from any FORMING selection alliance.
    for a in _team_memberships_on_forming_alliance(team):
        changed = False
        for f in ("captain_team_id", "pick1_team_id", "pick2_team_id"):
            if a.get(f) == teamId:
                a[f] = None
                changed = True
        if changed:
            touch(a)
    recompute_posture(event)
    return success(public(team))


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------

@bp.route("/frc-events/<eventId>/persons", methods=["POST"])
def create_person(eventId):
    require_roles("RegistrationOfficer", "TeamLead")
    event = resolve_event(eventId)
    gate_posture(event)
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    role_kind = req_enum(body, "role_kind", ROLE_KINDS)
    team_id = body.get("team_id")
    if not _EMAIL_RE.match(email):
        raise ApiError(ERR_INVALID_REQUEST, 400, "email must satisfy RFC 5322")
    if team_id is not None:
        t = store.teams.get(team_id)
        if t is None or t["event_id"] != eventId:
            raise ApiError(ERR_TEAM_NOT_FOUND, 404, "Team %s not found" % team_id)
    for p in store.persons.values():
        if p.get("_event_id") == eventId and p["email"] == email:
            raise ApiError(ERR_INVALID_REQUEST, 400, "email must be unique per event")
    person = {
        "team_id": team_id,
        "full_name": full_name,
        "email": email,
        "role_kind": role_kind,
        "screening_status": "PENDING",
        "screening_expires_at": None,
        "_event_id": eventId,
    }
    stamp_new(person)
    store.persons[person["id"]] = person
    return success(public(person), code=201)


@bp.route("/frc-events/<eventId>/persons", methods=["GET"])
def list_persons(eventId):
    require_roles(*PERSON_GET_ROLES)
    event = resolve_event(eventId)
    items = [p for p in store.persons.values() if p.get("_event_id") == event["id"]]
    team_id = request.args.get("team_id")
    if team_id is not None:
        items = [p for p in items if p.get("team_id") == team_id]
    role_kind = request.args.get("role_kind")
    if role_kind is not None:
        items = [p for p in items if p["role_kind"] == role_kind]
    screening_status = request.args.get("screening_status")
    if screening_status is not None:
        items = [p for p in items if p["screening_status"] == screening_status]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/persons/<personId>", methods=["GET"])
def get_person(eventId, personId):
    require_roles(*PERSON_GET_ROLES)
    event = resolve_event(eventId)
    person = resolve_person(event, personId)
    return success(public(person))


# ---------------------------------------------------------------------------
# ScreeningRecord
# ---------------------------------------------------------------------------

SCREENING_GET_ROLES = ("EventDirector", "ScreeningOfficer")


@bp.route("/frc-events/<eventId>/persons/<personId>/screening-records", methods=["POST"])
def create_screening_record(eventId, personId):
    require_roles("ScreeningOfficer")
    event = resolve_event(eventId)
    person = resolve_person(event, personId)
    if event["status"] not in ("SETUP", "REGISTRATION_OPEN", "REGISTRATION_LOCKED"):
        raise ApiError(ERR_EVENT_WRONG_STATUS, 409, "Screening submissions are accepted only in SETUP, REGISTRATION_OPEN or REGISTRATION_LOCKED")
    gate_posture(event)
    check_from_state(person, "screening_status", "PENDING", TERMINAL["Person"], "Person")
    body = get_body()
    channel = req_enum(body, "submission_channel", SUBMISSION_CHANNELS)
    vendor_reference = req_str(body, "vendor_reference")
    submitted_at = req_dt(body, "submitted_at")
    record = {
        "person_id": personId,
        "submission_channel": channel,
        "vendor_reference": vendor_reference,
        "submitted_at": submitted_at,
        "decision": "PENDING",
        "decided_by_role": None,
    }
    stamp_new(record)
    store.screening_records[record["id"]] = record
    person["screening_status"] = "IN_REVIEW"
    touch(person)
    return success(public(record), code=201)


@bp.route("/frc-events/<eventId>/persons/<personId>/screening-records", methods=["GET"])
def list_screening_records(eventId, personId):
    require_roles(*SCREENING_GET_ROLES)
    event = resolve_event(eventId)
    person = resolve_person(event, personId)
    items = [r for r in store.screening_records.values() if r["person_id"] == person["id"]]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/persons/<personId>/screening-records/<recordId>", methods=["GET"])
def get_screening_record(eventId, personId, recordId):
    require_roles(*SCREENING_GET_ROLES)
    event = resolve_event(eventId)
    person = resolve_person(event, personId)
    record = resolve_record(person, recordId)
    return success(public(record))


def _screening_decision(eventId, personId, recordId, approve):
    user_id, _ = require_roles("ScreeningOfficer")
    event = resolve_event(eventId)
    person = resolve_person(event, personId)
    record = resolve_record(person, recordId)
    gate_posture(event)
    # Priority 6: person must be IN_REVIEW.
    check_from_state(person, "screening_status", "IN_REVIEW", TERMINAL["Person"], "Person")
    # Priority 7: segregation of duties — officer cannot decide their own package.
    if user_id == person["id"]:
        raise ApiError(ERR_SEGREGATION_VIOLATION, 403, "ScreeningOfficer cannot decide their own screening package")
    # Priority 8: record must still be PENDING.
    if record["decision"] != "PENDING":
        raise ApiError(ERR_RECORD_NOT_PENDING, 409, "ScreeningRecord decision is no longer PENDING")
    body = get_body()
    if approve:
        # Priority 22: OCC against Person.version.
        expected = body.get("expected_person_version")
        if expected is not None:
            if not isinstance(expected, int) or isinstance(expected, bool):
                raise ApiError(ERR_INVALID_REQUEST, 400, "expected_person_version must be an integer")
            if expected != person["version"]:
                raise ApiError(ERR_STALE_VERSION, 412, "expected_person_version does not match current person version")
        record["decision"] = "APPROVE"
        record["decided_by_role"] = "ScreeningOfficer"
        touch(record)
        person["screening_status"] = "CLEARED"
        if person["role_kind"] in ("MENTOR", "JUDGE"):
            person["screening_expires_at"] = now() + timedelta(days=180)
        elif person["role_kind"] == "VOLUNTEER":
            person["screening_expires_at"] = now() + timedelta(days=90)
        else:
            person["screening_expires_at"] = None
        touch(person)
    else:
        record["decision"] = "REJECT"
        record["decided_by_role"] = "ScreeningOfficer"
        touch(record)
        person["screening_status"] = "REJECTED"
        person["screening_expires_at"] = None
        touch(person)
        # Knock-on cascade: rejected MENTOR reverts a ROSTER_SUBMITTED team.
        if person["role_kind"] == "MENTOR" and person.get("team_id"):
            team = store.teams.get(person["team_id"])
            if team is not None and team["registration_status"] == "ROSTER_SUBMITTED":
                team["registration_status"] = "PAYMENT_CLEARED"
                touch(team)
    recompute_posture(event)
    return success(public(person))


@bp.route("/frc-events/<eventId>/persons/<personId>/screening-records/<recordId>/approve", methods=["POST"])
def approve_screening(eventId, personId, recordId):
    return _screening_decision(eventId, personId, recordId, approve=True)


@bp.route("/frc-events/<eventId>/persons/<personId>/screening-records/<recordId>/reject", methods=["POST"])
def reject_screening(eventId, personId, recordId):
    return _screening_decision(eventId, personId, recordId, approve=False)
