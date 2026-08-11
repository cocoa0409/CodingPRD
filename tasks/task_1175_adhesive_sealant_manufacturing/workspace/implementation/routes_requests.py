"""FormulationRequest endpoints (technical-service pipeline)."""
from flask import Blueprint, request, g

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INSUFFICIENT_PERMISSIONS,
    ERR_REQUEST_INVALID_STATE, not_found,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_int, f_num, f_bool, f_enum,
)
from services import new_entity, touch, get_request, ser_request, sorted_rows

bp = Blueprint("requests", __name__)

CHEMISTRY_FAMILIES = ["EPOXY", "POLYURETHANE", "SILICONE", "ACRYLIC"]
DECIDE_OUTCOMES = ["APPROVED", "DECLINED"]


@bp.post("/api/formulation-requests")
@require_roles("Distributor")
def create_request():
    b = body_json()
    # ownership (priority 2): distributor_id must equal the caller's X-User-ID
    raw_dist = b.get("distributor_id")
    if isinstance(raw_dist, str) and raw_dist != g.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Distributor may only submit requests for its own account",
            403,
        )
    distributor_id = f_str(b, "distributor_id")
    contact_name = f_str(b, "contact_name")
    substrate = f_str(b, "target_substrate")
    required_mpa = f_num(b, "required_bond_strength_mpa", lo=0)
    notes = f_str(b, "application_notes")
    if distributor_id != g.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Distributor may only submit requests for its own account",
            403,
        )
    if distributor_id not in store.distributors:
        raise not_found("Distributor")
    r = new_entity()
    r.update({
        "distributor_id": distributor_id,
        "contact_name": contact_name,
        "target_substrate": substrate,
        "required_bond_strength_mpa": required_mpa,
        "application_notes": notes,
        "info_request_note": None,
        "response_note": None,
        "decision_outcome": None,
        "resulting_formulation_id": None,
        "status": "SUBMITTED",
    })
    store.requests[r["id"]] = r
    return ok(ser_request(r), 201)


@bp.get("/api/formulation-requests")
@require_roles(*ALL_ROLES)
def list_requests():
    limit, offset = pagination_params()
    rows = list(store.requests.values())
    # Distributor-role callers see only their own rows
    if g.user_role == "Distributor":
        rows = [r for r in rows if r["distributor_id"] == g.user_id]
    did = request.args.get("distributor_id")
    fid = request.args.get("resulting_formulation_id")
    if did is not None:
        rows = [r for r in rows if r["distributor_id"] == did]
    if fid is not None:
        rows = [r for r in rows if r["resulting_formulation_id"] == fid]
    return ok_list([ser_request(r) for r in sorted_rows(rows)], limit, offset)


@bp.get("/api/formulation-requests/<rid>")
@require_roles(*ALL_ROLES)
def get_one_request(rid):
    return ok(ser_request(get_request(rid)), 200)


@bp.post("/api/formulation-requests/<rid>/start-review")
@require_roles("TechServiceEngineer")
def start_review(rid):
    body_json()
    r = get_request(rid)
    if r["status"] != "SUBMITTED":
        raise ApiError(ERR_REQUEST_INVALID_STATE, "start-review requires SUBMITTED", 409)
    r["status"] = "TECH_REVIEW"
    touch(r)
    return ok(ser_request(r), 200)


@bp.post("/api/formulation-requests/<rid>/request-info")
@require_roles("TechServiceEngineer")
def request_info(rid):
    b = body_json()
    note = f_str(b, "info_request_note")
    r = get_request(rid)
    if r["status"] != "TECH_REVIEW":
        raise ApiError(ERR_REQUEST_INVALID_STATE, "request-info requires TECH_REVIEW", 409)
    r["info_request_note"] = note
    r["status"] = "NEEDS_INFO"
    touch(r)
    return ok(ser_request(r), 200)


@bp.post("/api/formulation-requests/<rid>/respond")
@require_roles("Distributor")
def respond(rid):
    b = body_json()
    note = f_str(b, "response_note")
    r = get_request(rid)
    if r["distributor_id"] != g.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Only the owning distributor may respond",
            403,
        )
    if r["status"] != "NEEDS_INFO":
        raise ApiError(ERR_REQUEST_INVALID_STATE, "respond requires NEEDS_INFO", 409)
    r["response_note"] = note
    r["status"] = "TECH_REVIEW"
    touch(r)
    return ok(ser_request(r), 200)


@bp.post("/api/formulation-requests/<rid>/decide")
@require_roles("TechServiceEngineer")
def decide(rid):
    b = body_json()
    outcome = f_enum(b, "outcome", DECIDE_OUTCOMES)
    r = get_request(rid)
    if r["status"] != "TECH_REVIEW":
        raise ApiError(ERR_REQUEST_INVALID_STATE, "decide requires TECH_REVIEW", 409)
    r["decision_outcome"] = outcome
    r["status"] = outcome
    touch(r)
    return ok(ser_request(r), 200)


@bp.post("/api/formulation-requests/<rid>/start-development")
@require_roles("TechServiceEngineer")
def start_development(rid):
    body_json()
    r = get_request(rid)
    if r["status"] != "APPROVED":
        raise ApiError(ERR_REQUEST_INVALID_STATE, "start-development requires APPROVED", 409)
    r["status"] = "IN_DEVELOPMENT"
    touch(r)
    return ok(ser_request(r), 200)


@bp.post("/api/formulation-requests/<rid>/convert")
@require_roles("TechServiceEngineer")
def convert(rid):
    b = body_json()
    code = f_str(b, "formulation_code")
    name = f_str(b, "formulation_name")
    family = f_enum(b, "chemistry_family", CHEMISTRY_FAMILIES)
    moisture = f_bool(b, "moisture_sensitive")
    solvent = f_num(b, "solvent_content_pct", lo=0, hi=100)
    flash = f_num(b, "flash_point_c")
    pot_life = f_int(b, "pot_life_minutes", lo=0)
    shelf_life = f_int(b, "shelf_life_months", lo=0)
    spec_min = f_num(b, "spec_min_bond_strength_mpa", lo=0)
    min_shelf = f_int(b, "min_remaining_shelf_life_days", lo=0)
    r = get_request(rid)
    if r["status"] != "IN_DEVELOPMENT":
        raise ApiError(ERR_REQUEST_INVALID_STATE, "convert requires IN_DEVELOPMENT", 409)
    if any(f["code"] == code for f in store.formulations.values()):
        raise ApiError(ERR_INVALID_REQUEST, "formulation_code must be unique across all formulations", 400)
    f = new_entity()
    f.update({
        "code": code,
        "name": name,
        "chemistry_family": family,
        "moisture_sensitive": moisture,
        "solvent_content_pct": solvent,
        "flash_point_c": flash,
        "pot_life_minutes": pot_life,
        "shelf_life_months": shelf_life,
        "spec_min_bond_strength_mpa": spec_min,
        "min_remaining_shelf_life_days": min_shelf,
        "status": "DRAFT",
    })
    store.formulations[f["id"]] = f
    r["resulting_formulation_id"] = f["id"]
    r["status"] = "CONVERTED"
    touch(r)
    return ok(ser_request(r), 200)
