"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .types import (
    BrokerSide,
    CommissionBasis,
    EnvironmentalPhase,
    InvoiceStatus,
    LoiStatus,
    MilestoneStatus,
    MilestoneType,
    OptionStatus,
    ParcelType,
    PlanStatus,
    PricingMethod,
    RequirementStatus,
    ReviewStatus,
    ReviewType,
    SiteStatus,
    TourStatus,
    UseType,
)


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(
        data.get("version"), int
    ), f"{entity}.version must be an integer"


def assert_tenant_requirement(data: dict):
    _assert_common_fields(data, "TenantRequirement")
    assert isinstance(data["tenant_name"], str) and data["tenant_name"]
    assert data["use_type"] in {m.value for m in UseType}
    assert isinstance(data["min_sf"], int) and data["min_sf"] > 0
    assert isinstance(data["max_sf"], int) and data["max_sf"] >= data["min_sf"]
    assert isinstance(data["min_clear_height_ft"], (int, float))
    assert isinstance(data["min_dock_doors"], int)
    assert isinstance(data["min_power_amps"], int)
    assert isinstance(data["min_yard_depth_ft"], int)
    assert isinstance(data["target_submarket"], str)
    assert isinstance(data["tenant_rep_id"], str) and data["tenant_rep_id"]
    assert data["status"] in {m.value for m in RequirementStatus}


def assert_site(data: dict):
    _assert_common_fields(data, "Site")
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["submarket"], str)
    assert data["parcel_type"] in {m.value for m in ParcelType}
    assert isinstance(data["total_sf"], int) and data["total_sf"] > 0
    assert isinstance(data["clear_height_ft"], (int, float))
    assert isinstance(data["dock_doors"], int)
    assert isinstance(data["power_amps"], int)
    assert isinstance(data["yard_depth_ft"], int)
    assert isinstance(data["zoning_designation"], str)
    assert data["environmental_phase"] in {m.value for m in EnvironmentalPhase}
    assert isinstance(data["asking_rate_psf"], (int, float))
    assert isinstance(data["reserved_sf"], int)
    assert isinstance(data["available_sf"], int)
    assert data["status"] in {m.value for m in SiteStatus}


def assert_site_sf_invariant(data: dict):
    """PRD §3.1: available_sf always equals total_sf minus reserved_sf."""
    assert data["available_sf"] == data["total_sf"] - data["reserved_sf"], (
        f"available_sf {data['available_sf']} != total_sf {data['total_sf']} "
        f"- reserved_sf {data['reserved_sf']}"
    )


def assert_tour(data: dict):
    _assert_common_fields(data, "Tour")
    assert is_valid_uuid(data.get("site_id", "")), "Tour.site_id must be a UUID"
    assert is_valid_uuid(
        data.get("requirement_id", "")
    ), "Tour.requirement_id must be a UUID"
    assert isinstance(data["tenant_rep_id"], str) and data["tenant_rep_id"]
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at ISO 8601"
    assert data["status"] in {m.value for m in TourStatus}


def assert_loi(data: dict):
    _assert_common_fields(data, "LOI")
    assert is_valid_uuid(
        data.get("requirement_id", "")
    ), "LOI.requirement_id must be a UUID"
    assert is_valid_uuid(data.get("site_id", "")), "LOI.site_id must be a UUID"
    assert isinstance(data["term_years"], int) and 1 <= data["term_years"] <= 30
    assert isinstance(data["leased_sf"], int) and data["leased_sf"] > 0
    assert isinstance(data["base_rate_psf"], (int, float))
    assert isinstance(data["ti_allowance_psf"], (int, float))
    assert isinstance(data["free_rent_months"], int)
    assert isinstance(data["escalation_pct"], (int, float))
    assert data["commission_basis"] in {m.value for m in CommissionBasis}
    assert isinstance(data["aggregate_rent_total"], (int, float))
    assert isinstance(data["net_effective_rent_psf"], (int, float))
    assert isinstance(data["negotiation_round"], int)
    assert data.get("rent_commencement_date") is None or isinstance(
        data["rent_commencement_date"], str
    )
    assert isinstance(data["abatement_days"], int)
    assert data["status"] in {m.value for m in LoiStatus}


def assert_bts_plan(data: dict):
    _assert_common_fields(data, "BuildToSuitPlan")
    assert is_valid_uuid(data.get("loi_id", "")), "BuildToSuitPlan.loi_id UUID"
    assert data["status"] in {m.value for m in PlanStatus}


def assert_priced_plan(data: dict):
    """PRD §3.5: a successful pricing writes all five computed fields."""
    assert_bts_plan(data)
    for field in (
        "provisional_base_rate_psf",
        "commission_cost_estimate",
        "total_project_cost",
        "converted_base_rate_psf",
        "yield_on_cost",
    ):
        assert isinstance(
            data.get(field), (int, float)
        ), f"BuildToSuitPlan.{field} must be numeric after pricing"
    assert data["pricing_method"] in {m.value for m in PricingMethod}


def assert_delivery_milestone(data: dict):
    _assert_common_fields(data, "DeliveryMilestone")
    assert is_valid_uuid(data.get("plan_id", "")), "DeliveryMilestone.plan_id UUID"
    assert data["milestone_type"] in {m.value for m in MilestoneType}
    assert is_iso8601_timestamp(data.get("planned_date", "")), "planned_date ISO 8601"
    assert data.get("actual_date") is None or isinstance(data["actual_date"], str)
    assert data["status"] in {m.value for m in MilestoneStatus}


def assert_expansion_option(data: dict):
    _assert_common_fields(data, "ExpansionOption")
    assert is_valid_uuid(data.get("loi_id", "")), "ExpansionOption.loi_id UUID"
    assert is_valid_uuid(
        data.get("land_site_id", "")
    ), "ExpansionOption.land_site_id UUID"
    assert isinstance(data["option_sf"], int) and data["option_sf"] > 0
    assert is_iso8601_timestamp(
        data.get("window_open_date", "")
    ), "window_open_date ISO 8601"
    assert is_iso8601_timestamp(
        data.get("window_close_date", "")
    ), "window_close_date ISO 8601"
    assert data["status"] in {m.value for m in OptionStatus}


def assert_compliance_review(data: dict):
    _assert_common_fields(data, "ComplianceReview")
    assert is_valid_uuid(data.get("site_id", "")), "ComplianceReview.site_id UUID"
    assert is_valid_uuid(
        data.get("requirement_id", "")
    ), "ComplianceReview.requirement_id UUID"
    assert data["review_type"] in {m.value for m in ReviewType}
    assert data.get("findings") is None or isinstance(data["findings"], str)
    assert data["status"] in {m.value for m in ReviewStatus}


def assert_commission_invoice(data: dict):
    _assert_common_fields(data, "CommissionInvoice")
    assert is_valid_uuid(data.get("loi_id", "")), "CommissionInvoice.loi_id UUID"
    assert data["broker_side"] in {m.value for m in BrokerSide}
    assert data["commission_basis"] in {m.value for m in CommissionBasis}
    assert isinstance(data["commission_basis_amount"], (int, float))
    assert isinstance(data["total_commission"], (int, float))
    assert isinstance(data["installment_1_amount"], (int, float))
    assert isinstance(data["installment_2_amount"], (int, float))
    assert isinstance(data["installment_1_paid"], bool)
    assert isinstance(data["installment_2_paid"], bool)
    assert isinstance(data["installment_2_due"], bool)
    assert data.get("dispute_reason") is None or isinstance(data["dispute_reason"], str)
    assert data["status"] in {m.value for m in InvoiceStatus}


def assert_installment_conservation(data: dict):
    """PRD §3.7: installment_2_amount is total minus installment_1_amount."""
    total = data["total_commission"]
    assert data["installment_1_amount"] + data["installment_2_amount"] == pytest.approx(
        total, abs=0.001
    ), (
        f"installments {data['installment_1_amount']} + "
        f"{data['installment_2_amount']} != total_commission {total}"
    )


def assert_same_instant(actual: str, expected: str):
    """Compare two ISO 8601 instants, tolerant of fractional-digit rendering
    ('2027-04-15T00:00:00Z' vs '2027-04-15T00:00:00.000Z')."""
    from datetime import datetime, timezone

    def _parse(value: str) -> datetime:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    assert _parse(actual) == _parse(
        expected
    ), f"Expected instant {expected}, got {actual}"
