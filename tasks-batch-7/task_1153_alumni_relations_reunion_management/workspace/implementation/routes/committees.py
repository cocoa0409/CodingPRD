"""ReunionCommittee and CommitteeMembership endpoints."""

from flask import Blueprint, request

import db
from errors import (
    err_alumnus_not_active, err_chair_exists, err_committee_locked,
    err_duplicate_child, err_invalid_request, err_invalid_state, err_not_found,
    err_referential, err_unauthorized,
)
from middleware import require_roles
from response import success_list, success_object
from services.calculations import rederive_posture
from services.common import (
    apply_pagination, json_body, logical_ts, new_entity, pagination_args,
    req_enum, req_str, touch,
)
from services.serializers import COMMITTEE_FIELDS, MEMBERSHIP_FIELDS, serialize
from routes.events import get_event_or_404

bp = Blueprint("committees", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
COMMITTEE_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair",
                  "CommitteeVolunteer")
MEMBERSHIP_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair",
                   "CommitteeVolunteer", "Alumni")
MEMBER_ROLES = ("CHAIR", "TREASURER", "LOGISTICS", "OUTREACH", "MEMBER")


def get_committee_or_404(committee_id):
    c = db.committees.get(committee_id)
    if c is None:
        raise err_not_found("ReunionCommittee not found")
    return c


def get_membership_or_404(mid):
    m = db.memberships.get(mid)
    if m is None:
        raise err_not_found("CommitteeMembership not found")
    return m


def _bump_committee_count(event, delta):
    event["committee_count"] = max(0, event["committee_count"] + delta)
    rederive_posture(event)


# ---------------------------------------------------------------------------
# ReunionCommittee
# ---------------------------------------------------------------------------

@bp.route("/alumni/events/<eid>/committee", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def create_committee(eid, _role, _user_id):
    event = get_event_or_404(eid)
    existing = next((c for c in db.committees.values() if c["event_id"] == eid), None)
    if existing is not None:
        raise err_duplicate_child("A committee already exists for this event")
    body = json_body(required=["name"])
    name = req_str(body["name"], "name")
    committee = new_entity({
        "event_id": eid,
        "name": name,
        "chair_membership_id": None,
        "locked": False,
    })
    db.committees[committee["id"]] = committee
    return success_object(serialize(committee, COMMITTEE_FIELDS), status=201)


@bp.route("/alumni/events/<eid>/committee", methods=["GET"])
@require_roles(*COMMITTEE_READ)
def get_committee(eid, _role, _user_id):
    get_event_or_404(eid)
    rows = [c for c in db.committees.values() if c["event_id"] == eid]
    rows.sort(key=lambda c: (c["created_at"], c["id"]))
    return success_list([serialize(c, COMMITTEE_FIELDS) for c in rows],
                        limit=len(rows) if rows else 10, offset=0,
                        total_count=len(rows))


# ---------------------------------------------------------------------------
# CommitteeMembership
# ---------------------------------------------------------------------------

@bp.route("/alumni/committees/<committeeId>/memberships", methods=["POST"])
@require_roles("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair")
def invite_member(committeeId, _role, _user_id):
    committee = get_committee_or_404(committeeId)
    if _role == "ReunionChair":
        chair = _active_chair_membership(committee["id"])
        if chair is None or chair["alumni_id"] != _user_id:
            raise err_unauthorized("Acting user is not the ACTIVE CHAIR of this committee")
    if committee["locked"]:
        raise err_committee_locked()
    body = json_body(required=["alumni_id", "role"])
    alumni_id = req_str(body["alumni_id"], "alumni_id")
    role = req_enum(body["role"], "role", MEMBER_ROLES)
    record = db.records.get(alumni_id)
    if record is None:
        raise err_referential("AlumniRecord not found")
    if record["status"] == "DECEASED":
        raise err_referential("Alumnus is DECEASED")

    membership = new_entity({
        "committee_id": committee["id"],
        "alumni_id": alumni_id,
        "role": role,
        "status": "INVITED",
        "invited_at": logical_ts(),
        "ended_reason": None,
    })
    db.memberships[membership["id"]] = membership
    return success_object(serialize(membership, MEMBERSHIP_FIELDS), status=201)


@bp.route("/alumni/committees/<committeeId>/memberships", methods=["GET"])
@require_roles(*COMMITTEE_READ)
def list_committee_memberships(committeeId, _role, _user_id):
    get_committee_or_404(committeeId)
    limit, offset = pagination_args()
    rows = [m for m in db.memberships.values() if m["committee_id"] == committeeId]
    status = request.args.get("status")
    if status:
        rows = [m for m in rows if m["status"] == status]
    role = request.args.get("role")
    if role:
        rows = [m for m in rows if m["role"] == role]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(m, MEMBERSHIP_FIELDS) for m in page], limit, offset, total)


@bp.route("/alumni/memberships", methods=["GET"])
@require_roles(*MEMBERSHIP_READ)
def list_memberships(_role, _user_id):
    limit, offset = pagination_args()
    rows = list(db.memberships.values())
    alumni_id = request.args.get("alumni_id")
    if alumni_id:
        rows = [m for m in rows if m["alumni_id"] == alumni_id]
    committee_id = request.args.get("committee_id")
    if committee_id:
        rows = [m for m in rows if m["committee_id"] == committee_id]
    status = request.args.get("status")
    if status:
        rows = [m for m in rows if m["status"] == status]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(m, MEMBERSHIP_FIELDS) for m in page], limit, offset, total)


@bp.route("/alumni/memberships/<mid>", methods=["GET"])
@require_roles(*MEMBERSHIP_READ)
def get_membership(mid, _role, _user_id):
    return success_object(serialize(get_membership_or_404(mid), MEMBERSHIP_FIELDS))


def _active_chair_membership(committee_id):
    for m in db.memberships.values():
        if (m["committee_id"] == committee_id and m["role"] == "CHAIR"
                and m["status"] == "ACTIVE"):
            return m
    return None


@bp.route("/alumni/memberships/<mid>/accept", methods=["POST"])
@require_roles("CommitteeVolunteer", "AlumniRelationsStaff", "AlumniRelationsDirector")
def accept_membership(mid, _role, _user_id):
    membership = get_membership_or_404(mid)
    if _role == "CommitteeVolunteer" and membership["alumni_id"] != _user_id:
        raise err_unauthorized("Acting user does not own this membership")
    if membership["status"] != "INVITED":
        raise err_invalid_state("Membership must be INVITED to accept")
    committee = db.committees.get(membership["committee_id"])
    if committee is None:
        raise err_not_found("ReunionCommittee not found")
    if committee["locked"]:
        raise err_committee_locked()
    record = db.records.get(membership["alumni_id"])
    if record is None or record["status"] != "ACTIVE":
        raise err_alumnus_not_active()
    if membership["role"] == "CHAIR":
        existing_chair = _active_chair_membership(committee["id"])
        if existing_chair is not None:
            raise err_chair_exists()

    membership["status"] = "ACTIVE"
    touch(membership)
    if membership["role"] == "CHAIR":
        committee["chair_membership_id"] = membership["id"]
        touch(committee)
    event = db.events.get(committee["event_id"])
    if event is not None:
        _bump_committee_count(event, +1)
    return success_object(serialize(membership, MEMBERSHIP_FIELDS))


@bp.route("/alumni/memberships/<mid>/decline", methods=["POST"])
@require_roles("CommitteeVolunteer")
def decline_membership(mid, _role, _user_id):
    membership = get_membership_or_404(mid)
    if membership["alumni_id"] != _user_id:
        raise err_unauthorized("Acting user does not own this membership")
    if membership["status"] != "INVITED":
        raise err_invalid_state("Membership must be INVITED to decline")
    membership["status"] = "DECLINED"
    touch(membership)
    return success_object(serialize(membership, MEMBERSHIP_FIELDS))


@bp.route("/alumni/memberships/<mid>/end", methods=["POST"])
@require_roles("ReunionChair", "AlumniRelationsStaff", "AlumniRelationsDirector")
def end_membership_route(mid, _role, _user_id):
    membership = get_membership_or_404(mid)
    committee = db.committees.get(membership["committee_id"])
    if committee is None:
        raise err_not_found("ReunionCommittee not found")
    if _role == "ReunionChair":
        chair = _active_chair_membership(committee["id"])
        if chair is None or chair["alumni_id"] != _user_id:
            raise err_unauthorized("Acting user is not the ACTIVE CHAIR of this committee")
    if membership["status"] != "ACTIVE":
        raise err_invalid_state("Membership must be ACTIVE to end")
    if committee["locked"]:
        raise err_committee_locked()

    membership["status"] = "ENDED"
    membership["ended_reason"] = "REMOVED" if _role in STAFF_OR_DIRECTOR else "RESIGNED"
    touch(membership)
    if membership["role"] == "CHAIR" and committee.get("chair_membership_id") == membership["id"]:
        committee["chair_membership_id"] = None
        touch(committee)
    event = db.events.get(committee["event_id"])
    if event is not None:
        _bump_committee_count(event, -1)
    return success_object(serialize(membership, MEMBERSHIP_FIELDS))
