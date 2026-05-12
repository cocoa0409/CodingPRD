"""Skill catalog and VolunteerSkill endpoints."""
import re

from flask import Blueprint, g, request

import db
from errors import (
    ERR_DUPLICATE_SKILL_DECLARATION,
    ERR_FORBIDDEN,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    err,
)
from middleware import auth_required
from pagination import parse_pagination, slice_sorted
from response import list_response, success
from services.occ import check_occ
from validators import as_bool, as_enum, as_str, opt_field, require_field
from views import view_skill, view_volunteer_skill


bp = Blueprint("skills", __name__)

SKILL_CODE_RE = re.compile(r"^[A-Z0-9]+(_[A-Z0-9]+)*$")


@bp.post("/skills")
@auth_required(["SkillAdmin"])
def create_skill():
    body = request.get_json(silent=True) or {}
    code = as_str(require_field(body, "code"), "code", 2, 40)
    if not SKILL_CODE_RE.match(code):
        raise err(ERR_INVALID_INPUT, "skill code must be uppercase snake_case")
    name = as_str(require_field(body, "name"), "name", 1)
    requires_certificate = opt_field(body, "requires_certificate", False)
    if requires_certificate is None:
        requires_certificate = False
    if not isinstance(requires_certificate, bool):
        raise err(ERR_INVALID_INPUT, "requires_certificate must be boolean")
    sensitivity_level = opt_field(body, "sensitivity_level", "STANDARD") or "STANDARD"
    sensitivity_level = as_enum(sensitivity_level, "sensitivity_level",
                                {"STANDARD", "SENSITIVE"})

    with db.lock():
        for s in db.skills.values():
            if s.get("code") == code:
                raise err(ERR_INVALID_INPUT, "skill code already exists")
        row = {
            "code": code,
            "name": name,
            "requires_certificate": requires_certificate,
            "sensitivity_level": sensitivity_level,
        }
        db.init_common(row)
        db.skills[row["id"]] = row
    return success(view_skill(row), status_code=201)


@bp.get("/skills")
@auth_required(["Volunteer", "Organizer", "SkillAdmin"])
def list_skills():
    limit, offset = parse_pagination()
    page, total = slice_sorted(list(db.skills.values()), limit, offset)
    return list_response([view_skill(r) for r in page], limit, offset, total)


@bp.post("/volunteer-skills")
@auth_required(["Volunteer"])
def declare_skill():
    body = request.get_json(silent=True) or {}
    skill_id = as_str(require_field(body, "skill_id"), "skill_id", 1)
    cert_url = opt_field(body, "certificate_url", None)
    skill = db.skills.get(skill_id)
    if not skill:
        raise err(ERR_NOT_FOUND, "skill not found")
    volunteer = db.volunteers.get(g.user_id)
    if not volunteer:
        raise err(ERR_FORBIDDEN, "acting volunteer does not exist")
    if cert_url is not None and not isinstance(cert_url, str):
        raise err(ERR_INVALID_INPUT, "certificate_url must be a string")

    with db.lock():
        # Uniqueness: at most one (volunteer_id, skill_id) row in non-REJECTED
        for vs in db.volunteer_skills.values():
            if vs["volunteer_id"] == g.user_id and vs["skill_id"] == skill_id \
                    and vs["review_status"] != "REJECTED":
                raise err(ERR_DUPLICATE_SKILL_DECLARATION,
                          "duplicate non-rejected declaration")
        row = {
            "volunteer_id": g.user_id,
            "skill_id": skill_id,
            "certificate_url": cert_url,
            "review_status": "SELF_DECLARED",
            "reviewed_at": None,
            "reviewer_id": None,
        }
        db.init_common(row, with_version=False)
        db.volunteer_skills[row["id"]] = row
    return success(view_volunteer_skill(row), status_code=201)


@bp.post("/volunteer-skills/<vsid>/submit")
@auth_required(["Volunteer"])
def submit_vskill(vsid):
    row = db.volunteer_skills.get(vsid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer-skill not found")
    if row["volunteer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    skill = db.skills.get(row["skill_id"])
    with db.lock():
        if row["review_status"] != "SELF_DECLARED":
            raise err(ERR_INVALID_STATE, "must be SELF_DECLARED")
        if skill and skill.get("requires_certificate") and not row.get("certificate_url"):
            raise err(ERR_INVALID_STATE, "certificate_url required for this skill")
        row["review_status"] = "UNDER_REVIEW"
    return success(view_volunteer_skill(row))


@bp.post("/volunteer-skills/<vsid>/approve")
@auth_required(["SkillAdmin"])
def approve_vskill(vsid):
    row = db.volunteer_skills.get(vsid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer-skill not found")
    with db.lock():
        if row["review_status"] != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "must be UNDER_REVIEW")
        row["review_status"] = "APPROVED"
        row["reviewer_id"] = g.user_id
        row["reviewed_at"] = db.now_str()
    return success(view_volunteer_skill(row))


@bp.post("/volunteer-skills/<vsid>/reject")
@auth_required(["SkillAdmin"])
def reject_vskill(vsid):
    row = db.volunteer_skills.get(vsid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer-skill not found")
    with db.lock():
        if row["review_status"] != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "must be UNDER_REVIEW")
        row["review_status"] = "REJECTED"
        row["reviewer_id"] = g.user_id
        row["reviewed_at"] = db.now_str()
    return success(view_volunteer_skill(row))


@bp.post("/volunteer-skills/<vsid>/resubmit")
@auth_required(["Volunteer"])
def resubmit_vskill(vsid):
    row = db.volunteer_skills.get(vsid)
    if not row:
        raise err(ERR_NOT_FOUND, "volunteer-skill not found")
    if row["volunteer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    cert_url = require_field(body, "certificate_url")
    if not isinstance(cert_url, str):
        raise err(ERR_INVALID_INPUT, "certificate_url must be a string")
    with db.lock():
        if row["review_status"] != "APPROVED":
            raise err(ERR_INVALID_STATE, "must be APPROVED to resubmit")
        row["certificate_url"] = cert_url
        row["review_status"] = "UNDER_REVIEW"
    return success(view_volunteer_skill(row))
