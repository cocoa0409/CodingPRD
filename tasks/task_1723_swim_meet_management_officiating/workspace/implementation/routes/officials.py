"""Official and OfficialAssignment endpoints."""

from flask import Blueprint, request

from db import STORE, new_id
from errors import (
    ERR_EVENT_ALREADY_UNDERWAY,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_MEET_NOT_FOUND,
    ERR_OFFICIAL_ASSIGNMENT_CONFLICT,
    ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND,
    ERR_OFFICIAL_NOT_FOUND,
    raise_err,
)
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import (
    DECK_ROLES,
    bump,
    get_or_404,
    paginate,
    pub_assignment,
    pub_official,
    req_body,
    sort_created,
    stamp,
    v_date,
    v_str,
    v_str_list,
)
from routes.events import _assignment_conflict

bp = Blueprint("officials", __name__)


@bp.post("/officials")
def create_official():
    _, role = ctx()
    require_role(role, "MeetDirector")
    b = req_body()
    meet_id = v_str(b, "meet_id")
    full_name = v_str(b, "full_name")
    lsc_membership_id = v_str(b, "lsc_membership_id")
    certifications = v_str_list(b, "certifications", allowed=DECK_ROLES)
    expires = v_date(b, "certification_expires_on")
    get_or_404("meets", meet_id, ERR_MEET_NOT_FOUND)
    for o in STORE["officials"].values():
        if o["meet_id"] == meet_id and o["lsc_membership_id"] == lsc_membership_id:
            raise_err(ERR_INVALID_REQUEST, "lsc_membership_id must be unique within the meet")
    official = stamp(
        {
            "id": new_id(),
            "meet_id": meet_id,
            "full_name": full_name,
            "lsc_membership_id": lsc_membership_id,
            "certifications": certifications,
            "certification_expires_on": expires,
        }
    )
    STORE["officials"][official["id"]] = official
    return ok_object(pub_official(official), 201)


@bp.get("/officials/<oid>")
def get_official(oid):
    ctx()
    official = get_or_404("officials", oid, ERR_OFFICIAL_NOT_FOUND)
    return ok_object(pub_official(official))


@bp.get("/officials")
def list_officials():
    ctx()
    items = list(STORE["officials"].values())
    meet_id = request.args.get("meet_id")
    if meet_id is not None:
        items = [o for o in items if o["meet_id"] == meet_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_official(o) for o in page], limit, offset, total)


@bp.get("/official-assignments/<aid>")
def get_assignment(aid):
    ctx()
    assignment = get_or_404(
        "official_assignments", aid, ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND
    )
    return ok_object(pub_assignment(assignment))


@bp.get("/official-assignments")
def list_assignments():
    ctx()
    items = list(STORE["official_assignments"].values())
    official_id = request.args.get("official_id")
    if official_id is not None:
        items = [a for a in items if a["official_id"] == official_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_assignment(a) for a in page], limit, offset, total)


@bp.post("/official-assignments/<aid>/confirm")
def confirm_assignment(aid):
    user_id, role = ctx()
    require_role(role, "DeckOfficial", "MeetReferee")
    assignment = get_or_404(
        "official_assignments", aid, ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND
    )
    # Self-confirmation: X-User-ID must equal the assignment's official_id.
    if assignment["official_id"] != user_id:
        raise_err(
            ERR_INSUFFICIENT_PERMISSIONS, "an official confirms only their own assignment"
        )
    if assignment["status"] != "PROPOSED":
        raise_err(ERR_INVALID_REQUEST, "assignment is not PROPOSED")
    event = STORE["events"][assignment["event_id"]]
    if _assignment_conflict(
        assignment["official_id"], event, ("CONFIRMED",), exclude_id=assignment["id"]
    ):
        raise_err(
            ERR_OFFICIAL_ASSIGNMENT_CONFLICT,
            "official has an overlapping CONFIRMED assignment on this session_date",
        )
    assignment["status"] = "CONFIRMED"
    bump(assignment)
    return ok_object(pub_assignment(assignment))


@bp.post("/official-assignments/<aid>/release")
def release_assignment(aid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    assignment = get_or_404(
        "official_assignments", aid, ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND
    )
    if assignment["status"] == "PROPOSED":
        pass  # always releasable
    elif assignment["status"] == "CONFIRMED":
        event = STORE["events"][assignment["event_id"]]
        if event["status"] not in ("PENDING", "SEEDED"):
            raise_err(ERR_EVENT_ALREADY_UNDERWAY, "event is already underway")
    else:
        raise_err(ERR_INVALID_REQUEST, "assignment is already RELEASED")
    assignment["status"] = "RELEASED"
    bump(assignment)
    return ok_object(pub_assignment(assignment))
