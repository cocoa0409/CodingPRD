"""Payload factories — one per resource, client-supplied input fields only."""

from typing import Any, Dict, List, Optional

from .constants import (
    ALL_ENDORSEMENTS,
    CORN_NO_1_FACTORS,
    DEFAULT_CERTIFIED_UNTIL,
    DEFAULT_LICENSE_EXPIRES_AT,
    SIX_CORN_DRAFTS,
    TEST_DEFAULTS,
)


def _payload(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides over defaults; a value of ``...`` drops the key entirely
    so tests can omit a field to exercise a required-field rule."""
    merged = dict(defaults)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v is not ...}


# --------------------------------------------------------------------------- #
# Service areas and fee schedules
# --------------------------------------------------------------------------- #

def service_area_payload(**overrides) -> Dict[str, Any]:
    return _payload(
        {
            "name": TEST_DEFAULTS["AREA_NAME_DESIGNATED"],
            "state_code": "TX",
            "authority_type": "DESIGNATED",
        },
        overrides,
    )


def designated_area_payload(**overrides) -> Dict[str, Any]:
    return service_area_payload(
        name=TEST_DEFAULTS["AREA_NAME_DESIGNATED"],
        state_code="TX",
        authority_type="DESIGNATED",
        **overrides,
    )


def delegated_area_payload(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": TEST_DEFAULTS["AREA_NAME_DELEGATED"],
        "state_code": "KS",
        "authority_type": "DELEGATED",
        "supervision_required": False,
    }
    defaults.update(overrides)
    return service_area_payload(**defaults)


def fee_schedule_payload(service_area_id: str, service_class: str, **overrides):
    return _payload(
        {
            "service_area_id": service_area_id,
            "service_class": service_class,
            "base_fee_cents": 10000,
            "effective_from": "2026-01-01T00:00:00Z",
        },
        overrides,
    )


# --------------------------------------------------------------------------- #
# Applicants
# --------------------------------------------------------------------------- #

def applicant_payload(**overrides) -> Dict[str, Any]:
    return _payload(
        {
            "name": "Prairie Grain Elevator LLC",
            "account_code": "ELEV-001",
            "contact_email": "billing@prairiegrain.example",
        },
        overrides,
    )


def payment_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    return _payload({"amount_cents": amount_cents}, overrides)


# --------------------------------------------------------------------------- #
# Inspectors
# --------------------------------------------------------------------------- #

def inspector_payload(service_area_id: str, **overrides) -> Dict[str, Any]:
    return _payload(
        {
            "service_area_id": service_area_id,
            "license_number": "L-1001",
            "full_name": "Dana Whitfield",
            "endorsements": list(ALL_ENDORSEMENTS),
            "license_expires_at": DEFAULT_LICENSE_EXPIRES_AT,
        },
        overrides,
    )


def training_record_payload(hours: int = 24, **overrides) -> Dict[str, Any]:
    return _payload(
        {"course_code": TEST_DEFAULTS["COURSE_CODE"], "hours": hours}, overrides
    )


def suspension_payload(reason: str = "Under investigation", **overrides):
    return _payload({"suspension_reason": reason}, overrides)


# --------------------------------------------------------------------------- #
# Equipment
# --------------------------------------------------------------------------- #

def equipment_payload(service_area_id: str, equipment_kind: str, **overrides):
    defaults: Dict[str, Any] = {
        "service_area_id": service_area_id,
        "equipment_kind": equipment_kind,
        "asset_code": "ASSET-1",
        "model": "Generic 1",
    }
    if equipment_kind == "SAMPLING_DEVICE":
        defaults["asset_code"] = "PROBE-1"
        defaults["model"] = TEST_DEFAULTS["SAMPLING_DEVICE_MODEL"]
    elif equipment_kind == "SCALE":
        defaults["asset_code"] = "SCALE-1"
        defaults["model"] = TEST_DEFAULTS["SCALE_MODEL"]
        defaults["capacity_lbs"] = TEST_DEFAULTS["SCALE_CAPACITY_LBS"]
        defaults["tolerance_lbs"] = TEST_DEFAULTS["SCALE_TOLERANCE_LBS"]
    elif equipment_kind == "PROTEIN_INSTRUMENT":
        defaults["asset_code"] = "NIR-1"
        defaults["model"] = TEST_DEFAULTS["PROTEIN_INSTRUMENT_MODEL"]
    return _payload(defaults, overrides)


def certify_payload(**overrides) -> Dict[str, Any]:
    return _payload({"certified_until": DEFAULT_CERTIFIED_UNTIL}, overrides)


def comparison_check_payload(
    instrument_id: str,
    inspector_id: str,
    reference_value_pct: float,
    instrument_reading_pct: float,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "instrument_id": instrument_id,
            "inspector_id": inspector_id,
            "reference_value_pct": reference_value_pct,
            "instrument_reading_pct": instrument_reading_pct,
        },
        overrides,
    )


# --------------------------------------------------------------------------- #
# Inspection requests and samples
# --------------------------------------------------------------------------- #

def inspection_request_payload(
    applicant_id: str, service_area_id: str, **overrides
) -> Dict[str, Any]:
    return _payload(
        {
            "applicant_id": applicant_id,
            "service_area_id": service_area_id,
            "commodity": "CORN",
            "point_of_service": "LOADING",
            "lot_identifier": "LOT-A1",
            "declared_quantity_bushels": 4000,
            "requested_services": ["GRADING"],
        },
        overrides,
    )


def sample_payload(
    inspection_request_id: str, sampling_device_id: str, inspector_id: str, **overrides
) -> Dict[str, Any]:
    return _payload(
        {
            "inspection_request_id": inspection_request_id,
            "sampling_device_id": sampling_device_id,
            "inspector_id": inspector_id,
            "seal_number": "SEAL-1",
            "portions_count": 3,
        },
        overrides,
    )


def break_seal_payload(reason: Optional[str] = "seal found cut on arrival", **overrides):
    return _payload({"reason": reason}, overrides)


# --------------------------------------------------------------------------- #
# Determinations
# --------------------------------------------------------------------------- #

def grading_result_payload(
    inspection_request_id: str,
    sample_id: str,
    inspector_id: str,
    factors: Optional[Dict[str, float]] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "inspection_request_id": inspection_request_id,
        "sample_id": sample_id,
        "inspector_id": inspector_id,
    }
    defaults.update(factors if factors is not None else CORN_NO_1_FACTORS)
    return _payload(defaults, overrides)


def protein_analysis_payload(
    inspection_request_id: str,
    sample_id: str,
    instrument_id: str,
    inspector_id: str,
    protein_pct_as_is: float = 34.60,
    instrument_moisture_pct: float = 11.20,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "inspection_request_id": inspection_request_id,
            "sample_id": sample_id,
            "instrument_id": instrument_id,
            "inspector_id": inspector_id,
            "protein_pct_as_is": protein_pct_as_is,
            "instrument_moisture_pct": instrument_moisture_pct,
        },
        overrides,
    )


def weighing_record_payload(
    inspection_request_id: str,
    scale_id: str,
    weigher_inspector_id: str,
    drafts: Optional[List[Dict[str, int]]] = None,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "inspection_request_id": inspection_request_id,
            "scale_id": scale_id,
            "weigher_inspector_id": weigher_inspector_id,
            "drafts": list(drafts) if drafts is not None else list(SIX_CORN_DRAFTS),
        },
        overrides,
    )


def supervise_payload(supervisor_inspector_id: str, **overrides) -> Dict[str, Any]:
    return _payload({"supervisor_inspector_id": supervisor_inspector_id}, overrides)


# --------------------------------------------------------------------------- #
# Certificates, appeals, votes
# --------------------------------------------------------------------------- #

def certificate_payload(
    inspection_request_id: str,
    issuing_inspector_id: str,
    certificate_type: str = "GRADE",
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "inspection_request_id": inspection_request_id,
            "issuing_inspector_id": issuing_inspector_id,
            "certificate_type": certificate_type,
        },
        overrides,
    )


def appeal_payload(
    certificate_id: str,
    applicant_id: str,
    expected_certificate_version: int,
    appeal_type: str = "APPEAL",
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "certificate_id": certificate_id,
            "applicant_id": applicant_id,
            "appeal_type": appeal_type,
            "expected_certificate_version": expected_certificate_version,
        },
        overrides,
    )


def appeal_vote_payload(
    appeal_id: str, inspector_id: str, vote: str, expected_appeal_version: int, **overrides
) -> Dict[str, Any]:
    return _payload(
        {
            "appeal_id": appeal_id,
            "inspector_id": inspector_id,
            "vote": vote,
            "expected_appeal_version": expected_appeal_version,
        },
        overrides,
    )


def assign_sample_payload(sample_id: str, **overrides) -> Dict[str, Any]:
    return _payload({"sample_id": sample_id}, overrides)


def dismiss_payload(reason: str = "withdrawn by the applicant", **overrides):
    return _payload({"reason": reason}, overrides)


# --------------------------------------------------------------------------- #
# Vessel watches
# --------------------------------------------------------------------------- #

def vessel_watch_payload(
    inspection_request_id: str,
    supervisor_inspector_id: str,
    window_start_at: str,
    window_end_at: str,
    holds_declared: int = 3,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "inspection_request_id": inspection_request_id,
            "supervisor_inspector_id": supervisor_inspector_id,
            "vessel_name": "MV Gulf Trader",
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "holds_declared": holds_declared,
        },
        overrides,
    )


def close_watch_payload(holds_supervised: int, stowage_certified: bool, **overrides):
    return _payload(
        {"holds_supervised": holds_supervised, "stowage_certified": stowage_certified},
        overrides,
    )


def clock_payload(current_utc: str, **overrides) -> Dict[str, Any]:
    return _payload({"current_utc": current_utc}, overrides)
