"""Sampling/inspections, noncompliance response, PSC deficiencies, and
enforcement cases (PRD 3.5, 3.6, 3.10, 3.11)."""

from datetime import timedelta

from flask import Blueprint, g

from auth import ALL_ROLES, require_roles
from db import now, store
from errors import (ApiError, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_STALE_VERSION)
from response import ok, ok_list
from services import (INTERNAL_ORGANISM_LIMIT, INTERNAL_TSS_LIMIT,
                      ORGANISM_LIMIT, TSS_LIMIT, case_json,
                      create_noncompliance, deficiency_json, get_case,
                      get_deficiency, get_inspection, get_noncompliance,
                      get_vessel, get_voyage, inspection_json, mint,
                      noncompliance_json, recompute_posture, touch)
from utils import (by_created, get_body, pagination_params, parse_dt,
                   query_bool, query_filter, req_enum, req_field, req_int,
                   req_list, req_num)

bp = Blueprint("compliance", __name__)

INSPECTION_KINDS = ("PORT_STATE_CONTROL", "FLAG_STATE", "CLASS_SOCIETY",
                    "COMPANY_INTERNAL")
SAMPLED_BY_ROLES = ("PSC_OFFICER", "FLAG_SURVEYOR", "COMPANY_AUDITOR")


# ---------------------------------------------------------------------------
# Sampling / inspections
# ---------------------------------------------------------------------------

@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/inspections")
@require_roles("PSCOfficer", "FlagSurveyor")
def create_inspection(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    body = get_body()
    kind = req_enum(body, "inspection_kind", INSPECTION_KINDS)
    sampled_at = parse_dt(req_field(body, "sampled_at"), "sampled_at")
    sampled_by = req_enum(body, "sampled_by_role", SAMPLED_BY_ROLES)
    organism = req_num(body, "indicator_organism_concentration", gte=0)
    tss = req_num(body, "tss_mg_per_l", gte=0)
    findings = req_list(body, "findings")

    with store.lock:
        inspection = mint({
            "voyage_id": voyage["id"],
            "inspection_kind": kind,
            "sampled_at": sampled_at,
            "sampled_by_role": sampled_by,
            "indicator_organism_concentration": organism,
            "tss_mg_per_l": tss,
            "findings": findings,
            "status": "RECORDED",
            "exceeded": None,
        })
        inspection["_recorded_by"] = g.user_id
        store.inspections[inspection["id"]] = inspection
        if kind == "PORT_STATE_CONTROL":
            vessel["last_psc_inspection_at"] = sampled_at
    return ok(inspection_json(inspection), 201)


@bp.get("/vessels/<vessel_id>/voyages/<voyage_id>/inspections")
@require_roles(*ALL_ROLES)
def list_inspections(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    limit, offset = pagination_params()
    kind = query_filter("inspection_kind")
    status = query_filter("status")
    items = [i for i in store.inspections.values()
             if i["voyage_id"] == voyage["id"]]
    if kind is not None:
        items = [i for i in items if i["inspection_kind"] == kind]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([inspection_json(i) for i in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/inspections/<inspection_id>/evaluate")
@require_roles("FlagSurveyor")
def evaluate_inspection(vessel_id, voyage_id, inspection_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    inspection = get_inspection(voyage, inspection_id)
    if inspection["status"] != "RECORDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a RECORDED inspection may be evaluated")
    if inspection.get("_recorded_by") == g.user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "the same X-User-ID may not both record and evaluate "
                       "an inspection")

    with store.lock:
        if inspection["inspection_kind"] == "COMPANY_INTERNAL":
            organism_limit = INTERNAL_ORGANISM_LIMIT
            tss_limit = INTERNAL_TSS_LIMIT
        else:
            organism_limit = ORGANISM_LIMIT
            tss_limit = TSS_LIMIT
        exceeded = (inspection["indicator_organism_concentration"] >= organism_limit
                    or inspection["tss_mg_per_l"] >= tss_limit)
        inspection["exceeded"] = exceeded
        inspection["status"] = "EVALUATED"
        touch(inspection)

        if exceeded:
            create_noncompliance(vessel, voyage["id"], "SAMPLING_EXCEEDANCE",
                                 inspection["id"])
            if inspection["inspection_kind"] == "PORT_STATE_CONTROL":
                identified = inspection["sampled_at"]
                deficiency = mint({
                    "vessel_id": vessel["id"],
                    "voyage_id": voyage["id"],
                    "psc_inspection_id": inspection["id"],
                    "deficiency_code": "14806",
                    "action_code": "A15",
                    "rectification_deadline": identified + timedelta(days=14),
                    "identified_at": identified,
                    "rectification_status": "OPEN",
                    "rectified_at": None,
                    "verified_at": None,
                    "is_priority_one": True,
                })
                deficiency["_claimed_by"] = None
                store.deficiencies[deficiency["id"]] = deficiency
            recompute_posture(vessel)
    return ok(inspection_json(inspection), 200)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/inspections/<inspection_id>/close")
@require_roles("FlagSurveyor")
def close_inspection(vessel_id, voyage_id, inspection_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    inspection = get_inspection(voyage, inspection_id)
    if inspection["status"] != "EVALUATED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an EVALUATED inspection may be closed")
    if inspection["exceeded"]:
        unresolved = any(
            r for r in store.noncompliance.values()
            if r["source_type"] == "SAMPLING_EXCEEDANCE"
            and r["source_id"] == inspection["id"]
            and r["response_status"] not in ("RESPONDED", "CLOSED"))
        if unresolved:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "linked noncompliance records must be RESPONDED or "
                           "CLOSED before the inspection can be closed")
    with store.lock:
        inspection["status"] = "CLOSED"
        touch(inspection)
        touch(vessel)
    return ok(inspection_json(inspection), 200)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/inspections/<inspection_id>/reopen")
@require_roles("FlagSurveyor")
def reopen_inspection(vessel_id, voyage_id, inspection_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    inspection = get_inspection(voyage, inspection_id)
    if inspection["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a CLOSED inspection may be reopened")
    if now() > inspection["sampled_at"] + timedelta(days=90):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "an inspection may only be reopened within 90 days of "
                       "sampling")
    with store.lock:
        inspection["status"] = "REOPENED"
        touch(inspection)
        for rec in store.noncompliance.values():
            if (rec["source_id"] == inspection["id"]
                    and rec["response_status"] == "CLOSED"):
                rec["response_status"] = "OPEN"
                touch(rec)
        recompute_posture(vessel)
    return ok(inspection_json(inspection), 200)


# ---------------------------------------------------------------------------
# Noncompliance records
# ---------------------------------------------------------------------------

@bp.get("/vessels/<vessel_id>/voyages/<voyage_id>/noncompliance")
@require_roles(*ALL_ROLES)
def list_noncompliance(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    limit, offset = pagination_params()
    response_status = query_filter("response_status")
    severity = query_filter("severity")
    items = [r for r in store.noncompliance.values()
             if r["voyage_id"] == voyage["id"]]
    if response_status is not None:
        items = [r for r in items if r["response_status"] == response_status]
    if severity is not None:
        items = [r for r in items if r["severity"] == severity]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([noncompliance_json(r) for r in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/noncompliance/<record_id>/respond")
@require_roles("ShoreComplianceOfficer")
def respond_noncompliance(vessel_id, voyage_id, record_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    rec = get_noncompliance(voyage, record_id)
    if rec["response_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an OPEN noncompliance record may be responded to")
    if now() > rec["response_due_at"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the response deadline has passed")
    with store.lock:
        rec["response_status"] = "RESPONDED"
        touch(rec)
        touch(vessel)
    return ok(noncompliance_json(rec), 200)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/noncompliance/<record_id>/close")
@require_roles("FlagSurveyor")
def close_noncompliance(vessel_id, voyage_id, record_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    rec = get_noncompliance(voyage, record_id)
    if rec["response_status"] != "RESPONDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a RESPONDED noncompliance record may be closed")
    with store.lock:
        rec["response_status"] = "CLOSED"
        touch(rec)
        recompute_posture(vessel)
    return ok(noncompliance_json(rec), 200)


# ---------------------------------------------------------------------------
# Port state control deficiencies
# ---------------------------------------------------------------------------

@bp.get("/vessels/<vessel_id>/deficiencies")
@require_roles(*ALL_ROLES)
def list_deficiencies(vessel_id):
    vessel = get_vessel(vessel_id)
    limit, offset = pagination_params()
    status = query_filter("rectification_status")
    p1 = query_bool("is_priority_one")
    items = [d for d in store.deficiencies.values()
             if d["vessel_id"] == vessel["id"]]
    if status is not None:
        items = [d for d in items if d["rectification_status"] == status]
    if p1 is not None:
        items = [d for d in items if d["is_priority_one"] == p1]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([deficiency_json(d) for d in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/deficiencies/<deficiency_id>/begin-rectification")
@require_roles("VesselMaster")
def begin_rectification(vessel_id, deficiency_id):
    vessel = get_vessel(vessel_id)
    deficiency = get_deficiency(vessel, deficiency_id)
    if deficiency["rectification_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an OPEN deficiency may begin rectification")
    with store.lock:
        deficiency["rectification_status"] = "RECTIFYING"
        touch(deficiency)
        touch(vessel)
    return ok(deficiency_json(deficiency), 200)


@bp.post("/vessels/<vessel_id>/deficiencies/<deficiency_id>/claim-rectified")
@require_roles("VesselMaster")
def claim_rectified(vessel_id, deficiency_id):
    vessel = get_vessel(vessel_id)
    deficiency = get_deficiency(vessel, deficiency_id)
    if deficiency["rectification_status"] != "RECTIFYING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a RECTIFYING deficiency may be claimed rectified")
    body = get_body()
    expected = req_int(body, "expected_deficiency_version")
    if expected != deficiency["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_deficiency_version does not match the "
                       "deficiency's current version")
    with store.lock:
        deficiency["rectification_status"] = "RECTIFIED"
        deficiency["rectified_at"] = now()
        deficiency["_claimed_by"] = g.user_id
        touch(deficiency)
    return ok(deficiency_json(deficiency), 200)


@bp.post("/vessels/<vessel_id>/deficiencies/<deficiency_id>/verify")
@require_roles("PSCOfficer")
def verify_deficiency(vessel_id, deficiency_id):
    vessel = get_vessel(vessel_id)
    deficiency = get_deficiency(vessel, deficiency_id)
    if deficiency["rectification_status"] != "RECTIFIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a RECTIFIED deficiency may be verified")
    if deficiency.get("_claimed_by") is not None \
            and deficiency.get("_claimed_by") == g.user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "the same X-User-ID may not both claim and verify a "
                       "rectification")
    with store.lock:
        deficiency["rectification_status"] = "VERIFIED"
        deficiency["verified_at"] = now()
        touch(deficiency)
        recompute_posture(vessel)
    return ok(deficiency_json(deficiency), 200)


@bp.post("/vessels/<vessel_id>/deficiencies/<deficiency_id>/reject-verification")
@require_roles("PSCOfficer")
def reject_verification(vessel_id, deficiency_id):
    vessel = get_vessel(vessel_id)
    deficiency = get_deficiency(vessel, deficiency_id)
    if deficiency["rectification_status"] != "RECTIFIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a RECTIFIED deficiency may have its verification "
                       "rejected")
    with store.lock:
        deficiency["rectification_status"] = "REOPENED"
        deficiency["rectification_deadline"] = (
            deficiency["rectification_deadline"] + timedelta(days=7))
        touch(deficiency)
        recompute_posture(vessel)
    return ok(deficiency_json(deficiency), 200)


# ---------------------------------------------------------------------------
# Enforcement cases
# ---------------------------------------------------------------------------

@bp.get("/vessels/<vessel_id>/enforcement-cases")
@require_roles(*ALL_ROLES)
def list_cases(vessel_id):
    vessel = get_vessel(vessel_id)
    limit, offset = pagination_params()
    status = query_filter("status")
    items = [c for c in store.enforcement_cases.values()
             if c["vessel_id"] == vessel["id"]]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([case_json(c) for c in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/enforcement-cases/<case_id>/submit-response")
@require_roles("ShoreComplianceOfficer")
def submit_case_response(vessel_id, case_id):
    vessel = get_vessel(vessel_id)
    case = get_case(vessel, case_id)
    if case["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an ACTIVE case may receive a response")
    with store.lock:
        case["status"] = "UNDER_REVIEW"
        touch(case)
        touch(vessel)
    return ok(case_json(case), 200)


@bp.post("/vessels/<vessel_id>/enforcement-cases/<case_id>/close")
@require_roles("FlagSurveyor")
def close_case(vessel_id, case_id):
    vessel = get_vessel(vessel_id)
    case = get_case(vessel, case_id)
    if case["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an UNDER_REVIEW case may be closed")
    body = get_body()
    penalty = body.get("penalty_assessed")
    if penalty is None:
        penalty = False
    if not isinstance(penalty, bool):
        raise ApiError("ERR_VALIDATION", 400,
                       "penalty_assessed must be a boolean")
    with store.lock:
        if penalty:
            case["status"] = "CLOSED_PENALTY"
        else:
            unclosed = any(
                r for r_id in case["linked_noncompliance_ids"]
                for r in [store.noncompliance.get(r_id)]
                if r is not None and r["response_status"] != "CLOSED")
            if unclosed:
                raise ApiError(ERR_INVALID_STATE, 409,
                               "every linked noncompliance record must be "
                               "CLOSED before the case can close as compliant")
            case["status"] = "CLOSED_COMPLIANT"
        case["closed_at"] = now()
        touch(case)
        if vessel["active_enforcement_case_id"] == case["id"]:
            vessel["active_enforcement_case_id"] = None
        recompute_posture(vessel)
    return ok(case_json(case), 200)


@bp.post("/vessels/<vessel_id>/enforcement-cases/<case_id>/withdraw")
@require_roles("FlagSurveyor")
def withdraw_case(vessel_id, case_id):
    vessel = get_vessel(vessel_id)
    case = get_case(vessel, case_id)
    if case["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an ACTIVE case may be withdrawn")
    with store.lock:
        case["status"] = "WITHDRAWN"
        case["closed_at"] = now()
        touch(case)
        if vessel["active_enforcement_case_id"] == case["id"]:
            vessel["active_enforcement_case_id"] = None
        recompute_posture(vessel)
    return ok(case_json(case), 200)
