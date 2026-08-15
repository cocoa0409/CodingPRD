"""Clock, vessel, and plan endpoints (PRD 3.1, 3.12)."""

import re

from flask import Blueprint

from auth import ALL_ROLES, require_roles
from db import store
from errors import (ApiError, ERR_INVALID_STATE, ERR_MULTIPLE_APPROVED_PLANS,
                    ERR_PLAN_REVISION_REGRESSION, ERR_STALE_VERSION,
                    ERR_VALIDATION)
from response import ok, ok_list
from services import (compute_determination, get_plan, get_vessel, mint,
                      plan_json, reevaluate_time_transitions, touch,
                      vessel_json)
from utils import (by_created, get_body, pagination_params, parse_dt,
                   query_filter, req_bool, req_enum, req_field, req_int,
                   req_num, req_str)

bp = Blueprint("core", __name__)

BWMS_TYPES = ("NONE", "EXCHANGE_ONLY", "TREATMENT_USCG_TYPE_APPROVED",
              "TREATMENT_ALTERNATIVE")
PLAN_AUTHORITIES = ("USCG", "CLASS_SOCIETY_ON_BEHALF")
IMO_RE = re.compile(r"^\d{7}$")
VOYAGE_TERMINAL = ("COMPLIANT", "NONCOMPLIANT", "EXEMPT")


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    body = get_body()
    ts = parse_dt(req_field(body, "to_iso8601"), "to_iso8601")
    with store.lock:
        store.clock = ts
        reevaluate_time_transitions()
    return ok({}, 200)


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------

@bp.post("/vessels")
@require_roles("ShoreComplianceOfficer")
def create_vessel():
    body = get_body()
    imo = req_str(body, "imo_number")
    if not IMO_RE.match(imo):
        raise ApiError(ERR_VALIDATION, 400,
                       "imo_number must be a unique 7-digit numeric string")
    if any(v["imo_number"] == imo for v in store.vessels.values()):
        raise ApiError(ERR_VALIDATION, 400, "imo_number is already registered")
    name = req_str(body, "vessel_name")
    bwms_type = req_enum(body, "bwms_type", BWMS_TYPES)
    installation = None
    if bwms_type != "NONE":
        installation = parse_dt(req_field(body, "bwms_installation_date"),
                                "bwms_installation_date")
    elif body.get("bwms_installation_date") is not None:
        installation = parse_dt(body["bwms_installation_date"],
                                "bwms_installation_date")
    gross_tonnage = req_int(body, "gross_tonnage", min_v=1)
    keel_laid = parse_dt(req_field(body, "keel_laid_date"), "keel_laid_date")
    capacity = req_num(body, "ballast_capacity_m3", gt=0)

    with store.lock:
        vessel = mint({
            "imo_number": imo,
            "vessel_name": name,
            "flag_state": "US",
            "bwms_type": bwms_type,
            "bwms_installation_date": installation,
            "gross_tonnage": gross_tonnage,
            "keel_laid_date": keel_laid,
            "ballast_capacity_m3": capacity,
            "compliance_posture": "OPEN",
            "active_enforcement_case_id": None,
            "last_psc_inspection_at": None,
        })
        store.vessels[vessel["id"]] = vessel
    return ok(vessel_json(vessel), 201)


@bp.get("/vessels")
@require_roles(*ALL_ROLES)
def list_vessels():
    limit, offset = pagination_params()
    imo = query_filter("imo_number")
    posture = query_filter("compliance_posture")
    items = list(store.vessels.values())
    if imo is not None:
        items = [v for v in items if v["imo_number"] == imo]
    if posture is not None:
        items = [v for v in items if v["compliance_posture"] == posture]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([vessel_json(v) for v in page], total, limit, offset)


@bp.get("/vessels/<vessel_id>")
@require_roles(*ALL_ROLES)
def fetch_vessel(vessel_id):
    return ok(vessel_json(get_vessel(vessel_id)), 200)


# ---------------------------------------------------------------------------
# Ballast water management plans
# ---------------------------------------------------------------------------

@bp.post("/vessels/<vessel_id>/plans")
@require_roles("ShoreComplianceOfficer")
def create_plan(vessel_id):
    vessel = get_vessel(vessel_id)
    body = get_body()
    expected = req_int(body, "expected_vessel_version")
    if expected != vessel["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_vessel_version does not match the vessel's "
                       "current version")
    revision = req_int(body, "plan_revision", min_v=1)
    authority = req_enum(body, "approval_authority", PLAN_AUTHORITIES)
    approved_at = parse_dt(req_field(body, "approved_at"), "approved_at")
    distance = req_num(body, "exchange_distance_nm", gt=0)
    sediment = req_bool(body, "sediment_management_included")

    with store.lock:
        existing = [p["plan_revision"] for p in store.plans.values()
                    if p["vessel_id"] == vessel["id"]]
        if existing and revision <= max(existing):
            raise ApiError(ERR_PLAN_REVISION_REGRESSION, 422,
                           "plan_revision must be strictly greater than every "
                           "existing revision for the vessel")
        plan = mint({
            "vessel_id": vessel["id"],
            "plan_revision": revision,
            "approval_authority": authority,
            "approved_at": approved_at,
            "status": "DRAFT",
            "exchange_distance_nm": distance,
            "sediment_management_included": sediment,
        })
        store.plans[plan["id"]] = plan
        touch(vessel)
    return ok(plan_json(plan), 201)


@bp.get("/vessels/<vessel_id>/plans")
@require_roles(*ALL_ROLES)
def list_plans(vessel_id):
    vessel = get_vessel(vessel_id)
    limit, offset = pagination_params()
    status = query_filter("status")
    items = [p for p in store.plans.values() if p["vessel_id"] == vessel["id"]]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([plan_json(p) for p in page], total, limit, offset)


@bp.get("/vessels/<vessel_id>/plans/<plan_id>")
@require_roles(*ALL_ROLES)
def fetch_plan(vessel_id, plan_id):
    vessel = get_vessel(vessel_id)
    return ok(plan_json(get_plan(vessel, plan_id)), 200)


@bp.post("/vessels/<vessel_id>/plans/<plan_id>/submit")
@require_roles("ShoreComplianceOfficer")
def submit_plan(vessel_id, plan_id):
    vessel = get_vessel(vessel_id)
    plan = get_plan(vessel, plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT plan may be submitted")
    if vessel["bwms_type"] == "NONE" and not plan["sediment_management_included"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "submission requires an installed BWMS or sediment "
                       "management procedures in the plan")
    with store.lock:
        plan["status"] = "SUBMITTED"
        touch(plan)
        touch(vessel)
    return ok(plan_json(plan), 200)


@bp.post("/vessels/<vessel_id>/plans/<plan_id>/approve")
@require_roles("FlagSurveyor")
def approve_plan(vessel_id, plan_id):
    vessel = get_vessel(vessel_id)
    plan = get_plan(vessel, plan_id)
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SUBMITTED plan may be approved")
    with store.lock:
        higher_approved = any(
            p for p in store.plans.values()
            if p["vessel_id"] == vessel["id"] and p["id"] != plan["id"]
            and p["status"] == "APPROVED"
            and p["plan_revision"] > plan["plan_revision"])
        if higher_approved:
            raise ApiError(ERR_MULTIPLE_APPROVED_PLANS, 409,
                           "another plan with a higher plan_revision is "
                           "already APPROVED for the vessel")
        for other in store.plans.values():
            if (other["vessel_id"] == vessel["id"] and other["id"] != plan["id"]
                    and other["status"] == "APPROVED"):
                other["status"] = "SUPERSEDED"
                touch(other)
        plan["status"] = "APPROVED"
        touch(plan)
        touch(vessel)
        # Recompute determinations for every non-terminal voyage.
        for voyage in store.voyages.values():
            if (voyage["vessel_id"] == vessel["id"]
                    and voyage["compliance_status"] not in VOYAGE_TERMINAL):
                compute_determination(vessel, voyage, "PLAN_AMENDMENT")
                touch(voyage)
    return ok(plan_json(plan), 200)


@bp.post("/vessels/<vessel_id>/plans/<plan_id>/withdraw")
@require_roles("ShoreComplianceOfficer")
def withdraw_plan(vessel_id, plan_id):
    vessel = get_vessel(vessel_id)
    plan = get_plan(vessel, plan_id)
    if plan["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT or SUBMITTED plan may be withdrawn")
    with store.lock:
        plan["status"] = "WITHDRAWN"
        touch(plan)
    return ok(plan_json(plan), 200)
