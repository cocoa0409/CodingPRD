"""Customer routes."""
from __future__ import annotations

from typing import Any

from flask import Flask

from ..audit import write_audit
from ..auth import current_actor, require_auth
from ..calculations import compute_customer_risk_score
from ..errors import ApiError
from ..services.validation import check_occ, customer_age_at, require_keys, require_str
from ..store import LOCK, common_fields_create, bump_version, get_store
from ._helpers import created, get_json_body, ok


_KYC_STATUSES = {"NOT_VERIFIED", "PENDING", "VERIFIED", "REJECTED"}
_REQUIRED_DECL_KEYS = ("is_pregnant", "has_uncontrolled_hypertension", "has_active_infection", "has_bleeding_disorder")


def _validate_health_declaration(hd: Any) -> dict[str, Any]:
    if hd is None:
        return {k: False for k in _REQUIRED_DECL_KEYS}
    if not isinstance(hd, dict):
        raise ApiError("ERR_INVALID_INPUT", "health_declaration must be object")
    for k in _REQUIRED_DECL_KEYS:
        if k not in hd:
            raise ApiError("ERR_INVALID_INPUT", f"health_declaration.{k} required")
        if not isinstance(hd[k], bool):
            raise ApiError("ERR_INVALID_INPUT", f"health_declaration.{k} must be boolean")
    return dict(hd)


def _ensure_str_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ApiError("ERR_INVALID_INPUT", f"{name} must be an array")
    for v in value:
        if not isinstance(v, str):
            raise ApiError("ERR_INVALID_INPUT", f"{name} entries must be strings")
    return list(value)


def _ownership_or_role(cust: dict[str, Any], allowed_roles: set[str]) -> None:
    user_id, role = current_actor()
    if role == "Customer":
        if cust["id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", "Customer can only access own resource")
        return
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted")


def register(app: Flask) -> None:
    @app.route("/aesthetics/customers", methods=["POST"])
    @require_auth("Consultant")
    def create_customer():
        body = get_json_body()
        require_keys(body, ["full_name", "date_of_birth", "contact_phone"])
        full_name = require_str(body["full_name"], "full_name")
        dob = require_str(body["date_of_birth"], "date_of_birth")
        # Validate parseable
        customer_age_at(dob)
        phone = require_str(body["contact_phone"], "contact_phone")
        with LOCK:
            cust = common_fields_create()
            cust.update({
                "full_name": full_name,
                "date_of_birth": dob,
                "contact_phone": phone,
                "medical_history": _ensure_str_list(body.get("medical_history", []), "medical_history"),
                "allergies": _ensure_str_list(body.get("allergies", []), "allergies"),
                "medication_history": _ensure_str_list(body.get("medication_history", []), "medication_history"),
                "health_declaration": _validate_health_declaration(body.get("health_declaration")),
                "photo_archive_ids": _ensure_str_list(body.get("photo_archive_ids", []), "photo_archive_ids"),
                "scan3d_archive_ids": _ensure_str_list(body.get("scan3d_archive_ids", []), "scan3d_archive_ids"),
                "kyc_status": "NOT_VERIFIED",
                "credit_score": None,
                "adverse_event_count": 0,
                "risk_score": 0.0,
            })
            cust["risk_score"] = compute_customer_risk_score(cust)
            get_store().customers[cust["id"]] = cust
        return created(cust)

    @app.route("/aesthetics/customers/<cid>", methods=["PATCH"])
    @require_auth("Consultant", "Customer")
    def update_customer(cid: str):
        body = get_json_body()
        with LOCK:
            cust = get_store().customers.get(cid)
            if not cust:
                raise ApiError("ERR_NOT_FOUND", "Customer not found")
            _ownership_or_role(cust, {"Consultant"})
            check_occ(cust, body)
            if "full_name" in body:
                cust["full_name"] = require_str(body["full_name"], "full_name")
            if "contact_phone" in body:
                cust["contact_phone"] = require_str(body["contact_phone"], "contact_phone")
            if "medical_history" in body:
                cust["medical_history"] = _ensure_str_list(body["medical_history"], "medical_history")
            if "allergies" in body:
                cust["allergies"] = _ensure_str_list(body["allergies"], "allergies")
            if "medication_history" in body:
                cust["medication_history"] = _ensure_str_list(body["medication_history"], "medication_history")
            if "health_declaration" in body:
                cust["health_declaration"] = _validate_health_declaration(body["health_declaration"])
            if "photo_archive_ids" in body:
                cust["photo_archive_ids"] = _ensure_str_list(body["photo_archive_ids"], "photo_archive_ids")
            if "scan3d_archive_ids" in body:
                cust["scan3d_archive_ids"] = _ensure_str_list(body["scan3d_archive_ids"], "scan3d_archive_ids")
            cust["risk_score"] = compute_customer_risk_score(cust)
            bump_version(cust)
        return ok(cust)

    @app.route("/aesthetics/customers/<cid>/kyc", methods=["POST"])
    @require_auth("FinanceOfficer")
    def kyc(cid: str):
        body = get_json_body()
        require_keys(body, ["kyc_status", "credit_score"])
        if body["kyc_status"] not in _KYC_STATUSES:
            raise ApiError("ERR_INVALID_INPUT", "invalid kyc_status")
        cs = body["credit_score"]
        if cs is not None and (not isinstance(cs, int) or isinstance(cs, bool) or cs < 0 or cs > 1000):
            raise ApiError("ERR_INVALID_INPUT", "credit_score must be int 0..1000 or null")
        with LOCK:
            cust = get_store().customers.get(cid)
            if not cust:
                raise ApiError("ERR_NOT_FOUND", "Customer not found")
            cust["kyc_status"] = body["kyc_status"]
            cust["credit_score"] = cs
            bump_version(cust)
            write_audit("CUSTOMER_KYC", "Customer", cid, {"kyc_status": cust["kyc_status"], "credit_score": cust["credit_score"]})
        return ok(cust)

    @app.route("/aesthetics/customers/<cid>", methods=["GET"])
    @require_auth("Consultant", "AttendingPhysician", "SeniorPhysician", "Nurse", "FinanceOfficer", "Customer")
    def fetch_customer(cid: str):
        cust = get_store().customers.get(cid)
        if not cust:
            raise ApiError("ERR_NOT_FOUND", "Customer not found")
        # Customer can only see own record
        user_id, role = current_actor()
        if role == "Customer" and cust["id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", "Customer can only access own record")
        return ok(cust)
