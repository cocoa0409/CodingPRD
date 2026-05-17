"""Prescription routes."""
from flask import Blueprint, jsonify, request

from app.auth import require_roles
from app.errors import (
    err_compliance_score_low,
    err_dea_requirements,
    err_forbidden,
    err_invalid_state,
    err_not_found,
    err_physician_mismatch,
    err_rx_field_out_of_range,
    err_schedule_ii_refills,
)
from app.responses import success_object
from app.services.compliance import compute_compliance_score
from app.services.licenses import find_active_matching_license
from app.store import store
from app.utils import (
    bump_version_and_timestamp,
    check_version_if_supplied,
    parse_json_body,
)


bp = Blueprint("prescriptions", __name__)


VALID_DEA_SCHEDULES = {"NONE", "II", "III", "IV", "V"}


def _validate_rx_fields(days_supply, refills) -> None:
    if not isinstance(days_supply, int) or days_supply < 1 or days_supply > 90:
        raise err_rx_field_out_of_range()
    if not isinstance(refills, int) or refills < 0 or refills > 11:
        raise err_rx_field_out_of_range()


@bp.post("/telemed/consults/<cid>/prescriptions")
@require_roles(["Physician"])
def create_prescription(cid: str):
    consult = store.consults.get(cid)
    if not consult:
        raise err_not_found()
    user_id = request.headers.get("X-User-ID")
    body = parse_json_body()

    # State: consult must be IN_PROGRESS.
    if consult["status"] != "IN_PROGRESS":
        raise err_invalid_state("Owning Consult is not IN_PROGRESS")
    # Physician mismatch — priority 5, before range checks (priority 11).
    if consult.get("physician_id") != user_id:
        raise err_physician_mismatch()

    drug_name = body.get("drug_name")
    dea_schedule = body.get("dea_schedule")
    days_supply = body.get("days_supply")
    refills = body.get("refills", 0)
    epcs_token = body.get("epcs_two_factor_token", None)

    if not isinstance(drug_name, str) or not drug_name:
        raise err_invalid_state("drug_name is required")
    if dea_schedule not in VALID_DEA_SCHEDULES:
        raise err_invalid_state("dea_schedule must be one of NONE, II, III, IV, V")
    _validate_rx_fields(days_supply, refills)
    if epcs_token is not None and not isinstance(epcs_token, str):
        raise err_invalid_state("epcs_two_factor_token must be a string when present")

    with store.lock:
        now_iso = store.now_iso()
        rx = {
            "id": store.new_id(),
            "consult_id": cid,
            "prescribing_physician_id": user_id,
            "drug_name": drug_name,
            "dea_schedule": dea_schedule,
            "days_supply": days_supply,
            "refills": refills,
            "epcs_two_factor_token": epcs_token,
            "status": "DRAFT",
            "void_reason": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.prescriptions[rx["id"]] = rx

    return jsonify(success_object(rx)), 201


@bp.patch("/telemed/prescriptions/<rid>")
@require_roles(["Physician"])
def patch_prescription(rid: str):
    rx = store.prescriptions.get(rid)
    if not rx:
        raise err_not_found()
    user_id = request.headers.get("X-User-ID")
    body = parse_json_body()

    # State: must still be DRAFT.
    if rx["status"] != "DRAFT":
        raise err_invalid_state("Prescription is not in DRAFT state")
    # Ownership.
    if rx.get("prescribing_physician_id") != user_id:
        raise err_physician_mismatch()
    check_version_if_supplied(rx, body)

    # Compute proposed values to validate ranges.
    new_days_supply = body["days_supply"] if "days_supply" in body else rx["days_supply"]
    new_refills = body["refills"] if "refills" in body else rx["refills"]
    _validate_rx_fields(new_days_supply, new_refills)

    if "dea_schedule" in body:
        if body["dea_schedule"] not in VALID_DEA_SCHEDULES:
            raise err_invalid_state("dea_schedule must be one of NONE, II, III, IV, V")
        rx["dea_schedule"] = body["dea_schedule"]
    if "drug_name" in body:
        if not isinstance(body["drug_name"], str) or not body["drug_name"]:
            raise err_invalid_state("drug_name must be a non-empty string")
        rx["drug_name"] = body["drug_name"]
    if "days_supply" in body:
        rx["days_supply"] = new_days_supply
    if "refills" in body:
        rx["refills"] = new_refills
    if "epcs_two_factor_token" in body:
        tok = body["epcs_two_factor_token"]
        if tok is not None and not isinstance(tok, str):
            raise err_invalid_state("epcs_two_factor_token must be a string or null")
        rx["epcs_two_factor_token"] = tok

    now_iso = store.now_iso()
    bump_version_and_timestamp(rx, now_iso)
    return jsonify(success_object(rx)), 200


@bp.post("/telemed/prescriptions/<rid>/issue")
@require_roles(["Physician"])
def issue_prescription(rid: str):
    rx = store.prescriptions.get(rid)
    if not rx:
        raise err_not_found()
    user_id = request.headers.get("X-User-ID")
    body = parse_json_body()

    # State first (priority 4).
    if rx["status"] != "DRAFT":
        raise err_invalid_state("Prescription is not in DRAFT state")
    check_version_if_supplied(rx, body)

    consult = store.consults.get(rx.get("consult_id", ""))
    if not consult:
        raise err_not_found()
    if consult["status"] != "IN_PROGRESS":
        raise err_invalid_state("Owning Consult is not IN_PROGRESS")

    # Ownership: acting Physician == prescribing_physician_id.
    if rx.get("prescribing_physician_id") != user_id:
        raise err_forbidden()

    # Priority 5: physician mismatch — Rx.prescribing_physician_id must equal Consult.physician_id.
    if rx["prescribing_physician_id"] != consult.get("physician_id"):
        raise err_physician_mismatch()

    physician = store.physicians.get(rx["prescribing_physician_id"])
    if not physician:
        raise err_not_found()

    # Matched license must be ACTIVE (priority 6 / state license check).
    matched = find_active_matching_license(physician["id"], consult["present_state_code"])
    if not matched:
        from app.errors import err_no_valid_license
        raise err_no_valid_license()

    dea_schedule = rx["dea_schedule"]
    refills = int(rx["refills"])

    # Priority 7: DEA requirements.
    if dea_schedule != "NONE":
        if not physician.get("dea_number") or not rx.get("epcs_two_factor_token"):
            raise err_dea_requirements()

    # Priority 8: Schedule II hard rule.
    if dea_schedule == "II" and refills != 0:
        raise err_schedule_ii_refills()

    # Priority 9: compliance score >= 80.
    routing_basis = consult.get("routing_basis")
    score = compute_compliance_score(
        routing_basis=routing_basis,
        dea_schedule=dea_schedule,
        has_dea_number=bool(physician.get("dea_number")),
        has_epcs_token=bool(rx.get("epcs_two_factor_token")),
        refills=refills,
        days_supply=int(rx["days_supply"]),
    )
    if score < 80:
        raise err_compliance_score_low()

    with store.lock:
        if rx["status"] != "DRAFT":
            raise err_invalid_state("Prescription is not in DRAFT state")
        rx["status"] = "ISSUED"
        now_iso = store.now_iso()
        bump_version_and_timestamp(rx, now_iso)
        store.append_audit(
            event_type="RX_ISSUED",
            subject_entity="Prescription",
            subject_id=rx["id"],
            actor_role="Physician",
            payload_json={"consult_id": consult["id"], "score": score},
        )

    return jsonify(success_object(rx)), 200


@bp.post("/telemed/prescriptions/<rid>/transmit")
@require_roles(["Physician"])
def transmit_prescription(rid: str):
    rx = store.prescriptions.get(rid)
    if not rx:
        raise err_not_found()
    user_id = request.headers.get("X-User-ID")
    body = parse_json_body()
    if rx["status"] != "ISSUED":
        raise err_invalid_state("Prescription is not in ISSUED state")
    if rx.get("prescribing_physician_id") != user_id:
        raise err_forbidden()
    check_version_if_supplied(rx, body)
    with store.lock:
        if rx["status"] != "ISSUED":
            raise err_invalid_state("Prescription is not in ISSUED state")
        rx["status"] = "TRANSMITTED"
        now_iso = store.now_iso()
        bump_version_and_timestamp(rx, now_iso)
    return jsonify(success_object(rx)), 200


@bp.post("/telemed/prescriptions/<rid>/mark-dispensed")
@require_roles(["ComplianceOfficer"])
def mark_dispensed(rid: str):
    rx = store.prescriptions.get(rid)
    if not rx:
        raise err_not_found()
    body = parse_json_body()
    if rx["status"] != "TRANSMITTED":
        raise err_invalid_state("Prescription is not in TRANSMITTED state")
    check_version_if_supplied(rx, body)
    with store.lock:
        if rx["status"] != "TRANSMITTED":
            raise err_invalid_state("Prescription is not in TRANSMITTED state")
        rx["status"] = "DISPENSED"
        now_iso = store.now_iso()
        bump_version_and_timestamp(rx, now_iso)
    return jsonify(success_object(rx)), 200


@bp.post("/telemed/prescriptions/<rid>/void")
@require_roles(["Physician"])
def void_prescription(rid: str):
    rx = store.prescriptions.get(rid)
    if not rx:
        raise err_not_found()
    user_id = request.headers.get("X-User-ID")
    body = parse_json_body()
    if rx["status"] not in {"DRAFT", "ISSUED", "TRANSMITTED"}:
        raise err_invalid_state("Prescription cannot be voided from its current state")
    if rx.get("prescribing_physician_id") != user_id:
        raise err_forbidden()
    check_version_if_supplied(rx, body)
    void_reason = body.get("void_reason")
    if not isinstance(void_reason, str) or not void_reason:
        raise err_invalid_state("void_reason is required")

    with store.lock:
        if rx["status"] not in {"DRAFT", "ISSUED", "TRANSMITTED"}:
            raise err_invalid_state("Prescription cannot be voided from its current state")
        rx["status"] = "VOIDED"
        rx["void_reason"] = void_reason
        now_iso = store.now_iso()
        bump_version_and_timestamp(rx, now_iso)
        store.append_audit(
            event_type="RX_VOIDED",
            subject_entity="Prescription",
            subject_id=rx["id"],
            actor_role="Physician",
            payload_json={"void_reason": void_reason},
        )
    return jsonify(success_object(rx)), 200
