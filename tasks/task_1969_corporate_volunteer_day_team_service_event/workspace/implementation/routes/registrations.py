"""Registration endpoints: self-registration, waiver dimension, rsvp dimension, transport."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_REGISTRATION_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_MANIFEST_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_PROJECT_LEAD,
    ERR_INVALID_REGISTRATION_TRANSITION,
    ERR_INVALID_PROJECT_TRANSITION,
    ERR_INVALID_MANIFEST_TRANSITION,
    ERR_EVENT_STATE_FORBIDS_WRITE,
    ERR_WAIVER_NOT_SIGNED,
    ERR_WAIVER_NOT_VERIFIED,
    ERR_GUARDIAN_SIGNATURE_REQUIRED,
    ERR_PROJECT_AT_CAPACITY,
    ERR_MANIFEST_FULL,
    ERR_DUPLICATE_REGISTRATION,
    ERR_PROJECT_EVENT_MISMATCH,
    ERR_MANIFEST_EVENT_MISMATCH,
    ERR_VALIDATION,
)
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.core import (
    mint,
    bump,
    touch,
    refresh_event,
    maybe_demote_project,
    ser_registration,
    sort_entities,
)
from timeutil import fmt_ts
from validate import req_string, opt_bool, req_enum, opt_string, req_bool

bp = Blueprint("registrations", __name__)

WRITABLE_FOR_REGISTRATION = ("PLANNING", "REGISTRATION_OPEN", "REGISTRATION_LOCKED")


def load_registration(reg_id):
    r = db.registrations.get(reg_id)
    if r is None:
        raise_err(ERR_REGISTRATION_NOT_FOUND, "registration not found")
    return r


def _event(r):
    return db.events.get(r["event_id"])


def _project(r):
    return db.projects.get(r["project_id"])


@bp.post("/registrations")
def create_registration():
    uid, role, vol = authenticate(["EmployeeVolunteer"])
    data = body()
    event_id = req_string(data, "event_id")
    project_id = req_string(data, "project_id")
    wants_transport = opt_bool(data, "wants_transport", False)
    wants_meal = opt_bool(data, "wants_meal", True)
    # body FK existence (step 5), declared order: event then project
    ev = db.events.get(event_id)
    if ev is None:
        raise_err(ERR_EVENT_NOT_FOUND, "service event not found")
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "service project not found")
    # state (step 6): event writable; project MATCHED/LOCKED
    if ev["status"] not in WRITABLE_FOR_REGISTRATION:
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event state forbids new registrations")
    if project["status"] not in ("MATCHED", "LOCKED"):
        raise_err(ERR_INVALID_PROJECT_TRANSITION, "project must be MATCHED or LOCKED")
    # uniqueness (step 11): one non-CANCELLED registration per (event, volunteer)
    for r in db.registrations.values():
        if (
            r["event_id"] == ev["id"]
            and r["volunteer_id"] == uid
            and r["rsvp_status"] != "CANCELLED"
        ):
            raise_err(ERR_DUPLICATE_REGISTRATION, "volunteer already has a live registration for this event")
    # cross-reference (step 12): project matched to this event
    if project["event_id"] != ev["id"]:
        raise_err(ERR_PROJECT_EVENT_MISMATCH, "project is not matched to this event")
    r = mint()
    r.update(
        {
            "event_id": ev["id"],
            "project_id": project["id"],
            "volunteer_id": uid,
            "rsvp_status": "REGISTERED",
            "waiver_status": "WAIVER_PENDING",
            "waiver_signed_version": None,
            "waiver_signer_relation": None,
            "waiver_signer_name": None,
            "media_consent": False,
            "wants_transport": wants_transport,
            "wants_meal": wants_meal,
            "transport_manifest_id": None,
            "scheduled_hours_credit": 0,
            "checked_in_at": None,
        }
    )
    db.registrations[r["id"]] = r
    refresh_event(ev)
    return success_object(ser_registration(r), 201)


@bp.get("/registrations")
def list_registrations():
    authenticate(["Any"])
    items = list(db.registrations.values())
    for param in ("event_id", "volunteer_id", "project_id", "transport_manifest_id", "rsvp_status"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if str(r.get(param)) == val]
    return success_list([ser_registration(r) for r in sort_entities(items)])


@bp.get("/registrations/<registrationId>")
def get_registration(registrationId):
    authenticate(["Any"])
    return success_object(ser_registration(load_registration(registrationId)))


@bp.post("/registrations/<registrationId>/confirm")
def confirm_registration(registrationId):
    authenticate(["CommunityEngagementManager"])
    r = load_registration(registrationId)
    ev = _event(r)
    project = _project(r)
    # state (step 6)
    if r["rsvp_status"] != "REGISTERED":
        raise_err(ERR_INVALID_REGISTRATION_TRANSITION, "only a REGISTERED registration can be confirmed")
    if ev is None or ev["status"] not in ("REGISTRATION_OPEN", "REGISTRATION_LOCKED"):
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event must be REGISTRATION_OPEN or REGISTRATION_LOCKED")
    if project is None or project["status"] not in ("MATCHED", "LOCKED"):
        raise_err(ERR_INVALID_PROJECT_TRANSITION, "project must be MATCHED or LOCKED")
    # waiver safety (step 7)
    if r["waiver_status"] not in ("WAIVER_SIGNED", "WAIVER_VERIFIED"):
        raise_err(ERR_WAIVER_NOT_SIGNED, "waiver must be signed before confirmation")
    # capacity (step 11)
    if calc.project_confirmed_count(project) >= project["max_volunteers"]:
        raise_err(ERR_PROJECT_AT_CAPACITY, "project is at capacity")
    r["rsvp_status"] = "CONFIRMED"
    bump(r)
    # auto-demotion: if LOCKED and new requirement exceeds active leads
    maybe_demote_project(project)
    touch(project)
    refresh_event(ev)
    return success_object(ser_registration(r))


@bp.post("/registrations/<registrationId>/cancel")
def cancel_registration(registrationId):
    uid, role, _ = authenticate(["CommunityEngagementManager", "EmployeeVolunteer"])
    r = load_registration(registrationId)
    if role == "EmployeeVolunteer" and uid != r["volunteer_id"]:
        raise_err(ERR_FORBIDDEN_ROLE, "volunteers may only cancel their own registrations")
    if r["rsvp_status"] not in ("REGISTERED", "CONFIRMED"):
        raise_err(ERR_INVALID_REGISTRATION_TRANSITION, "registration cannot be cancelled from its current state")
    was_confirmed = r["rsvp_status"] == "CONFIRMED"
    r["rsvp_status"] = "CANCELLED"
    r["transport_manifest_id"] = None
    bump(r)
    project = _project(r)
    if project is not None:
        if was_confirmed:
            maybe_demote_project(project)
        touch(project)
    ev = _event(r)
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_registration(r))


@bp.post("/registrations/<registrationId>/check-in")
def check_in_registration(registrationId):
    uid, role, _ = authenticate(["CommunityEngagementManager", "StaffLead"])
    r = load_registration(registrationId)
    if role == "StaffLead":
        has_assignment = any(
            a["project_id"] == r["project_id"]
            and a["lead_volunteer_id"] == uid
            and a["status"] == "ACTIVE"
            for a in db.assignments.values()
        )
        if not has_assignment:
            raise_err(ERR_NOT_PROJECT_LEAD, "staff lead holds no ACTIVE supervision assignment on this project")
    # state (step 6)
    if r["rsvp_status"] != "CONFIRMED":
        raise_err(ERR_INVALID_REGISTRATION_TRANSITION, "only a CONFIRMED registration can check in")
    ev = _event(r)
    if ev is None or ev["status"] != "IN_PROGRESS":
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event must be IN_PROGRESS for check-in")
    # waiver safety (step 7)
    if r["waiver_status"] != "WAIVER_VERIFIED":
        raise_err(ERR_WAIVER_NOT_VERIFIED, "waiver must be WAIVER_VERIFIED at check-in")
    r["rsvp_status"] = "CHECKED_IN"
    r["checked_in_at"] = fmt_ts(db.now())
    r["scheduled_hours_credit"] = calc.scheduled_hours(ev)
    bump(r)
    refresh_event(ev)
    return success_object(ser_registration(r))


@bp.post("/registrations/<registrationId>/sign-waiver")
def sign_waiver(registrationId):
    uid, role, _ = authenticate(["EmployeeVolunteer"])
    r = load_registration(registrationId)
    if uid != r["volunteer_id"]:
        raise_err(ERR_FORBIDDEN_ROLE, "volunteers may only sign their own waiver")
    data = body()
    signer_name = req_string(data, "signer_name")
    relation = req_enum(data, "signer_relation", ("SELF", "GUARDIAN"))
    media_consent = req_bool(data, "media_consent")
    guardian_name = opt_string(data, "guardian_name")
    # state (step 6)
    if r["waiver_status"] not in ("WAIVER_PENDING", "WAIVER_VOIDED"):
        raise_err(ERR_INVALID_REGISTRATION_TRANSITION, "waiver cannot be signed from its current state")
    ev = _event(r)
    if ev is None or ev["status"] not in ("REGISTRATION_OPEN", "REGISTRATION_LOCKED", "IN_PROGRESS"):
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event state forbids waiver signing")
    # guardian rule (step 7)
    if calc.reg_is_minor(r):
        if relation != "GUARDIAN" or not guardian_name:
            raise_err(
                ERR_GUARDIAN_SIGNATURE_REQUIRED,
                "a minor's waiver requires signer_relation GUARDIAN and a non-empty guardian_name",
            )
    else:
        if relation != "SELF":
            raise_err(ERR_VALIDATION, "an adult waiver requires signer_relation SELF")
    r["waiver_status"] = "WAIVER_SIGNED"
    r["waiver_signed_version"] = ev["waiver_document_version"]
    r["waiver_signer_relation"] = relation
    r["waiver_signer_name"] = guardian_name if relation == "GUARDIAN" else signer_name
    r["media_consent"] = media_consent
    bump(r)
    ev_touch = _event(r)
    if ev_touch is not None:
        refresh_event(ev_touch)
    return success_object(ser_registration(r))


@bp.post("/registrations/<registrationId>/verify-waiver")
def verify_waiver(registrationId):
    authenticate(["CommunityEngagementManager"])
    r = load_registration(registrationId)
    if r["waiver_status"] != "WAIVER_SIGNED":
        raise_err(ERR_INVALID_REGISTRATION_TRANSITION, "only a WAIVER_SIGNED waiver can be verified")
    r["waiver_status"] = "WAIVER_VERIFIED"
    bump(r)
    return success_object(ser_registration(r))


@bp.post("/registrations/<registrationId>/assign-transport")
def assign_transport(registrationId):
    authenticate(["LogisticsCoordinator"])
    r = load_registration(registrationId)
    data = body()
    manifest_id = req_string(data, "transport_manifest_id")
    m = db.manifests.get(manifest_id)
    if m is None:
        raise_err(ERR_MANIFEST_NOT_FOUND, "transport manifest not found")
    # state (step 6): manifest assignable
    if m["status"] not in ("BOOKED", "CONFIRMED"):
        raise_err(ERR_INVALID_MANIFEST_TRANSITION, "manifest is not assignable in its current status")
    # capacity (step 11)
    vehicle = db.vehicles.get(m["vehicle_id"])
    capacity = vehicle["seat_capacity"] if vehicle is not None else 0
    if calc.manifest_assigned_seats(m) >= capacity:
        raise_err(ERR_MANIFEST_FULL, "manifest has no free seats")
    # cross-reference (step 12)
    if m["event_id"] != r["event_id"]:
        raise_err(ERR_MANIFEST_EVENT_MISMATCH, "manifest belongs to a different event")
    r["transport_manifest_id"] = m["id"]
    bump(r)
    touch(m)
    return success_object(ser_registration(r))
