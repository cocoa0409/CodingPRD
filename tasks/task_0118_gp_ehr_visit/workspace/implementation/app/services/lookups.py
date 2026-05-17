"""Helpers to look up entities and raise ERR_NOT_FOUND if missing."""
from __future__ import annotations

from ..errors import err_not_found, err_reference_not_found
from ..store import store


def get_patient(patient_id: str, *, source: str = "path") -> dict:
    row = store().patients.get(patient_id)
    if row is None:
        if source == "path":
            raise err_not_found(f"Patient {patient_id} not found")
        raise err_reference_not_found(f"Patient {patient_id} not found")
    return row


def get_provider(provider_id: str, *, source: str = "path") -> dict:
    row = store().providers.get(provider_id)
    if row is None:
        if source == "path":
            raise err_not_found(f"Provider {provider_id} not found")
        raise err_reference_not_found(f"Provider {provider_id} not found")
    return row


def get_encounter(encounter_id: str, *, source: str = "path") -> dict:
    row = store().encounters.get(encounter_id)
    if row is None:
        if source == "path":
            raise err_not_found(f"Encounter {encounter_id} not found")
        raise err_reference_not_found(f"Encounter {encounter_id} not found")
    return row


def get_cpt_line_item(line_id: str, *, source: str = "path") -> dict:
    row = store().cpt_line_items.get(line_id)
    if row is None:
        if source == "path":
            raise err_not_found(f"CptLineItem {line_id} not found")
        raise err_reference_not_found(f"CptLineItem {line_id} not found")
    return row


def get_cpt_fee(cpt_code: str, *, source: str = "path") -> dict:
    row = store().cpt_fee_catalog.get(cpt_code)
    if row is None:
        if source == "path":
            raise err_not_found(f"CPT code {cpt_code} not found")
        raise err_reference_not_found(f"CPT code {cpt_code} not found")
    return row


def get_prescription(prescription_id: str, *, source: str = "path") -> dict:
    row = store().prescriptions.get(prescription_id)
    if row is None:
        if source == "path":
            raise err_not_found(f"Prescription {prescription_id} not found")
        raise err_reference_not_found(f"Prescription {prescription_id} not found")
    return row


def get_referral(referral_id: str, *, source: str = "path") -> dict:
    row = store().referrals.get(referral_id)
    if row is None:
        if source == "path":
            raise err_not_found(f"Referral {referral_id} not found")
        raise err_reference_not_found(f"Referral {referral_id} not found")
    return row


def get_portal_message(message_id: str, *, source: str = "path") -> dict:
    row = store().portal_messages.get(message_id)
    if row is None:
        if source == "path":
            raise err_not_found(f"PortalMessage {message_id} not found")
        raise err_reference_not_found(f"PortalMessage {message_id} not found")
    return row
