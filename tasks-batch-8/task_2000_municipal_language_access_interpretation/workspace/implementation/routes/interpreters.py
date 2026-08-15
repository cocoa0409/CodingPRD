"""Interpreter endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CONTRACT_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INTERPRETER_NOT_FOUND,
    ERR_INVALID_TRANSITION,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_endpoint
from services.core import touch
from services.serializers import serialize_interpreter
from util import CLOCK, new_id, next_seq
from validate import (
    get_body,
    opt_enum,
    opt_enum_list,
    opt_str,
    opt_str_list,
    reject_unknown_fields,
    req_enum,
    req_str,
    req_str_list,
    require_path,
)

bp = Blueprint("interpreters", __name__)

MODALITIES = {"PHONE", "VIDEO", "IN_PERSON"}
TIERS = {"PROVISIONAL", "REGISTERED", "CERTIFIED"}


@bp.post("/interpreters")
def create_interpreter():
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(
        body, {"full_name", "language_codes", "modalities", "tier", "vendor_contract_id"})
    full_name = req_str(body, "full_name")
    language_codes = req_str_list(body, "language_codes")
    modalities = opt_enum_list(body, "modalities", MODALITIES, default=None)
    if modalities is None:
        raise_error(ERR_VALIDATION, "modalities is required")
    tier = req_enum(body, "tier", TIERS)
    vendor_contract_id = req_str(body, "vendor_contract_id")

    require_path("vendor_contracts", vendor_contract_id, ERR_CONTRACT_NOT_FOUND)

    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "language_codes": language_codes,
        "modalities": modalities,
        "tier": tier,
        "vendor_contract_id": vendor_contract_id,
        "confidentiality_signed_at": None,
        "quality_rating": 1000,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["interpreters"][rec["id"]] = rec
    return success_object(serialize_interpreter(rec), status=201)


@bp.get("/interpreters")
def list_interpreters():
    filters = {
        "vendor_contract_id": request.args.get("vendor_contract_id"),
        "language_code": request.args.get("language_code"),
        "modality": request.args.get("modality"),
        "tier": request.args.get("tier"),
        "status": request.args.get("status"),
    }
    return list_endpoint("interpreters", serialize_interpreter, filters)


@bp.get("/interpreters/<rid>")
def get_interpreter(rid):
    return get_one("interpreters", rid, ERR_INTERPRETER_NOT_FOUND, serialize_interpreter)


@bp.patch("/interpreters/<rid>")
def patch_interpreter(rid):
    caller = authorized(["LanguageAccessCoordinator", "ComplianceOfficer"])
    body = get_body()
    # Priority 2: only a ComplianceOfficer may pass an interpreter status change.
    if "status" in body and body.get("status") is not None and caller.role != "ComplianceOfficer":
        raise_error(ERR_FORBIDDEN_ROLE, "interpreter status changes are ComplianceOfficer-only")
    reject_unknown_fields(
        body,
        {"full_name", "language_codes", "modalities", "tier", "confidentiality_signed", "status"})
    full_name = opt_str(body, "full_name")
    language_codes = opt_str_list(body, "language_codes")
    modalities = opt_enum_list(body, "modalities", MODALITIES)
    tier = opt_enum(body, "tier", TIERS)
    confidentiality_signed = body.get("confidentiality_signed", None)
    if confidentiality_signed is not None and confidentiality_signed is not True:
        raise_error(ERR_VALIDATION, "confidentiality_signed accepts only true")
    status = opt_enum(body, "status", {"ACTIVE", "SUSPENDED"})

    rec = require_path("interpreters", rid, ERR_INTERPRETER_NOT_FOUND)

    # State gate for the manual transition (PRD §3.5): attempted from the
    # wrong state -> ERR_INVALID_TRANSITION. Manual suspension does NOT cancel
    # assigned work; reinstatement resets the rating to the probationary floor.
    if status is not None:
        if status == rec["status"]:
            raise_error(ERR_INVALID_TRANSITION, f"interpreter is already {status}")

    if full_name is not None:
        rec["full_name"] = full_name
    if language_codes is not None:
        rec["language_codes"] = language_codes
    if modalities is not None:
        rec["modalities"] = modalities
    if tier is not None:
        rec["tier"] = tier
    if confidentiality_signed is True:
        rec["confidentiality_signed_at"] = CLOCK.now_iso()
    if status is not None:
        rec["status"] = status
        if status == "ACTIVE":
            rec["quality_rating"] = 600  # probationary floor reset
    touch(rec)
    return success_object(serialize_interpreter(rec))
