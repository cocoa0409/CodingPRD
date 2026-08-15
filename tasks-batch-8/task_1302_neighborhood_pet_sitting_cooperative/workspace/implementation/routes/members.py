"""Member lifecycle: application, liability, vetting, suspend/reinstate/remove."""

from flask import Blueprint, request

import clock
import db
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INSUFFICIENT_REFERENCES,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LIABILITY_NOT_ACCEPTED,
    ERR_NOT_FOUND,
    ERR_REMOVAL_CRITERIA_NOT_MET,
    ERR_RECIPROCITY_NOT_MET,
)
from middleware import body, paginate, require_roles
from response import created, ok
from serializers import member_view
from services.calc import JOINING_GRANT_HOURS, SCORE_INIT, append_ledger
from services.cascade import removal_eligible, remove_cascade, suspend_cascade
from util import base_entity, round2, touch

bp = Blueprint("members", __name__)


def get_member_or_404(member_id):
    member = db.store["members"].get(member_id)
    if member is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Member {member_id} does not exist")
    return member


def _require_non_empty(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is required")
    return value


@bp.post("/coop/members")
def apply_for_membership():
    require_roles("Anonymous")
    data = body()
    display_name = _require_non_empty(data, "display_name")
    email = _require_non_empty(data, "email")
    address_block = _require_non_empty(data, "address_block")
    phone = _require_non_empty(data, "phone")
    mediator_flag = data.get("mediator_flag", False)
    if not isinstance(mediator_flag, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "mediator_flag must be a boolean")
    # Email uniqueness, compared case-insensitively.
    for existing in db.store["members"].values():
        if existing["email"].lower() == email.lower():
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "email is already registered"
            )
    member = base_entity()
    member.update(
        {
            "display_name": display_name,
            "email": email,
            "address_block": address_block,
            "phone": phone,
            "vetting_status": "APPLIED",
            "mediator_flag": mediator_flag,
            "credit_balance_hours": round2(0),
            "provisional_credit_hours": round2(0),
            "reliability_score": SCORE_INIT,
            "suspension_reason": None,
            "removal_reason": None,
            "accepted_liability_at": None,
            "co_op_joined_at": None,
        }
    )
    db.store["members"][member["id"]] = member
    return created(member_view(member))


@bp.get("/coop/members")
def list_members():
    require_roles("CoopAdmin", "Member")
    items = list(db.store["members"].values())
    vetting_status = request.args.get("vetting_status")
    if vetting_status is not None:
        items = [m for m in items if m["vetting_status"] == vetting_status]
    return paginate(items, member_view)


@bp.get("/coop/members/<member_id>")
def get_member(member_id):
    require_roles("CoopAdmin", "Member")
    return ok(member_view(get_member_or_404(member_id)))


@bp.post("/coop/members/<member_id>/accept-liability")
def accept_liability(member_id):
    user_id, _ = require_roles("Member")
    member = get_member_or_404(member_id)
    if user_id != member["id"]:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the member themself may accept the liability agreement"
        )
    member["accepted_liability_at"] = clock.now()
    touch(member)
    return ok(member_view(member))


@bp.post("/coop/members/<member_id>/submit-references")
def submit_references(member_id):
    require_roles("CoopAdmin")
    member = get_member_or_404(member_id)
    if member["vetting_status"] != "APPLIED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Member must be in APPLIED to submit references"
        )
    pending = [
        r
        for r in db.store["references"].values()
        if r["subject_member_id"] == member["id"] and r["status"] == "PENDING"
    ]
    if len(pending) < 2:
        raise ApiError(
            ERR_INSUFFICIENT_REFERENCES,
            409,
            "At least 2 PENDING references are required",
        )
    member["vetting_status"] = "REFERENCES_PENDING"
    touch(member)
    return ok(member_view(member))


@bp.post("/coop/members/<member_id>/finalize-vetting")
def finalize_vetting(member_id):
    require_roles("CoopAdmin")
    member = get_member_or_404(member_id)
    if member["vetting_status"] != "REFERENCES_PENDING":
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Member must be in REFERENCES_PENDING to finalize vetting",
        )
    accepted = [
        r
        for r in db.store["references"].values()
        if r["subject_member_id"] == member["id"] and r["status"] == "ACCEPTED"
    ]
    if len(accepted) < 2:
        raise ApiError(
            ERR_INSUFFICIENT_REFERENCES,
            409,
            "At least 2 ACCEPTED references are required",
        )
    # Mutual reference requirement: for every ACCEPTED reference R, the
    # reverse reference (subject vouching for R's referee) must be ACCEPTED.
    for ref in accepted:
        reverse_ok = any(
            r["subject_member_id"] == ref["referee_member_id"]
            and r["referee_member_id"] == member["id"]
            and r["status"] == "ACCEPTED"
            for r in db.store["references"].values()
        )
        if not reverse_ok:
            raise ApiError(
                ERR_RECIPROCITY_NOT_MET,
                409,
                "Mutual reference requirement not satisfied",
            )
    if member["accepted_liability_at"] is None:
        raise ApiError(
            ERR_LIABILITY_NOT_ACCEPTED,
            409,
            "Member has not accepted the co-op liability agreement",
        )
    member["vetting_status"] = "VETTED"
    member["co_op_joined_at"] = clock.now()
    member["credit_balance_hours"] = round2(0)
    touch(member)
    append_ledger(
        member,
        "JOINING_GRANT",
        JOINING_GRANT_HOURS,
        memo="Joining grant on vetting",
    )
    return ok(member_view(member))


@bp.post("/coop/members/<member_id>/suspend")
def suspend_member(member_id):
    require_roles("CoopAdmin")
    member = get_member_or_404(member_id)
    if member["vetting_status"] != "VETTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Member must be VETTED to suspend")
    data = body()
    reason = data.get("suspension_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "suspension_reason must be non-empty"
        )
    member["vetting_status"] = "SUSPENDED"
    member["suspension_reason"] = reason
    touch(member)
    suspend_cascade(member)
    return ok(member_view(member))


@bp.post("/coop/members/<member_id>/reinstate")
def reinstate_member(member_id):
    require_roles("CoopAdmin")
    member = get_member_or_404(member_id)
    if member["vetting_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Member must be SUSPENDED to reinstate")
    member["vetting_status"] = "VETTED"
    member["suspension_reason"] = None
    touch(member)
    return ok(member_view(member))


@bp.post("/coop/members/<member_id>/remove")
def remove_member(member_id):
    require_roles("CoopAdmin")
    member = get_member_or_404(member_id)
    if member["vetting_status"] not in ("VETTED", "SUSPENDED"):
        raise ApiError(
            ERR_INVALID_STATE, 409, "Member must be VETTED or SUSPENDED to remove"
        )
    data = body()
    reason = data.get("removal_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "removal_reason must be non-empty")
    if not removal_eligible(member):
        raise ApiError(
            ERR_REMOVAL_CRITERIA_NOT_MET,
            409,
            "Member does not meet removal eligibility criteria",
        )
    remove_cascade(member, reason)
    member["vetting_status"] = "REMOVED"
    member["removal_reason"] = reason
    touch(member)
    return ok(member_view(member))
