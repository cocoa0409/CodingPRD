"""
Request payload builders for the Urology Practice & In-Office Procedure Suite.

Each builder returns the payload of one write operation with every required
field populated with a valid, ordinary value; keyword arguments override any
field, and passing ``None`` for an optional field leaves it out entirely so
tests can exercise defaulting. Identifiers are unique per process so repeated
creations never collide on a natural key.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    AGENT_AUTO,
    CLEANUP_LOW,
    CONDITION_INTACT,
    DECISION_ACCEPT,
    DEFAULT_PREP_CODE,
    DEVICE_CLASS_SINGLE_USE_SCOPE_SHEATH,
    NOTIFY_OUTCOME_REACHED,
    OUTCOME_PASS,
    PROGRAM_PELVIC_FLOOR_PT,
    PROTOCOL_STONE,
    RESULT_BENIGN,
    ROLE_TYPE_UROLOGIST,
    ROOM_TYPE_CYSTO_SUITE,
    SPECIMEN_PROSTATE_CORE,
    STAGE_PRECLEAN,
    TIER_LOW,
    TYPE_CYSTOSCOPY,
    VISIT_ACTION_LOG,
    CHANNEL_PHONE,
)

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def _drop_unset(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys whose value is ``None`` so the field is simply absent."""
    return {k: v for k, v in payload.items() if v is not None}


def unique_suffix() -> str:
    """A short token unique within this test process."""
    return f"{_seq():05d}"


# ─── Providers ─────────────────────────────────────────────────────────────
def provider_payload(
    role_type: str = ROLE_TYPE_UROLOGIST,
    full_name: Optional[str] = None,
    npi: Optional[str] = None,
    hld_certified: Optional[bool] = None,
    ultrasound_accreditation_expires_on: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload = {
        "full_name": full_name if full_name is not None else f"Provider {suffix}",
        "npi": npi if npi is not None else f"10{suffix}00{suffix}"[:10],
        "role_type": role_type,
        "hld_certified": hld_certified,
        "ultrasound_accreditation_expires_on": ultrasound_accreditation_expires_on,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def provider_update_payload(**fields: Any) -> Dict[str, Any]:
    return dict(fields)


# ─── Patients ──────────────────────────────────────────────────────────────
def patient_payload(
    primary_urologist_id: str,
    egfr: float = 90,
    mrn: Optional[str] = None,
    full_name: Optional[str] = None,
    date_of_birth: str = "1962-04-11",
    anticoagulant_flag: Optional[bool] = None,
    antibiotic_allergy_class: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload = {
        "mrn": mrn if mrn is not None else f"MRN-{suffix}",
        "full_name": full_name if full_name is not None else f"Patient {suffix}",
        "date_of_birth": date_of_birth,
        "primary_urologist_id": primary_urologist_id,
        "egfr": egfr,
        "anticoagulant_flag": anticoagulant_flag,
        "antibiotic_allergy_class": antibiotic_allergy_class,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def patient_update_payload(**fields: Any) -> Dict[str, Any]:
    return dict(fields)


# ─── Procedure rooms ───────────────────────────────────────────────────────
def procedure_room_payload(
    room_type: str = ROOM_TYPE_CYSTO_SUITE,
    name: Optional[str] = None,
    turnover_minutes: Optional[int] = None,
    accreditation_body: Optional[str] = None,
    accreditation_expires_on: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload = {
        "name": name if name is not None else f"Room {suffix}",
        "room_type": room_type,
        "turnover_minutes": turnover_minutes,
        "accreditation_body": accreditation_body,
        "accreditation_expires_on": accreditation_expires_on,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def procedure_room_update_payload(**fields: Any) -> Dict[str, Any]:
    return dict(fields)


# ─── Procedure types ───────────────────────────────────────────────────────
def procedure_type_payload(
    code: str = TYPE_CYSTOSCOPY,
    base_minutes: int = 20,
    cleanup_class: str = CLEANUP_LOW,
    allowed_room_type: str = ROOM_TYPE_CYSTO_SUITE,
    requires_scope: Optional[bool] = None,
    requires_specimen: Optional[bool] = None,
    requires_antibiotic: Optional[bool] = None,
    consignment_required: Optional[bool] = None,
    single_use_device_sku: Optional[str] = None,
    required_prep_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "code": code,
        "base_minutes": base_minutes,
        "cleanup_class": cleanup_class,
        "allowed_room_type": allowed_room_type,
        "requires_scope": requires_scope,
        "requires_specimen": requires_specimen,
        "requires_antibiotic": requires_antibiotic,
        "consignment_required": consignment_required,
        "single_use_device_sku": single_use_device_sku,
        "required_prep_codes": required_prep_codes,
    }
    payload.update(overrides)
    return _drop_unset(payload)


# ─── Scope assets ──────────────────────────────────────────────────────────
def scope_asset_payload(
    serial_number: Optional[str] = None,
    scope_model: str = "FlexCysto-3000",
    channel_count: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload = {
        "serial_number": serial_number if serial_number is not None else f"SN-{suffix}",
        "scope_model": scope_model,
        "channel_count": channel_count,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def commissioning_payload(attesting_provider_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"attesting_provider_id": attesting_provider_id}
    payload.update(overrides)
    return payload


# ─── Consignment lots ──────────────────────────────────────────────────────
def consignment_lot_payload(
    sku: Optional[str] = None,
    device_class: str = DEVICE_CLASS_SINGLE_USE_SCOPE_SHEATH,
    quantity_received: int = 10,
    unit_price_cents: int = 2000,
    lot_expires_on: str = "2027-06-30",
    supplier_name: str = "Meridian Urology Supply",
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload = {
        "supplier_name": supplier_name,
        "sku": sku if sku is not None else f"SKU-{suffix}",
        "device_class": device_class,
        "quantity_received": quantity_received,
        "unit_price_cents": unit_price_cents,
        "lot_expires_on": lot_expires_on,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def lot_return_payload(quantity: int, **overrides: Any) -> Dict[str, Any]:
    payload = {"quantity": quantity}
    payload.update(overrides)
    return payload


# ─── Procedure cases ───────────────────────────────────────────────────────
def procedure_case_payload(
    patient_id: str,
    procedure_type_id: str,
    room_id: str,
    primary_provider_id: str,
    scheduled_start_at: str,
    indication_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "patient_id": patient_id,
        "procedure_type_id": procedure_type_id,
        "room_id": room_id,
        "primary_provider_id": primary_provider_id,
        "scheduled_start_at": scheduled_start_at,
        "indication_note": indication_note,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def schedule_payload(expected_room_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {"expected_room_version": expected_room_version}
    payload.update(overrides)
    return payload


def reschedule_payload(
    scheduled_start_at: str, room_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {"scheduled_start_at": scheduled_start_at, "room_id": room_id}
    payload.update(overrides)
    return _drop_unset(payload)


def prep_acknowledgement_payload(
    instruction_code: str = DEFAULT_PREP_CODE,
    channel: str = CHANNEL_PHONE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"instruction_code": instruction_code, "channel": channel}
    payload.update(overrides)
    return payload


def clearance_review_payload(
    decision: str, block_reason_code: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {"decision": decision, "block_reason_code": block_reason_code}
    payload.update(overrides)
    return _drop_unset(payload)


def scope_assignment_payload(
    scope_asset_id: str, expected_scope_asset_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "scope_asset_id": scope_asset_id,
        "expected_scope_asset_version": expected_scope_asset_version,
    }
    payload.update(overrides)
    return payload


def device_reservation_payload(
    consignment_lot_id: str, quantity: int, expected_lot_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "consignment_lot_id": consignment_lot_id,
        "quantity": quantity,
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def complete_case_payload(outcome_note: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload = {"outcome_note": outcome_note}
    payload.update(overrides)
    return _drop_unset(payload)


def cancel_payload(cancel_reason_code: str = "PATIENT_REQUEST", **overrides: Any) -> Dict[str, Any]:
    payload = {"cancel_reason_code": cancel_reason_code}
    payload.update(overrides)
    return payload


# ─── Antibiotic orders ─────────────────────────────────────────────────────
def antibiotic_order_payload(
    case_id: str,
    ordered_by_provider_id: str,
    requested_agent: str = AGENT_AUTO,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "case_id": case_id,
        "ordered_by_provider_id": ordered_by_provider_id,
        "requested_agent": requested_agent,
    }
    payload.update(overrides)
    return payload


def administer_payload(administered_at: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"administered_at": administered_at}
    payload.update(overrides)
    return payload


# ─── Reprocessing logs ─────────────────────────────────────────────────────
def reprocessing_log_payload(
    scope_asset_id: str,
    performed_by_provider_id: str,
    stage: str = STAGE_PRECLEAN,
    case_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "scope_asset_id": scope_asset_id,
        "stage": stage,
        "performed_by_provider_id": performed_by_provider_id,
        "case_id": case_id,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def reprocessing_complete_payload(
    attested_by_provider_id: str, outcome: str = OUTCOME_PASS, **overrides: Any
) -> Dict[str, Any]:
    payload = {"outcome": outcome, "attested_by_provider_id": attested_by_provider_id}
    payload.update(overrides)
    return payload


# ─── Specimens ─────────────────────────────────────────────────────────────
def specimen_payload(
    case_id: str,
    collected_by_provider_id: str,
    container_label: Optional[str] = None,
    specimen_type: str = SPECIMEN_PROSTATE_CORE,
    site_code: str = "LEFT_APEX",
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload = {
        "case_id": case_id,
        "collected_by_provider_id": collected_by_provider_id,
        "container_label": (
            container_label if container_label is not None else f"CTR-{suffix}"
        ),
        "specimen_type": specimen_type,
        "site_code": site_code,
    }
    payload.update(overrides)
    return payload


def accession_payload(
    received_at: str,
    accession_number: Optional[str] = None,
    condition_on_receipt: str = CONDITION_INTACT,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload = {
        "accession_number": (
            accession_number if accession_number is not None else f"ACC-{suffix}"
        ),
        "received_at": received_at,
        "condition_on_receipt": condition_on_receipt,
    }
    payload.update(overrides)
    return payload


def result_payload(pathology_result: str = RESULT_BENIGN, **overrides: Any) -> Dict[str, Any]:
    payload = {"pathology_result": pathology_result}
    payload.update(overrides)
    return payload


def notification_attempt_payload(
    outcome: str = NOTIFY_OUTCOME_REACHED, channel: str = CHANNEL_PHONE, **overrides: Any
) -> Dict[str, Any]:
    payload = {"outcome": outcome, "channel": channel}
    payload.update(overrides)
    return payload


# ─── Surveillance recalls ──────────────────────────────────────────────────
def surveillance_recall_payload(
    patient_id: str,
    expected_patient_version: int,
    protocol: str = PROTOCOL_STONE,
    risk_tier: str = TIER_LOW,
    anchor_date: str = "2026-08-01",
    source_specimen_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "patient_id": patient_id,
        "protocol": protocol,
        "risk_tier": risk_tier,
        "anchor_date": anchor_date,
        "expected_patient_version": expected_patient_version,
        "source_specimen_id": source_specimen_id,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def recall_close_payload(closed_reason: str = "PATIENT_TRANSFERRED", **overrides: Any) -> Dict[str, Any]:
    payload = {"closed_reason": closed_reason}
    payload.update(overrides)
    return payload


# ─── Pelvic health referrals ───────────────────────────────────────────────
def referral_payload(
    patient_id: str,
    source_case_id: str,
    program: str = PROGRAM_PELVIC_FLOOR_PT,
    requested_visits: int = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "patient_id": patient_id,
        "source_case_id": source_case_id,
        "program": program,
        "requested_visits": requested_visits,
    }
    payload.update(overrides)
    return payload


def referral_decision_payload(
    decision: str = DECISION_ACCEPT,
    authorized_visits: Optional[int] = None,
    decline_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "decision": decision,
        "authorized_visits": authorized_visits,
        "decline_reason": decline_reason,
    }
    payload.update(overrides)
    return _drop_unset(payload)


def referral_visit_payload(
    action: str = VISIT_ACTION_LOG, visit_date: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {"action": action, "visit_date": visit_date}
    payload.update(overrides)
    return _drop_unset(payload)
