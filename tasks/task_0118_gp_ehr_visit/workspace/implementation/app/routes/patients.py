"""Patient endpoints: create, get, patch, list, bind-pcp, unbind-pcp.

Note: nested resource routes for encounters/prescriptions/referrals that begin with
/patients/{patient_id}/... are registered in their own blueprints to keep this file focused.
"""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import (
    ROLE_BILLING_CLERK,
    ROLE_CLINIC_ADMIN,
    ROLE_NURSE,
    ROLE_PATIENT_PORTAL,
    ROLE_PROVIDER,
    ROLE_RECEPTIONIST,
    require_roles,
)
from ..clock import now
from ..errors import (
    err_forbidden,
    err_invalid_input,
    err_panel_full,
    err_pcp_already_bound,
    err_provider_not_pcp,
)
from ..helpers import (
    assert_array,
    assert_bool,
    assert_enum,
    assert_string,
    new_uuid,
    occ_check,
    paginate,
    parse_iso_date,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.audit import write_audit
from ..services.calculations import recompute_provider_panel
from ..services.lookups import get_patient, get_provider
from ..services.mutations import bump
from ..services.serialize import patient_to_dict
from ..store import store

bp = Blueprint("patients", __name__)


SEX_AT_BIRTH = ["MALE", "FEMALE", "UNKNOWN"]
SMOKING_STATUS = ["NEVER", "FORMER", "CURRENT", "UNKNOWN"]
MRN_PATTERN = r"^MRN[0-9]{8}$"


def _enforce_portal_self(patient: dict, caller_id: str, caller_role: str) -> None:
    """Portal users may only read their own patient-scoped resources."""
    if caller_role != ROLE_PATIENT_PORTAL:
        return
    from ..errors import err_portal_disabled
    if not patient.get("portal_enabled"):
        raise err_portal_disabled()
    if patient["id"] != caller_id:
        raise err_portal_disabled()


@bp.route("/patients", methods=["POST"])
@require_roles(ROLE_RECEPTIONIST, ROLE_CLINIC_ADMIN)
def create_patient(**_kwargs):
    body = require_json_object()

    mrn = assert_string(body.get("mrn"), "mrn", pattern=MRN_PATTERN)
    first_name = assert_string(body.get("first_name"), "first_name")
    last_name = assert_string(body.get("last_name"), "last_name")
    dob = parse_iso_date(body.get("date_of_birth"), "date_of_birth")
    sex = assert_enum(body.get("sex_at_birth"), "sex_at_birth", SEX_AT_BIRTH)

    portal_enabled = body.get("portal_enabled", False)
    if portal_enabled is None:
        portal_enabled = False
    portal_enabled = assert_bool(portal_enabled, "portal_enabled")

    smoking_status = body.get("smoking_status", "UNKNOWN")
    if smoking_status is None:
        smoking_status = "UNKNOWN"
    smoking_status = assert_enum(smoking_status, "smoking_status", SMOKING_STATUS)

    chronic_conditions = body.get("chronic_conditions", [])
    if chronic_conditions is None:
        chronic_conditions = []
    chronic_conditions = assert_array(chronic_conditions, "chronic_conditions")
    for c in chronic_conditions:
        if not isinstance(c, str):
            raise err_invalid_input("chronic_conditions must contain strings")

    s = store()
    with s.lock:
        ts = now()
        row = {
            "id": new_uuid(),
            "mrn": mrn,
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": dob,
            "sex_at_birth": sex,
            "pcp_provider_id": None,
            "pcp_bound_at": None,
            "portal_enabled": bool(portal_enabled),
            "smoking_status": smoking_status,
            "chronic_conditions": list(chronic_conditions),
            "status": "ACTIVE",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.patients[row["id"]] = row
    return created(patient_to_dict(row))


@bp.route("/patients/<pid>", methods=["GET"])
@require_roles(
    ROLE_RECEPTIONIST, ROLE_NURSE, ROLE_PROVIDER, ROLE_CLINIC_ADMIN, ROLE_PATIENT_PORTAL
)
def get_patient_route(pid: str, *, _caller_id: str, _caller_role: str):
    s = store()
    with s.lock:
        row = get_patient(pid)
        _enforce_portal_self(row, _caller_id, _caller_role)
        # Audit log per scaffold side_effects
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="patient.view",
            target_entity="Patient",
            target_id=pid,
        )
    return ok(patient_to_dict(row))


@bp.route("/patients/<pid>", methods=["PATCH"])
@require_roles(ROLE_NURSE, ROLE_PROVIDER, ROLE_CLINIC_ADMIN)
def patch_patient_route(pid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        row = get_patient(pid)
        # OCC tail of business validation
        if "smoking_status" in body and body["smoking_status"] is not None:
            ss = assert_enum(body["smoking_status"], "smoking_status", SMOKING_STATUS)
            row["smoking_status"] = ss
        if "chronic_conditions" in body and body["chronic_conditions"] is not None:
            cc = assert_array(body["chronic_conditions"], "chronic_conditions")
            for c in cc:
                if not isinstance(c, str):
                    raise err_invalid_input("chronic_conditions must contain strings")
            row["chronic_conditions"] = list(cc)
        if "portal_enabled" in body and body["portal_enabled"] is not None:
            pe = assert_bool(body["portal_enabled"], "portal_enabled")
            row["portal_enabled"] = bool(pe)

        # OCC: at tail
        occ_check(body.get("version"), row["version"])
        bump(row)
    return ok(patient_to_dict(row))


@bp.route("/patients", methods=["GET"])
@require_roles(ROLE_RECEPTIONIST, ROLE_NURSE, ROLE_PROVIDER, ROLE_CLINIC_ADMIN)
def list_patients(**_kwargs):
    limit, offset = parse_pagination()
    pcp_provider_id = request.args.get("pcp_provider_id")
    status = request.args.get("status")
    mrn = request.args.get("mrn")
    s = store()
    with s.lock:
        items = list(s.patients.values())
        if pcp_provider_id is not None:
            items = [p for p in items if p.get("pcp_provider_id") == pcp_provider_id]
        if status is not None:
            items = [p for p in items if p.get("status") == status]
        if mrn is not None:
            items = [p for p in items if p.get("mrn") == mrn]
        items.sort(key=lambda r: r["created_at"])
        total = len(items)
        page = paginate(items, limit, offset)
        out = [patient_to_dict(p) for p in page]
    return listing(out, total, limit, offset)


@bp.route("/patients/<pid>/bind-pcp", methods=["POST"])
@require_roles(ROLE_RECEPTIONIST, ROLE_CLINIC_ADMIN)
def bind_pcp(pid: str, **_kwargs):
    body = require_json_object()
    provider_id = assert_string(body.get("provider_id"), "provider_id")
    s = store()
    with s.lock:
        patient = get_patient(pid)
        provider = get_provider(provider_id, source="body")
        # State-eligibility (no real state machine here); business safety rules in order:
        # 8: PCP-eligibility (ERR_PROVIDER_NOT_PCP) — priority 8
        if provider.get("role_type") not in {"PCP_ONLY", "BOTH"}:
            raise err_provider_not_pcp()
        # 9: PCP_ALREADY_BOUND — priority 9
        if patient.get("pcp_provider_id") is not None:
            raise err_pcp_already_bound()
        # 15: panel_size + 1 <= panel_cap when role_type in {PCP_ONLY, BOTH}
        if provider.get("role_type") in {"PCP_ONLY", "BOTH"}:
            recompute_provider_panel(provider_id)
            if provider.get("panel_size", 0) + 1 > provider.get("panel_cap", 2000):
                raise err_panel_full()
        # OCC tail
        occ_check(body.get("version"), patient["version"])
        # Apply
        patient["pcp_provider_id"] = provider_id
        patient["pcp_bound_at"] = now()
        bump(patient)
        recompute_provider_panel(provider_id)
        # Provider mutates panel_size -> bump
        bump(provider)
    return ok(patient_to_dict(patient))


@bp.route("/patients/<pid>/unbind-pcp", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN)
def unbind_pcp(pid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        patient = get_patient(pid)
        prior_pcp = patient.get("pcp_provider_id")
        # OCC tail
        occ_check(body.get("version"), patient["version"])
        patient["pcp_provider_id"] = None
        patient["pcp_bound_at"] = None
        bump(patient)
        if prior_pcp:
            recompute_provider_panel(prior_pcp)
            prior_prov = s.providers.get(prior_pcp)
            if prior_prov is not None:
                bump(prior_prov)
    return ok(patient_to_dict(patient))
