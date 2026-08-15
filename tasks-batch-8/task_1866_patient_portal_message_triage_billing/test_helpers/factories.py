"""Payload factories — one per creatable resource, input fields only.

Optional fields are omitted from the payload unless an explicit (non-None)
override is supplied, so conditional-field rules stay observable.
"""
from .constants import (
    DEFAULT_COPAY_CENTS,
    NURSE_TARGET_EMERGENT,
    NURSE_TARGET_ROUTINE,
    NURSE_TARGET_URGENT,
    PROVIDER_TARGET_EMERGENT,
    PROVIDER_TARGET_ROUTINE,
    PROVIDER_TARGET_URGENT,
    WIDE_COVERAGE_END,
    WIDE_COVERAGE_START,
)


def create_patient_payload(full_name="Pat", plan_type="COPAY",
                           copay_cents=DEFAULT_COPAY_CENTS,
                           coinsurance_pct=None, date_of_birth=None) -> dict:
    payload = {"full_name": full_name, "plan_type": plan_type}
    if date_of_birth is not None:
        payload["date_of_birth"] = date_of_birth
    if copay_cents is not None:
        payload["copay_cents"] = copay_cents
    if coinsurance_pct is not None:
        payload["coinsurance_pct"] = coinsurance_pct
    return payload


def create_staff_payload(full_name="Staff", staff_type="NURSE") -> dict:
    return {"full_name": full_name, "staff_type": staff_type}


def create_pool_payload(name="Pool", pool_kind="PROVIDER_INBOX",
                        deadline_policy="FROM_TRIAGE",
                        target_minutes_emergent=PROVIDER_TARGET_EMERGENT,
                        target_minutes_urgent=PROVIDER_TARGET_URGENT,
                        target_minutes_routine=PROVIDER_TARGET_ROUTINE) -> dict:
    return {
        "name": name,
        "pool_kind": pool_kind,
        "target_minutes_emergent": target_minutes_emergent,
        "target_minutes_urgent": target_minutes_urgent,
        "target_minutes_routine": target_minutes_routine,
        "deadline_policy": deadline_policy,
    }


def create_nurse_pool_payload(name="NurseTriage", deadline_policy="FROM_TRIAGE",
                              target_minutes_emergent=NURSE_TARGET_EMERGENT,
                              target_minutes_urgent=NURSE_TARGET_URGENT,
                              target_minutes_routine=NURSE_TARGET_ROUTINE) -> dict:
    return create_pool_payload(
        name=name, pool_kind="NURSE_TRIAGE", deadline_policy=deadline_policy,
        target_minutes_emergent=target_minutes_emergent,
        target_minutes_urgent=target_minutes_urgent,
        target_minutes_routine=target_minutes_routine,
    )


def create_coverage_window_payload(pool_id, staff_id,
                                   start_utc=WIDE_COVERAGE_START,
                                   end_utc=WIDE_COVERAGE_END) -> dict:
    return {"pool_id": pool_id, "staff_id": staff_id,
            "start_utc": start_utc, "end_utc": end_utc}


def create_on_call_shift_payload(provider_id, start_utc, end_utc) -> dict:
    return {"provider_id": provider_id, "start_utc": start_utc,
            "end_utc": end_utc}


def create_delegation_grant_payload(delegate_staff_id, pool_id,
                                    start_utc, end_utc) -> dict:
    return {"delegate_staff_id": delegate_staff_id, "pool_id": pool_id,
            "start_utc": start_utc, "end_utc": end_utc}


def create_portal_message_payload(subject="S", body="B") -> dict:
    return {"subject": subject, "body": body}


def triage_payload(urgency, category, pool_id, expected_message_version) -> dict:
    return {
        "urgency": urgency,
        "category": category,
        "pool_id": pool_id,
        "expected_message_version": expected_message_version,
    }


def assign_payload(staff_id=None) -> dict:
    payload: dict = {}
    if staff_id is not None:
        payload["staff_id"] = staff_id
    return payload


def reply_payload(body="reply") -> dict:
    return {"body": body}


def complete_payload(resolution_summary="done") -> dict:
    return {"resolution_summary": resolution_summary}


def cosign_payload(action="COSIGN") -> dict:
    return {"action": action}


def escalate_payload(reason="escalation") -> dict:
    return {"reason": reason}


def determine_billing_payload(disposition, expected_message_version) -> dict:
    return {"disposition": disposition,
            "expected_message_version": expected_message_version}


def create_time_entry_payload(message_id, entry_kind, minutes, note=None) -> dict:
    payload = {"message_id": message_id, "entry_kind": entry_kind,
               "minutes": minutes}
    if note is not None:
        payload["note"] = note
    return payload


def create_education_notice_payload(message_id, notice_kind, body,
                                    blocking=None) -> dict:
    payload = {"message_id": message_id, "notice_kind": notice_kind,
               "body": body}
    if blocking is not None:
        payload["blocking"] = blocking
    return payload


def respond_consent_payload(decision) -> dict:
    return {"decision": decision}


def create_evisit_claim_payload(message_id, rendering_provider_id) -> dict:
    return {"message_id": message_id,
            "rendering_provider_id": rendering_provider_id}


def record_adjudication_payload(outcome, denial_reason=None) -> dict:
    payload = {"outcome": outcome}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
