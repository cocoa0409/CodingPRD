"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def assert_money(actual, expected, label="amount"):
    """Money is stored rounded half-up to 2dp (PRD §2.6); compare to the cent."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected {label} == {expected}, got {actual}"
    )


def _assert_common_fields(data):
    """PRD §2.5: primary resources carry id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lean_fields(data):
    """PRD §2.5: subordinate records carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "updated_at must be absent from lean records"
    assert "version" not in data, "version must be absent from lean records"


def _assert_money_field(data, field, nullable=False):
    value = data.get(field)
    if value is None and nullable:
        return
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number"
    )
    assert_cost_precision(float(value))


def assert_sponsor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sponsor_name"], str) and len(data["sponsor_name"]) > 0
    assert data["airport_size_tier"] in ["LARGE_HUB", "MEDIUM_HUB", "SMALL_HUB", "NONHUB"]
    assert data["status"] == "ACTIVE"
    _assert_money_field(data, "npe_entitlement_total")
    _assert_money_field(data, "npe_entitlement_available")


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert isinstance(data["facility_name"], str) and len(data["facility_name"]) > 0
    assert data["facility_type"] in ["RUNWAY", "TAXIWAY", "APRON"]


def assert_capital_program(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert isinstance(data["fiscal_year"], int)
    _assert_money_field(data, "selection_budget")
    _assert_money_field(data, "selected_total_cost")
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "AMENDMENT_DRAFT", "EXPIRED"]


def assert_cip_project(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["project_type"] in [
        "RUNWAY_SAFETY", "CAPACITY", "PRESERVATION", "SECURITY", "ENVIRONMENTAL", "NOISE",
    ]
    _assert_money_field(data, "estimated_cost")
    for score_field in ["safety_score", "capacity_score", "preservation_score",
                        "security_score", "environmental_score"]:
        assert isinstance(data[score_field], int), f"{score_field} must be an integer"
    assert isinstance(data["runway_safety_noncompliant"], bool)
    assert isinstance(data["multi_airport_system"], bool)
    _assert_money_field(data, "priority_score_sponsor", nullable=True)
    _assert_money_field(data, "priority_score_federal", nullable=True)
    assert data.get("selection_rank") is None or isinstance(data["selection_rank"], int)
    assert data["status"] in ["PROPOSED", "SELECTED", "DEFERRED", "DROPPED"]


def assert_grant_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["project_ids"], list)
    _assert_money_field(data, "total_eligible_cost")
    assert isinstance(data["created_by_user_id"], str)
    assert isinstance(data["assurances_total"], int)
    assert isinstance(data["assurances_cleared"], int)
    assert is_iso8601_timestamp(data.get("submission_deadline", "")), \
        "submission_deadline must be ISO 8601"
    _assert_money_field(data, "offered_federal_obligated", nullable=True)
    _assert_money_field(data, "offered_entitlement_portion", nullable=True)
    assert data.get("created_grant_id") is None or is_valid_uuid(data["created_grant_id"])
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "RETURNED", "OFFERED", "ACCEPTED", "DECLINED", "EXPIRED",
    ]


def assert_sponsor_assurance(data: dict):
    _assert_lean_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data["assurance_code"] in [
        "TITLE_VI", "BUY_AMERICAN", "DBE_PROGRAM",
        "ENVIRONMENTAL_REVIEW", "PREVAILING_WAGE", "AIRPORT_FEES",
    ]
    assert data.get("certified_by_user_id") is None or isinstance(
        data["certified_by_user_id"], str)
    assert data["status"] in ["PENDING", "CERTIFIED", "WAIVED"]


def assert_grant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["grant_number"], str) and data["grant_number"].startswith("AIP-")
    _assert_money_field(data, "federal_share_pct")
    _assert_money_field(data, "total_budget")
    _assert_money_field(data, "federal_obligated")
    _assert_money_field(data, "federal_drawn")
    _assert_money_field(data, "federal_available")
    _assert_money_field(data, "state_share_estimated")
    _assert_money_field(data, "local_share_estimated")
    _assert_money_field(data, "entitlement_portion")
    assert data["status"] in ["ACTIVE", "CLOSEOUT_REQUESTED", "UNDER_AUDIT", "CLOSED"]


def assert_grant_amendment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("grant_id", "")), "grant_id must be a UUID"
    _assert_money_field(data, "added_scope_cost")
    assert isinstance(data["reason"], str)
    _assert_money_field(data, "contingency_amount")
    _assert_money_field(data, "new_total_budget")
    _assert_money_field(data, "federal_delta")
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED", "SUPERSEDED"]


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert isinstance(data["contractor_name"], str) and len(data["contractor_name"]) > 0
    assert isinstance(data["dbe_certified"], bool)
    assert data["status"] in ["REGISTERED", "SUSPENDED"]


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("grant_id", "")), "grant_id must be a UUID"
    assert is_valid_uuid(data.get("cip_project_id", "")), "cip_project_id must be a UUID"
    assert is_valid_uuid(data.get("contractor_id", "")), "contractor_id must be a UUID"
    _assert_money_field(data, "awarded_value")
    _assert_money_field(data, "dbe_goal_pct")
    _assert_money_field(data, "retainage_pct")
    _assert_money_field(data, "invoiced_total")
    _assert_money_field(data, "remaining_value")
    _assert_money_field(data, "retainage_held")
    assert data["dbe_posture"] in ["UNEVALUATED", "COMPLIANT", "NON_COMPLIANT"]
    assert data["status"] in ["AWARDED", "CLOSED"]


def assert_dbe_report(data: dict):
    _assert_lean_fields(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["reporting_period"], str) and len(data["reporting_period"]) > 0
    _assert_money_field(data, "dbe_paid_amount")
    _assert_money_field(data, "total_paid_amount")
    _assert_money_field(data, "achieved_dbe_pct")
    assert data["status"] in ["PENDING", "COMPLIANT", "SHORTFALL"]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["invoice_number"], str) and len(data["invoice_number"]) > 0
    assert isinstance(data["period"], str) and len(data["period"]) > 0
    _assert_money_field(data, "gross_amount")
    _assert_money_field(data, "retainage_withheld")
    _assert_money_field(data, "net_payable")
    assert data.get("drawdown_id") is None or is_valid_uuid(data["drawdown_id"])
    assert data["status"] in [
        "SUBMITTED", "VERIFIED", "REJECTED", "INCLUDED", "PAID", "WITHHELD",
    ]


def assert_reimbursement_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("grant_id", "")), "grant_id must be a UUID"
    assert isinstance(data["invoice_ids"], list)
    _assert_money_field(data, "total_net")
    _assert_money_field(data, "federal_amount")
    assert isinstance(data["prepared_by_user_id"], str)
    assert data.get("certified_by_user_id") is None or isinstance(
        data["certified_by_user_id"], str)
    assert data["status"] in ["DRAFT", "CERTIFIED", "SUBMITTED", "APPROVED"]


def assert_audit_finding(data: dict):
    _assert_lean_fields(data)
    assert is_valid_uuid(data.get("grant_id", "")), "grant_id must be a UUID"
    assert data["finding_code"] in [
        "INELIGIBLE_COST", "MISSING_DOCUMENTATION", "DBE_SHORTFALL", "PROCUREMENT", "OTHER",
    ]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["description"], str)
    assert data["status"] in ["OPEN", "RESOLVED"]


def assert_grant_asset(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("grant_id", "")), "grant_id must be a UUID"
    assert data["asset_kind"] in ["EQUIPMENT", "LAND"]
    assert isinstance(data["description"], str)
    _assert_money_field(data, "acquisition_federal_share")
    assert isinstance(data["useful_life_years"], int)
    assert is_iso8601_timestamp(data.get("in_service_date", "")), \
        "in_service_date must be ISO 8601"
    _assert_money_field(data, "service_credit_value")
    _assert_money_field(data, "remaining_restricted_value")
    _assert_money_field(data, "payback_due")
    assert data["status"] in ["IN_SERVICE", "DISPOSAL_REQUESTED", "DISPOSED"]


def assert_construction_phase(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("grant_id", "")), "grant_id must be a UUID"
    assert is_valid_uuid(data.get("cip_project_id", "")), "cip_project_id must be a UUID"
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert is_valid_uuid(data.get("contractor_id", "")), "contractor_id must be a UUID"
    assert data["closure_type"] in ["FULL_CLOSURE", "NIGHT_ONLY"]
    assert is_iso8601_timestamp(data.get("start_utc", "")), "start_utc must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_utc", "")), "end_utc must be ISO 8601"
    assert data["status"] in ["PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"]


def assert_grant_funds_conserved(grant: dict):
    """PRD §3.4: federal_available is always the obligated amount minus the drawn amount."""
    assert grant["federal_obligated"] == pytest.approx(
        grant["federal_drawn"] + grant["federal_available"], abs=0.005), (
        f"federal_obligated {grant['federal_obligated']} != federal_drawn "
        f"{grant['federal_drawn']} + federal_available {grant['federal_available']}"
    )


def assert_asset_value_conserved(asset: dict):
    """PRD §3.9: remaining_restricted_value is the exact remainder of
    acquisition_federal_share minus service_credit_value while the asset is in service."""
    assert asset["acquisition_federal_share"] == pytest.approx(
        asset["service_credit_value"] + asset["remaining_restricted_value"], abs=0.005), (
        f"acquisition_federal_share {asset['acquisition_federal_share']} != "
        f"service_credit_value {asset['service_credit_value']} + "
        f"remaining_restricted_value {asset['remaining_restricted_value']}"
    )
