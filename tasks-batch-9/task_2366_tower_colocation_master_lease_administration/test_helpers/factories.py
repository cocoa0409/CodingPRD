"""Request-payload builders with PRD-legal defaults.

Each builder returns a plain dict and accepts keyword overrides, so a test can
say exactly the one field it cares about and let everything else default to a
value the PRD accepts. Passing ``None`` as an override does not drop the key —
use ``payload.pop(...)`` when a test needs a field genuinely absent.
"""

import itertools
import string
from typing import Any, Dict, Optional

_carrier_code_counter = itertools.count(1)
_site_name_counter = itertools.count(1)

_ALPHABET = string.ascii_uppercase


def unique_carrier_code() -> str:
    """A fresh 3-to-12 character uppercase alphanumeric carrier code."""
    n = next(_carrier_code_counter)
    return f"CC{n:04d}"


def unique_site_name(prefix: str = "Site") -> str:
    """A fresh non-blank site name inside the 1..120 character range."""
    return f"{prefix} {next(_site_name_counter):04d}"


# ─── Towers (PRD §3.1) ───────────────────────────────────────────────────────


def tower_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_name": unique_site_name("Tower"),
        "structure_type": "MONOPOLE",
        "rated_capacity_load_units": 10000,
        "min_colocation_elevation_ft": 50,
        "max_elevation_ft": 300,
        "ground_space_total_sqft": 20000,
        "baseline_reserved_load_units": 0,
        "baseline_reserved_ground_sqft": 0,
    }
    payload.update(overrides)
    return payload


# ─── Landlords (PRD §3.1) ────────────────────────────────────────────────────


def landlord_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Ridge Land LLC",
        "remit_contact_email": "pay@ridge.example",
        "w9_on_file": True,
    }
    payload.update(overrides)
    return payload


# ─── Ground leases (PRD §3.2) ────────────────────────────────────────────────


def ground_lease_payload(tower_id: str, landlord_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tower_id": tower_id,
        "landlord_id": landlord_id,
        "base_monthly_rent_cents": 400000,
        "escalator_pct": 2.5,
        "commencement_date": "2020-06-01",
        "term_end_date": "2031-05-31",
        "renewal_option_count": 2,
        "renewal_term_years": 5,
        "buyout_price_cents": 12000000,
    }
    payload.update(overrides)
    return payload


def landlord_payment_payload(
    ground_lease_id: str, period_start_date: str, period_end_date: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ground_lease_id": ground_lease_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
    payload.update(overrides)
    return payload


# ─── Tenants (PRD §3.3) ──────────────────────────────────────────────────────


def tenant_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Alpha Wireless",
        "carrier_code": unique_carrier_code(),
    }
    payload.update(overrides)
    return payload


def tenant_payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ─── Master lease agreements (PRD §3.3) ──────────────────────────────────────


def master_lease_agreement_payload(tenant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "base_monthly_rent_cents": 250000,
        "escalator_pct": 3.5,
        "initial_term_years": 10,
        "renewal_terms_count": 2,
        "expires_on": "2036-07-31",
    }
    payload.update(overrides)
    return payload


# ─── Colocation applications and equipment lines (PRD §3.4) ──────────────────


def colocation_application_payload(
    tower_id: str, master_lease_agreement_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tower_id": tower_id,
        "master_lease_agreement_id": master_lease_agreement_id,
        "requested_elevation_bottom_ft": 150,
        "requested_elevation_top_ft": 190,
        "requested_ground_space_sqft": 500,
    }
    payload.update(overrides)
    return payload


def equipment_line_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "equipment_type": "ANTENNA",
        "model_code": "AX-60",
        "quantity": 3,
        "unit_weight_lbs": 60,
        "wind_area_sqft": 8,
        "mount_elevation_ft": 125,
    }
    payload.update(overrides)
    return payload


# ─── Structural analyses (PRD §3.5) ──────────────────────────────────────────


def structural_analysis_payload(
    colocation_application_id: str,
    expected_tower_version: int,
    variant: str = "PRELIMINARY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "colocation_application_id": colocation_application_id,
        "variant": variant,
        "expected_tower_version": expected_tower_version,
    }
    payload.update(overrides)
    return payload


def quotation_payload(modification_construction_cost_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "modification_construction_cost_cents": modification_construction_cost_cents
    }
    payload.update(overrides)
    return payload


# ─── Site amendments (PRD §3.7) ──────────────────────────────────────────────


def site_amendment_payload(
    master_lease_agreement_id: str,
    tower_id: str,
    colocation_application_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "master_lease_agreement_id": master_lease_agreement_id,
        "tower_id": tower_id,
        "colocation_application_id": colocation_application_id,
        "effective_date": "2026-08-01",
        "term_end_date": "2031-05-31",
        "base_monthly_rent_cents": 250000,
        "escalator_pct": 3.5,
        "restoration_deposit_cents": 0,
    }
    payload.update(overrides)
    return payload


def execute_payload(signature_received: bool = True, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"signature_received": signature_received}
    payload.update(overrides)
    return payload


def billing_status_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


def complete_decommission_payload(
    restoration_confirmed: bool = True, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"restoration_confirmed": restoration_confirmed}
    payload.update(overrides)
    return payload


# ─── Modification projects and cost shares (PRD §3.6) ────────────────────────


def modification_project_payload(
    tower_id: str, originating_analysis_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tower_id": tower_id,
        "originating_analysis_id": originating_analysis_id,
        "construction_window_start_date": "2026-09-01",
        "construction_window_end_date": "2026-10-31",
        "allocation_basis": "PRO_RATA_LOAD",
    }
    payload.update(overrides)
    return payload


def reallocate_payload(
    expected_modification_project_version: int,
    allocation_basis: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_modification_project_version": expected_modification_project_version
    }
    if allocation_basis is not None:
        payload["allocation_basis"] = allocation_basis
    payload.update(overrides)
    return payload


def certify_completion_payload(added_capacity_load_units: float, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"added_capacity_load_units": added_capacity_load_units}
    payload.update(overrides)
    return payload


def cancel_project_payload(cancellation_reason: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


def decline_cost_share_payload(decline_reason: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decline_reason": decline_reason}
    payload.update(overrides)
    return payload


# ─── Equipment audits and findings (PRD §3.9) ────────────────────────────────


def equipment_audit_payload(tower_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tower_id": tower_id,
        "audit_date": "2026-07-31",
        "basis": "INSTALL_DATE_BASIS",
    }
    payload.update(overrides)
    return payload


def audit_finding_payload(tenant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "description": "unauthorized microwave dish at 230 ft",
        "observed_load_units": 3400,
        "installed_on_date": "2023-02-15",
        "mount_elevation_ft": 230,
    }
    payload.update(overrides)
    return payload


# ─── Logical clock (PRD §2.4) ────────────────────────────────────────────────


def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ─── Rejection / revision notes ──────────────────────────────────────────────


def reject_payload(rejection_reason: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


def revise_payload(revision_note: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if revision_note is not None:
        payload["revision_note"] = revision_note
    payload.update(overrides)
    return payload
