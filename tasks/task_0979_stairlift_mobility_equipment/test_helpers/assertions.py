"""Entity assertions and domain invariant checkers.

Each assert_* validates the PRD-promised shape of one resource: server-minted
UUID id, ISO 8601 timestamps, version integer (for lifecycle-tracked resources),
and the status vocabulary named in the PRD workflow narratives.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_lean(data: dict, entity: str):
    """Reference/log rows carry only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["home_region_code"], str)
    assert data["status"] in ("PROSPECT", "ACTIVE", "FORMER")
    assert isinstance(data["lifetime_outstanding_cents"], int)


def assert_home_assessment(data: dict):
    _assert_common(data, "HomeAssessment")
    assert data["status"] in ("SCHEDULED", "MEASURED", "APPROVED", "REJECTED", "SUPERSEDED")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["scheduled_date"], str)


def assert_product_model(data: dict):
    _assert_lean(data, "ProductModel")
    assert isinstance(data["model_code"], str) and len(data["model_code"]) > 0
    assert data["kind"] in ("STAIRLIFT", "VERTICAL_LIFT", "SCOOTER")
    assert isinstance(data["supports_curved"], bool)
    assert isinstance(data["supports_outdoor"], bool)
    assert isinstance(data["min_stair_width_mm"], int)
    assert isinstance(data["base_purchase_price_cents"], int)
    assert isinstance(data["monthly_rental_rate_cents"], int)
    assert isinstance(data["install_labor_hours"], int)


def assert_equipment_unit(data: dict):
    _assert_common(data, "EquipmentUnit")
    assert isinstance(data["model_code"], str)
    assert isinstance(data["serial_number"], str)
    assert data["condition_grade"] in ("NEW", "REFURB_A", "REFURB_B", "REFURB_C", "RETIRED")
    assert data["status"] in ("IN_STOCK", "RESERVED", "INSTALLED", "IN_SERVICE",
                              "REMOVED", "RETIRED")
    assert isinstance(data["lifetime_rental_months"], int)


def assert_quote(data: dict):
    _assert_common(data, "Quote")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["home_assessment_id"], str)
    assert isinstance(data["model_code"], str)
    assert data["acquisition_mode"] in ("RENTAL", "PURCHASE")
    assert data["status"] in ("DRAFT", "ISSUED", "ACCEPTED", "EXPIRED", "SUPERSEDED")
    assert isinstance(data["revision_number"], int)


def assert_funding_application(data: dict):
    _assert_common(data, "FundingApplication")
    assert isinstance(data["quote_id"], str)
    assert data["source_kind"] in ("STATE_GRANT", "INSURANCE", "CHARITY", "VETERAN_BENEFIT")
    assert isinstance(data["requested_cents"], int)
    assert data["status"] in ("PENDING", "APPROVED", "PARTIALLY_APPROVED",
                              "DENIED", "WITHDRAWN")
    assert isinstance(data["approved_cents"], int)
    assert isinstance(data["priority_rank"], int)


def assert_agreement(data: dict):
    _assert_common(data, "Agreement")
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["mode"] in ("RENTAL", "PURCHASE")
    assert data["status"] in ("PENDING_FUNDING", "FUNDED", "SCHEDULED", "INSTALLED",
                              "ACTIVE", "REMOVAL_REQUESTED", "REMOVED", "CLOSED",
                              "CANCELLED")
    assert isinstance(data["equipment_unit_id"], str)
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["funding_applied_cents"], int)
    assert isinstance(data["paid_to_date_cents"], int)
    assert isinstance(data["liability_waiver_signed"], bool)


def assert_install_job(data: dict):
    _assert_common(data, "InstallJob")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["technician_crew_id"], str)
    assert isinstance(data["scheduled_start_utc"], str)
    assert isinstance(data["scheduled_end_utc"], str)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED")


def assert_service_plan(data: dict):
    _assert_common(data, "ServicePlan")
    assert isinstance(data["agreement_id"], str)
    assert data["tier"] in ("BASIC", "STANDARD", "PREMIUM")
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED")
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["coverage_cap_cents"], int)
    assert isinstance(data["coverage_used_cents"], int)


def assert_warranty_claim(data: dict):
    _assert_common(data, "WarrantyClaim")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["service_plan_id"], str)
    assert data["claim_kind"] in ("MECHANICAL", "ELECTRICAL", "STRUCTURAL", "WEAR_AND_TEAR")
    assert isinstance(data["claimed_cents"], int)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "PAID")
    assert isinstance(data["approved_cents"], int)


def assert_removal_job(data: dict):
    _assert_common(data, "RemovalJob")
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["technician_crew_id"], str)
    assert isinstance(data["scheduled_start_utc"], str)
    assert isinstance(data["scheduled_end_utc"], str)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_audit_event(data: dict):
    _assert_lean(data, "AuditEvent")
    assert isinstance(data["entity_kind"], str)
    assert isinstance(data["entity_id"], str)
    assert isinstance(data["event_kind"], str)
    assert isinstance(data["actor_role"], str)


def assert_agreement_money_invariants(agreement: dict):
    """Money invariants on an Agreement: funding is capped at list price."""
    assert agreement["funding_applied_cents"] >= 0
    assert agreement["funding_applied_cents"] <= agreement["list_price_cents"]
    assert agreement["paid_to_date_cents"] >= 0


def assert_service_plan_cap_invariants(plan: dict):
    """Coverage used never exceeds the lifetime coverage cap."""
    assert 0 <= plan["coverage_used_cents"] <= plan["coverage_cap_cents"]
