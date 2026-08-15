"""Entity assertions and domain invariant checkers (PRD §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["display_name"], str)
    assert data["category"] in ("GASOLINE", "DIESEL")
    assert isinstance(data["federal_excise_tc_per_gal"], int)
    assert isinstance(data["temp_coeff"], (int, float)) and data["temp_coeff"] > 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_dealer_station(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["station_name"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["home_terminal_code"], str)
    assert isinstance(data["state_excise_tc_per_gal"], int)
    assert isinstance(data["local_option_tc_per_gal"], int)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_terms_days"], int)
    assert isinstance(data["current_exposure_cents"], int)
    assert data["operating_status"] in ("ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["credit_status"] in ("GOOD_STANDING", "WATCH", "HOLD")
    assert data["compliance_status"] in ("COMPLIANT", "CURE_PERIOD", "DEFAULT")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_supply_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["station_id"], str)
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)
    assert isinstance(data["committed_gallons"], int)
    assert isinstance(data["fulfilled_gallons"], int)
    assert isinstance(data["imaging_allowance_cents"], int)
    assert isinstance(data["margin_tc_per_gal"], int)
    assert isinstance(data["shortfall_penalty_tc_per_gal"], int)
    assert data["buyout_method"] in ("UNAMORTIZED_DISCOUNT", "LOST_MARGIN")
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["renewal_credit_cents"], int)
    assert data["status"] in (
        "DRAFT", "ACTIVE", "RENEWAL_PENDING", "DEFAULT_NOTICE",
        "BUYOUT_PENDING", "EXPIRED", "TERMINATED", "BOUGHT_OUT",
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_rack_price_posting(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["terminal_code"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["price_tc_per_gal"], int)
    assert data["status"] in ("DRAFT", "POSTED", "SUPERSEDED", "DISCARDED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_storage_tank(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["station_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["capacity_gallons"], int)
    assert isinstance(data["safe_fill_pct"], (int, float))
    assert isinstance(data["opening_physical_gallons"], int)
    assert isinstance(data["physical_gallons"], (int, float))
    assert isinstance(data["book_inventory_gallons"], (int, float))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_truck(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["truck_code"], str)
    assert isinstance(data["capacity_gallons"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_transport_drop(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["station_id"], str)
    assert isinstance(data["tank_id"], str)
    assert isinstance(data["truck_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["planned_gallons"], int)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["estimated_amount_cents"], int)
    assert isinstance(data["failure_count"], int)
    assert data["status"] in (
        "PLANNED", "SCHEDULED", "EN_ROUTE", "DELIVERED",
        "DELIVERY_FAILED", "RECONCILED", "CANCELLED",
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_meter_reading(data: dict):
    """MeterReading carries only id + created_at (no version / updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["tank_id"], str)
    assert isinstance(data["reading_at"], str)
    assert isinstance(data["totalizer_gallons"], int)
    assert isinstance(data["metered_gallons"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "MeterReading must not carry version"
    assert "updated_at" not in data, "MeterReading must not carry updated_at"


def assert_loss_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["station_id"], str)
    assert data["loss_type"] in ("DRIVE_OFF", "SHRINKAGE", "SPILL", "THEFT")
    assert isinstance(data["gallons"], int)
    assert isinstance(data["occurred_at"], str)
    assert isinstance(data["auto_generated"], bool)
    assert data["status"] in ("REPORTED", "VERIFIED", "DISPUTED", "WRITTEN_OFF", "VOIDED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_inventory_reconciliation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["station_id"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["threshold_gallons"], int)
    assert isinstance(data["book_gallons"], (int, float))
    assert isinstance(data["physical_gross_gallons"], (int, float))
    assert isinstance(data["variance_gross_gallons"], (int, float))
    assert isinstance(data["variance_net_gallons"], (int, float))
    assert data["status"] in ("OPEN", "VARIANCE_FLAGGED", "RESOLVED")
    assert isinstance(data["opener_user_id"], str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["station_id"], str)
    assert isinstance(data["drop_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["gallons_delivered"], int)
    assert isinstance(data["price_tc_per_gal"], int)
    assert isinstance(data["fuel_amount_cents"], int)
    assert isinstance(data["freight_amount_cents"], int)
    assert isinstance(data["tax_amount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["invoice_date"], str)
    assert isinstance(data["due_date"], str)
    assert data["status"] in ("ISSUED", "OVERDUE", "PAID", "VOID")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_eft_draft(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["station_id"], str)
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["attempts"], int)
    assert data["status"] in ("SCHEDULED", "SETTLED", "FAILED", "CANCELLED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_tax_remittance(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["state_code"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["due_date"], str)
    assert data["status"] in ("ACCRUING", "FILED", "PAID")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_brand_compliance_audit(data: dict):
    """BrandComplianceAudit carries only id + created_at (no version / updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["station_id"], str)
    assert isinstance(data["audit_date"], str)
    assert isinstance(data["score"], int)
    assert isinstance(data["deficiencies"], list)
    assert data["result"] in ("PASS", "FAIL")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "BrandComplianceAudit must not carry version"
    assert "updated_at" not in data, "BrandComplianceAudit must not carry updated_at"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_invoice_component_sum(invoice: dict):
    """total == fuel + freight + tax (per-component rounding before sum)."""
    assert invoice["total_cents"] == (
        invoice["fuel_amount_cents"]
        + invoice["freight_amount_cents"]
        + invoice["tax_amount_cents"]
    ), (
        f"total_cents {invoice['total_cents']} != fuel {invoice['fuel_amount_cents']} "
        f"+ freight {invoice['freight_amount_cents']} + tax {invoice['tax_amount_cents']}"
    )


def assert_buyout_net_never_negative(quote: dict):
    """Buyout net settlement is floored at zero."""
    assert quote["net_settlement_cents"] >= 0
    assert quote["net_settlement_cents"] == max(
        0, quote["base_cents"] - quote["shortfall_penalty_cents"]
    )
