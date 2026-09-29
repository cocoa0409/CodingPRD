"""Request-body builders.

Every builder emits only fields the endpoint declares as inputs; computed and
system fields are never supplied (except by the deliberate probes that check
they are ignored, which pass them explicitly through ``**overrides``).
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_ACCOMMODATION_CHANNEL,
    DEFAULT_CLOCK_INPUT,
    DEFAULT_EXPOSURE_CEILING_CENTS,
    DEFAULT_ORG_NAME,
    DEFAULT_ORG_TYPE,
    ILLINOIS_PROFILE,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


_OMIT = object()
OMIT = _OMIT  # sentinel: pass OMIT for a field that must be absent from the body


# ----------------------------------------------------------------------
# ComplianceProgram / Jurisdiction
# ----------------------------------------------------------------------
def program_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "org_name": DEFAULT_ORG_NAME,
            "org_type": DEFAULT_ORG_TYPE,
            "exposure_ceiling_cents": DEFAULT_EXPOSURE_CEILING_CENTS,
        },
        overrides,
    )


def jurisdiction_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {"program_id": program_id}
    base.update(ILLINOIS_PROFILE)
    return _merge(base, overrides)


def oregon_jurisdiction_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Oregon: a LIMITED private right of action with a cure period and no
    written release or translation requirement."""
    return _merge(
        {
            "program_id": program_id,
            "state_code": "OR",
            "statute_name": "ORS 646A.622",
            "private_right_of_action": "LIMITED",
            "damages_model": "STATUTORY_PER_VIOLATION",
            "requires_written_release": False,
            "translation_required": False,
            "required_locales": ["en"],
            "retention_max_days": 730,
            "notice_lead_days": 0,
            "per_violation_negligent_cents": 33336,
            "per_violation_reckless_cents": 99999,
            "cure_period_days": 30,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Vendor / VendorContract
# ----------------------------------------------------------------------
def vendor_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A clean processor: no data sale, no subprocessors, a 15-day deletion SLA
    and complete subprocessor disclosure."""
    return _merge(
        {
            "program_id": program_id,
            "name": "ClockPoint Systems",
            "sells_biometric_data": False,
            "subprocessor_count": 0,
            "deletion_sla_days": 15,
            "subprocessor_disclosure_complete": True,
        },
        overrides,
    )


def vendor_contract_payload(vendor_id: str, **overrides: Any) -> Dict[str, Any]:
    """A fully clause-complete contract at the 30-day deletion target."""
    return _merge(
        {
            "vendor_id": vendor_id,
            "prohibits_sale": True,
            "restricts_disclosure": True,
            "requires_deletion_on_termination": True,
            "deletion_deadline_days": 30,
            "indemnity_cap_cents": 5000000,
            "effective_from": DEFAULT_CLOCK_INPUT,
        },
        overrides,
    )


def attestation_payload(attestation_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"attestation_status": attestation_status}, overrides)


# ----------------------------------------------------------------------
# BiometricPolicy / NoticePacket
# ----------------------------------------------------------------------
def policy_payload(program_id: str, jurisdiction_scope: List[str], **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "version_label": "v1.0",
            "retention_days": 30,
            "destruction_trigger": "FIXED_SCHEDULE",
            "release_language_included": True,
            "jurisdiction_scope": list(jurisdiction_scope),
        },
        overrides,
    )


def notice_packet_payload(
    program_id: str, jurisdiction_id: str, policy_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "policy_id": policy_id,
            "audience": "EMPLOYEE",
            "locales": ["en", "es"],
            "accommodation_channel": DEFAULT_ACCOMMODATION_CHANNEL,
            "effective_from": DEFAULT_CLOCK_INPUT,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# BiometricAsset
# ----------------------------------------------------------------------
def asset_payload(program_id: str, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "system_category": "TIMEKEEPING",
            "modality": "FINGERPRINT",
            "subject_class": "EMPLOYEE",
            "template_storage_location": "tk-vault-01",
            "declared_retention_days": 30,
            "retention_basis": "SCHEDULE_ONLY",
        },
        overrides,
    )


def access_control_asset_payload(
    program_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return asset_payload(
        program_id,
        jurisdiction_id,
        system_category="ACCESS_CONTROL",
        modality="HAND_GEOMETRY",
        template_storage_location="door-vault-01",
        **overrides,
    )


def camera_asset_payload(program_id: str, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return asset_payload(
        program_id,
        jurisdiction_id,
        system_category="SECURITY_CAMERA",
        modality="FACE_GEOMETRY",
        template_storage_location="cam-vault-01",
        **overrides,
    )


# ----------------------------------------------------------------------
# DataSubject / ConsentRecord / AlternativeAccommodation
# ----------------------------------------------------------------------
def data_subject_payload(
    program_id: str, jurisdiction_id: str, external_ref: str = "EMP-0001", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "subject_type": "EMPLOYEE",
            "external_ref": external_ref,
            "preferred_locale": "en",
        },
        overrides,
    )


def consent_payload(data_subject_id: str, asset_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"data_subject_id": data_subject_id, "asset_id": asset_id, "locale": "en"}, overrides)


def accommodation_payload(
    data_subject_id: str,
    asset_id: str,
    starts_at: str,
    ends_at: str,
    method: str = "MANUAL_TIMESHEET",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "data_subject_id": data_subject_id,
            "asset_id": asset_id,
            "method": method,
            "starts_at": starts_at,
            "ends_at": ends_at,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# IncidentCase / ExposureAssessment
# ----------------------------------------------------------------------
def incident_payload(program_id: str, affected_asset_ids: List[str], **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "affected_asset_ids": list(affected_asset_ids),
            "exposure_vector": "MISCONFIGURED_EXPORT",
            "description": "Template export bucket left world-readable for six hours.",
            "exposed_subject_count": 45,
            "translation_locale_count": 2,
        },
        overrides,
    )


def exposure_assessment_payload(
    program_id: str,
    jurisdiction_id: str,
    expected_jurisdiction_version: int,
    variant: str = "PER_VIOLATION_STACKED",
    incident_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "program_id": program_id,
        "jurisdiction_id": jurisdiction_id,
        "variant": variant,
        "expected_jurisdiction_version": expected_jurisdiction_version,
    }
    if incident_id is not None:
        base["incident_id"] = incident_id
    return _merge(base, overrides)


# ----------------------------------------------------------------------
# Transition bodies
# ----------------------------------------------------------------------
def transition(to_status: str, **extra: Any) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, extra)
