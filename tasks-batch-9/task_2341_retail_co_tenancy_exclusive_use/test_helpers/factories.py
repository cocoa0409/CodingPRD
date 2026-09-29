"""Request-payload builders.

Each builder returns the minimal valid body for one write endpoint.  Optional
parameters left at ``None`` are **omitted from the body entirely**, so tests
about declared defaults can simply not pass them.  Anything supplied through
``**overrides`` is applied last and is never pruned, which is how a test sends
an explicit ``null`` or an intentionally malformed value.
"""
from typing import Any, Dict, List, Optional

from .constants import DEFAULT_CLOCK_UTC


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


def _finish(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    body = _prune(payload)
    body.update(overrides)
    return body


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def clock_payload(to_iso8601: str = DEFAULT_CLOCK_UTC, **overrides: Any) -> Dict[str, Any]:
    return _finish({"to_iso8601": to_iso8601}, overrides)


# --------------------------------------------------------------------------
# Centers and tenants
# --------------------------------------------------------------------------
def center_payload(
    name: str = "Northgate Crossing",
    total_gla_sqft: int = 300000,
    occupancy_grace_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "name": name,
            "total_gla_sqft": total_gla_sqft,
            "occupancy_grace_days": occupancy_grace_days,
        },
        overrides,
    )


def tenant_payload(
    legal_name: str = "Harbor Goods LLC",
    notice_email: str = "notices@harborgoods.example",
    primary_use_code: str = "APPAREL",
    is_national_chain: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "legal_name": legal_name,
            "notice_email": notice_email,
            "primary_use_code": primary_use_code,
            "is_national_chain": is_national_chain,
        },
        overrides,
    )


def tenant_patch_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    return _finish({"status": status}, overrides)


# --------------------------------------------------------------------------
# Leases
# --------------------------------------------------------------------------
def lease_payload(
    tenant_id: str,
    suite_code: str = "A-100",
    gla_sqft: int = 3000,
    parcel_kind: str = "INLINE",
    primary_use_code: str = "APPAREL",
    base_rent_monthly_cents: int = 1000000,
    commencement_date: str = "2026-01-01",
    expiration_date: str = "2031-12-31",
    replacement_for_lease_id: Optional[str] = None,
    incidental_use_codes: Optional[List[str]] = None,
    projected_incidental_sales_pct: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "tenant_id": tenant_id,
            "suite_code": suite_code,
            "gla_sqft": gla_sqft,
            "parcel_kind": parcel_kind,
            "primary_use_code": primary_use_code,
            "base_rent_monthly_cents": base_rent_monthly_cents,
            "commencement_date": commencement_date,
            "expiration_date": expiration_date,
            "replacement_for_lease_id": replacement_for_lease_id,
            "incidental_use_codes": incidental_use_codes,
            "projected_incidental_sales_pct": projected_incidental_sales_pct,
        },
        overrides,
    )


def terminate_payload(
    termination_reason_code: str = "LANDLORD_RECAPTURE", **overrides: Any
) -> Dict[str, Any]:
    return _finish({"termination_reason_code": termination_reason_code}, overrides)


# --------------------------------------------------------------------------
# Co-tenancy conditions and anchor requirements
# --------------------------------------------------------------------------
def condition_payload(
    condition_kind: str = "ONGOING",
    measurement_basis: str = "GLA_PCT",
    required_occupancy_pct: Optional[float] = 70.0,
    required_open_store_count: Optional[int] = None,
    required_anchor_count: Optional[int] = None,
    grace_period_days: Optional[int] = None,
    cure_period_days: Optional[int] = None,
    remedy_type: str = "RENT_REDUCTION_ONLY",
    max_reduction_pct: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "condition_kind": condition_kind,
            "measurement_basis": measurement_basis,
            "required_occupancy_pct": required_occupancy_pct,
            "required_open_store_count": required_open_store_count,
            "required_anchor_count": required_anchor_count,
            "grace_period_days": grace_period_days,
            "cure_period_days": cure_period_days,
            "remedy_type": remedy_type,
            "max_reduction_pct": max_reduction_pct,
        },
        overrides,
    )


def store_count_condition_payload(
    required_open_store_count: int,
    condition_kind: str = "ONGOING",
    **overrides: Any,
) -> Dict[str, Any]:
    """A ``STORE_COUNT`` condition, which must not carry an occupancy percentage."""
    return condition_payload(
        condition_kind=condition_kind,
        measurement_basis="STORE_COUNT",
        required_occupancy_pct=None,
        required_open_store_count=required_open_store_count,
        **overrides,
    )


def anchor_requirement_payload(
    anchor_lease_id: str,
    substitution_allowed: Optional[bool] = None,
    min_substitute_gla_sqft: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "anchor_lease_id": anchor_lease_id,
            "substitution_allowed": substitution_allowed,
            "min_substitute_gla_sqft": min_substitute_gla_sqft,
        },
        overrides,
    )


def waive_payload(
    waiver_reason_code: str = "LANDLORD_ACCOMMODATION", **overrides: Any
) -> Dict[str, Any]:
    return _finish({"waiver_reason_code": waiver_reason_code}, overrides)


# --------------------------------------------------------------------------
# Exclusive-use clauses and radius restrictions
# --------------------------------------------------------------------------
def clause_payload(
    protected_use_codes: Optional[List[str]] = None,
    exclusivity_scope: str = "CENTER_WIDE",
    effective_from_date: str = "2026-01-01",
    effective_through_date: str = "2031-12-31",
    gla_carve_out_sqft: Optional[int] = None,
    incidental_sales_pct_cap: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "protected_use_codes": (
                ["COFFEE"] if protected_use_codes is None else protected_use_codes
            ),
            "exclusivity_scope": exclusivity_scope,
            "effective_from_date": effective_from_date,
            "effective_through_date": effective_through_date,
            "gla_carve_out_sqft": gla_carve_out_sqft,
            "incidental_sales_pct_cap": incidental_sales_pct_cap,
        },
        overrides,
    )


def radius_restriction_payload(
    radius_miles: float = 3.0,
    measured_from: str = "CENTER_BOUNDARY",
    recapture_basis: str = "GROSS_SALES",
    recapture_pct: float = 6.0,
    window_from_date: str = "2026-01-01",
    window_through_date: str = "2026-12-31",
    protected_baseline_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "radius_miles": radius_miles,
            "measured_from": measured_from,
            "recapture_basis": recapture_basis,
            "recapture_pct": recapture_pct,
            "window_from_date": window_from_date,
            "window_through_date": window_through_date,
            "protected_baseline_cents": protected_baseline_cents,
        },
        overrides,
    )


def radius_violation_report_payload(
    reported_offending_sales_cents: int,
    narrative: Optional[str] = None,
    cure_period_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "reported_offending_sales_cents": reported_offending_sales_cents,
            "narrative": narrative,
            "cure_period_days": cure_period_days,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Notices and disputes
# --------------------------------------------------------------------------
def notice_payload(
    violating_lease_id: str,
    notice_kind: str = "EXCLUSIVE_USE",
    clause_id: Optional[str] = None,
    narrative: Optional[str] = None,
    cure_period_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "violating_lease_id": violating_lease_id,
            "notice_kind": notice_kind,
            "clause_id": clause_id,
            "narrative": narrative,
            "cure_period_days": cure_period_days,
        },
        overrides,
    )


def cure_payload(
    cure_evidence_code: str = "USE_DISCONTINUED", **overrides: Any
) -> Dict[str, Any]:
    return _finish({"cure_evidence_code": cure_evidence_code}, overrides)


def withdraw_payload(
    withdrawal_reason_code: str = "LANDLORD_RECONSIDERED", **overrides: Any
) -> Dict[str, Any]:
    return _finish({"withdrawal_reason_code": withdrawal_reason_code}, overrides)


def dispute_payload(
    grounds_code: str = "NO_PROHIBITED_USE",
    narrative: str = "The suite has never conducted the protected use.",
    cure_extension_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "grounds_code": grounds_code,
            "narrative": narrative,
            "cure_extension_days": cure_extension_days,
        },
        overrides,
    )


def adjudicate_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _finish({"outcome": outcome}, overrides)


# --------------------------------------------------------------------------
# Measurements
# --------------------------------------------------------------------------
def measurement_payload(
    variant: str = "SNAPSHOT_STRICT",
    window_from_date: str = "2026-07-01",
    window_through_date: str = "2026-08-01",
    expected_center_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "variant": variant,
            "window_from_date": window_from_date,
            "window_through_date": window_through_date,
            "expected_center_version": expected_center_version,
        },
        overrides,
    )


def supersede_payload(
    supersede_reason_code: str = "REMEASURED", **overrides: Any
) -> Dict[str, Any]:
    return _finish({"supersede_reason_code": supersede_reason_code}, overrides)


# --------------------------------------------------------------------------
# Remedy elections
# --------------------------------------------------------------------------
def election_payload(
    election_kind: str = "RENT_REDUCTION",
    window_from_date: str = "2026-08-01",
    window_through_date: str = "2026-11-01",
    condition_id: Optional[str] = None,
    source_notice_id: Optional[str] = None,
    expected_lease_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "election_kind": election_kind,
            "window_from_date": window_from_date,
            "window_through_date": window_through_date,
            "condition_id": condition_id,
            "source_notice_id": source_notice_id,
            "expected_lease_version": expected_lease_version,
        },
        overrides,
    )


def rescind_payload(
    rescission_reason_code: str = "TENANT_WITHDREW", **overrides: Any
) -> Dict[str, Any]:
    return _finish({"rescission_reason_code": rescission_reason_code}, overrides)


# --------------------------------------------------------------------------
# Estoppel certificates
# --------------------------------------------------------------------------
def certificate_payload(
    measurement_id: Optional[str] = None,
    expedite_requested: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "measurement_id": measurement_id,
            "expedite_requested": expedite_requested,
        },
        overrides,
    )


def reject_certificate_payload(
    rejection_reason_code: str = "LENDER_DECLINED", **overrides: Any
) -> Dict[str, Any]:
    return _finish({"rejection_reason_code": rejection_reason_code}, overrides)


# --------------------------------------------------------------------------
# Redevelopment plans
# --------------------------------------------------------------------------
def plan_payload(
    plan_kind: str = "PAD_SALE",
    removed_gla_sqft: Optional[int] = None,
    pad_parcel_lease_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "plan_kind": plan_kind,
            "removed_gla_sqft": removed_gla_sqft,
            "pad_parcel_lease_id": pad_parcel_lease_id,
        },
        overrides,
    )


def record_plan_payload(
    consent_confirmed: Optional[bool] = None, **overrides: Any
) -> Dict[str, Any]:
    return _finish({"consent_confirmed": consent_confirmed}, overrides)


def abandon_plan_payload(
    abandon_reason_code: str = "PLAN_SHELVED", **overrides: Any
) -> Dict[str, Any]:
    return _finish({"abandon_reason_code": abandon_reason_code}, overrides)
