"""Entity assertions and domain invariant checkers (PRD sections 2.4-2.6, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    DocumentKind,
    DocumentStatus,
    DiscoveredVia,
    EasementCaseStatus,
    EncroachmentStatus,
    EncroachmentType,
    FieldInspectionStatus,
    LocationWithinZone,
    OfferStatus,
    PermitApprovalStatus,
    PermitType,
    ReferralReason,
    ReferralStatus,
    SearchScope,
    SeverityTier,
    TitleTaskStatus,
    VegetationZoneStatus,
    ViolationStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def assert_easement_case(data: dict):
    _assert_common(data)
    assert isinstance(data["case_code"], str) and data["case_code"]
    assert isinstance(data["utility_district"], str)
    assert isinstance(data["county"], str)
    assert isinstance(data["parcel_id"], str)
    assert _is_number(data["easement_width_ft"])
    assert _is_number(data["easement_area_sqft"])
    assert _is_number(data["fair_market_value_per_sqft"])
    assert isinstance(data["acquisition_budget_cents"], int)
    assert isinstance(data["compensation_committed_cents"], int)
    assert isinstance(data["compensation_balance_cents"], int)
    assert isinstance(data["open_encroachment_count"], int)
    assert data["open_encroachment_count"] >= 0
    assert _is_number(data["encroachment_pressure_score"])
    assert isinstance(data["title_cleared"], bool)
    assert isinstance(data["active_permit_count"], int)
    assert data["status"] in {s.value for s in EasementCaseStatus}


def assert_easement_document(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["doc_kind"] in {k.value for k in DocumentKind}
    assert isinstance(data["instrument_number"], str) and data["instrument_number"]
    assert isinstance(data["grantor_name"], str)
    assert isinstance(data["grantee_name"], str)
    assert _is_number(data["width_ft"])
    assert data["status"] in {s.value for s in DocumentStatus}


def assert_encroachment(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["discovered_via"] in {v.value for v in DiscoveredVia}
    assert data["encroachment_type"] in {t.value for t in EncroachmentType}
    assert _is_number(data["encroachment_area_sqft"])
    assert _is_number(data["depth_into_easement_ft"])
    assert isinstance(data["encroaches_document_id"], str)
    assert data["severity_tier"] in {t.value for t in SeverityTier}
    assert isinstance(data["estimated_removal_cost_cents"], int)
    assert isinstance(data["negotiation_round"], int)
    assert data["status"] in {s.value for s in EncroachmentStatus}


def assert_acquisition_offer(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["landowner_name"], str)
    assert _is_number(data["offered_area_sqft"])
    assert isinstance(data["base_compensation_cents"], int)
    assert isinstance(data["negotiated_compensation_cents"], int)
    assert isinstance(data["severance_damages_cents"], int)
    assert isinstance(data["total_compensation_cents"], int)
    assert isinstance(data["negotiation_round"], int)
    assert isinstance(data["requires_director_approval"], bool)
    assert data["status"] in {s.value for s in OfferStatus}


def assert_third_party_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["permittee_name"], str)
    assert data["permit_type"] in {t.value for t in PermitType}
    assert _is_number(data["requested_area_sqft"])
    assert data["approval_status"] in {s.value for s in PermitApprovalStatus}
    assert data["field_inspection_status"] in {s.value for s in FieldInspectionStatus}
    assert isinstance(data["insurance_certificate_on_file"], bool)


def assert_vegetation_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["zone_label"], str)
    assert _is_number(data["max_allowed_height_ft"])
    assert isinstance(data["prohibited_species"], list)
    assert _is_number(data["wire_zone_width_ft"])
    assert _is_number(data["border_zone_width_ft"])
    assert isinstance(data["violation_count"], int)
    assert data["status"] in {s.value for s in VegetationZoneStatus}


def assert_vegetation_violation(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_id"], str)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["species"], str)
    assert _is_number(data["observed_height_ft"])
    assert data["location_within_zone"] in {loc.value for loc in LocationWithinZone}
    assert _is_number(data["excess_height_ft"])
    assert data["status"] in {s.value for s in ViolationStatus}


def assert_title_search_task(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["search_scope"] in {s.value for s in SearchScope}
    assert data["status"] in {s.value for s in TitleTaskStatus}


def assert_litigation_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["referral_reason"] in {r.value for r in ReferralReason}
    assert data["status"] in {s.value for s in ReferralStatus}


def assert_compensation_invariant(case_data: dict):
    """PRD section 3.5: committed + balance always equals the budget."""
    committed = case_data["compensation_committed_cents"]
    balance = case_data["compensation_balance_cents"]
    budget = case_data["acquisition_budget_cents"]
    assert committed + balance == budget, (
        f"compensation ledger broken: committed {committed} + balance {balance} "
        f"!= budget {budget}"
    )
    assert balance >= 0, f"compensation_balance_cents must stay non-negative, got {balance}"
