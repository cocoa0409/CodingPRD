"""Animal tagging and verification (PRD 3.4)."""

from flask import Blueprint

import clock
import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        require_member_ownership, new_common_fields, touch)
from validation import get_body, as_str, as_enum, as_datetime_str, present
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from services import calc
from services.serialize import animal_tag_view

bp = Blueprint("animal_tags", __name__)

SPECIES = ("BEEF", "SHEEP", "SWINE")


@bp.post("/animal-tags")
def create_animal_tag():
    role, user_id = authenticate(["Member", "Volunteer"])
    body = get_body()
    # Priority 3: referenced identifiers exist (project_id).
    project = None
    if isinstance(body.get("project_id"), str):
        project = must_find("projects", body["project_id"], "Project")
    resolve_caller(role, user_id)
    # Priority 4: a member may only tag animals on their own projects.
    if role == "Member" and project is not None:
        require_member_ownership(user_id, project["member_id"])
    # Priority 14: request shape.
    project_id = present(body, "project_id")
    if not isinstance(project_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'project_id': must be a string")
    if project is None:
        project = must_find("projects", project_id, "Project")
    tag_number = as_str(body, "tag_number")
    species = as_enum(body, "species", SPECIES)
    owned_since = as_datetime_str(body, "owned_since")
    # The official ear-tag number is unique per program year (PRD 3.4).
    for existing in db.table("animal_tags").values():
        other = db.table("projects").get(existing["project_id"])
        if (other is not None and other["program_year"] == project["program_year"]
                and existing["tag_number"] == tag_number):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Tag number '%s' is already used in program year %s"
                           % (tag_number, project["program_year"]))
    rec = new_common_fields()
    rec.update({
        "project_id": project["id"],
        "tag_number": tag_number,
        "species": species,
        "owned_since": owned_since,                       # echoed verbatim
        "_owned_since_dt": clock.parse_iso(owned_since),  # parsed for arithmetic
        "tagged_at": clock.iso3(clock.now()),             # stamped from the logical clock
        "tagging_status": "TAGGED",
    })
    db.table("animal_tags")[rec["id"]] = rec
    return response.success(animal_tag_view(rec), status=201)


def _verify_or_reject(tid, target):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("animal_tags", tid, "AnimalTag")
    resolve_caller(role, user_id)
    if rec["tagging_status"] != "TAGGED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Animal tag tagging_status must be TAGGED")
    rec["tagging_status"] = target
    touch(rec)
    # Either decision recomputes the owning member's eligibility_posture.
    project = db.table("projects").get(rec["project_id"])
    if project is not None:
        member = db.table("members").get(project["member_id"])
        if member is not None:
            calc.recompute_member_posture(member)
    return response.success(animal_tag_view(rec))


@bp.post("/animal-tags/<tid>/verify")
def verify_animal_tag(tid):
    return _verify_or_reject(tid, "VERIFIED")


@bp.post("/animal-tags/<tid>/reject")
def reject_animal_tag(tid):
    return _verify_or_reject(tid, "REJECTED")
