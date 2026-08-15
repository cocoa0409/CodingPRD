"""BundleProgram / BundleEnrollment / RebateAccrual endpoints (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_INVALID_STATE,
    ERR_PROGRAM_NOT_ACTIVE,
    ERR_STALE_CLINIC_VERSION,
)
from middleware import authorized, check_ownership
from response import success_object, success_list
from services.calculations import (
    PRODUCT_TYPES,
    finalize_program_accruals,
    reverse_accruals_for_enrollment,
)
from services.core import (
    get_body, require_fields, require_string, require_int, public,
    get_or_404, get_clinic_or_404, require_clinic_active, paginate,
)
from util import new_id, now_ts, touch

bp = Blueprint("bundles", __name__)

READ_ROLES = ["AccountManager", "ClinicBuyer", "SupplyChainPlanner", "ComplianceOfficer"]
ENROLL_READ_ROLES = ["AccountManager", "ClinicBuyer", "ComplianceOfficer"]


# ---------------------------------------------------------------------------
# BundleProgram
# ---------------------------------------------------------------------------

@bp.route("/vet/bundle-programs", methods=["POST"])
def create_program():
    authorized(["AccountManager"])
    body = get_body()
    require_fields(body, ["program_name", "manufacturer_code",
                          "qualifying_product_types", "min_distinct_categories",
                          "bundle_discount_pct", "rebate_base_rate_bp",
                          "rebate_bonus_rate_bp", "bonus_threshold_cents"])
    program_name = require_string(body, "program_name")
    manufacturer_code = require_string(body, "manufacturer_code")
    qpt = body.get("qualifying_product_types")
    if not isinstance(qpt, list) or not qpt or any(t not in PRODUCT_TYPES for t in qpt):
        raise_error(ERR_INVALID_REQUEST,
                    "qualifying_product_types must be a non-empty subset of product types")
    min_distinct = require_int(body, "min_distinct_categories", minimum=1)
    discount_pct = require_int(body, "bundle_discount_pct", minimum=0, maximum=100)
    base_bp = require_int(body, "rebate_base_rate_bp", minimum=0)
    bonus_bp = require_int(body, "rebate_bonus_rate_bp", minimum=0)
    if bonus_bp < base_bp:
        raise_error(ERR_INVALID_REQUEST,
                    "rebate_bonus_rate_bp must be >= rebate_base_rate_bp")
    threshold = require_int(body, "bonus_threshold_cents", minimum=0)

    program = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "program_name": program_name,
        "manufacturer_code": manufacturer_code,
        "qualifying_product_types": list(qpt),
        "min_distinct_categories": min_distinct,
        "bundle_discount_pct": discount_pct,
        "rebate_base_rate_bp": base_bp,
        "rebate_bonus_rate_bp": bonus_bp,
        "bonus_threshold_cents": threshold,
        "status": "DRAFT",
    }
    db["bundle_programs"][program["id"]] = program
    return success_object(public(program), status=201)


@bp.route("/vet/bundle-programs/<pid>", methods=["GET"])
def get_program(pid):
    authorized(READ_ROLES)
    program = get_or_404("bundle_programs", pid)
    return success_object(public(program))


@bp.route("/vet/bundle-programs/<pid>/activate", methods=["POST"])
def activate_program(pid):
    authorized(["AccountManager"])
    program = get_or_404("bundle_programs", pid)
    if program["status"] != "DRAFT":
        raise_error(ERR_PROGRAM_INVALID_STATE,
                    f"program must be DRAFT (is {program['status']})")
    program["status"] = "ACTIVE"
    touch(program)
    return success_object(public(program))


@bp.route("/vet/bundle-programs/<pid>/close", methods=["POST"])
def close_program(pid):
    authorized(["AccountManager"])
    program = get_or_404("bundle_programs", pid)
    if program["status"] != "ACTIVE":
        raise_error(ERR_PROGRAM_INVALID_STATE,
                    f"program must be ACTIVE (is {program['status']})")
    finalize_program_accruals(program)
    program["status"] = "CLOSED"
    touch(program)
    return success_object(public(program))


# ---------------------------------------------------------------------------
# BundleEnrollment (nested create under clinic; OCC-guarded)
# ---------------------------------------------------------------------------

@bp.route("/vet/clinics/<cid>/bundle-enrollments", methods=["POST"])
def create_enrollment(cid):
    caller = authorized(["ClinicBuyer"])
    # Ownership (priority 2.5) precedes existence (priority 3).
    check_ownership(caller, cid)
    clinic = get_clinic_or_404(cid)
    body = get_body()
    require_fields(body, ["program_id", "quarter", "expected_clinic_version"])
    program = get_or_404("bundle_programs", body["program_id"])
    quarter = body["quarter"]
    if not isinstance(quarter, str) or not quarter.strip():
        raise_error(ERR_INVALID_REQUEST, "quarter must be a string like 2026-Q3")

    # Cross-entity state gates: clinic ACTIVE, program ACTIVE.
    require_clinic_active(clinic)
    if program["status"] != "ACTIVE":
        raise_error(ERR_PROGRAM_NOT_ACTIVE, "program must be ACTIVE")

    # OCC: expected_clinic_version must match the clinic's current version.
    expected = body["expected_clinic_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_error(ERR_STALE_CLINIC_VERSION,
                    "expected_clinic_version must be an integer")
    if expected != clinic["version"]:
        raise_error(ERR_STALE_CLINIC_VERSION,
                    "expected_clinic_version does not match the clinic's current version")

    # Supersede the prior ACTIVE enrollment for the same clinic + quarter.
    for enr in db["bundle_enrollments"].values():
        if (enr["clinic_id"] == clinic["id"] and enr["quarter"] == quarter
                and enr["status"] == "ACTIVE"):
            enr["status"] = "SUPERSEDED"
            touch(enr)
            reverse_accruals_for_enrollment(enr)

    enrollment = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "clinic_id": clinic["id"],
        "program_id": program["id"],
        "quarter": quarter,
        "status": "ACTIVE",
        "qtd_qualifying_cents": 0,
    }
    db["bundle_enrollments"][enrollment["id"]] = enrollment
    touch(clinic)  # successful OCC-guarded enrollment increments Clinic.version
    return success_object(public(enrollment), status=201)


@bp.route("/vet/bundle-enrollments", methods=["GET"])
def list_enrollments():
    authorized(ENROLL_READ_ROLES)
    items = list(db["bundle_enrollments"].values())
    for param in ("clinic_id", "program_id", "quarter", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [e for e in items if str(e.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([public(e) for e in page], total, limit, offset)


@bp.route("/vet/bundle-enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    authorized(ENROLL_READ_ROLES)
    enrollment = get_or_404("bundle_enrollments", eid)
    return success_object(public(enrollment))


# ---------------------------------------------------------------------------
# RebateAccrual (read-only)
# ---------------------------------------------------------------------------

@bp.route("/vet/rebate-accruals", methods=["GET"])
def list_accruals():
    authorized(ENROLL_READ_ROLES)
    items = list(db["rebate_accruals"].values())
    for param in ("enrollment_id", "order_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if str(a.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([public(a) for a in page], total, limit, offset)


@bp.route("/vet/rebate-accruals/<aid>", methods=["GET"])
def get_accrual(aid):
    authorized(ENROLL_READ_ROLES)
    accrual = get_or_404("rebate_accruals", aid)
    return success_object(public(accrual))
