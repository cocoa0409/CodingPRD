"""Patient routes."""
from flask import Blueprint, jsonify

from app.auth import require_roles
from app.errors import err_invalid_state, err_not_found
from app.responses import success_object
from app.store import store
from app.utils import (
    bump_version_and_timestamp,
    check_version_if_supplied,
    is_valid_state_code,
    parse_iso_datetime,
    parse_json_body,
)


bp = Blueprint("patients", __name__)


def _validate_insurance_payload(body: dict) -> dict:
    out = {}
    payer_id = body.get("insurance_payer_id", None)
    member_id = body.get("insurance_member_id", None)
    deductible = body.get("insurance_deductible_remaining_cents", 0)
    copay = body.get("insurance_copay_cents", 0)
    coinsurance_bps = body.get("insurance_coinsurance_bps", 0)

    if payer_id is not None and not isinstance(payer_id, str):
        raise err_invalid_state("insurance_payer_id must be a string when present")
    if payer_id is not None and member_id is None:
        raise err_invalid_state("insurance_member_id is required when insurance_payer_id is present")
    if member_id is not None and not isinstance(member_id, str):
        raise err_invalid_state("insurance_member_id must be a string when present")

    if not isinstance(deductible, int) or deductible < 0:
        raise err_invalid_state("insurance_deductible_remaining_cents must be a non-negative integer")
    if not isinstance(copay, int) or copay < 0:
        raise err_invalid_state("insurance_copay_cents must be a non-negative integer")
    if not isinstance(coinsurance_bps, int) or coinsurance_bps < 0 or coinsurance_bps > 10000:
        raise err_invalid_state("insurance_coinsurance_bps must be in [0,10000]")

    out["insurance_payer_id"] = payer_id
    out["insurance_member_id"] = member_id
    out["insurance_deductible_remaining_cents"] = deductible
    out["insurance_copay_cents"] = copay
    out["insurance_coinsurance_bps"] = coinsurance_bps
    return out


@bp.post("/telemed/patients")
@require_roles(["PlatformAdmin"])
def create_patient():
    body = parse_json_body()
    full_name = body.get("full_name")
    dob_raw = body.get("date_of_birth")
    home_state = body.get("home_state_code")
    present_state = body.get("present_state_code", None)

    if not isinstance(full_name, str) or not full_name:
        raise err_invalid_state("full_name is required")
    try:
        dob = parse_iso_datetime(dob_raw)
    except ValueError:
        raise err_invalid_state("date_of_birth must be an ISO 8601 string")
    if not is_valid_state_code(home_state):
        raise err_invalid_state("home_state_code must be a 2-letter state code")
    if present_state is None:
        present_state = home_state
    elif not is_valid_state_code(present_state):
        raise err_invalid_state("present_state_code must be a 2-letter state code")

    insurance = _validate_insurance_payload(body)

    now_iso = store.now_iso()
    dob_iso = dob.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dob.microsecond // 1000:03d}Z"
    patient = {
        "id": store.new_id(),
        "full_name": full_name,
        "date_of_birth": dob_iso,
        "home_state_code": home_state,
        "present_state_code": present_state,
        **insurance,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    store.patients[patient["id"]] = patient
    return jsonify(success_object(patient)), 201


@bp.get("/telemed/patients/<pid>")
@require_roles(["PlatformAdmin", "ComplianceOfficer", "Physician"])
def get_patient(pid: str):
    patient = store.patients.get(pid)
    if not patient:
        raise err_not_found()
    return jsonify(success_object(patient)), 200


@bp.patch("/telemed/patients/<pid>")
@require_roles(["PlatformAdmin"])
def patch_patient(pid: str):
    patient = store.patients.get(pid)
    if not patient:
        raise err_not_found()
    body = parse_json_body()
    check_version_if_supplied(patient, body)

    if "present_state_code" in body:
        ps = body["present_state_code"]
        if not is_valid_state_code(ps):
            raise err_invalid_state("present_state_code must be a 2-letter state code")
        patient["present_state_code"] = ps

    for key in (
        "insurance_deductible_remaining_cents",
        "insurance_copay_cents",
        "insurance_coinsurance_bps",
    ):
        if key in body:
            val = body[key]
            if not isinstance(val, int) or val < 0:
                raise err_invalid_state(f"{key} must be a non-negative integer")
            if key == "insurance_coinsurance_bps" and val > 10000:
                raise err_invalid_state(f"{key} must be at most 10000")
            patient[key] = val

    now_iso = store.now_iso()
    bump_version_and_timestamp(patient, now_iso)
    return jsonify(success_object(patient)), 200
