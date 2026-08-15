"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    AmendmentStatus,
    AmendmentType,
    CarOwnership,
    ClaimStatus,
    DeviceStatus,
    DeviceType,
    DwellStatus,
    InspectionResult,
    InspectionStatus,
    OrderStatus,
    OrderType,
    PlacementStatus,
    ProjectStatus,
    SegmentStatus,
)

_AGREEMENT_STATUSES = [s.value for s in AgreementStatus]
_AMENDMENT_STATUSES = [s.value for s in AmendmentStatus]
_AMENDMENT_TYPES = [t.value for t in AmendmentType]
_PROJECT_STATUSES = [s.value for s in ProjectStatus]
_SEGMENT_STATUSES = [s.value for s in SegmentStatus]
_INSPECTION_STATUSES = [s.value for s in InspectionStatus]
_INSPECTION_RESULTS = [r.value for r in InspectionResult]
_DEVICE_STATUSES = [s.value for s in DeviceStatus]
_DEVICE_TYPES = [t.value for t in DeviceType]
_ORDER_STATUSES = [s.value for s in OrderStatus]
_ORDER_TYPES = [t.value for t in OrderType]
_DWELL_STATUSES = [s.value for s in DwellStatus]
_CAR_OWNERSHIPS = [o.value for o in CarOwnership]
_PLACEMENT_STATUSES = [s.value for s in PlacementStatus]
_CLAIM_STATUSES = [s.value for s in ClaimStatus]


def _assert_common_fields(data: dict, entity: str):
    """System-managed fields of PRD §2.5 present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_track_agreement(data: dict):
    _assert_common_fields(data, "TrackAgreement")
    assert isinstance(data["shipper_name"], str) and data["shipper_name"]
    assert isinstance(data["shipper_user_id"], str) and data["shipper_user_id"]
    assert isinstance(data["facility_name"], str) and data["facility_name"]
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)
    assert isinstance(data["renewal_notice_days"], int)
    assert isinstance(data["renewal_term_months"], int)
    assert isinstance(data["shipper_cost_share_pct"], (int, float))
    assert isinstance(data["liability_cap_cents"], int)
    assert isinstance(data["shipper_indemnity_default_pct"], (int, float))
    assert isinstance(data["free_time_hours"], int)
    assert isinstance(data["demurrage_base_rate_cents"], int)
    assert isinstance(data["demurrage_escalated_rate_cents"], int)
    assert isinstance(data["storage_rate_per_car_month_cents"], int)
    assert isinstance(data["inspection_cadence_days"], int)
    assert isinstance(data["removal_period_days"], int)
    assert isinstance(data["removal_penalty_per_day_cents"], int)
    assert isinstance(data["service_days_of_week"], list)
    assert isinstance(data["max_switches_per_day"], int)
    assert isinstance(data["removal_penalty_cents"], int)
    assert data["status"] in _AGREEMENT_STATUSES


def assert_amendment(data: dict):
    _assert_common_fields(data, "Amendment")
    assert isinstance(data["agreement_id"], str)
    assert data["amendment_type"] in _AMENDMENT_TYPES
    assert isinstance(data["proposed_by_role"], str)
    assert isinstance(data["proposed_by_user_id"], str)
    assert data["status"] in _AMENDMENT_STATUSES


def assert_construction_project(data: dict):
    _assert_common_fields(data, "ConstructionProject")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["shipper_share_pct"], (int, float))
    assert isinstance(data["spec_revision_no"], int) and data["spec_revision_no"] >= 0
    assert isinstance(data["amount_paid_cents"], int)
    assert data["status"] in _PROJECT_STATUSES


def assert_track_segment(data: dict):
    _assert_common_fields(data, "TrackSegment")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["segment_name"], str) and data["segment_name"]
    assert isinstance(data["length_feet"], int) and data["length_feet"] > 0
    assert isinstance(data["storage_capacity_cars"], int)
    assert isinstance(data["stored_car_count"], int)
    assert isinstance(data["accrued_storage_cents"], int)
    assert isinstance(data["safety_suspended"], bool)
    assert data["status"] in _SEGMENT_STATUSES


def assert_safety_inspection(data: dict):
    _assert_common_fields(data, "SafetyInspection")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["segment_id"], str)
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["due_date"], str)
    if data.get("result") is not None:
        assert data["result"] in _INSPECTION_RESULTS
    assert isinstance(data.get("cited_device_ids", []), list)
    assert data["status"] in _INSPECTION_STATUSES


def assert_derail_device(data: dict):
    _assert_common_fields(data, "DerailDevice")
    assert isinstance(data["segment_id"], str)
    assert data["device_type"] in _DEVICE_TYPES
    assert isinstance(data["location_description"], str)
    assert data["status"] in _DEVICE_STATUSES


def assert_service_order(data: dict):
    _assert_common_fields(data, "ServiceOrder")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["segment_id"], str)
    assert data["order_type"] in _ORDER_TYPES
    assert isinstance(data["service_date"], str)
    assert isinstance(data["start_hour"], int)
    assert isinstance(data["end_hour"], int)
    assert data["status"] in _ORDER_STATUSES


def assert_car_dwell(data: dict):
    _assert_common_fields(data, "CarDwell")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["car_mark"], str) and data["car_mark"]
    assert data["car_ownership"] in _CAR_OWNERSHIPS
    assert isinstance(data["placed_at"], str)
    assert isinstance(data["accrued_demurrage_cents"], int)
    assert data["status"] in _DWELL_STATUSES


def assert_storage_placement(data: dict):
    _assert_common_fields(data, "StoragePlacement")
    assert isinstance(data["segment_id"], str)
    assert isinstance(data["car_mark"], str) and data["car_mark"]
    assert isinstance(data["placed_date"], str)
    assert isinstance(data["accrued_storage_charge_cents"], int)
    assert data["status"] in _PLACEMENT_STATUSES


def assert_liability_claim(data: dict):
    _assert_common_fields(data, "LiabilityClaim")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["claimant_name"], str) and data["claimant_name"]
    assert isinstance(data["incident_date"], str)
    assert isinstance(data["claim_amount_cents"], int)
    assert data["status"] in _CLAIM_STATUSES


def assert_project_ledger_invariant(project: dict):
    """PRD §3.3: amount_paid_cents + outstanding_share_cents == shipper_final_share_cents.

    Only meaningful once the project is COMPLETED (final share computed).
    """
    total = project["amount_paid_cents"] + project["outstanding_share_cents"]
    assert total == project["shipper_final_share_cents"], (
        f"Ledger invariant violated: {project['amount_paid_cents']} + "
        f"{project['outstanding_share_cents']} != "
        f"{project['shipper_final_share_cents']}"
    )


def assert_segment_storage_invariants(segment: dict):
    """Segment ledger sanity: counts non-negative, flag is boolean (PRD §3.4/§3.6)."""
    assert segment["stored_car_count"] >= 0
    assert segment["accrued_storage_cents"] >= 0
    assert isinstance(segment["safety_suspended"], bool)
