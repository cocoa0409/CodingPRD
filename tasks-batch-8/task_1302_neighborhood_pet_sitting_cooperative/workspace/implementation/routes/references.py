"""MemberReference endpoints: create/list/get, accept/reject/withdraw."""

from flask import Blueprint

import clock
import db
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFEREE_NOT_VETTED,
    ERR_SELF_REFERENCE,
)
from middleware import body, paginate, require_roles
from response import created, ok
from routes.members import get_member_or_404
from serializers import reference_view
from util import base_entity, touch

bp = Blueprint("references", __name__)


def get_reference_or_404(reference_id):
    ref = db.store["references"].get(reference_id)
    if ref is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"MemberReference {reference_id} does not exist")
    return ref


@bp.post("/coop/members/<member_id>/references")
def create_reference(member_id):
    user_id, role = require_roles("CoopAdmin", "Member")
    subject = get_member_or_404(member_id)
    if role == "Member" and user_id != subject["id"]:
        raise ApiError(
            ERR_FORBIDDEN,
            403,
            "Only the subject member (or an admin) may register references",
        )
    data = body()
    referee_member_id = data.get("referee_member_id")
    if not isinstance(referee_member_id, str) or not referee_member_id.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "referee_member_id is required")
    referee = db.store["members"].get(referee_member_id)
    if referee is None:
        raise ApiError(
            ERR_NOT_FOUND, 404, f"Referee member {referee_member_id} does not exist"
        )
    if referee_member_id == subject["id"]:
        raise ApiError(
            ERR_SELF_REFERENCE, 422, "Self-vouching is prohibited: referee == subject"
        )
    relationship_years = data.get("relationship_years")
    if (
        not isinstance(relationship_years, int)
        or isinstance(relationship_years, bool)
        or relationship_years < 1
    ):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "relationship_years must be an integer >= 1"
        )
    attestation_text = data.get("attestation_text")
    if not isinstance(attestation_text, str) or len(attestation_text) < 20:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "attestation_text must be at least 20 characters",
        )
    ref = base_entity()
    ref.update(
        {
            "subject_member_id": subject["id"],
            "referee_member_id": referee_member_id,
            "relationship_years": relationship_years,
            "attestation_text": attestation_text,
            "reciprocal_reference_id": None,
            "status": "PENDING",
            "decided_at": None,
        }
    )
    db.store["references"][ref["id"]] = ref
    return created(reference_view(ref))


@bp.get("/coop/members/<member_id>/references")
def list_references(member_id):
    require_roles("CoopAdmin", "Member")
    get_member_or_404(member_id)
    items = [
        r
        for r in db.store["references"].values()
        if r["subject_member_id"] == member_id
    ]
    return paginate(items, reference_view)


@bp.get("/coop/member-references/<reference_id>")
def get_reference(reference_id):
    require_roles("CoopAdmin", "Member")
    return ok(reference_view(get_reference_or_404(reference_id)))


@bp.post("/coop/member-references/<reference_id>/accept")
def accept_reference(reference_id):
    require_roles("CoopAdmin")
    ref = get_reference_or_404(reference_id)
    if ref["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Reference must be PENDING to accept")
    referee = db.store["members"].get(ref["referee_member_id"])
    # The referee-vetting gate fires for referees who have lost (or never
    # could hold) standing. Applicants in the vetting pipeline may vouch so
    # the mutual-reference web can be built; a suspended or removed member's
    # vouching is worthless and is rejected.
    if referee is None or referee["vetting_status"] in ("SUSPENDED", "REMOVED"):
        raise ApiError(
            ERR_REFEREE_NOT_VETTED, 409, "referee_member_id must reference a VETTED member"
        )
    if ref["referee_member_id"] == ref["subject_member_id"]:
        raise ApiError(
            ERR_SELF_REFERENCE, 422, "Self-vouching is prohibited: referee == subject"
        )
    ref["status"] = "ACCEPTED"
    ref["decided_at"] = clock.now()
    touch(ref)
    # Reciprocity auto-linking: if the reverse reference (subject vouching
    # for the referee) is also ACCEPTED, link the pair on both rows.
    for other in db.store["references"].values():
        if (
            other["id"] != ref["id"]
            and other["subject_member_id"] == ref["referee_member_id"]
            and other["referee_member_id"] == ref["subject_member_id"]
            and other["status"] == "ACCEPTED"
        ):
            ref["reciprocal_reference_id"] = other["id"]
            other["reciprocal_reference_id"] = ref["id"]
            touch(ref)
            touch(other)
            break
    return ok(reference_view(ref))


@bp.post("/coop/member-references/<reference_id>/reject")
def reject_reference(reference_id):
    require_roles("CoopAdmin")
    ref = get_reference_or_404(reference_id)
    if ref["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Reference must be PENDING to reject")
    ref["status"] = "REJECTED"
    ref["decided_at"] = clock.now()
    touch(ref)
    return ok(reference_view(ref))


@bp.post("/coop/member-references/<reference_id>/withdraw")
def withdraw_reference(reference_id):
    user_id, _ = require_roles("Member")
    ref = get_reference_or_404(reference_id)
    if ref["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Reference must be PENDING to withdraw")
    if user_id != ref["referee_member_id"]:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the referee may withdraw their own reference"
        )
    ref["status"] = "WITHDRAWN"
    touch(ref)
    return ok(reference_view(ref))
