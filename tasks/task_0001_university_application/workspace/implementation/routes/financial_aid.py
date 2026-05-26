"""FinancialAidProfile + AidPackage endpoints."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_FORBIDDEN_OWNER_MISMATCH,
    ERR_FAFSA_DISALLOWS_ASSETS,
)
from middleware import auth_required
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, get_body, require_fields, order_by_created_at,
)
from services import calculations, state_machines
from services.common import new_common_fields, touch

bp = Blueprint("financial_aid", __name__)

PROFILE_TYPES = {"FAFSA", "CSS_PROFILE"}


def _is_int_nn(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


# --------------------------- FinancialAidProfile ---------------------------
@bp.post("/financial-aid-profiles")
def create_fap():
    auth_required({"Applicant"})()
    body = get_body()
    require_fields(body, ["applicant_id", "profile_type", "household_income_cents", "household_size"])
    applicant_id = body["applicant_id"]
    if applicant_id not in db.applicants:
        raise APIError(ERR_NOT_FOUND, 404, "Applicant not found")
    if g.user_id != applicant_id:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this applicant")
    # uniqueness: one fap per applicant
    for p in db.financial_aid_profiles.values():
        if p["applicant_id"] == applicant_id:
            raise APIError(ERR_INVALID_REQUEST, 400, "FinancialAidProfile already exists for applicant")
    profile_type = body["profile_type"]
    if profile_type not in PROFILE_TYPES:
        raise APIError(ERR_INVALID_REQUEST, 400, "profile_type invalid")
    hic = body["household_income_cents"]
    if not _is_int_nn(hic):
        raise APIError(ERR_INVALID_REQUEST, 400, "household_income_cents must be non-negative integer")
    hsz = body["household_size"]
    if not isinstance(hsz, int) or isinstance(hsz, bool) or hsz < 1 or hsz > 20:
        raise APIError(ERR_INVALID_REQUEST, 400, "household_size out of range")
    da = body.get("declared_assets_cents", 0)
    if not _is_int_nn(da):
        raise APIError(ERR_INVALID_REQUEST, 400, "declared_assets_cents must be non-negative integer")
    if profile_type == "FAFSA" and da != 0:
        raise APIError(ERR_FAFSA_DISALLOWS_ASSETS, 422, "FAFSA disallows declared_assets_cents > 0")
    efc = calculations.efc_calc(profile_type, hic, hsz, da)
    common = new_common_fields()
    fap = {
        **common,
        "applicant_id": applicant_id,
        "profile_type": profile_type,
        "household_income_cents": hic,
        "household_size": hsz,
        "declared_assets_cents": da,
        "expected_family_contribution_cents": efc,
    }
    db.financial_aid_profiles[fap["id"]] = fap
    return ok_object(fap, http_status=201)


@bp.get("/financial-aid-profiles/<pid>")
def read_fap(pid):
    auth_required({"Applicant", "FinancialAidOfficer", "PlatformAdmin"})()
    fap = db.financial_aid_profiles.get(pid)
    if fap is None:
        raise APIError(ERR_NOT_FOUND, 404, "FinancialAidProfile not found")
    if g.user_role == "Applicant" and g.user_id != fap["applicant_id"]:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this profile")
    return ok_object(fap)


@bp.get("/financial-aid-profiles")
def list_fap():
    auth_required({"Applicant", "FinancialAidOfficer", "PlatformAdmin"})()
    applicant_id = request.args.get("applicant_id")
    limit, offset = parse_pagination()
    items = []
    for p in db.financial_aid_profiles.values():
        if applicant_id and p["applicant_id"] != applicant_id:
            continue
        if g.user_role == "Applicant" and p["applicant_id"] != g.user_id:
            continue
        items.append(p)
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.patch("/financial-aid-profiles/<pid>")
def update_fap(pid):
    auth_required({"Applicant"})()
    fap = db.financial_aid_profiles.get(pid)
    if fap is None:
        raise APIError(ERR_NOT_FOUND, 404, "FinancialAidProfile not found")
    if g.user_id != fap["applicant_id"]:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this profile")
    body = get_body()
    if "household_income_cents" in body:
        v = body["household_income_cents"]
        if not _is_int_nn(v):
            raise APIError(ERR_INVALID_REQUEST, 400, "household_income_cents must be non-negative integer")
        fap["household_income_cents"] = v
    if "household_size" in body:
        v = body["household_size"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 20:
            raise APIError(ERR_INVALID_REQUEST, 400, "household_size out of range")
        fap["household_size"] = v
    if "declared_assets_cents" in body:
        v = body["declared_assets_cents"]
        if not _is_int_nn(v):
            raise APIError(ERR_INVALID_REQUEST, 400, "declared_assets_cents must be non-negative integer")
        if fap["profile_type"] == "FAFSA" and v != 0:
            raise APIError(ERR_FAFSA_DISALLOWS_ASSETS, 422, "FAFSA disallows declared_assets_cents > 0")
        fap["declared_assets_cents"] = v
    fap["expected_family_contribution_cents"] = calculations.efc_calc(
        fap["profile_type"], fap["household_income_cents"], fap["household_size"], fap["declared_assets_cents"]
    )
    touch(fap)
    return ok_object(fap)


# --------------------------- AidPackage ---------------------------
@bp.post("/aid-packages")
def create_aid_package():
    auth_required({"FinancialAidOfficer"})()
    body = get_body()
    require_fields(body, ["application_id", "grant_cents", "loan_cents", "work_study_cents"])
    application_id = body["application_id"]
    if application_id not in db.applications:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    # uniqueness
    for ap in db.aid_packages.values():
        if ap["application_id"] == application_id:
            raise APIError(ERR_INVALID_REQUEST, 400, "AidPackage already exists for application")
    for k in ("grant_cents", "loan_cents", "work_study_cents"):
        if not _is_int_nn(body[k]):
            raise APIError(ERR_INVALID_REQUEST, 400, f"{k} must be non-negative integer")
    common = new_common_fields()
    ap = {
        **common,
        "application_id": application_id,
        "status": "DRAFT",
        "grant_cents": body["grant_cents"],
        "loan_cents": body["loan_cents"],
        "work_study_cents": body["work_study_cents"],
        "net_cost_cents": None,
    }
    db.aid_packages[ap["id"]] = ap
    return ok_object(ap, http_status=201)


@bp.post("/aid-packages/<aid>/finalize")
def finalize_aid(aid):
    auth_required({"FinancialAidOfficer"})()
    ap = db.aid_packages.get(aid)
    if ap is None:
        raise APIError(ERR_NOT_FOUND, 404, "AidPackage not found")
    state_machines.aid_finalize(ap)
    return ok_object(ap)


@bp.get("/aid-packages/<aid>")
def read_aid_package(aid):
    auth_required({"Applicant", "FinancialAidOfficer", "PlatformAdmin"})()
    ap = db.aid_packages.get(aid)
    if ap is None:
        raise APIError(ERR_NOT_FOUND, 404, "AidPackage not found")
    if g.user_role == "Applicant":
        app = db.applications.get(ap["application_id"])
        if not app or app["applicant_id"] != g.user_id:
            raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this aid package")
    return ok_object(ap)


@bp.get("/aid-packages")
def list_aid_packages():
    auth_required({"Applicant", "FinancialAidOfficer", "PlatformAdmin"})()
    application_id = request.args.get("application_id")
    limit, offset = parse_pagination()
    items = []
    for ap in db.aid_packages.values():
        if application_id and ap["application_id"] != application_id:
            continue
        if g.user_role == "Applicant":
            app = db.applications.get(ap["application_id"])
            if not app or app["applicant_id"] != g.user_id:
                continue
        items.append(ap)
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(page, limit, offset, total)
