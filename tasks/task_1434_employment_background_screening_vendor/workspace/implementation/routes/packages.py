"""ScreeningPackage endpoints (OCC-guarded update)."""
from flask import Blueprint

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_STALE, ERR_PACKAGE_NOT_DRAFT,
    ERR_PACKAGE_NOT_ACTIVE, ERR_PACKAGE_IN_USE,
)
from middleware import (
    auth, require_role, get_body, req_str, req_enum, req_int, opt_str,
    opt_int, invalid, ALL_ROLES,
)
from response import success_object

bp = Blueprint("packages", __name__)

RISK_TIERS = ("TIER_1_STANDARD", "TIER_2_ELEVATED", "TIER_3_HIGH_RISK")
CHECK_TYPES = (
    "CRIMINAL_COUNTY", "CRIMINAL_STATE", "CRIMINAL_FEDERAL", "SSN_TRACE",
    "EMPLOYMENT_VERIFY", "EDUCATION_VERIFY", "MVR", "CREDIT_CHECK",
    "GLOBAL_SANCTIONS",
)


def _validate_check_types(value):
    if not isinstance(value, list) or len(value) < 1:
        invalid("check_types must be a non-empty array")
    for ct in value:
        if not isinstance(ct, str) or ct not in CHECK_TYPES:
            invalid("check_types contains an invalid member")


@bp.route("/screening-packages", methods=["POST"])
def create_package():
    auth_uid, role = auth()
    require_role(role, {"HRAdmin"})
    body = get_body()
    name = req_str(body, "name")
    risk_tier = req_enum(body, "risk_tier", RISK_TIERS)
    _validate_check_types(body.get("check_types"))
    tat = req_int(body, "tat_business_hours", minimum=1)
    fee = req_int(body, "fee_cents", minimum=0)
    pkg = db.new_entity({
        "name": name,
        "risk_tier": risk_tier,
        "check_types": list(body["check_types"]),
        "tat_business_hours": tat,
        "fee_cents": fee,
        "status": "DRAFT",
    })
    db.packages[pkg["id"]] = pkg
    return success_object(pkg, 201)


def _load_package(package_id):
    pkg = db.packages.get(package_id)
    if pkg is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Package not found")
    return pkg


@bp.route("/screening-packages/<package_id>", methods=["GET"])
def get_package(package_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return success_object(_load_package(package_id), 200)


@bp.route("/screening-packages/<package_id>", methods=["PUT"])
def update_package(package_id):
    auth_uid, role = auth()
    require_role(role, {"HRAdmin"})
    pkg = _load_package(package_id)
    body = get_body()
    # OCC (priority 3.5) — before request shape and state checks
    expected = body.get("expected_package_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            invalid("expected_package_version must be an integer")
        if expected != pkg["version"]:
            raise ApiError(ERR_STALE, 412,
                           "expected_package_version does not match current version")
    # shape (3.8)
    if expected is None:
        invalid("expected_package_version is required")
    name = opt_str(body, "name")
    if "check_types" in body and body["check_types"] is not None:
        _validate_check_types(body["check_types"])
    tat = opt_int(body, "tat_business_hours", minimum=1)
    fee = opt_int(body, "fee_cents", minimum=0)
    # state (4)
    if pkg["status"] != "DRAFT":
        raise ApiError(ERR_PACKAGE_NOT_DRAFT, 409,
                       "Update requires package DRAFT")
    if name is not None:
        pkg["name"] = name
    if body.get("check_types") is not None:
        pkg["check_types"] = list(body["check_types"])
    if tat is not None:
        pkg["tat_business_hours"] = tat
    if fee is not None:
        pkg["fee_cents"] = fee
    bump(pkg)
    return success_object(pkg, 200)


@bp.route("/screening-packages/<package_id>/activate", methods=["POST"])
def activate_package(package_id):
    auth_uid, role = auth()
    require_role(role, {"HRAdmin"})
    pkg = _load_package(package_id)
    if pkg["status"] != "DRAFT":
        raise ApiError(ERR_PACKAGE_NOT_DRAFT, 409,
                       "Activate requires package DRAFT")
    pkg["status"] = "ACTIVE"
    bump(pkg)
    return success_object(pkg, 200)


@bp.route("/screening-packages/<package_id>/retire", methods=["POST"])
def retire_package(package_id):
    auth_uid, role = auth()
    require_role(role, {"HRAdmin"})
    pkg = _load_package(package_id)
    if pkg["status"] != "ACTIVE":
        raise ApiError(ERR_PACKAGE_NOT_ACTIVE, 409,
                       "Retire requires package ACTIVE")
    for order in db.orders.values():
        if order["fulfillment_status"] in ("CLOSED", "CANCELLED"):
            continue
        if order["pinned_package_id"] == pkg["id"]:
            raise ApiError(ERR_PACKAGE_IN_USE, 409,
                           "Non-terminal orders reference this package")
        position = db.positions.get(order["position_id"])
        if position is not None and position["package_id"] == pkg["id"]:
            raise ApiError(ERR_PACKAGE_IN_USE, 409,
                           "Non-terminal orders reference this package")
    pkg["status"] = "RETIRED"
    bump(pkg)
    return success_object(pkg, 200)
