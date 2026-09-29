"""Request payload factories.

Each factory builds only the caller supplied fields of one write endpoint, so
that a test can pass ``None`` for an optional field and let the server apply its
own declared default.
"""

import itertools
from typing import Any, Dict, List, Optional

from .types import (
    ConsentOutcome,
    DeliveryChannel,
    Material,
    PublicationBasis,
    SampleType,
    Side,
    SourceKind,
    SourceType,
    VerificationMethod,
)

_pwsid_counter = itertools.count(1)
_address_counter = itertools.count(1)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys whose value was left unset by the caller."""
    return {key: value for key, value in payload.items() if value is not None}


def unique_pwsid(prefix: str = "IL2999") -> str:
    """A pwsid that will not collide with another one minted in this process."""
    return f"{prefix}{next(_pwsid_counter):03d}"


def unique_address_label(prefix: str = "Test Address") -> str:
    """An address label that will not collide with another one in this process."""
    return f"{prefix} {next(_address_counter)}"


# ---------------------------------------------------------------------------
# WaterSystem
# ---------------------------------------------------------------------------


def water_system_payload(
    pwsid: str,
    system_name: str = "Test Water",
    compliance_deadline_date: str = "2027-10-16",
    baseline_lead_and_grr_count: Optional[int] = None,
    disadvantaged_tract_codes: Optional[List[str]] = None,
    funding_mode: Optional[str] = None,
    cct_optimization_status: Optional[str] = None,
    cct_orthophosphate_mg_l: Optional[float] = None,
    cct_target_ph: Optional[float] = None,
) -> Dict[str, Any]:
    """Body for POST /lsl/water-systems."""
    return _prune(
        {
            "pwsid": pwsid,
            "system_name": system_name,
            "compliance_deadline_date": compliance_deadline_date,
            "baseline_lead_and_grr_count": baseline_lead_and_grr_count,
            "disadvantaged_tract_codes": disadvantaged_tract_codes,
            "funding_mode": funding_mode,
            "cct_optimization_status": cct_optimization_status,
            "cct_orthophosphate_mg_l": cct_orthophosphate_mg_l,
            "cct_target_ph": cct_target_ph,
        }
    )


def advance_inventory_status_payload(target_status: str) -> Dict[str, Any]:
    """Body for POST /lsl/water-systems/{id}/advance-inventory-status."""
    return {"target_status": target_status}


def funding_policy_payload(funding_mode: str) -> Dict[str, Any]:
    """Body for PATCH /lsl/water-systems/{id}/funding-policy."""
    return {"funding_mode": funding_mode}


def corrosion_control_payload(
    cct_optimization_status: str,
    cct_orthophosphate_mg_l: Optional[float] = None,
    cct_target_ph: Optional[float] = None,
) -> Dict[str, Any]:
    """Body for PATCH /lsl/water-systems/{id}/corrosion-control."""
    return _prune(
        {
            "cct_optimization_status": cct_optimization_status,
            "cct_orthophosphate_mg_l": cct_orthophosphate_mg_l,
            "cct_target_ph": cct_target_ph,
        }
    )


# ---------------------------------------------------------------------------
# ServiceLine
# ---------------------------------------------------------------------------


def service_line_payload(
    water_system_id: str,
    address_label: str = "101 Elm St",
    census_tract_code: str = "17031-9900",
    street_project_id: Optional[str] = None,
    serves_sensitive_population: Optional[bool] = None,
    interior_diameter_mm: Optional[float] = None,
    total_length_m: Optional[float] = None,
) -> Dict[str, Any]:
    """Body for POST /lsl/service-lines."""
    return _prune(
        {
            "water_system_id": water_system_id,
            "address_label": address_label,
            "census_tract_code": census_tract_code,
            "street_project_id": street_project_id,
            "serves_sensitive_population": serves_sensitive_population,
            "interior_diameter_mm": interior_diameter_mm,
            "total_length_m": total_length_m,
        }
    )


def classification_override_payload(
    expected_service_line_version: int,
    side: str,
    asserted_material: str,
    justification: str = "Field crew resurveyed the tap.",
) -> Dict[str, Any]:
    """Body for POST /lsl/service-lines/{id}/classification-overrides."""
    return {
        "expected_service_line_version": expected_service_line_version,
        "side": side,
        "asserted_material": asserted_material,
        "justification": justification,
    }


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------


def evidence_item_payload(
    service_line_id: str,
    source_type: str = SourceType.HISTORIC_RECORD,
    side: str = Side.UTILITY,
    observed_material: str = Material.LEAD,
    observed_at: str = "2026-06-01T00:00:00Z",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Body for POST /lsl/evidence-items."""
    return _prune(
        {
            "service_line_id": service_line_id,
            "source_type": source_type,
            "side": side,
            "observed_material": observed_material,
            "observed_at": observed_at,
            "notes": notes,
        }
    )


def retract_evidence_payload(reason: str = "RECORD_VOIDED") -> Dict[str, Any]:
    """Body for POST /lsl/evidence-items/{id}/retract."""
    return {"reason": reason}


# ---------------------------------------------------------------------------
# VerificationCrew and VerificationAppointment
# ---------------------------------------------------------------------------


def verification_crew_payload(
    water_system_id: str,
    crew_name: str = "Crew Alpha",
    shift_start_utc_time: str = "08:00",
    shift_end_utc_time: str = "18:00",
    daily_appointment_capacity: int = 5,
    certified_methods: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Body for POST /lsl/verification-crews."""
    return {
        "water_system_id": water_system_id,
        "crew_name": crew_name,
        "shift_start_utc_time": shift_start_utc_time,
        "shift_end_utc_time": shift_end_utc_time,
        "daily_appointment_capacity": daily_appointment_capacity,
        "certified_methods": list(certified_methods)
        if certified_methods is not None
        else [VerificationMethod.POTHOLE],
    }


def crew_status_payload(status: str) -> Dict[str, Any]:
    """Body for POST /lsl/verification-crews/{id}/status."""
    return {"status": status}


def verification_appointment_payload(
    service_line_id: str,
    crew_id: str,
    method: str = VerificationMethod.POTHOLE,
    window_start_utc: str = "2026-08-05T09:00:00Z",
    window_end_utc: str = "2026-08-05T10:00:00Z",
) -> Dict[str, Any]:
    """Body for POST /lsl/verification-appointments."""
    return {
        "service_line_id": service_line_id,
        "crew_id": crew_id,
        "method": method,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }


def appointment_complete_payload(
    observed_side: str = Side.UTILITY, observed_material: str = Material.COPPER
) -> Dict[str, Any]:
    """Body for POST /lsl/verification-appointments/{id}/complete."""
    return {"observed_side": observed_side, "observed_material": observed_material}


def no_access_payload(barrier_reason: str) -> Dict[str, Any]:
    """Body for POST /lsl/verification-appointments/{id}/no-access."""
    return {"barrier_reason": barrier_reason}


def reschedule_payload(window_start_utc: str, window_end_utc: str) -> Dict[str, Any]:
    """Body for POST /lsl/verification-appointments/{id}/reschedule."""
    return {"window_start_utc": window_start_utc, "window_end_utc": window_end_utc}


# ---------------------------------------------------------------------------
# SamplingBatch
# ---------------------------------------------------------------------------


def sampling_batch_payload(
    water_system_id: str, stratum_code: str = "STR-A", stratum_line_count: int = 20
) -> Dict[str, Any]:
    """Body for POST /lsl/sampling-batches."""
    return {
        "water_system_id": water_system_id,
        "stratum_code": stratum_code,
        "stratum_line_count": stratum_line_count,
    }


def sample_payload(
    service_line_id: str,
    lead_ppb: float,
    collected_at: str,
    sample_type: str = SampleType.FIRST_DRAW,
) -> Dict[str, Any]:
    """Body for POST /lsl/sampling-batches/{id}/samples."""
    return {
        "service_line_id": service_line_id,
        "lead_ppb": lead_ppb,
        "collected_at": collected_at,
        "sample_type": sample_type,
    }


def invalidate_sample_payload(sample_seq: int, reason: str) -> Dict[str, Any]:
    """Body for POST /lsl/sampling-batches/{id}/invalidate-sample."""
    return {"sample_seq": sample_seq, "reason": reason}


def reopen_batch_payload(reason: str = "RESAMPLE_ROUND_2") -> Dict[str, Any]:
    """Body for POST /lsl/sampling-batches/{id}/reopen."""
    return {"reason": reason}


# ---------------------------------------------------------------------------
# InventoryPublication
# ---------------------------------------------------------------------------


def inventory_publication_payload(
    water_system_id: str,
    expected_water_system_version: int,
    basis: str = PublicationBasis.RECORDS,
    reporting_period_label: str = "2026-H2",
) -> Dict[str, Any]:
    """Body for POST /lsl/inventory-publications."""
    return {
        "water_system_id": water_system_id,
        "basis": basis,
        "reporting_period_label": reporting_period_label,
        "expected_water_system_version": expected_water_system_version,
    }


# ---------------------------------------------------------------------------
# CustomerNotification
# ---------------------------------------------------------------------------


def deliver_notification_payload(
    delivered_at: str, delivery_channel: str = DeliveryChannel.MAIL
) -> Dict[str, Any]:
    """Body for POST /lsl/customer-notifications/{id}/deliver."""
    return {"delivery_channel": delivery_channel, "delivered_at": delivered_at}


def acknowledge_notification_payload(acknowledged_at: str) -> Dict[str, Any]:
    """Body for POST /lsl/customer-notifications/{id}/acknowledge."""
    return {"acknowledged_at": acknowledged_at}


def return_notification_payload(return_reason: str) -> Dict[str, Any]:
    """Body for POST /lsl/customer-notifications/{id}/return."""
    return {"return_reason": return_reason}


# ---------------------------------------------------------------------------
# ReplacementOrder
# ---------------------------------------------------------------------------


def replacement_order_payload(
    service_line_id: str,
    estimated_cost_cents: int = 100000,
    excavation_start_date: str = "2026-08-10",
    excavation_end_date: str = "2026-08-11",
    street_project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Body for POST /lsl/replacement-orders."""
    return _prune(
        {
            "service_line_id": service_line_id,
            "estimated_cost_cents": estimated_cost_cents,
            "excavation_start_date": excavation_start_date,
            "excavation_end_date": excavation_end_date,
            "street_project_id": street_project_id,
        }
    )


def consent_response_payload(
    outcome: str = ConsentOutcome.GRANTED, barrier_reason: Optional[str] = None
) -> Dict[str, Any]:
    """Body for POST /lsl/replacement-orders/{id}/consent-response."""
    return _prune({"outcome": outcome, "barrier_reason": barrier_reason})


def schedule_order_payload(
    excavation_start_date: str, excavation_end_date: str
) -> Dict[str, Any]:
    """Body for POST /lsl/replacement-orders/{id}/schedule."""
    return {
        "excavation_start_date": excavation_start_date,
        "excavation_end_date": excavation_end_date,
    }


def complete_order_payload(completed_at: str, replaced_sides: List[str]) -> Dict[str, Any]:
    """Body for POST /lsl/replacement-orders/{id}/complete."""
    return {"completed_at": completed_at, "replaced_sides": list(replaced_sides)}


def cancel_order_payload(reason: str) -> Dict[str, Any]:
    """Body for POST /lsl/replacement-orders/{id}/cancel."""
    return {"reason": reason}


# ---------------------------------------------------------------------------
# StreetProject
# ---------------------------------------------------------------------------


def street_project_payload(
    water_system_id: str,
    project_name: str = "Elm St Resurfacing",
    moratorium_start_date: str = "2026-12-01",
    moratorium_end_date: str = "2026-12-31",
    paving_start_date: str = "2027-06-01",
    max_concurrent_excavations: Optional[int] = None,
) -> Dict[str, Any]:
    """Body for POST /lsl/street-projects."""
    return _prune(
        {
            "water_system_id": water_system_id,
            "project_name": project_name,
            "moratorium_start_date": moratorium_start_date,
            "moratorium_end_date": moratorium_end_date,
            "paving_start_date": paving_start_date,
            "max_concurrent_excavations": max_concurrent_excavations,
        }
    )


# ---------------------------------------------------------------------------
# FundingSource
# ---------------------------------------------------------------------------


def funding_source_payload(
    water_system_id: str,
    authorized_cents: int = 200000,
    priority_rank: int = 1,
    source_kind: str = SourceKind.STATE_REVOLVING_FUND,
    max_share_pct: Optional[float] = None,
    equity_required_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Body for POST /lsl/funding-sources."""
    return _prune(
        {
            "water_system_id": water_system_id,
            "source_kind": source_kind,
            "authorized_cents": authorized_cents,
            "priority_rank": priority_rank,
            "max_share_pct": max_share_pct,
            "equity_required_pct": equity_required_pct,
        }
    )


def funding_source_status_payload(status: str) -> Dict[str, Any]:
    """Body for POST /lsl/funding-sources/{id}/status."""
    return {"status": status}


# ---------------------------------------------------------------------------
# ProgressReport
# ---------------------------------------------------------------------------


def progress_report_payload(
    water_system_id: str, period_start_date: str, period_end_date: str
) -> Dict[str, Any]:
    """Body for POST /lsl/progress-reports."""
    return {
        "water_system_id": water_system_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
