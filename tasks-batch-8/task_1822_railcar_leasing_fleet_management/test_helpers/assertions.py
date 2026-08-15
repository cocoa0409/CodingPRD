"""Entity assertions and domain invariant checkers (PRD §2.4 common fields,
§3 per-entity field shapes)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer (PRD §2.4)"
    )


def assert_lessee(data: dict):
    _assert_common(data, "Lessee")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["credit_tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["security_deposit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_railcar(data: dict):
    _assert_common(data, "Railcar")
    assert isinstance(data["car_mark"], str) and data["car_mark"]
    assert data["car_type"] in (
        "BOX", "COVERED_HOPPER", "GONDOLA", "FLAT", "TANK_GENERAL", "TANK_PRESSURE",
    )
    assert isinstance(data["built_year"], int)
    assert isinstance(data["car_age_years"], int)
    assert isinstance(data["cumulative_miles"], int)
    assert data["compliance_posture"] in ("COMPLIANT", "RETROFIT_DUE", "NON_COMPLIANT")
    assert data["status"] in (
        "AVAILABLE", "ON_LEASE", "IN_SHOP", "RETIREMENT_PENDING", "RETIRED",
    )
    assert isinstance(data["open_shop_repair_count"], int)


def assert_lease_agreement(data: dict):
    _assert_common(data, "LeaseAgreement")
    assert isinstance(data["lessee_id"], str)
    assert data["lease_type"] in ("FULL_SERVICE", "NET")
    assert isinstance(data["base_daily_rate_cents"], int)
    assert isinstance(data["car_hire_lessor_share_pct"], int)
    assert isinstance(data["authorized_repair_cap_cents"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "ACTIVE", "EXPIRED", "TERMINATED",
    )


def assert_tariff_rate(data: dict):
    _assert_common(data, "TariffRate")
    assert data["rate_kind"] in ("CAR_HIRE_BASE", "MILEAGE_CREDIT")
    assert isinstance(data["unit_rate_cents"], int)
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)


def assert_lease_assignment(data: dict):
    _assert_common(data, "LeaseAssignment")
    assert isinstance(data["lease_id"], str)
    assert isinstance(data["railcar_id"], str)
    assert data["planned_commodity"] in (
        "GRAIN", "COAL", "PLASTIC_PELLETS", "CEMENT", "LUMBER", "CRUDE_OIL",
        "GASOLINE", "ETHANOL", "CORN_SYRUP", "CHEMICAL_SOLVENT",
    )
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert data["status"] in (
        "SCHEDULED", "ON_LEASE", "RETURNED", "SETTLED", "CANCELLED",
    )


def assert_mileage_report(data: dict):
    _assert_common(data, "MileageReport")
    assert isinstance(data["railcar_id"], str)
    assert isinstance(data["lease_assignment_id"], str)
    assert isinstance(data["report_month"], str)
    assert isinstance(data["loaded_miles"], int)
    assert isinstance(data["empty_miles"], int)
    assert data["status"] in ("SUBMITTED", "VALIDATED", "DISPUTED")


def assert_car_hire_statement(data: dict):
    _assert_common(data, "CarHireStatement")
    assert isinstance(data["lease_assignment_id"], str)
    assert isinstance(data["railcar_id"], str)
    assert isinstance(data["lessee_id"], str)
    assert isinstance(data["statement_month"], str)
    assert isinstance(data["days_on_lease"], int)
    assert isinstance(data["gross_car_hire_cents"], int)
    assert isinstance(data["loaded_miles_used"], int)
    assert isinstance(data["tier_excess_miles"], int)
    assert isinstance(data["mileage_credit_cents"], int)
    assert isinstance(data["provisional_net_cents"], int)
    assert data["tariff_source"] in ("CURRENT", "PINNED")
    assert data["status"] in ("PROVISIONAL", "DISPUTED", "FINALIZED", "SETTLED")


def assert_repair_authorization(data: dict):
    _assert_common(data, "RepairAuthorization")
    assert isinstance(data["railcar_id"], str)
    assert data["defect_cause"] in ("WEAR_AND_TEAR", "LESSEE_DAMAGE", "PRE_EXISTING")
    assert isinstance(data["estimate_cents"], int)
    assert isinstance(data["requires_shop"], bool)
    assert isinstance(data["lessee_share_cents"], int)
    assert isinstance(data["lessor_share_cents"], int)
    assert isinstance(data["lessee_preauth_required"], bool)
    assert isinstance(data["lessee_preauthorized"], bool)
    assert isinstance(data["revision_count"], int)
    assert data["status"] in (
        "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "IN_PROGRESS",
        "COMPLETED", "REJECTED",
    )


def assert_cleaning_record(data: dict):
    _assert_common(data, "CleaningRecord")
    assert isinstance(data["railcar_id"], str)
    assert data["cleaning_grade_required"] in ("WASH", "STEAM_CLEAN")
    assert data["bill_to"] in ("LESSEE", "LESSOR")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CERTIFIED", "FAILED")


def assert_damage_assessment(data: dict):
    _assert_common(data, "DamageAssessment")
    assert isinstance(data["lease_assignment_id"], str)
    assert isinstance(data["railcar_id"], str)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "DISPUTED", "FINALIZED", "INVOICED", "PAID",
    )


def assert_compliance_directive(data: dict):
    _assert_common(data, "ComplianceDirective")
    assert isinstance(data["directive_code"], str) and data["directive_code"]
    assert isinstance(data["applies_to_car_types"], list)
    assert isinstance(data["retrofit_deadline"], str)
    assert isinstance(data["grace_days"], int)
    assert isinstance(data["daily_penalty_cents"], int)
    assert isinstance(data["penalty_cap_cents"], int)
    assert data["status"] in ("ANNOUNCED", "EFFECTIVE")


def assert_retrofit_order(data: dict):
    _assert_common(data, "RetrofitOrder")
    assert isinstance(data["railcar_id"], str)
    assert isinstance(data["directive_id"], str)
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["deferral_count"], int)
    assert data["status"] in (
        "SCHEDULED", "DEFERRED", "IN_PROGRESS", "COMPLETED", "CERTIFIED",
        "CANCELLED",
    )


def assert_retirement_case(data: dict):
    _assert_common(data, "RetirementCase")
    assert isinstance(data["railcar_id"], str)
    assert data["reason"] in (
        "AGE_LIMIT", "DAMAGE_BEYOND_REPAIR", "OBSOLESCENCE", "DIRECTIVE_ECONOMIC",
    )
    assert isinstance(data["proposer_user_id"], str)
    assert data["status"] in (
        "PROPOSED", "APPRAISED", "APPROVED", "EXECUTED", "CANCELLED",
    )


def assert_capital_pool(data: dict):
    _assert_common(data, "CapitalPool")
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["replenishment_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["delivered_spend_cents"], int)
    assert isinstance(data["available_cents"], int)


def assert_purchase_commitment(data: dict):
    _assert_common(data, "PurchaseCommitment")
    assert isinstance(data["pool_id"], str)
    assert isinstance(data["car_type"], str)
    assert isinstance(data["unit_cost_cents"], int)
    assert data["status"] in ("COMMITTED", "DELIVERED", "CANCELLED")


def assert_pool_available_invariant(pool: dict):
    """PRD §3.14 waterfall: available = opening + replenishment - committed
    - delivered_spend."""
    expected = (
        pool["opening_balance_cents"]
        + pool["replenishment_cents"]
        - pool["committed_cents"]
        - pool["delivered_spend_cents"]
    )
    assert pool["available_cents"] == expected, (
        f"available_cents {pool['available_cents']} != waterfall {expected}"
    )
