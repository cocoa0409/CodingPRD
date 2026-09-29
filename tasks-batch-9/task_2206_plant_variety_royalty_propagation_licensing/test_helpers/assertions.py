"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    AuditEngagementStatus,
    Exclusivity,
    FindingSeverity,
    GeneticTestResult,
    InstrumentType,
    LapseReason,
    ProtectionFilingStatus,
    ProtectionPosture,
    QualityTier,
    QuotaStatus,
    ReviewStatus,
    RevocationReason,
    RoyaltyBasis,
    SettlementStatus,
    SublicenseStatus,
    SurveillanceCaseStatus,
    SuspensionReason,
    TagOrderStatus,
    TerritoryClass,
    VarietyBrandStatus,
    VarietyLifecycleState,
    VarietyTrialStatus,
)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and any number
    of fractional digits."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 instants by value, not by string spelling."""
    assert actual is not None, f"{label} must not be null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_decimal_places(value, places: int, label: str = "value") -> None:
    """Assert a decimal quantity carries no more than `places` decimals."""
    quantum = Decimal(1).scaleb(-places)
    as_dec = Decimal(str(value))
    assert as_dec == as_dec.quantize(quantum), (
        f"{label} {value} must carry at most {places} decimal places"
    )


def assert_decimal_equals(actual, expected: str, label: str = "value") -> None:
    """Compare a decimal quantity by numeric value rather than by JSON spelling,
    so that 52.5 and 52.5000 compare equal."""
    assert Decimal(str(actual)) == Decimal(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_common_fields(data: dict, entity: str = "entity") -> None:
    """id / created_at / updated_at / version, carried by every entity except
    the immutable GeneticTest."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_variety(data: dict) -> None:
    assert_common_fields(data, "Variety")
    assert isinstance(data["denomination"], str) and 1 <= len(data["denomination"]) <= 80
    assert isinstance(data["species"], str) and len(data["species"]) >= 1
    assert isinstance(data["breeder_code"], str) and data["breeder_code"].isupper()
    assert data["lifecycle_state"] in [s.value for s in VarietyLifecycleState]
    assert data["brand_status"] in [s.value for s in VarietyBrandStatus]
    assert data["protection_posture"] in [s.value for s in ProtectionPosture]
    assert isinstance(data["protected_jurisdictions"], list)
    assert data["protected_jurisdictions"] == sorted(set(data["protected_jurisdictions"])), (
        "protected_jurisdictions must be distinct and lexicographically ascending"
    )
    assert data["royalty_basis_default"] in [b.value for b in RoyaltyBasis]
    assert isinstance(data["base_royalty_cents_per_plant"], int)
    assert isinstance(data["base_royalty_cents_per_acre"], int)
    assert_decimal_places(data["regional_performance_index"], 2, "regional_performance_index")
    assert isinstance(data["passed_trial_region_count"], int)
    assert isinstance(data["active_sublicense_count"], int)
    assert isinstance(data["brand_renewal_count"], int)


def assert_protection_filing(data: dict) -> None:
    assert_common_fields(data, "ProtectionFiling")
    assert is_valid_uuid(data["variety_id"])
    assert data["instrument_type"] in [i.value for i in InstrumentType]
    assert isinstance(data["jurisdiction_code"], str) and 2 <= len(data["jurisdiction_code"]) <= 4
    assert data["status"] in [s.value for s in ProtectionFilingStatus]
    assert 5 <= data["term_years"] <= 25
    assert data["annuity_base_cents"] >= 1000
    assert data["annuity_sequence_no"] >= 0
    assert 0 <= data["annuity_grace_days"] <= 90
    assert data["annuity_days_late"] >= 0
    assert data["annuity_surcharge_cents"] >= 0
    assert data["annuity_volume_credit_cents"] >= 0
    assert data["annuity_total_due_cents"] >= 0
    assert data["installments_paid_count"] >= 0
    assert data["lapse_reason"] is None or data["lapse_reason"] in [r.value for r in LapseReason]


def assert_trial_site(data: dict) -> None:
    assert_common_fields(data, "TrialSite")
    assert isinstance(data["site_name"], str) and len(data["site_name"]) >= 1
    assert isinstance(data["region_code"], str) and 2 <= len(data["region_code"]) <= 6
    assert data["plot_capacity"] >= 1
    assert data["occupied_plot_count"] >= 0


def assert_variety_trial(data: dict) -> None:
    assert_common_fields(data, "VarietyTrial")
    assert is_valid_uuid(data["variety_id"])
    assert is_valid_uuid(data["trial_site_id"])
    assert data["plot_count"] >= 1
    assert data["status"] in [s.value for s in VarietyTrialStatus]
    assert_decimal_places(data["performance_index"], 2, "performance_index")
    if data.get("propagation_pass_rate") is not None:
        assert 0 <= float(data["propagation_pass_rate"]) <= 1
        assert_decimal_places(data["propagation_pass_rate"], 4, "propagation_pass_rate")
    assert parse_instant(data["harvest_date"]) > parse_instant(data["plant_date"]), (
        "harvest_date must be strictly later than plant_date"
    )


def assert_propagator(data: dict) -> None:
    assert_common_fields(data, "Propagator")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 80
    assert isinstance(data["home_territory_code"], str)
    assert 0 <= data["compliance_score"] <= 100
    assert 0 <= data["lifetime_compliance_score"] <= 100
    assert data["royalty_payable_cents"] >= 0
    assert data["royalty_settled_cents"] >= 0
    assert data["damages_credit_cents"] >= 0
    assert data["material_audit_finding_count"] >= 0


def assert_propagator_agreement(data: dict) -> None:
    assert_common_fields(data, "PropagatorAgreement")
    assert is_valid_uuid(data["propagator_id"])
    assert data["status"] in [s.value for s in AgreementStatus]
    assert data["quality_tier"] in [t.value for t in QualityTier]
    assert isinstance(data["territory_codes"], list) and len(data["territory_codes"]) >= 1
    assert parse_instant(data["term_end"]) > parse_instant(data["term_start"])
    assert data["suspension_reason"] is None or data["suspension_reason"] in [
        r.value for r in SuspensionReason
    ]
    assert data["reinstatement_count"] >= 0


def assert_production_quota(data: dict) -> None:
    assert_common_fields(data, "ProductionQuota")
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["variety_id"])
    assert isinstance(data["season_code"], str) and 4 <= len(data["season_code"]) <= 8
    assert data["basis"] in [b.value for b in RoyaltyBasis]
    assert data["territory_class"] in [c.value for c in TerritoryClass]
    assert data["status"] in [s.value for s in QuotaStatus]
    assert data["allocated_units"] >= 1
    assert data["tags_committed_units"] >= 0
    assert data["tags_activated_units"] >= 0
    assert_quota_inventory_invariant(data)


def assert_tag_order(data: dict) -> None:
    assert_common_fields(data, "TagOrder")
    assert is_valid_uuid(data["quota_id"])
    assert data["requested_units"] >= 1
    assert data["status"] in [s.value for s in TagOrderStatus]
    assert data["activated_units"] >= 0
    assert data["voided_units"] >= 0


def assert_royalty_report(data: dict) -> None:
    assert_common_fields(data, "RoyaltyReport")
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["period_code"], str) and 4 <= len(data["period_code"]) <= 10
    assert data["review_status"] in [s.value for s in ReviewStatus]
    assert data["settlement_status"] in [s.value for s in SettlementStatus]
    assert isinstance(data["is_late"], bool)
    assert data["provisional_total_cents"] >= 0
    assert data["final_total_cents"] >= 0
    assert data["late_fee_cents"] >= 0
    assert data["booked_amount_cents"] >= 0
    assert data["revision_no"] >= 0


def assert_royalty_line_item(data: dict) -> None:
    assert_common_fields(data, "RoyaltyLineItem")
    assert is_valid_uuid(data["report_id"])
    assert is_valid_uuid(data["quota_id"])
    assert data["reported_units"] >= 0
    assert data["billable_units"] >= 0
    assert_decimal_places(data["effective_rate_cents"], 4, "effective_rate_cents")
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["final_amount_cents"], int)
    assert isinstance(data["overrun_flagged"], bool)


def assert_sublicense_grant(data: dict) -> None:
    assert_common_fields(data, "SublicenseGrant")
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["variety_id"])
    assert isinstance(data["sublicensee_name"], str) and 1 <= len(data["sublicensee_name"]) <= 80
    assert data["exclusivity"] in [e.value for e in Exclusivity]
    assert data["status"] in [s.value for s in SublicenseStatus]
    assert data["revocation_reason"] is None or data["revocation_reason"] in [
        r.value for r in RevocationReason
    ]
    assert parse_instant(data["expiry_date"]) > parse_instant(data["effective_date"])


def assert_surveillance_case(data: dict) -> None:
    assert_common_fields(data, "SurveillanceCase")
    assert is_valid_uuid(data["variety_id"])
    assert data["status"] in [s.value for s in SurveillanceCaseStatus]
    assert isinstance(data["market_survey_ref"], str) and 1 <= len(data["market_survey_ref"]) <= 40
    assert data["sampled_unit_count"] >= 0
    assert_decimal_places(data["max_match_confidence"], 4, "max_match_confidence")
    assert 0 <= float(data["max_match_confidence"]) <= 1
    assert_damages_waterfall_conservation(data)


def assert_genetic_test(data: dict) -> None:
    """A genetic test carries id and created_at only: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "GeneticTest.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "GeneticTest.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "GeneticTest must expose no updated_at field"
    assert "version" not in data, "GeneticTest must expose no version field"
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["lab_code"], str) and 2 <= len(data["lab_code"]) <= 12
    assert isinstance(data["marker_panel"], str) and 2 <= len(data["marker_panel"]) <= 16
    assert_decimal_places(data["match_confidence"], 4, "match_confidence")
    assert data["result"] in [r.value for r in GeneticTestResult]


def assert_audit_engagement(data: dict) -> None:
    assert_common_fields(data, "AuditEngagement")
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["royalty_report_id"])
    assert data["status"] in [s.value for s in AuditEngagementStatus]
    assert data["finding_severity"] is None or data["finding_severity"] in [
        s.value for s in FindingSeverity
    ]
    assert data["underreported_units"] >= 0


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_quota_inventory_invariant(quota: dict) -> None:
    """allocated_units always equals units_available plus tags_committed_units."""
    assert quota["allocated_units"] == quota["units_available"] + quota["tags_committed_units"], (
        "allocated_units ({}) must equal units_available ({}) + tags_committed_units ({})".format(
            quota["allocated_units"], quota["units_available"], quota["tags_committed_units"]
        )
    )


def assert_propagator_ledger_invariant(propagator: dict, expected_accepted_total: int) -> None:
    """royalty_payable_cents plus royalty_settled_cents always equals the sum of
    booked_amount_cents over that propagator's accepted reports."""
    total = propagator["royalty_payable_cents"] + propagator["royalty_settled_cents"]
    assert total == expected_accepted_total, (
        "royalty_payable_cents + royalty_settled_cents ({}) must equal the accepted "
        "booked total ({})".format(total, expected_accepted_total)
    )


def assert_damages_waterfall_conservation(case: dict) -> None:
    """enforcement_recovery_cents plus breeder_pool_cents plus
    propagator_credit_cents always equals recovered_damages_cents exactly."""
    buckets = (
        case["enforcement_recovery_cents"]
        + case["breeder_pool_cents"]
        + case["propagator_credit_cents"]
    )
    assert buckets == case["recovered_damages_cents"], (
        "waterfall buckets ({}) must sum to recovered_damages_cents ({})".format(
            buckets, case["recovered_damages_cents"]
        )
    )
    assert case["enforcement_recovery_cents"] >= 0
    assert case["breeder_pool_cents"] >= 0
    assert case["propagator_credit_cents"] >= 0


def assert_version_is(data: dict, expected: int, label: str = "record") -> None:
    assert data["version"] == expected, (
        f"Expected {label}.version {expected}, got {data['version']}"
    )
