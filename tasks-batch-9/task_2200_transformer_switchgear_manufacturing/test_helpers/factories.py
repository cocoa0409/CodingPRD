"""Payload builders using the exact field names of the PRD.

Each builder returns a complete, PRD-valid payload; keyword overrides replace
individual fields, and passing ``None`` for an optional field is honoured so a
test can exercise omission by popping the key instead.
"""

from typing import Any, Dict

from .constants import (
    ALLOCATION_POLICY_PREEMPTIBLE,
    MV_SWITCHGEAR,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# --- PRD 3.1 --------------------------------------------------------------
def engineered_order_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "order_number": "ORD-CORNER-001",
            "customer_name": "Riverbend Utility",
            "product_family": MV_SWITCHGEAR,
            "rated_kv": 15,
            "contract_value_cents": 4000000,
            "sold_at": "2026-01-05T00:00:00Z",
            "promised_ship_at": "2026-10-01T00:00:00Z",
            "owning_sales_user_id": "u-sales-1",
        },
        overrides,
    )


# --- PRD 3.2 --------------------------------------------------------------
def submittal_drawing_payload(
    expected_engineered_order_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "drawing_set_code": "DS-CORNER-A",
            "authored_by_user_id": "u_de_1",
            "expected_engineered_order_version": expected_engineered_order_version,
        },
        overrides,
    )


def disposition_payload(disposition: str, reviewed_by_user_id: str, **overrides):
    return _merge(
        {
            "disposition": disposition,
            "reviewed_by_user_id": reviewed_by_user_id,
        },
        overrides,
    )


# --- PRD 3.3 --------------------------------------------------------------
def escalation_clause_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "copper_weight_bp": 6000,
            "aluminum_weight_bp": 2000,
            "core_steel_weight_bp": 2000,
            "escalatable_base_cents": 2000000,
            "base_index_month": "2026-01",
            "cap_bp": 1000,
            "collar_bp": 200,
            "final_window_end_month": "2026-06",
        },
        overrides,
    )


def commodity_index_point_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "commodity": "COPPER",
            "index_month": "2026-01",
            "index_value": 10000,
            "published_at": "2026-02-05T00:00:00Z",
            "is_provisional": False,
        },
        overrides,
    )


def escalation_adjustment_payload(
    escalation_clause_id: str,
    expected_engineered_order_version: int,
    variant: str = "PROVISIONAL",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "escalation_clause_id": escalation_clause_id,
            "variant": variant,
            "prepared_by_user_id": "u-contract-1",
            "expected_engineered_order_version": expected_engineered_order_version,
        },
        overrides,
    )


# --- PRD 3.4 --------------------------------------------------------------
def supplier_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "supplier_code": "SUP-CORNER-01",
            "legal_name": "Cascade Coil Works",
            "region": "NA",
        },
        overrides,
    )


def long_lead_component_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "part_number": "PN-CORNER-01",
            "category": "HV_BUSHING",
            "lead_time_days": 120,
            "quantity_on_hand": 10,
            "allocation_policy": ALLOCATION_POLICY_PREEMPTIBLE,
        },
        overrides,
    )


def component_allocation_payload(
    long_lead_component_id: str,
    engineered_order_id: str,
    expected_component_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "long_lead_component_id": long_lead_component_id,
            "engineered_order_id": engineered_order_id,
            "quantity": 4,
            "priority_class": 2,
            "need_by_date": "2026-09-01T00:00:00Z",
            "expected_component_version": expected_component_version,
        },
        overrides,
    )


# --- PRD 3.5 --------------------------------------------------------------
def test_bay_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "bay_code": "BAY-CORNER-01",
            "max_kv": 145,
            "changeover_buffer_hours": 4,
            "supports_impulse": False,
        },
        overrides,
    )


def factory_acceptance_test_payload(engineered_order_id: str, **overrides):
    return _merge(
        {
            "engineered_order_id": engineered_order_id,
            "test_duration_hours": 8,
            "witness_required": False,
            "requires_impulse": False,
        },
        overrides,
    )


def witness_party_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "party_code": "WP-1",
            "display_name": "Riverbend Inspection",
            "party_type": "CUSTOMER",
            "home_region": "NA",
            "daily_witness_capacity": 1,
            "credential_expires_at": "2027-12-31T00:00:00Z",
        },
        overrides,
    )


def witness_assignment_payload(witness_party_id: str, **overrides):
    return _merge(
        {
            "witness_party_id": witness_party_id,
            "travel_region": "NA",
        },
        overrides,
    )


# --- PRD 3.6 --------------------------------------------------------------
def test_report_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "winding_temp_rise_c": 55,
            "temp_rise_limit_c": 65,
            "short_circuit_current_ka": 25,
            "arc_duration_ms": 200,
            "working_distance_mm": 455,
        },
        overrides,
    )


def compliance_label_payload(
    submittal_drawing_id: str,
    test_report_id: str,
    expected_engineered_order_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "submittal_drawing_id": submittal_drawing_id,
            "test_report_id": test_report_id,
            "generated_by_user_id": "u_co_1",
            "expected_engineered_order_version": expected_engineered_order_version,
        },
        overrides,
    )


# --- PRD 3.7 --------------------------------------------------------------
def shipment_release_payload(
    expected_engineered_order_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "stage_index": 1,
            "stage_share_bp": 10000,
            "is_final_stage": True,
            "expected_engineered_order_version": expected_engineered_order_version,
        },
        overrides,
    )


def site_storage_agreement_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "storage_start_at": "2026-03-01T00:00:00Z",
            "crate_count": 1,
            "insured_value_cents": 0,
        },
        overrides,
    )


# --- PRD 3.8 --------------------------------------------------------------
def commissioning_job_payload(shipment_release_id: str, **overrides):
    return _merge(
        {
            "shipment_release_id": shipment_release_id,
            "mobilization_at": "2026-08-20T08:00:00Z",
            "lead_field_user_id": "u_fs_1",
        },
        overrides,
    )


def punch_list_item_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "severity": "MINOR",
            "description_text": "Cable gland torque to be re-checked",
        },
        overrides,
    )


# --- PRD 3.9 --------------------------------------------------------------
def warranty_claim_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "claim_number": "WC-CORNER-001",
            "suspect_component_id": None,
            "failure_reported_at": "2026-09-01T00:00:00Z",
            "parts_claim_cents": 250000,
            "labor_claim_cents": 80000,
            "freight_claim_cents": 20000,
        },
        overrides,
    )


def failure_analysis_report_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "root_cause_code": "SUPPLIER_DEFECT",
            "authored_by_user_id": "u_qe_2",
            "quarantine_recommended": False,
            "defect_weight": 5,
        },
        overrides,
    )
