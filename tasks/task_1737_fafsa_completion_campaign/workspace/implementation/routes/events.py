"""Completion events, staff assignments, event registrations."""

from flask import Blueprint, request

import dates
import errors
import middleware
import validate
from db import store, make_common, touch
from response import success_object, success_list
from services import core

bp = Blueprint("events", __name__)

ALL_ROLES = ["CampaignAdmin", "SchoolCoordinator", "StaffMember", "Specialist", "MatchReviewer", "DataImporter"]
ASSIGNMENT_READ_ROLES = ["CampaignAdmin", "SchoolCoordinator", "StaffMember", "Specialist"]
REGISTRATION_READ_ROLES = ["CampaignAdmin", "SchoolCoordinator", "Specialist"]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bp.route("/fafsa/events", methods=["POST"])
def create_event():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    body = validate.get_json_body(required=True)
    validate.check_fields(
        body,
        required=["school_id", "title", "start_time", "end_time", "capacity", "cost_estimate_cents", "required_expert_count", "supported_languages"],
        optional=[],
    )
    school_id = validate.req_string(body, "school_id")
    title = validate.req_string(body, "title")
    start_time = validate.req_datetime(body, "start_time")
    end_time = validate.req_datetime(body, "end_time")
    capacity = validate.req_int(body, "capacity", minimum=1)
    cost_estimate_cents = validate.req_int(body, "cost_estimate_cents")
    required_expert_count = validate.req_int(body, "required_expert_count", minimum=0)
    supported_languages = validate.req_array(body, "supported_languages")

    school = core.get_school_or_404(school_id)
    middleware.require_school_scope(auth, school["id"])
    campaign = core.get_campaign_or_404(school["campaign_id"])

    # State gates
    if school["status"] != "ENROLLED":
        errors.raise_error(errors.ERR_SCHOOL_NOT_ENROLLED, "School must be ENROLLED")
    if campaign["status"] not in ("OPEN", "STATE_GRACE"):
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_OPEN, "Campaign must be OPEN or STATE_GRACE")

    # Temporal: window sanity then future-start
    s = dates.parse_datetime(start_time)
    e = dates.parse_datetime(end_time)
    if e <= s:
        errors.raise_error(errors.ERR_EVENT_WINDOW_INVALID, "end_time must be after start_time")
    if s <= store.clock_now:
        errors.raise_error(errors.ERR_EVENT_IN_PAST, "start_time must be in the future")

    common = make_common()
    event = {
        **common,
        "school_id": school_id,
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "capacity": capacity,
        "cost_estimate_cents": cost_estimate_cents,
        "actual_cost_cents": None,
        "required_expert_count": required_expert_count,
        "supported_languages": supported_languages,
        "status": "DRAFT",
        "_seq": store.next_seq(),
    }
    store.events[event["id"]] = event
    return success_object(core.serialize(event, "events"), 201)


@bp.route("/fafsa/events", methods=["GET"])
def list_events():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ALL_ROLES)
    limit, offset = validate.parse_pagination()
    school_id = request.args.get("school_id")
    status = request.args.get("status")
    items = list(store.events.values())
    if school_id is not None:
        items = [e for e in items if e["school_id"] == school_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(e, "events") for e in page], limit, offset, total)


@bp.route("/fafsa/events/<eid>", methods=["GET"])
def get_event(eid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ALL_ROLES)
    event = core.get_event_or_404(eid)
    return success_object(core.serialize(event, "events"))


@bp.route("/fafsa/events/<eid>/publish", methods=["POST"])
def publish_event(eid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    event = core.get_event_or_404(eid)
    middleware.require_school_scope(auth, event["school_id"])
    campaign = core.campaign_of_event(event)
    if campaign is None:
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_FOUND, "Campaign not found")
    if campaign["status"] not in ("OPEN", "STATE_GRACE"):
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_OPEN, "Campaign must be OPEN or STATE_GRACE")
    if event["status"] != "DRAFT":
        errors.raise_error(errors.ERR_EVENT_NOT_DRAFT, "publish requires DRAFT")
    # Temporal
    s = dates.parse_datetime(event["start_time"])
    if s <= store.clock_now:
        errors.raise_error(errors.ERR_EVENT_IN_PAST, "start_time must be in the future")
    if core.venue_buffer_conflict(event["school_id"], event, exclude_event_id=event["id"]):
        errors.raise_error(errors.ERR_EVENT_OVERLAP_BUFFER, "Another event within the 30-minute venue buffer")
    # Staffing invariant (constraint family, priority 9)
    if not core.staffing_invariant_met(event):
        errors.raise_error(errors.ERR_STAFFING_INVARIANT_NOT_MET, "Staffing invariant not met")
    # Fiscal gate last (priority 10)
    core.recompute_budget(campaign)
    if campaign["committed_budget_cents"] + event["cost_estimate_cents"] > campaign["total_budget_cents"]:
        errors.raise_error(errors.ERR_BUDGET_EXCEEDED, "Budget exceeded")
    event["status"] = "PUBLISHED"
    touch(event)
    core.recompute_budget(campaign)
    core.bump_campaign_version(campaign)
    return success_object(core.serialize(event, "events"))


@bp.route("/fafsa/events/<eid>/unpublish", methods=["POST"])
def unpublish_event(eid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    event = core.get_event_or_404(eid)
    middleware.require_school_scope(auth, event["school_id"])
    if event["status"] != "PUBLISHED":
        errors.raise_error(errors.ERR_EVENT_NOT_PUBLISHED, "unpublish requires PUBLISHED")
    campaign = core.campaign_of_event(event)
    event["status"] = "DRAFT"
    touch(event)
    # REGISTERED registrations -> CANCELLED; assignments unchanged.
    for r in store.event_registrations.values():
        if r["event_id"] == event["id"] and r["status"] == "REGISTERED":
            core.cancel_registration(r)
    if campaign is not None:
        core.recompute_budget(campaign)
        core.bump_campaign_version(campaign)
    return success_object(core.serialize(event, "events"))


@bp.route("/fafsa/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    event = core.get_event_or_404(eid)
    middleware.require_school_scope(auth, event["school_id"])
    if event["status"] not in ("DRAFT", "PUBLISHED"):
        errors.raise_error(errors.ERR_EVENT_NOT_CANCELLABLE, "cancel requires DRAFT or PUBLISHED")
    core.cancel_event_cascade(event)
    return success_object(core.serialize(event, "events"))


@bp.route("/fafsa/events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    event = core.get_event_or_404(eid)
    middleware.require_school_scope(auth, event["school_id"])
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["actual_cost_cents"], optional=[])
    actual_cost_cents = validate.req_int(body, "actual_cost_cents")
    if event["status"] != "IN_PROGRESS":
        errors.raise_error(errors.ERR_EVENT_NOT_IN_PROGRESS, "complete requires IN_PROGRESS")
    campaign = core.campaign_of_event(event)
    if campaign is None:
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_FOUND, "Campaign not found")
    # Fiscal gate
    core.recompute_budget(campaign)
    if campaign["spent_budget_cents"] + actual_cost_cents > campaign["total_budget_cents"]:
        errors.raise_error(errors.ERR_BUDGET_EXCEEDED, "Budget exceeded")
    event["actual_cost_cents"] = actual_cost_cents
    event["status"] = "COMPLETED"
    touch(event)
    # Attendance settlement
    for a in list(store.staff_assignments.values()):
        if a["event_id"] != event["id"]:
            continue
        if a["status"] in ("INVITED", "ACCEPTED"):
            a["status"] = "CANCELLED"
            touch(a)
        elif a["status"] == "CONFIRMED":
            a["status"] = "NO_SHOW"
            touch(a)
            core.release_hours(a)
            profile = store.staff_profiles.get(a["staff_profile_id"])
            if profile is not None:
                profile["no_show_count"] = profile.get("no_show_count", 0) + 1
                touch(profile)
                if profile["no_show_count"] >= campaign["no_show_limit"]:
                    core.suspend_staff_contagion(profile)
    core.recompute_budget(campaign)
    core.bump_campaign_version(campaign)
    return success_object(core.serialize(event, "events"))


# ---------------------------------------------------------------------------
# Staff assignments
# ---------------------------------------------------------------------------

@bp.route("/fafsa/staff-assignments", methods=["POST"])
def create_assignment():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["event_id", "staff_profile_id", "assigned_role"], optional=[])
    event_id = validate.req_string(body, "event_id")
    staff_profile_id = validate.req_string(body, "staff_profile_id")
    assigned_role = validate.req_enum(body, "assigned_role", core.ASSIGNED_ROLES)

    event = core.get_event_or_404(event_id)
    profile = core.get_staff_or_404(staff_profile_id)
    middleware.require_school_scope(auth, event["school_id"])

    # State: event DRAFT or PUBLISHED
    if event["status"] not in ("DRAFT", "PUBLISHED"):
        errors.raise_error(errors.ERR_EVENT_NOT_CANCELLABLE, "Event must be DRAFT or PUBLISHED")

    # Cross-campaign: staff and event share one campaign
    event_campaign = core.campaign_of_event(event)
    if event_campaign is None or profile["campaign_id"] != event_campaign["id"]:
        errors.raise_error(errors.ERR_CROSS_CAMPAIGN_REFERENCE, "Staff and event belong to different campaigns")

    # Capability: EXPERT requires AID_EXPERT
    if assigned_role == "EXPERT" and "AID_EXPERT" not in (profile.get("capabilities") or []):
        errors.raise_error(errors.ERR_STAFF_LACKS_CAPABILITY, "EXPERT assignment requires AID_EXPERT capability")

    # One non-terminal assignment per (event, staff)
    for a in store.staff_assignments.values():
        if (
            a["event_id"] == event_id
            and a["staff_profile_id"] == staff_profile_id
            and a["status"] in core.NON_TERMINAL_ASSIGNMENT_STATUSES
        ):
            errors.raise_error(errors.ERR_DUPLICATE_ASSIGNMENT, "A non-terminal assignment already exists for this (event, staff)")

    # Overlap pre-check vs CONFIRMED/CHECKED_IN
    if core.staff_double_booked(staff_profile_id, event):
        errors.raise_error(errors.ERR_STAFF_DOUBLE_BOOKED, "Staff member has an overlapping commitment")

    common = make_common()
    assignment = {
        **common,
        "event_id": event_id,
        "staff_profile_id": staff_profile_id,
        "assigned_role": assigned_role,
        "status": "INVITED",
        "duration_hours": core.compute_duration_hours(event),
        "_seq": store.next_seq(),
    }
    store.staff_assignments[assignment["id"]] = assignment
    return success_object(core.serialize(assignment), 201)


@bp.route("/fafsa/staff-assignments", methods=["GET"])
def list_assignments():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ASSIGNMENT_READ_ROLES)
    limit, offset = validate.parse_pagination()
    event_id = request.args.get("event_id")
    staff_profile_id = request.args.get("staff_profile_id")
    status = request.args.get("status")
    items = list(store.staff_assignments.values())
    if auth.role in ("StaffMember", "Specialist"):
        items = [a for a in items if a["staff_profile_id"] == auth.user_id]
    if event_id is not None:
        items = [a for a in items if a["event_id"] == event_id]
    if staff_profile_id is not None:
        items = [a for a in items if a["staff_profile_id"] == staff_profile_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(a) for a in page], limit, offset, total)


@bp.route("/fafsa/staff-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ASSIGNMENT_READ_ROLES)
    assignment = core.get_assignment_or_404(aid)
    return success_object(core.serialize(assignment))


@bp.route("/fafsa/staff-assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["StaffMember"])
    assignment = core.get_assignment_or_404(aid)
    middleware.require_ownership(auth, assignment["staff_profile_id"])
    if assignment["status"] != "INVITED":
        errors.raise_error(errors.ERR_ASSIGNMENT_NOT_INVITED, "accept requires INVITED")
    assignment["status"] = "ACCEPTED"
    touch(assignment)
    return success_object(core.serialize(assignment))


@bp.route("/fafsa/staff-assignments/<aid>/decline", methods=["POST"])
def decline_assignment(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["StaffMember"])
    assignment = core.get_assignment_or_404(aid)
    middleware.require_ownership(auth, assignment["staff_profile_id"])
    if assignment["status"] != "INVITED":
        errors.raise_error(errors.ERR_ASSIGNMENT_NOT_INVITED, "decline requires INVITED")
    assignment["status"] = "DECLINED"
    touch(assignment)
    return success_object(core.serialize(assignment))


@bp.route("/fafsa/staff-assignments/<aid>/confirm", methods=["POST"])
def confirm_assignment(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    assignment = core.get_assignment_or_404(aid)
    event = core.get_event_or_404(assignment["event_id"])
    middleware.require_school_scope(auth, event["school_id"])
    if assignment["status"] != "ACCEPTED":
        errors.raise_error(errors.ERR_ASSIGNMENT_NOT_ACCEPTED, "confirm requires ACCEPTED")
    profile = core.get_staff_or_404(assignment["staff_profile_id"])
    # Business safety: background check
    if profile["background_check_status"] != "CLEARED":
        errors.raise_error(errors.ERR_BACKGROUND_CHECK_NOT_CLEARED, "background_check_status must be CLEARED")
    # Double-booking re-check
    if core.staff_double_booked(profile["id"], event, exclude_assignment_id=assignment["id"]):
        errors.raise_error(errors.ERR_STAFF_DOUBLE_BOOKED, "Staff member has an overlapping commitment")
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    core.add_hours(assignment)
    return success_object(core.serialize(assignment))


@bp.route("/fafsa/staff-assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    assignment = core.get_assignment_or_404(aid)
    event = core.get_event_or_404(assignment["event_id"])
    middleware.require_school_scope(auth, event["school_id"])
    if assignment["status"] not in ("INVITED", "ACCEPTED", "CONFIRMED"):
        errors.raise_error(errors.ERR_ASSIGNMENT_NOT_CANCELLABLE, "cancel requires INVITED/ACCEPTED/CONFIRMED")
    was_confirmed = assignment["status"] == "CONFIRMED"
    assignment["status"] = "CANCELLED"
    touch(assignment)
    if was_confirmed:
        core.release_hours(assignment)
    return success_object(core.serialize(assignment))


@bp.route("/fafsa/staff-assignments/<aid>/check-in", methods=["POST"])
def check_in_assignment(aid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    assignment = core.get_assignment_or_404(aid)
    event = core.get_event_or_404(assignment["event_id"])
    middleware.require_school_scope(auth, event["school_id"])
    if assignment["status"] != "CONFIRMED":
        errors.raise_error(errors.ERR_ASSIGNMENT_NOT_CONFIRMED, "check-in requires CONFIRMED")
    if event["status"] != "IN_PROGRESS":
        errors.raise_error(errors.ERR_EVENT_NOT_IN_PROGRESS, "check-in requires event IN_PROGRESS")
    assignment["status"] = "CHECKED_IN"
    touch(assignment)
    return success_object(core.serialize(assignment))


# ---------------------------------------------------------------------------
# Event registrations
# ---------------------------------------------------------------------------

@bp.route("/fafsa/event-registrations", methods=["POST"])
def create_registration():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["event_id", "senior_record_id"], optional=[])
    event_id = validate.req_string(body, "event_id")
    senior_record_id = validate.req_string(body, "senior_record_id")

    event = core.get_event_or_404(event_id)
    senior = core.get_senior_or_404(senior_record_id)
    middleware.require_school_scope(auth, event["school_id"])

    # State: event PUBLISHED; senior's school ENROLLED
    if event["status"] != "PUBLISHED":
        errors.raise_error(errors.ERR_EVENT_NOT_PUBLISHED, "Registration requires event PUBLISHED")
    school = store.schools.get(senior["school_id"])
    if school is None or school["status"] != "ENROLLED":
        errors.raise_error(errors.ERR_SCHOOL_NOT_ENROLLED, "Senior's school must be ENROLLED")

    # Consent: OUTREACH scope
    if not core.senior_has_granted_scope(senior["id"], "OUTREACH"):
        errors.raise_error(errors.ERR_CONSENT_REQUIRED, "No GRANTED consent with OUTREACH scope for this senior")

    # Duplicate
    for r in store.event_registrations.values():
        if r["event_id"] == event_id and r["senior_record_id"] == senior_record_id and r["status"] == "REGISTERED":
            errors.raise_error(errors.ERR_DUPLICATE_REGISTRATION, "A REGISTERED registration already exists for this (event, senior)")

    # Capacity
    registered_count = sum(
        1 for r in store.event_registrations.values() if r["event_id"] == event_id and r["status"] == "REGISTERED"
    )
    if registered_count >= event["capacity"]:
        errors.raise_error(errors.ERR_EVENT_FULL, "Event is full")

    common = make_common()
    registration = {
        **common,
        "event_id": event_id,
        "senior_record_id": senior_record_id,
        "status": "REGISTERED",
        "_seq": store.next_seq(),
    }
    store.event_registrations[registration["id"]] = registration
    return success_object(core.serialize(registration), 201)


@bp.route("/fafsa/event-registrations", methods=["GET"])
def list_registrations():
    auth = middleware.get_auth()
    middleware.require_roles(auth, REGISTRATION_READ_ROLES)
    limit, offset = validate.parse_pagination()
    event_id = request.args.get("event_id")
    senior_record_id = request.args.get("senior_record_id")
    status = request.args.get("status")
    items = list(store.event_registrations.values())
    if auth.role == "SchoolCoordinator":
        items = [
            r
            for r in items
            if store.events.get(r["event_id"], {}).get("school_id") == auth.user_id
        ]
    if event_id is not None:
        items = [r for r in items if r["event_id"] == event_id]
    if senior_record_id is not None:
        items = [r for r in items if r["senior_record_id"] == senior_record_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(r) for r in page], limit, offset, total)


@bp.route("/fafsa/event-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, REGISTRATION_READ_ROLES)
    registration = core.get_registration_or_404(rid)
    event = store.events.get(registration["event_id"])
    if auth.role == "SchoolCoordinator" and event and event["school_id"] != auth.user_id:
        errors.raise_error(errors.ERR_SCHOOL_SCOPE_VIOLATION, "Not your school's resource")
    return success_object(core.serialize(registration))


@bp.route("/fafsa/event-registrations/<rid>/cancel", methods=["POST"])
def cancel_registration_route(rid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["SchoolCoordinator"])
    registration = core.get_registration_or_404(rid)
    event = core.get_event_or_404(registration["event_id"])
    middleware.require_school_scope(auth, event["school_id"])
    if registration["status"] != "REGISTERED":
        errors.raise_error(errors.ERR_REGISTRATION_NOT_ACTIVE, "cancel requires REGISTERED")
    registration["status"] = "CANCELLED"
    touch(registration)
    return success_object(core.serialize(registration))
