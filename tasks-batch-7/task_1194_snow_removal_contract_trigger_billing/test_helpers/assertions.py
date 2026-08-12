"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be >= 1"


def assert_client(data: dict):
    _assert_common(data, "Client")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_exposure_cents"], int)


def assert_site(data: dict):
    _assert_common(data, "Site")
    assert isinstance(data["client_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["pavement_area_sqft"], int)


def assert_contract(data: dict):
    _assert_common(data, "Contract")
    assert data["contract_type"] in ("PER_PUSH", "SEASONAL", "HOURLY")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["season_billable_push_count"], int)
    assert isinstance(data["season_billable_minutes"], int)
    assert isinstance(data["season_billed_cents"], int)
    assert isinstance(data["unbilled_billable_cents"], int)
    assert isinstance(data["season_sla_miss_count"], int)
    assert isinstance(data["overage_active"], bool)


def assert_contract_site(data: dict):
    _assert_common(data, "ContractSite")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["priority_sequence"], int)
    assert isinstance(data["completion_target_minutes"], int) and data["completion_target_minutes"] > 0


def assert_amendment(data: dict):
    _assert_common(data, "ContractAmendment")
    assert isinstance(data["contract_id"], str)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_storm_event(data: dict):
    _assert_common(data, "StormEvent")
    assert isinstance(data["region_code"], str)
    assert data["status"] in ("REPORTED", "VERIFIED", "CHALLENGED", "CLOSED", "VOIDED")


def assert_observation(data: dict):
    """Append-only feed record: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "WeatherObservation.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only observation must not carry updated_at"
    assert "version" not in data, "append-only observation must not carry version"
    assert isinstance(data["storm_event_id"], str)
    assert isinstance(data["source_name"], str) and data["source_name"]
    assert data["accumulation_inches"] > 0


def assert_visit(data: dict):
    _assert_common(data, "ServiceVisit")
    assert data["execution_status"] in (
        "SCHEDULED", "IN_PROGRESS", "AWAITING_BACKUP", "COMPLETED",
        "MISSED", "CANCELLED", "VOIDED",
    )
    assert data["billing_status"] in (
        "PENDING", "BILLABLE_CONFIRMED", "NON_BILLABLE", "INVOICED",
        "DISPUTED", "SETTLED", "WRITTEN_OFF",
    )
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["site_id"], str)
    assert is_iso8601_timestamp(data.get("sla_deadline_at", "")), "sla_deadline_at must be ISO 8601"


def assert_material(data: dict):
    _assert_common(data, "MaterialApplication")
    assert data["material_type"] in ("ROCK_SALT", "ICE_MELT_BLEND", "LIQUID_BRINE")
    assert data["quantity_lbs"] > 0
    assert isinstance(data["rate_per_lb_cents_snapshot"], int)
    assert isinstance(data["line_cost_cents"], int)
    assert data["status"] in ("RECORDED", "VOIDED")


def assert_photo(data: dict):
    _assert_common(data, "ServicePhoto")
    assert data["phase"] in ("BEFORE", "AFTER")
    assert data["review_status"] in ("UPLOADED", "ACCEPTED", "REJECTED")


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert data["kind"] in ("EVENT", "PERIOD")
    assert data["status"] in (
        "DRAFT", "ISSUED", "PARTIALLY_CREDITED", "PARTIALLY_PAID", "PAID", "VOIDED",
    )
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["credit_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] - data["credit_cents"]


def assert_dispute(data: dict):
    _assert_common(data, "Dispute")
    assert data["reason"] in (
        "TRIGGER_NOT_MET", "INCOMPLETE_SERVICE", "PHOTO_INSUFFICIENT",
        "RATE_DISAGREEMENT", "MATERIAL_QUANTITY",
    )
    assert data["status"] in (
        "OPEN", "EVIDENCE_REVIEW", "RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "RESOLVED_REMOVED",
    )


def assert_claim(data: dict):
    _assert_common(data, "SlipFallClaim")
    assert data["severity"] in ("INJURY_REPORTED", "PROPERTY_DAMAGE", "NEAR_MISS")
    assert data["status"] in (
        "FILED", "DOCUMENTATION_REVIEW", "DOCUMENTED", "CLOSED", "WITHDRAWN",
    )


def assert_subcontractor(data: dict):
    _assert_common(data, "Subcontractor")
    assert data["status"] in ("PENDING", "APPROVED", "SUSPENDED")
    assert isinstance(data["assignments_released_count"], int)
    assert isinstance(data["assignments_failed_count"], int)
    assert isinstance(data["active_assignment_count"], int)
    assert isinstance(data["reliability_score"], int)
    assert 0 <= data["reliability_score"] <= 100


def assert_coverage(data: dict):
    _assert_common(data, "CoverageAssignment")
    assert data["status"] in ("CREATED", "ACTIVE", "RELEASED", "FAILED", "CANCELLED")


def assert_true_up(data: dict):
    _assert_common(data, "SeasonalTrueUp")
    assert data["status"] in ("DRAFT", "ISSUED", "SETTLED", "SUPERSEDED")
    assert isinstance(data["billable_push_count"], int)
    assert isinstance(data["overage_pushes"], int)
    assert isinstance(data["overage_cents"], int)
    assert isinstance(data["material_settlement_cents"], int)
    assert isinstance(data["performance_credit_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_contract_accumulator_invariants(contract: dict):
    """Season accumulators can never be negative and billed money is consistent."""
    assert contract["season_billable_push_count"] >= 0
    assert contract["season_billable_minutes"] >= 0
    assert contract["season_billed_cents"] >= 0
    assert contract["unbilled_billable_cents"] >= 0
    assert contract["season_sla_miss_count"] >= 0


def assert_client_exposure_invariants(client: dict):
    """Client exposure never exceeds the credit limit and never goes negative."""
    assert 0 <= client["credit_exposure_cents"] <= client["credit_limit_cents"]
