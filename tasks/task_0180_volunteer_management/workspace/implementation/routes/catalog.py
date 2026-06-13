"""Catalog + credential endpoints (PRD §3.1): Skill, VolunteerSkill,
WaiverTemplate, WaiverAcceptance, TrainingModule, TrainingCompletion."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_role
from response import object_response, array_response
from services.common import (base_record, get_or_404, find_fk_or_404,
                             require_org_active, get_json, require_field,
                             optional_field, list_collection)
from services.serialize import serialize, serialize_list
from timeutil import now_iso, parse_dt, add_seconds

bp = Blueprint("catalog", __name__)


# ---- Skill ----------------------------------------------------------------
@bp.post("/vm/skills")
@require_role("ComplianceOfficer", "ShiftCoordinator")
def create_skill():
    body = get_json()
    org_id = require_field(body, "organization_id", str)
    code = require_field(body, "code", str)
    label = require_field(body, "label", str)
    with store.lock:
        org = find_fk_or_404("organizations", org_id)
        require_org_active(org)
        for s in store.skills.values():
            if s["organization_id"] == org_id and s["code"] == code:
                raise ApiError("ERR_INVALID_REQUEST", "skill code already exists in org")
        rec = base_record("skills")
        rec.update({"organization_id": org_id, "code": code, "label": label})
        store.skills[rec["id"]] = rec
    return object_response(serialize("skills", rec), status=201)


@bp.get("/vm/skills")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def list_skills():
    org_id = request.args.get("organization_id")
    page, limit, offset, total = list_collection(
        "skills", lambda r: org_id is None or r["organization_id"] == org_id)
    return array_response(serialize_list("skills", page), limit, offset, total)


@bp.get("/vm/skills/<skill_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def get_skill(skill_id):
    rec = get_or_404("skills", skill_id)
    return object_response(serialize("skills", rec))


# ---- VolunteerSkill -------------------------------------------------------
@bp.post("/vm/volunteer-skills")
@require_role("ComplianceOfficer", "ShiftCoordinator")
def create_volunteer_skill():
    body = get_json()
    volunteer_id = require_field(body, "volunteer_id", str)
    skill_id = require_field(body, "skill_id", str)
    proficiency = optional_field(body, "proficiency", "VERIFIED", str)
    if proficiency not in ("SELF_DECLARED", "VERIFIED"):
        raise ApiError("ERR_INVALID_REQUEST", "proficiency invalid")
    with store.lock:
        volunteer = find_fk_or_404("volunteers", volunteer_id)
        skill = find_fk_or_404("skills", skill_id)
        org = store.organizations.get(volunteer["organization_id"])
        if org is not None:
            require_org_active(org)
        rec = base_record("volunteer_skills")
        rec.update({"volunteer_id": volunteer_id, "skill_id": skill_id,
                    "proficiency": proficiency})
        store.volunteer_skills[rec["id"]] = rec
    return object_response(serialize("volunteer_skills", rec), status=201)


@bp.get("/vm/volunteer-skills")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def list_volunteer_skills():
    volunteer_id = request.args.get("volunteer_id")
    skill_id = request.args.get("skill_id")

    def pred(r):
        if volunteer_id is not None and r["volunteer_id"] != volunteer_id:
            return False
        if skill_id is not None and r["skill_id"] != skill_id:
            return False
        return True

    page, limit, offset, total = list_collection("volunteer_skills", pred)
    return array_response(serialize_list("volunteer_skills", page), limit, offset, total)


@bp.get("/vm/volunteer-skills/<vs_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def get_volunteer_skill(vs_id):
    rec = get_or_404("volunteer_skills", vs_id)
    return object_response(serialize("volunteer_skills", rec))


# ---- WaiverTemplate -------------------------------------------------------
@bp.post("/vm/waiver-templates")
@require_role("ComplianceOfficer")
def create_waiver_template():
    body = get_json()
    org_id = require_field(body, "organization_id", str)
    code = require_field(body, "code", str)
    revision = optional_field(body, "revision", 1, int)
    if isinstance(revision, bool):
        raise ApiError("ERR_INVALID_REQUEST", "revision must be an integer")
    with store.lock:
        org = find_fk_or_404("organizations", org_id)
        require_org_active(org)
        for w in store.waiver_templates.values():
            if w["organization_id"] == org_id and w["code"] == code:
                raise ApiError("ERR_INVALID_REQUEST", "waiver code already exists in org")
        rec = base_record("waiver_templates")
        rec.update({"organization_id": org_id, "code": code, "revision": revision})
        store.waiver_templates[rec["id"]] = rec
    return object_response(serialize("waiver_templates", rec), status=201)


@bp.get("/vm/waiver-templates")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def list_waiver_templates():
    org_id = request.args.get("organization_id")
    page, limit, offset, total = list_collection(
        "waiver_templates", lambda r: org_id is None or r["organization_id"] == org_id)
    return array_response(serialize_list("waiver_templates", page), limit, offset, total)


@bp.get("/vm/waiver-templates/<wt_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def get_waiver_template(wt_id):
    rec = get_or_404("waiver_templates", wt_id)
    return object_response(serialize("waiver_templates", rec))


# ---- WaiverAcceptance -----------------------------------------------------
@bp.post("/vm/waiver-acceptances")
@require_role("Volunteer", "ComplianceOfficer")
def create_waiver_acceptance():
    body = get_json()
    volunteer_id = require_field(body, "volunteer_id", str)
    waiver_template_id = require_field(body, "waiver_template_id", str)
    with store.lock:
        volunteer = find_fk_or_404("volunteers", volunteer_id)
        template = find_fk_or_404("waiver_templates", waiver_template_id)
        org = store.organizations.get(volunteer["organization_id"])
        if org is not None:
            require_org_active(org)
        rec = base_record("waiver_acceptances")
        rec.update({"volunteer_id": volunteer_id,
                    "waiver_template_id": waiver_template_id,
                    "accepted_revision": template["revision"]})
        store.waiver_acceptances[rec["id"]] = rec
    return object_response(serialize("waiver_acceptances", rec), status=201)


@bp.get("/vm/waiver-acceptances")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def list_waiver_acceptances():
    volunteer_id = request.args.get("volunteer_id")
    waiver_template_id = request.args.get("waiver_template_id")

    def pred(r):
        if volunteer_id is not None and r["volunteer_id"] != volunteer_id:
            return False
        if waiver_template_id is not None and r["waiver_template_id"] != waiver_template_id:
            return False
        return True

    page, limit, offset, total = list_collection("waiver_acceptances", pred)
    return array_response(serialize_list("waiver_acceptances", page), limit, offset, total)


@bp.get("/vm/waiver-acceptances/<wa_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def get_waiver_acceptance(wa_id):
    rec = get_or_404("waiver_acceptances", wa_id)
    return object_response(serialize("waiver_acceptances", rec))


# ---- TrainingModule -------------------------------------------------------
@bp.post("/vm/training-modules")
@require_role("ComplianceOfficer")
def create_training_module():
    body = get_json()
    org_id = require_field(body, "organization_id", str)
    code = require_field(body, "code", str)
    valid_days = optional_field(body, "valid_days", 730, int)
    if isinstance(valid_days, bool):
        raise ApiError("ERR_INVALID_REQUEST", "valid_days must be an integer")
    with store.lock:
        org = find_fk_or_404("organizations", org_id)
        require_org_active(org)
        for t in store.training_modules.values():
            if t["organization_id"] == org_id and t["code"] == code:
                raise ApiError("ERR_INVALID_REQUEST", "training code already exists in org")
        rec = base_record("training_modules")
        rec.update({"organization_id": org_id, "code": code, "valid_days": valid_days})
        store.training_modules[rec["id"]] = rec
    return object_response(serialize("training_modules", rec), status=201)


@bp.get("/vm/training-modules")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def list_training_modules():
    org_id = request.args.get("organization_id")
    page, limit, offset, total = list_collection(
        "training_modules", lambda r: org_id is None or r["organization_id"] == org_id)
    return array_response(serialize_list("training_modules", page), limit, offset, total)


@bp.get("/vm/training-modules/<tm_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def get_training_module(tm_id):
    rec = get_or_404("training_modules", tm_id)
    return object_response(serialize("training_modules", rec))


# ---- TrainingCompletion ---------------------------------------------------
@bp.post("/vm/training-completions")
@require_role("Volunteer", "ComplianceOfficer")
def create_training_completion():
    body = get_json()
    volunteer_id = require_field(body, "volunteer_id", str)
    training_module_id = require_field(body, "training_module_id", str)
    completed_at_raw = require_field(body, "completed_at", str)
    try:
        completed_at = parse_dt(completed_at_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "completed_at must be ISO-8601")
    with store.lock:
        volunteer = find_fk_or_404("volunteers", volunteer_id)
        module = find_fk_or_404("training_modules", training_module_id)
        org = store.organizations.get(volunteer["organization_id"])
        if org is not None:
            require_org_active(org)
        expires_at = add_seconds(completed_at, module["valid_days"] * 86400)
        rec = base_record("training_completions")
        rec.update({"volunteer_id": volunteer_id,
                    "training_module_id": training_module_id,
                    "completed_at": now_iso(completed_at),
                    "expires_at": now_iso(expires_at)})
        store.training_completions[rec["id"]] = rec
    return object_response(serialize("training_completions", rec), status=201)


@bp.get("/vm/training-completions")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def list_training_completions():
    volunteer_id = request.args.get("volunteer_id")
    training_module_id = request.args.get("training_module_id")

    def pred(r):
        if volunteer_id is not None and r["volunteer_id"] != volunteer_id:
            return False
        if training_module_id is not None and r["training_module_id"] != training_module_id:
            return False
        return True

    page, limit, offset, total = list_collection("training_completions", pred)
    return array_response(serialize_list("training_completions", page), limit, offset, total)


@bp.get("/vm/training-completions/<tc_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator")
def get_training_completion(tc_id):
    rec = get_or_404("training_completions", tc_id)
    return object_response(serialize("training_completions", rec))
