"""Payload factories — one per entity, input fields only.

Factories emit exactly the fields the PRD names as caller-supplied; optional
fields are included only when a value is provided (or when a PRD-stated
default is part of the scenario under test and passed explicitly).
"""
from .constants import (
    DEFAULT_CASE_END,
    DEFAULT_CASE_START,
    DEFAULT_CREDENTIAL_EXPIRES,
    DEFAULT_STERILIZER,
    DEFAULT_VENDOR,
)


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": DEFAULT_VENDOR["vendor_name"],
        "vendor_code": DEFAULT_VENDOR["vendor_code"],
        "late_grace_minutes": DEFAULT_VENDOR["late_grace_minutes"],
        "late_rate_per_hour_cents": DEFAULT_VENDOR["late_rate_per_hour_cents"],
        "late_penalty_cap_cents": DEFAULT_VENDOR["late_penalty_cap_cents"],
        "delay_surcharge_per_minute_cents":
            DEFAULT_VENDOR["delay_surcharge_per_minute_cents"],
    }
    defaults.update(overrides)
    return defaults


def create_rep_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Rita Rep",
        "rep_email": "r@acme.com",
        "credential_doc_ref": "DOC-1",
    }
    defaults.update(overrides)
    return defaults


def approve_credential_payload(**overrides) -> dict:
    defaults = {
        "credential_expires_at": DEFAULT_CREDENTIAL_EXPIRES,
        "or_access_level": "OBSERVER",
    }
    defaults.update(overrides)
    return defaults


def create_or_room_payload(**overrides) -> dict:
    defaults = {"room_name": "OR-1", "turnover_buffer_minutes": 30}
    defaults.update(overrides)
    return defaults


def create_sterilizer_unit_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_STERILIZER)
    defaults.update(overrides)
    return defaults


def create_case_payload(or_room_id, **overrides) -> dict:
    defaults = {
        "case_number": "C-1001",
        "or_room_id": or_room_id,
        "procedure_type": "TOTAL_KNEE",
        "surgeon_name": "Dr. A",
        "scheduled_start_at": DEFAULT_CASE_START,
        "scheduled_end_at": DEFAULT_CASE_END,
    }
    defaults.update(overrides)
    return defaults


def reschedule_case_payload(expected_case_version, **overrides) -> dict:
    defaults = {
        "scheduled_start_at": "2026-08-05T14:00:00Z",
        "scheduled_end_at": "2026-08-05T17:00:00Z",
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def start_case_payload(**overrides) -> dict:
    return dict(overrides)


def create_delay_event_payload(cause, minutes, **overrides) -> dict:
    payload = {"cause": cause, "minutes": minutes}
    payload.update(overrides)
    return payload


def create_request_payload(case_id, vendor_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "vendor_id": vendor_id,
        "priority_class": "URGENT",
    }
    defaults.update(overrides)
    return defaults


def create_tray_payload(**overrides) -> dict:
    defaults = {
        "tray_code": "TK-1",
        "declared_instrument_count": 50,
        "replacement_value_cents": 300000,
    }
    defaults.update(overrides)
    return defaults


def decide_request_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def check_in_line(tray_id, instrument_count_delivered, **overrides) -> dict:
    line = {"tray_id": tray_id,
            "instrument_count_delivered": instrument_count_delivered}
    line.update(overrides)
    return line


def create_check_in_payload(lines, **overrides) -> dict:
    defaults = {
        "lines": lines,
        "ifu_provided": True,
        "loaner_agreement_ref": "LA-1",
    }
    defaults.update(overrides)
    return defaults


def line_disposition(tray_id, disposition="ACCEPT") -> dict:
    return {"tray_id": tray_id, "disposition": disposition}


def verify_check_in_payload(line_dispositions) -> dict:
    return {"line_dispositions": line_dispositions}


def fail_qa_payload(reason="wet pack") -> dict:
    return {"reason": reason}


def start_cycle_payload(sterilizer_unit_id) -> dict:
    return {"sterilizer_unit_id": sterilizer_unit_id}


def create_escalation_payload(type_, **overrides) -> dict:
    payload = {"type": type_}
    payload.update(overrides)
    return payload


def resolve_escalation_payload(resolution_type) -> dict:
    return {"resolution_type": resolution_type}


def create_access_pass_payload(rep_id, case_id) -> dict:
    return {"rep_id": rep_id, "case_id": case_id}


def decide_access_pass_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def pickup_line(tray_id, instrument_count_returned, condition="OK") -> dict:
    return {"tray_id": tray_id,
            "instrument_count_returned": instrument_count_returned,
            "condition": condition}


def create_pickup_payload(lines) -> dict:
    return {"lines": lines}


def dispute_pickup_payload(reason="counts contested") -> dict:
    return {"reason": reason}


def create_claim_payload(tray_id, request_id, damage_type,
                         claimed_amount_cents) -> dict:
    return {
        "tray_id": tray_id,
        "request_id": request_id,
        "damage_type": damage_type,
        "claimed_amount_cents": claimed_amount_cents,
    }


def apportion_claim_payload(vendor_share_percent, expected_claim_version) -> dict:
    return {"vendor_share_percent": vendor_share_percent,
            "expected_claim_version": expected_claim_version}


def dispute_claim_payload(reason="disputed") -> dict:
    return {"reason": reason}


def waive_penalty_payload(waive_amount_cents, reason="goodwill") -> dict:
    return {"waive_amount_cents": waive_amount_cents, "reason": reason}


def settle_penalty_payload(settle_amount_cents) -> dict:
    return {"settle_amount_cents": settle_amount_cents}
