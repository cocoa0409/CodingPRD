"""
Payload factories: valid-by-default request bodies with keyword overrides.

Every factory returns a dict whose fields are exactly the PRD's payload field
names. Passing `field=None` removes that field from the payload, which is how
tests probe required-field handling.
"""

from typing import Any, Dict

from .types import (
    AdjudicationDecision,
    AuditDecision,
    DefectType,
    FilingType,
    InclusionMode,
    OutreachChannel,
    OutreachOutcome,
    RateType,
    RegionCode,
    RiskSeverity,
    SaleStatus,
    WaveType,
)


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel `None` used to omit a field."""
    return {k: v for k, v in payload.items() if v is not None}


# ─── Recall campaign ──────────────────────────────────

def campaign_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "campaign_number": "26V-101",
        "defect_type": DefectType.SAFETY_DEFECT,
        "defect_description": "Driver airbag inflator may rupture on deployment",
        "risk_severity": RiskSeverity.MODERATE,
    }
    payload.update(overrides)
    return _clean(payload)


def defect_determination_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"defect_determination_date": "2026-08-03T09:00:00Z"}
    payload.update(overrides)
    return _clean(payload)


def interim_advisory_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "stop_sale": False,
        "do_not_drive": True,
        "justification": "Owners advised pending remedy availability",
    }
    payload.update(overrides)
    return _clean(payload)


def remedy_release_payload(labor_operation_id: str, expected_campaign_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "remedy_description": "Replace inflator with revised propellant module",
        "labor_operation_id": labor_operation_id,
        "expected_campaign_version": expected_campaign_version,
    }
    payload.update(overrides)
    return _clean(payload)


def close_campaign_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"closure_note": "All statutory obligations satisfied"}
    payload.update(overrides)
    return _clean(payload)


# ─── Build records ────────────────────────────────────

def vehicle_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "vin": "1HGCM82633A004352",
        "plant_code": "PLT1",
        "model_code": "MDLA",
        "model_year": 2024,
        "production_date": "2024-03-15",
        "suspect_part_number": 1500,
        "region_code": RegionCode.NE,
        "sale_status": SaleStatus.SOLD,
        "owner_name": "Ann Vega",
    }
    payload.update(overrides)
    return _clean(payload)


def vehicle_update_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return _clean(payload)


# ─── Population rules ─────────────────────────────────

def population_rule_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "inclusion_mode": InclusionMode.INCLUDE,
        "plant_code": "PLT1",
        "model_code": "MDLA",
        "model_year": 2024,
        "production_start_date": "2024-01-01",
        "production_end_date": "2024-07-01",
        "part_number_low": 1000,
        "part_number_high": 1999,
    }
    payload.update(overrides)
    return _clean(payload)


# ─── Regulatory filings ───────────────────────────────

def defect_notice_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "filing_type": FilingType.DEFECT_NOTICE,
        "narrative": "Part 573 defect information report for this campaign",
    }
    payload.update(overrides)
    return _clean(payload)


def quarterly_filing_payload(report_period: str = "2026Q3", **overrides: Any) -> Dict[str, Any]:
    payload = {
        "filing_type": FilingType.QUARTERLY,
        "report_period": report_period,
        "narrative": "Quarterly completion report",
    }
    payload.update(overrides)
    return _clean(payload)


def amendment_filing_payload(report_period: str = "2026Q3", **overrides: Any) -> Dict[str, Any]:
    payload = {
        "filing_type": FilingType.AMENDMENT,
        "report_period": report_period,
        "narrative": "Amendment correcting a stale quarterly snapshot",
    }
    payload.update(overrides)
    return _clean(payload)


# ─── Notification waves ───────────────────────────────

def notification_wave_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "wave_type": WaveType.REMEDY,
        "target_region_code": RegionCode.NE,
        "scheduled_mail_date": "2026-08-03",
    }
    payload.update(overrides)
    return _clean(payload)


def cancel_wave_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"cancel_reason": "Region deferred to a later drop"}
    payload.update(overrides)
    return _clean(payload)


# ─── Dealers ──────────────────────────────────────────

def dealer_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "dealer_code": "D-NE-01",
        "name": "Northeast Motors",
        "region_code": RegionCode.NE,
        "labor_rate_per_hour": 138.74,
        "monthly_repair_capacity": 40,
    }
    payload.update(overrides)
    return _clean(payload)


def suspend_dealer_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"suspension_reason": "Warranty claim irregularities under review"}
    payload.update(overrides)
    return _clean(payload)


# ─── Remedy parts and labor operations ────────────────

def remedy_part_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "part_number": "P-88123",
        "unit_cost": 21.90,
        "total_procured_qty": 100,
    }
    payload.update(overrides)
    return _clean(payload)


def labor_operation_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "labor_op_code": "R101-01",
        "description": "Replace driver airbag inflator",
        "flat_hours": 1.10,
        "rate_type": RateType.WARRANTY,
        "effective_from": "2026-08-01",
        "effective_to": "2027-12-31",
    }
    payload.update(overrides)
    return _clean(payload)


# ─── Parts allocations ────────────────────────────────

def parts_allocation_payload(
    remedy_part_id: str, dealer_id: str, expected_part_version: int, requested_qty: int = 2, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "remedy_part_id": remedy_part_id,
        "dealer_id": dealer_id,
        "requested_qty": requested_qty,
        "expected_part_version": expected_part_version,
    }
    payload.update(overrides)
    return _clean(payload)


def revoke_allocation_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"revoke_note": "Returned to the central pool"}
    payload.update(overrides)
    return _clean(payload)


# ─── Appointments, claims and audit ───────────────────

def schedule_payload(dealer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "dealer_id": dealer_id,
        "scheduled_repair_date": "2026-08-20",
    }
    payload.update(overrides)
    return _clean(payload)


def repair_claim_payload(
    affected_vehicle_id: str,
    dealer_id: str,
    labor_operation_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "affected_vehicle_id": affected_vehicle_id,
        "dealer_id": dealer_id,
        "labor_operation_id": labor_operation_id,
        "repair_date": "2026-08-03",
        "claimed_labor_hours": 1.10,
        "parts_used_qty": 1,
    }
    payload.update(overrides)
    return _clean(payload)


def audit_payload(decision: str = AuditDecision.APPROVE, **overrides: Any) -> Dict[str, Any]:
    payload = {"decision": decision, "audit_note": "Approved"}
    payload.update(overrides)
    return _clean(payload)


def reverse_claim_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"reversal_reason": "Post-audit finding: repair not substantiated"}
    payload.update(overrides)
    return _clean(payload)


# ─── Outreach attempts ────────────────────────────────

def outreach_attempt_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "channel": OutreachChannel.PHONE,
        "outcome": OutreachOutcome.NO_RESPONSE,
        "note": "Left voicemail for the registered owner",
    }
    payload.update(overrides)
    return _clean(payload)


# ─── Owner reimbursements ─────────────────────────────

def owner_reimbursement_payload(campaign_id: str, vehicle_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "campaign_id": campaign_id,
        "vehicle_id": vehicle_id,
        "invoice_date": "2026-07-15",
        "invoice_amount": 412.75,
        "labor_hours_claimed": 1.30,
    }
    payload.update(overrides)
    return _clean(payload)


def request_documents_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"requested_items": "Itemised repair invoice and proof of payment"}
    payload.update(overrides)
    return _clean(payload)


def resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return _clean(payload)


def adjudicate_payload(decision: str = AdjudicationDecision.APPROVE, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision == AdjudicationDecision.DENY:
        payload["denial_reason"] = "Invoice falls outside the reimbursement window"
    payload.update(overrides)
    return _clean(payload)


# ─── Logical clock ────────────────────────────────────

def clock_payload(to_iso8601: str = "2026-08-03T09:00:00Z", **overrides: Any) -> Dict[str, Any]:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return _clean(payload)
