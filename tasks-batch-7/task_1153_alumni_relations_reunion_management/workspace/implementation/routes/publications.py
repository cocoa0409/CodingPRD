"""MemorabiliaPublication endpoints."""

from flask import Blueprint, request

import db
from errors import (
    err_event_not_publishable, err_invalid_request, err_invalid_state,
    err_not_found,
)
from middleware import require_roles
from response import success_list, success_object
from services.calculations import recompute_engagement
from services.common import (
    apply_pagination, json_body, new_entity, pagination_args, req_str, touch,
)
from services.serializers import PUBLICATION_FIELDS, serialize
from routes.events import get_event_or_404

bp = Blueprint("publications", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
DIRECTOR = ("AlumniRelationsDirector",)
PUB_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair")


def get_publication_or_404(pid):
    p = db.publications.get(pid)
    if p is None:
        raise err_not_found("MemorabiliaPublication not found")
    return p


@bp.route("/alumni/events/<eid>/publications", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def create_publication(eid, _role, _user_id):
    get_event_or_404(eid)
    body = json_body(required=["title", "class_notes_body"])
    title = req_str(body["title"], "title")
    notes = req_str(body["class_notes_body"], "class_notes_body")
    pub = new_entity({
        "event_id": eid,
        "title": title,
        "class_notes_body": notes,
        "review_round": 0,
        "status": "DRAFT",
    })
    db.publications[pub["id"]] = pub
    return success_object(serialize(pub, PUBLICATION_FIELDS), status=201)


@bp.route("/alumni/events/<eid>/publications", methods=["GET"])
@require_roles(*PUB_READ)
def list_event_publications(eid, _role, _user_id):
    get_event_or_404(eid)
    limit, offset = pagination_args()
    rows = [p for p in db.publications.values() if p["event_id"] == eid]
    status = request.args.get("status")
    if status:
        rows = [p for p in rows if p["status"] == status]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(p, PUBLICATION_FIELDS) for p in page], limit, offset, total)


@bp.route("/alumni/publications/<pid>", methods=["GET"])
@require_roles(*PUB_READ)
def get_publication(pid, _role, _user_id):
    return success_object(serialize(get_publication_or_404(pid), PUBLICATION_FIELDS))


@bp.route("/alumni/publications/<pid>/submit-review", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def submit_review(pid, _role, _user_id):
    pub = get_publication_or_404(pid)
    if pub["status"] != "DRAFT":
        raise err_invalid_state("Publication must be DRAFT to submit for review")
    if len(pub.get("class_notes_body") or "") < 1:
        raise err_invalid_request("class_notes_body must be at least one character")
    pub["status"] = "IN_REVIEW"
    touch(pub)
    return success_object(serialize(pub, PUBLICATION_FIELDS))


@bp.route("/alumni/publications/<pid>/return-for-edits", methods=["POST"])
@require_roles(*DIRECTOR)
def return_for_edits(pid, _role, _user_id):
    pub = get_publication_or_404(pid)
    if pub["status"] != "IN_REVIEW":
        raise err_invalid_state("Publication must be IN_REVIEW to return for edits")
    pub["status"] = "DRAFT"
    pub["review_round"] += 1
    touch(pub)
    return success_object(serialize(pub, PUBLICATION_FIELDS))


@bp.route("/alumni/publications/<pid>/approve", methods=["POST"])
@require_roles(*DIRECTOR)
def approve(pid, _role, _user_id):
    pub = get_publication_or_404(pid)
    if pub["status"] != "IN_REVIEW":
        raise err_invalid_state("Publication must be IN_REVIEW to approve")
    pub["status"] = "APPROVED"
    touch(pub)
    return success_object(serialize(pub, PUBLICATION_FIELDS))


@bp.route("/alumni/publications/<pid>/request-re-review", methods=["POST"])
@require_roles(*DIRECTOR)
def request_re_review(pid, _role, _user_id):
    pub = get_publication_or_404(pid)
    if pub["status"] != "APPROVED":
        raise err_invalid_state("Publication must be APPROVED to request re-review")
    pub["status"] = "IN_REVIEW"
    touch(pub)
    return success_object(serialize(pub, PUBLICATION_FIELDS))


@bp.route("/alumni/publications/<pid>/publish", methods=["POST"])
@require_roles(*DIRECTOR)
def publish(pid, _role, _user_id):
    pub = get_publication_or_404(pid)
    if pub["status"] != "APPROVED":
        raise err_invalid_state("Publication must be APPROVED to publish")
    event = db.events.get(pub["event_id"])
    if event is None:
        raise err_not_found("ReunionEvent not found")
    if event["status"] not in ("OPEN_FOR_REGISTRATION", "HELD", "RECONCILED"):
        raise err_event_not_publishable()
    pub["status"] = "PUBLISHED"
    touch(pub)
    # engagement recompute scheduled for all registrants of the linked event
    seen = set()
    for reg in db.registrations.values():
        if reg["event_id"] == event["id"] and reg["alumni_id"] not in seen:
            seen.add(reg["alumni_id"])
            recompute_engagement(reg["alumni_id"])
    return success_object(serialize(pub, PUBLICATION_FIELDS))
