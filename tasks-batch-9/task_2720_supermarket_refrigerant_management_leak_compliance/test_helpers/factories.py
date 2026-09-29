"""
Request-payload builders.

Each builder returns a payload that is legal under the PRD unless a test
overrides a field on purpose, so a test can state only the one field it is
probing. Nothing here is derived: every default is a literal the PRD or a
scenario needs, and computed fields are never sent.
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_AUGUST_1
from .types import (
    CATEGORY_COMMERCIAL_REFRIGERATION,
    CERT_TYPE_II,
    CERT_UNIVERSAL,
    DETECTION_MANUAL_INSPECTION,
    LEAKED_CHARGE_BASED,
    METHOD_ROLLING_AVERAGE,
    ODS_HFC,
    ODS_NATURAL,
    PHASEDOWN_ALLOWED,
    PHASEDOWN_RESTRICTED_NEW_EQUIPMENT,
    PLAN_RETROFIT,
    PRESSURE_HIGH,
    PRESSURE_LOW,
    REASON_PARTS_UNAVAILABLE,
    REGION_WEST,
    REPORT_ANNUAL_LEAK_RATE,
    RESULT_PASS,
    SERVICE_ADD_REFRIGERANT,
    SEVERITY_MINOR,
)


def _payload(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge overrides into a default payload. A field set to the sentinel
    ``_OMIT`` is removed entirely, which is how a test drops a required field.
    """
    merged = dict(base)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v is not _OMIT}


class _Omit:
    """Sentinel: remove this key from the payload rather than send null."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "_OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Logical clock (§2.4) ─────────────────────────────────────────────


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ─── Store (§3.1) ─────────────────────────────────────────────────────


def store_payload(**overrides) -> Dict[str, Any]:
    """The reference store: Northgate Market, NG-001, CA, WEST."""
    return _payload(
        {
            "name": "Northgate Market",
            "store_code": "NG-001",
            "state_code": "CA",
            "region": REGION_WEST,
        },
        overrides,
    )


def second_store_payload(**overrides) -> Dict[str, Any]:
    """A second store, for the cross-store and store-scope scenarios."""
    return _payload(
        {
            "name": "Southgate Market",
            "store_code": "SG-002",
            "state_code": "AZ",
            "region": REGION_WEST,
        },
        overrides,
    )


# ─── Refrigerant types (§3.1) ─────────────────────────────────────────


def refrigerant_type_payload(**overrides) -> Dict[str, Any]:
    return _payload(
        {
            "name": "R-404A",
            "gwp": 3922,
            "pressure_class": PRESSURE_HIGH,
            "ods_class": ODS_HFC,
            "phasedown_status": PHASEDOWN_RESTRICTED_NEW_EQUIPMENT,
        },
        overrides,
    )


def r404a_payload(**overrides) -> Dict[str, Any]:
    """R-404A: gwp 3922, HIGH pressure, HFC, restricted for new equipment."""
    return refrigerant_type_payload(**overrides)


def r448a_payload(**overrides) -> Dict[str, Any]:
    """R-448A: gwp 1387, HIGH pressure, HFC, allowed — the retrofit target."""
    return _payload(
        {
            "name": "R-448A",
            "gwp": 1387,
            "pressure_class": PRESSURE_HIGH,
            "ods_class": ODS_HFC,
            "phasedown_status": PHASEDOWN_ALLOWED,
        },
        overrides,
    )


def r245fa_payload(**overrides) -> Dict[str, Any]:
    """R-245fa: gwp 1030, LOW pressure, HFC, allowed."""
    return _payload(
        {
            "name": "R-245fa",
            "gwp": 1030,
            "pressure_class": PRESSURE_LOW,
            "ods_class": ODS_HFC,
            "phasedown_status": PHASEDOWN_ALLOWED,
        },
        overrides,
    )


def r290_payload(**overrides) -> Dict[str, Any]:
    """R-290 propane: gwp 3, HIGH pressure, NATURAL, allowed."""
    return _payload(
        {
            "name": "R-290",
            "gwp": 3,
            "pressure_class": PRESSURE_HIGH,
            "ods_class": ODS_NATURAL,
            "phasedown_status": PHASEDOWN_ALLOWED,
        },
        overrides,
    )


# ─── Systems (§3.1) ───────────────────────────────────────────────────


def system_payload(store_id: str, refrigerant_type_id: str, **overrides) -> Dict[str, Any]:
    """
    The reference system: a 100.0 lb commercial refrigeration rack holding 80.0
    lbs, installed 2025-01-15, on the ROLLING_AVERAGE leak-rate method.
    """
    return _payload(
        {
            "store_id": store_id,
            "refrigerant_type_id": refrigerant_type_id,
            "system_category": CATEGORY_COMMERCIAL_REFRIGERATION,
            "full_charge_lbs": 100.0,
            "initial_charge_lbs": 80.0,
            "installed_on": "2025-01-15T00:00:00Z",
            "leak_rate_method": METHOD_ROLLING_AVERAGE,
        },
        overrides,
    )


def empty_system_payload(store_id: str, refrigerant_type_id: str, **overrides) -> Dict[str, Any]:
    """
    A 60.0 lb regulated system commissioned with no charge at all, installed
    2025-03-01. With `current_charge_lbs` already 0.0 it satisfies the
    charge precondition of the retirement action without any recovery work.
    """
    return system_payload(
        store_id,
        refrigerant_type_id,
        full_charge_lbs=60.0,
        initial_charge_lbs=0.0,
        installed_on="2025-03-01T00:00:00Z",
        **overrides,
    )


def retirement_payload(**overrides) -> Dict[str, Any]:
    return _payload({"retirement_reason_code": "END_OF_LIFE_REPLACEMENT"}, overrides)


# ─── Technicians (§3.2) ───────────────────────────────────────────────


def technician_payload(**overrides) -> Dict[str, Any]:
    """T1 Dana Ruiz: TYPE_II, certification valid to 2027-12-31."""
    return _payload(
        {
            "full_name": "Dana Ruiz",
            "epa_certification_number": "EPA-608-11111",
            "certification_type": CERT_TYPE_II,
            "certification_expires_on": "2027-12-31T00:00:00Z",
        },
        overrides,
    )


def second_technician_payload(**overrides) -> Dict[str, Any]:
    """T2 Ira Okonkwo: UNIVERSAL, valid to 2028-06-30 — the verifying technician."""
    return _payload(
        {
            "full_name": "Ira Okonkwo",
            "epa_certification_number": "EPA-608-22222",
            "certification_type": CERT_UNIVERSAL,
            "certification_expires_on": "2028-06-30T00:00:00Z",
        },
        overrides,
    )


def technician_status_change_payload(new_status: str, reason_code: str) -> Dict[str, Any]:
    return {"new_status": new_status, "reason_code": reason_code}


# ─── Recovery equipment (§3.2) ────────────────────────────────────────


def recovery_equipment_payload(
    store_id: str, assigned_technician_id: str, **overrides
) -> Dict[str, Any]:
    """EQ1 RM-9001: certified for HIGH pressure, last verified 2026-06-01."""
    return _payload(
        {
            "store_id": store_id,
            "assigned_technician_id": assigned_technician_id,
            "equipment_serial": "RM-9001",
            "certified_to_standard": "AHRI_740_2016",
            "certified_for_pressure_class": PRESSURE_HIGH,
            "last_verification_on": "2026-06-01T00:00:00Z",
        },
        overrides,
    )


def equipment_verification_payload(verified_on: str) -> Dict[str, Any]:
    return {"verified_on": verified_on}


# ─── Cylinders (§3.2) ─────────────────────────────────────────────────


def cylinder_payload(store_id: str, refrigerant_type_id: str, **overrides) -> Dict[str, Any]:
    """CYL-0001: 50.0 lb nominal water capacity holding 40.0 lbs."""
    return _payload(
        {
            "store_id": store_id,
            "refrigerant_type_id": refrigerant_type_id,
            "cylinder_serial": "CYL-0001",
            "nominal_capacity_lbs": 50.0,
            "initial_contents_lbs": 40.0,
        },
        overrides,
    )


def reclaim_shipment_payload(**overrides) -> Dict[str, Any]:
    return _payload({"reclaimer_name": "Pacific Reclaim Services"}, overrides)


def reclaim_certification_payload(
    reclaimed_quantity_lbs: float, reclaim_issued_on: str, **overrides
) -> Dict[str, Any]:
    return _payload(
        {
            "reclaim_certificate_number": "RC-2026-0001",
            "reclaimed_quantity_lbs": reclaimed_quantity_lbs,
            "purity_verified": True,
            "reclaim_issued_on": reclaim_issued_on,
        },
        overrides,
    )


# ─── Service records (§3.3, §3.8) ─────────────────────────────────────


def service_record_payload(
    system_id: str,
    technician_id: str,
    recovery_equipment_id: str,
    expected_system_version: int,
    **overrides,
) -> Dict[str, Any]:
    """
    An ADD_REFRIGERANT record of 10.0 lbs at the reference clock, two hours of
    work. `expected_system_version` is non-optional, so it is positional here.

    The default mass movement is non-zero, so §3.3 makes `cylinder_id`
    mandatory: pass `cylinder_id=` unless the caller also zeroes the movement.
    """
    return _payload(
        {
            "system_id": system_id,
            "technician_id": technician_id,
            "recovery_equipment_id": recovery_equipment_id,
            "service_type": SERVICE_ADD_REFRIGERANT,
            "refrigerant_added_lbs": 10.0,
            "performed_at": CLOCK_AUGUST_1,
            "duration_minutes": 120,
            "expected_system_version": expected_system_version,
        },
        overrides,
    )


def void_payload(**overrides) -> Dict[str, Any]:
    return _payload({"void_reason_code": "MISKEYED_QUANTITY"}, overrides)


# ─── Leak events, repairs and verifications (§3.5) ────────────────────


def leak_event_payload(system_id: str, **overrides) -> Dict[str, Any]:
    """A manually declared event at the reference clock."""
    return _payload(
        {
            "system_id": system_id,
            "detected_at": CLOCK_AUGUST_1,
            "detection_method": DETECTION_MANUAL_INSPECTION,
        },
        overrides,
    )


def repair_attempt_payload(
    leak_event_id: str,
    system_id: str,
    technician_id: str,
    recovery_equipment_id: str,
    repair_completed_at: str,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "leak_event_id": leak_event_id,
            "system_id": system_id,
            "technician_id": technician_id,
            "recovery_equipment_id": recovery_equipment_id,
            "repair_method_code": "BRAZE_JOINT",
            "repair_completed_at": repair_completed_at,
        },
        overrides,
    )


def verification_test_payload(
    leak_event_id: str,
    repair_attempt_id: str,
    technician_id: str,
    performed_at: str,
    **overrides,
) -> Dict[str, Any]:
    return _payload(
        {
            "leak_event_id": leak_event_id,
            "repair_attempt_id": repair_attempt_id,
            "technician_id": technician_id,
            "test_method_code": "PRESSURE_DECAY",
            "performed_at": performed_at,
            "result": RESULT_PASS,
            "measured_leak_rate_pct": 2.0,
        },
        overrides,
    )


# ─── Extension requests (§3.6) ────────────────────────────────────────


def extension_request_payload(leak_event_id: str, **overrides) -> Dict[str, Any]:
    return _payload(
        {
            "leak_event_id": leak_event_id,
            "reason_code": REASON_PARTS_UNAVAILABLE,
            "requested_days": 20,
            "justification": "compressor rack valve on national backorder",
        },
        overrides,
    )


def extension_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _payload({"decision": decision}, overrides)


def extension_revocation_payload(**overrides) -> Dict[str, Any]:
    return _payload({"revocation_reason_code": "JUSTIFICATION_WITHDRAWN"}, overrides)


# ─── Retrofit plans (§3.7) ────────────────────────────────────────────


def retrofit_plan_payload(
    system_id: str, expected_system_version: int, **overrides
) -> Dict[str, Any]:
    """A RETROFIT plan due 2026-11-06 at an estimated 125000.00 USD."""
    return _payload(
        {
            "system_id": system_id,
            "plan_type": PLAN_RETROFIT,
            "due_on": "2026-11-06T00:00:00Z",
            "estimated_cost_usd": 125000.00,
            "expected_system_version": expected_system_version,
        },
        overrides,
    )


def plan_submission_payload(**overrides) -> Dict[str, Any]:
    return _payload({"submission_note": "conversion to R-448A"}, overrides)


def plan_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _payload({"decision": decision}, overrides)


def plan_completion_payload(service_record_id: str) -> Dict[str, Any]:
    return {"service_record_id": service_record_id}


# ─── Regulatory reports (§3.9) ────────────────────────────────────────


def regulatory_report_payload(store_id: str, **overrides) -> Dict[str, Any]:
    return _payload(
        {
            "store_id": store_id,
            "report_type": REPORT_ANNUAL_LEAK_RATE,
            "period_start": "2025-07-01T00:00:00Z",
            "period_end": "2026-06-30T00:00:00Z",
            "leaked_lbs_method": LEAKED_CHARGE_BASED,
        },
        overrides,
    )


def report_submission_payload(**overrides) -> Dict[str, Any]:
    return _payload({"submission_note": "annual leak rate filing"}, overrides)


def report_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _payload({"decision": decision}, overrides)


# ─── Inspections (§3.9) ───────────────────────────────────────────────


def citation(
    citation_code: str = "608-LEAK-REPAIR-LATE",
    severity: str = SEVERITY_MINOR,
    violation_days: int = 1,
) -> Dict[str, Any]:
    return {
        "citation_code": citation_code,
        "severity": severity,
        "violation_days": violation_days,
    }


def two_minor_one_day_citations() -> List[Dict[str, Any]]:
    """The pair of one-day MINOR citations the penalty examples are priced on."""
    return [
        citation("608-LEAK-REPAIR-LATE", SEVERITY_MINOR, 1),
        citation("608-RECORDS-INCOMPLETE", SEVERITY_MINOR, 1),
    ]


def inspection_payload(
    store_id: str, citations: Optional[List[Dict[str, Any]]] = None, **overrides
) -> Dict[str, Any]:
    return _payload(
        {
            "store_id": store_id,
            "inspector_name": "CARB Field Office",
            "citations": two_minor_one_day_citations() if citations is None else citations,
        },
        overrides,
    )


def inspection_response_payload(**overrides) -> Dict[str, Any]:
    return _payload(
        {
            "response_summary": "leak repaired and verified; records reconciled",
            "corrective_action_code": "REPAIR_COMPLETED",
        },
        overrides,
    )


def inspection_closure_payload(**overrides) -> Dict[str, Any]:
    return _payload({"closure_note": "corrective action accepted"}, overrides)


# ─── Compliance sweep (§3.6) ──────────────────────────────────────────


def compliance_run_payload(**overrides) -> Dict[str, Any]:
    return _payload({}, overrides)
