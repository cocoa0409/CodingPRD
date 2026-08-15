"""BenchmarkingStudy lifecycle (PRD 3.2).

DRAFT -> CURRENT (approve; computes nearest-rank IQR; supersedes parent)
CURRENT -> STALE (system, fiscal-year close) -> SUPERSEDED (system, child approve)
Refresh CREATES a successor DRAFT (OCC-guarded) — not a state transition.
"""
from flask import Blueprint, request

import errors
from db import store, new_resource, touch, public
from errors import ApiError
from middleware import (
    require_auth, get_body, get_path, is_int, shape_str, shape_enum,
    list_page, ALL_ROLES,
)
from response import ok_object, ok_list
from services import calc

bp = Blueprint("studies", __name__)

TX_TYPES = ["GOODS", "SERVICES", "IP_ROYALTY", "FINANCING", "COST_SHARING"]


def _shape_comparables(body):
    comps = body.get("comparables_bp")
    if not isinstance(comps, list) or len(comps) < 5:
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "comparables_bp must contain at least 5 entries")
    if any(not is_int(c) for c in comps):
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "comparables_bp entries must be integers")
    return comps


@bp.post("/tp/benchmarking_studies")
def create_study():
    uid, _ = require_auth(["TaxAnalyst"])
    body = get_body()
    tt = shape_enum(body, "transaction_type", TX_TYPES)
    region = shape_str(body, "region")
    vintage = body.get("vintage_year")
    if not is_int(vintage):
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "vintage_year is required and must be an integer")
    comps = _shape_comparables(body)
    s = new_resource()
    s.update({
        "transaction_type": tt,
        "region": region,
        "vintage_year": vintage,
        "comparables_bp": list(comps),
        "p25_bp": None,
        "median_bp": None,
        "p75_bp": None,
        "status": "DRAFT",
        "supersedes_study_id": None,
        "created_by_user_id": uid,
    })
    store.studies[s["id"]] = s
    return ok_object(public(s), 201)


@bp.get("/tp/benchmarking_studies/<benchmarkingStudyId>")
def get_study(benchmarkingStudyId):
    require_auth(ALL_ROLES)
    s = get_path(store.studies, benchmarkingStudyId)
    return ok_object(public(s), 200)


@bp.get("/tp/benchmarking_studies")
def list_studies():
    require_auth(ALL_ROLES)
    filters = [
        ("supersedes_study_id", request.args.get("supersedes_study_id")),
        ("status", request.args.get("status")),
        ("transaction_type", request.args.get("transaction_type")),
    ]
    page, limit, offset, total = list_page(list(store.studies.values()), filters)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/tp/benchmarking_studies/<benchmarkingStudyId>/approve")
def approve_study(benchmarkingStudyId):
    uid, _ = require_auth(["TransferPricingLead"])
    s = get_path(store.studies, benchmarkingStudyId)
    if s["status"] != "DRAFT":
        raise ApiError(errors.INVALID_STATE, 409,
                       "approve requires the study to be DRAFT")
    if uid == s["created_by_user_id"]:
        raise ApiError(errors.SEGREGATION, 409,
                       "Approver must differ from the study creator")
    p25, med, p75 = calc.interquartile_range(s["comparables_bp"])
    s["p25_bp"] = p25
    s["median_bp"] = med
    s["p75_bp"] = p75
    s["status"] = "CURRENT"
    touch(s)
    # Supersede the parent study (CURRENT or STALE) this draft was refreshed from.
    parent_id = s.get("supersedes_study_id")
    if parent_id:
        parent = store.studies.get(parent_id)
        if parent is not None and parent["status"] in ("CURRENT", "STALE"):
            parent["status"] = "SUPERSEDED"
            touch(parent)
    return ok_object(public(s), 200)


@bp.post("/tp/benchmarking_studies/<benchmarkingStudyId>/refresh")
def refresh_study(benchmarkingStudyId):
    uid, _ = require_auth(["TransferPricingLead"])
    s = get_path(store.studies, benchmarkingStudyId)
    body = get_body()
    if s["status"] not in ("CURRENT", "STALE"):
        raise ApiError(errors.INVALID_STATE, 409,
                       "refresh requires the study to be CURRENT or STALE")
    # OCC guard (PRD 2.7): expected_study_version must match when supplied as int.
    expected = body.get("expected_study_version")
    if is_int(expected) and expected != s["version"]:
        raise ApiError(errors.STALE_VERSION, 412,
                       "expected_study_version does not match the study's current version")
    # (10) shape.
    comps = _shape_comparables(body)
    if not is_int(expected):
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "expected_study_version is required and must be an integer")
    child = new_resource()
    child.update({
        "transaction_type": s["transaction_type"],
        "region": s["region"],
        "vintage_year": s["vintage_year"],
        "comparables_bp": list(comps),
        "p25_bp": None,
        "median_bp": None,
        "p75_bp": None,
        "status": "DRAFT",
        "supersedes_study_id": s["id"],
        "created_by_user_id": uid,
    })
    store.studies[child["id"]] = child
    # The refreshed study's version advances by 1 as the OCC witness.
    touch(s)
    return ok_object(public(child), 201)
