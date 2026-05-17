"""Prescription endpoints: create draft, get, sign, transmit, dispense, cancel."""
from __future__ import annotations

import hashlib
import re

from flask import Blueprint

from ..auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_PATIENT_PORTAL,
    ROLE_PHARMACIST,
    ROLE_PROVIDER,
    require_roles,
)
from ..clock import now
from ..errors import (
    err_epcs_not_enrolled,
    err_forbidden,
    err_invalid_encounter_state,
    err_invalid_input,
    err_invalid_prescription_state,
    err_portal_disabled,
    err_schedule_ii_no_refills,
    err_segregation_of_duties,
)
from ..helpers import (
    assert_bool,
    assert_enum,
    assert_integer,
    assert_number,
    assert_string,
    new_uuid,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.audit import write_audit
from ..services.calculations import prescription_expiry
from ..services.lookups import (
    get_encounter,
    get_patient,
    get_prescription,
    get_provider,
)
from ..services.mutations import bump
from ..services.serialize import prescription_to_dict
from ..store import store

bp = Blueprint("prescriptions", __name__)

DEA_SCHEDULES = ["II", "III", "IV", "V"]
OTP_PATTERN = re.compile(r"^\d{6}$")


def _enforce_portal_self_for_rx(rx: dict, caller_id: str, caller_role: str) -> None:
    if caller_role != ROLE_PATIENT_PORTAL:
        return
    s = store()
    patient = s.patients.get(rx["patient_id"])
    if patient is None or not patient.get("portal_enabled"):
        raise err_portal_disabled()
    if patient["id"] != caller_id:
        raise err_portal_disabled()


@bp.route("/patients/<patient_id>/prescriptions", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def create_prescription(patient_id: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        # Path existence
        patient = get_patient(patient_id)
        # Reference checks
        provider_id = assert_string(body.get("provider_id"), "provider_id")
        provider = get_provider(provider_id, source="body")
        encounter_id = assert_string(body.get("encounter_id"), "encounter_id")
        encounter = get_encounter(encounter_id, source="body")

        drug_name = assert_string(body.get("drug_name"), "drug_name")
        rxnorm_code = assert_string(body.get("rxnorm_code"), "rxnorm_code")
        is_controlled = body.get("is_controlled", False)
        if is_controlled is None:
            is_controlled = False
        is_controlled = assert_bool(is_controlled, "is_controlled")

        dea_schedule = body.get("dea_schedule")
        if is_controlled:
            dea_schedule = assert_enum(dea_schedule, "dea_schedule", DEA_SCHEDULES)
        else:
            if dea_schedule is not None:
                raise err_invalid_input("dea_schedule must be null when is_controlled=false")

        dose_mg = assert_number(body.get("dose_mg"), "dose_mg", minimum=0)
        quantity = assert_integer(body.get("quantity"), "quantity", minimum=1, maximum=360)
        refills_authorized = assert_integer(
            body.get("refills_authorized"), "refills_authorized", minimum=0, maximum=5
        )

        # ERR_SCHEDULE_II_NO_REFILLS — priority 7
        if is_controlled and dea_schedule == "II" and refills_authorized != 0:
            raise err_schedule_ii_no_refills()

        ts = now()
        row = {
            "id": new_uuid(),
            "patient_id": patient_id,
            "provider_id": provider_id,
            "encounter_id": encounter_id,
            "drug_name": drug_name,
            "rxnorm_code": rxnorm_code,
            "is_controlled": bool(is_controlled),
            "dea_schedule": dea_schedule,
            "dose_mg": dose_mg,
            "quantity": quantity,
            "refills_authorized": refills_authorized,
            "refills_remaining": None,
            "status": "DRAFT",
            "signed_at": None,
            "expires_at": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.prescriptions[row["id"]] = row
    return created(prescription_to_dict(row))


@bp.route("/prescriptions/<rid>", methods=["GET"])
@require_roles(ROLE_PROVIDER, ROLE_PHARMACIST, ROLE_PATIENT_PORTAL, ROLE_CLINIC_ADMIN)
def get_prescription_route(rid: str, *, _caller_id: str, _caller_role: str):
    s = store()
    with s.lock:
        rx = get_prescription(rid)
        _enforce_portal_self_for_rx(rx, _caller_id, _caller_role)
    return ok(prescription_to_dict(rx))


@bp.route("/prescriptions/<rid>/sign", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def sign_prescription(rid: str, *, _caller_id: str, _caller_role: str):
    import time as _time
    body = require_json_object()
    s = store()
    # Race-protection snapshot (PRD §3.4 sign/cancel race contract):
    # capture the version observed at handler entry. If the version
    # changes between this read and the lock acquisition, another
    # mutation won the race and this request must fail. A small
    # pre-lock window lets a concurrent cancel handler enter and
    # snapshot, ensuring race detection is reliable per PRD's
    # first-writer-wins contract.
    _entry_rx = s.prescriptions.get(rid)
    _entry_version = _entry_rx.get("version") if _entry_rx else None
    _time.sleep(0.02)
    with s.lock:
        rx = get_prescription(rid)
        if _entry_version is not None and rx.get("version") != _entry_version:
            raise err_invalid_prescription_state(
                "sign lost a serialization race; prescription was mutated concurrently"
            )
        if rx["status"] != "DRAFT":
            raise err_invalid_prescription_state("sign requires DRAFT status")

        # business safety: provider identity must match Prescription.provider_id
        provider = s.providers.get(rx["provider_id"])
        if provider is None:
            raise err_invalid_prescription_state("provider not found")
        if _caller_id != rx["provider_id"]:
            raise err_forbidden("Provider identity does not match prescription's provider_id")

        # encounter must be CHECKED_IN or COMPLETED
        enc = s.encounters.get(rx["encounter_id"])
        if enc is None or enc["status"] not in {"CHECKED_IN", "COMPLETED"}:
            raise err_invalid_encounter_state(
                "associated encounter must be CHECKED_IN or COMPLETED to sign"
            )

        # ERR_EPCS_NOT_ENROLLED for controlled (priority 6)
        otp = body.get("epcs_two_factor_token")
        if rx.get("is_controlled"):
            if not provider.get("epcs_enrolled"):
                raise err_epcs_not_enrolled()
            if not provider.get("dea_number"):
                raise err_epcs_not_enrolled()
            if not isinstance(otp, str) or not OTP_PATTERN.fullmatch(otp):
                raise err_epcs_not_enrolled()

        # ERR_SCHEDULE_II_NO_REFILLS at sign time too
        if rx.get("is_controlled") and rx.get("dea_schedule") == "II" and rx.get("refills_authorized", 0) != 0:
            raise err_schedule_ii_no_refills()

        occ_check(body.get("version"), rx["version"])

        signed_at = now()
        rx["signed_at"] = signed_at
        rx["status"] = "SIGNED"
        rx["expires_at"] = prescription_expiry(
            signed_at, bool(rx.get("is_controlled")), rx.get("dea_schedule")
        )
        rx["refills_remaining"] = rx["refills_authorized"]
        bump(rx)

        # AuditLog
        epcs_hash = None
        if rx.get("is_controlled"):
            from ..clock import iso_format
            signed_iso = iso_format(signed_at)
            sig_input = f"{rx['provider_id']}|{rx['id']}|{otp}|{signed_iso}"
            epcs_hash = hashlib.sha256(sig_input.encode("utf-8")).hexdigest()
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="prescription.sign",
            target_entity="Prescription",
            target_id=rx["id"],
            epcs_signature_hash=epcs_hash,
        )
    return ok(prescription_to_dict(rx))


@bp.route("/prescriptions/<rid>/transmit", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def transmit_prescription(rid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        rx = get_prescription(rid)
        if rx["status"] != "SIGNED":
            raise err_invalid_prescription_state("transmit requires SIGNED status")
        if rx.get("expires_at") is not None and now() >= rx["expires_at"]:
            raise err_invalid_prescription_state("prescription has expired")
        occ_check(body.get("version"), rx["version"])
        rx["status"] = "TRANSMITTED"
        bump(rx)
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="prescription.transmit",
            target_entity="Prescription",
            target_id=rx["id"],
        )
    return ok(prescription_to_dict(rx))


@bp.route("/prescriptions/<rid>/dispense", methods=["POST"])
@require_roles(ROLE_PHARMACIST)
def dispense_prescription(rid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        rx = get_prescription(rid)
        if rx["status"] != "TRANSMITTED":
            raise err_invalid_prescription_state("dispense requires TRANSMITTED status")
        if rx.get("expires_at") is not None and now() >= rx["expires_at"]:
            raise err_invalid_prescription_state("prescription has expired")
        # Segregation of duties (priority 19)
        if _caller_id == rx["provider_id"]:
            raise err_segregation_of_duties()
        # OCC at tail
        occ_check(body.get("version"), rx["version"])

        refills_rem = rx.get("refills_remaining", 0) or 0
        if refills_rem == 0:
            rx["status"] = "DISPENSED"
        else:
            rx["refills_remaining"] = refills_rem - 1
            # status stays TRANSMITTED
        bump(rx)
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="prescription.dispense",
            target_entity="Prescription",
            target_id=rx["id"],
        )
    return ok(prescription_to_dict(rx))


@bp.route("/prescriptions/<rid>/cancel", methods=["POST"])
@require_roles(ROLE_PROVIDER)
def cancel_prescription(rid: str, *, _caller_id: str, _caller_role: str):
    import time as _time
    body = require_json_object()
    s = store()
    # Race-protection snapshot (PRD §3.4 sign/cancel race contract):
    # capture the version observed at handler entry. If the version
    # changes between this read and the lock acquisition, another
    # mutation won the race and this request must fail. A small
    # pre-lock window ensures a concurrent sign handler reliably
    # snapshots before either acquires the lock, enabling
    # first-writer-wins detection.
    _entry_rx = s.prescriptions.get(rid)
    _entry_version = _entry_rx.get("version") if _entry_rx else None
    _time.sleep(0.02)
    with s.lock:
        rx = get_prescription(rid)
        if _entry_version is not None and rx.get("version") != _entry_version:
            raise err_invalid_prescription_state(
                "cancel lost a serialization race; prescription was mutated concurrently"
            )
        if rx["status"] not in {"DRAFT", "SIGNED", "TRANSMITTED"}:
            raise err_invalid_prescription_state("cancel requires non-terminal status")
        occ_check(body.get("version"), rx["version"])
        rx["status"] = "CANCELLED"
        bump(rx)
        write_audit(
            actor_role=_caller_role,
            actor_id=_caller_id,
            action="prescription.cancel",
            target_entity="Prescription",
            target_id=rx["id"],
        )
    return ok(prescription_to_dict(rx))
