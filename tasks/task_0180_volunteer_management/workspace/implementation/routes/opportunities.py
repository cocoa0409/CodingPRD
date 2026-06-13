"""Opportunity + Shift endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_role
from response import object_response, array_response
from services.common import (base_record, touch, get_or_404, find_fk_or_404,
                             require_org_active, get_json, require_field,
                             optional_field, require_int, list_collection)
from services.serialize import serialize, serialize_list
from services.calc import BG_TIER_RANK
from services.domain import (recompute_staffing, cancel_shift_cascade,
                            complete_shift_cascade)
from timeutil import now_iso, parse_dt

bp = Blueprint("opportunities", __name__)

_BG_TIERS = {"NONE", "BASIC", "STANDARD", "ENHANCED"}


# ---- Opportunity ----------------------------------------------------------
@bp.post("/vm/opportunities")
@require_role("ShiftCoordinator")
def create_opportunity():
    body = get_json()
    org_id = require_field(body, "organization_id", str)
    title = require_field(body, "title", str)
    required_bg_tier = optional_field(body, "required_bg_tier", "NONE", str)
    required_skill_ids = optional_field(body, "required_skill_ids", [], list)
    required_waiver_template_id = optional_field(body, "required_waiver_template_id", None, str)
    required_training_module_id = optional_field(body, "required_training_module_id", None, str)
    is_group_event = optional_field(body, "is_group_event", False, bool)
    if required_bg_tier not in _BG_TIERS:
        raise ApiError("ERR_INVALID_REQUEST", "required_bg_tier invalid")
    if not all(isinstance(x, str) for x in required_skill_ids):
        raise ApiError("ERR_INVALID_REQUEST", "required_skill_ids must be a list of ids")
    with store.lock:
        org = find_fk_or_404("organizations", org_id)
        require_org_active(org)
        for sid in required_skill_ids:
            if sid not in store.skills:
                raise ApiError("ERR_SKILL_NOT_FOUND", "required skill not found")
        if required_waiver_template_id is not None:
            find_fk_or_404("waiver_templates", required_waiver_template_id)
        if required_training_module_id is not None:
            find_fk_or_404("training_modules", required_training_module_id)
        rec = base_record("opportunities")
        rec.update({
            "organization_id": org_id,
            "title": title,
            "publication_status": "DRAFT",
            "staffing_status": "UNDERSTAFFED",
            "required_bg_tier": required_bg_tier,
            "required_skill_ids": list(required_skill_ids),
            "required_waiver_template_id": required_waiver_template_id,
            "required_training_module_id": required_training_module_id,
            "is_group_event": is_group_event,
        })
        store.opportunities[rec["id"]] = rec
    return object_response(serialize("opportunities", rec), status=201)


@bp.get("/vm/opportunities")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator", "CorporateSponsor")
def list_opportunities():
    org_id = request.args.get("organization_id")
    pub_status = request.args.get("publication_status")
    req_waiver = request.args.get("required_waiver_template_id")
    req_training = request.args.get("required_training_module_id")

    def pred(r):
        if org_id is not None and r["organization_id"] != org_id:
            return False
        if pub_status is not None and r["publication_status"] != pub_status:
            return False
        if req_waiver is not None and r["required_waiver_template_id"] != req_waiver:
            return False
        if req_training is not None and r["required_training_module_id"] != req_training:
            return False
        return True

    page, limit, offset, total = list_collection("opportunities", pred)
    return array_response(serialize_list("opportunities", page), limit, offset, total)


@bp.get("/vm/opportunities/<opp_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator", "CorporateSponsor")
def get_opportunity(opp_id):
    rec = get_or_404("opportunities", opp_id)
    return object_response(serialize("opportunities", rec))


@bp.post("/vm/opportunities/<opp_id>/publish")
@require_role("ShiftCoordinator")
def publish_opportunity(opp_id):
    with store.lock:
        rec = get_or_404("opportunities", opp_id)
        if rec["publication_status"] != "DRAFT":
            raise ApiError("ERR_OPPORTUNITY_NOT_DRAFT", "publish requires DRAFT")
        has_shift = any(s["opportunity_id"] == opp_id for s in store.shifts.values())
        if not has_shift:
            raise ApiError("ERR_OPPORTUNITY_HAS_NO_SHIFTS", "opportunity has no shifts")
        rec["publication_status"] = "PUBLISHED"
        touch(rec)
        recompute_staffing(rec)
    return object_response(serialize("opportunities", rec))


@bp.post("/vm/opportunities/<opp_id>/close")
@require_role("ShiftCoordinator")
def close_opportunity(opp_id):
    with store.lock:
        rec = get_or_404("opportunities", opp_id)
        if rec["publication_status"] != "PUBLISHED":
            raise ApiError("ERR_OPPORTUNITY_NOT_PUBLISHED", "close requires PUBLISHED")
        rec["publication_status"] = "CLOSED"
        touch(rec)
        # cascade: every child shift in OPEN/FULL -> CANCELLED (full shift cascade)
        child_shifts = [s for s in store.shifts.values()
                        if s["opportunity_id"] == opp_id and s["status"] in ("OPEN", "FULL")]
        child_shifts.sort(key=lambda s: s["_seq"])
        for sh in child_shifts:
            cancel_shift_cascade(sh)
            touch(sh)
        recompute_staffing(rec)
    return object_response(serialize("opportunities", rec))


# ---- Shift ----------------------------------------------------------------
@bp.post("/vm/shifts")
@require_role("ShiftCoordinator")
def create_shift():
    body = get_json()
    opportunity_id = require_field(body, "opportunity_id", str)
    starts_at_raw = require_field(body, "starts_at", str)
    ends_at_raw = require_field(body, "ends_at", str)
    capacity = require_field(body, "capacity")
    if isinstance(capacity, bool) or not isinstance(capacity, int):
        raise ApiError("ERR_INVALID_REQUEST", "capacity must be an integer")
    try:
        starts_at = parse_dt(starts_at_raw)
        ends_at = parse_dt(ends_at_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "starts_at/ends_at must be ISO-8601")
    with store.lock:
        opp = find_fk_or_404("opportunities", opportunity_id)
        org = store.organizations.get(opp["organization_id"])
        if org is not None:
            require_org_active(org)
        if not (ends_at > starts_at):
            raise ApiError("ERR_INVALID_SHIFT_TIMES", "ends_at must be after starts_at")
        if capacity < 1:
            raise ApiError("ERR_INVALID_CAPACITY", "capacity must be >= 1")
        rec = base_record("shifts")
        rec.update({
            "opportunity_id": opportunity_id,
            "starts_at": now_iso(starts_at),
            "ends_at": now_iso(ends_at),
            "capacity": capacity,
            "reserved_count": 0,
            "status": "OPEN",
            "group_reserved_seats": 0,
        })
        store.shifts[rec["id"]] = rec
        recompute_staffing(opp)
    return object_response(serialize("shifts", rec), status=201)


@bp.get("/vm/shifts")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator", "CorporateSponsor")
def list_shifts():
    opportunity_id = request.args.get("opportunity_id")
    status = request.args.get("status")

    def pred(r):
        if opportunity_id is not None and r["opportunity_id"] != opportunity_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    page, limit, offset, total = list_collection("shifts", pred)
    return array_response(serialize_list("shifts", page), limit, offset, total)


@bp.get("/vm/shifts/<shift_id>")
@require_role("Volunteer", "ComplianceOfficer", "ShiftCoordinator", "CorporateSponsor")
def get_shift(shift_id):
    rec = get_or_404("shifts", shift_id)
    return object_response(serialize("shifts", rec))


@bp.post("/vm/shifts/<shift_id>/cancel")
@require_role("ShiftCoordinator")
def cancel_shift(shift_id):
    with store.lock:
        rec = get_or_404("shifts", shift_id)
        if rec["status"] not in ("OPEN", "FULL"):
            raise ApiError("ERR_SHIFT_NOT_CANCELLABLE", "cancel requires OPEN/FULL")
        cancel_shift_cascade(rec)
        touch(rec)
    return object_response(serialize("shifts", rec))


@bp.post("/vm/shifts/<shift_id>/complete")
@require_role("ShiftCoordinator")
def complete_shift(shift_id):
    with store.lock:
        rec = get_or_404("shifts", shift_id)
        if rec["status"] not in ("OPEN", "FULL"):
            raise ApiError("ERR_SHIFT_NOT_COMPLETABLE", "complete requires OPEN/FULL")
        now = store.now()
        if now < parse_dt(rec["ends_at"]):
            raise ApiError("ERR_SHIFT_NOT_ENDED", "shift has not ended")
        complete_shift_cascade(rec)
        touch(rec)
    return object_response(serialize("shifts", rec))
