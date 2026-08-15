"""Entity assertions and domain invariant checkers (PRD sections 2.4, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity_label}.id must be a server-minted UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_label}.version must be a positive integer, got {data.get('version')}"


def assert_dealer(data: dict):
    """Validate a Dealer response against the PRD contract."""
    _assert_common_fields(data, "Dealer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert isinstance(data["region"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] > 0
    assert isinstance(data["min_stock_value_cents"], int)
    assert data["min_stock_value_cents"] >= 0
    assert isinstance(data["floorplan_utilization_cents"], int)
    assert isinstance(data["floorplan_available_cents"], int)
    assert isinstance(data["default_loss_cents"], int)
    assert isinstance(data["chargeback_balance_cents"], int)
    assert isinstance(data["discount_reconciliation_cents"], int)
    assert isinstance(data["parts_purchases_ytd_cents"], int)
    assert isinstance(data["stock_observed_value_cents"], int)
    assert isinstance(data["stock_compliant"], bool)
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert data["status"] in ("ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_dealer_floorplan_invariants(data: dict):
    """Floor-plan credit invariant: available == limit - utilization (PRD 3.1)."""
    assert data["floorplan_utilization_cents"] >= 0
    assert data["floorplan_available_cents"] == (
        data["credit_limit_cents"] - data["floorplan_utilization_cents"]
    ), (
        "floorplan_available_cents must equal credit_limit_cents minus "
        f"floorplan_utilization_cents: {data['floorplan_available_cents']} != "
        f"{data['credit_limit_cents']} - {data['floorplan_utilization_cents']}"
    )


def assert_agreement(data: dict):
    _assert_common_fields(data, "DealerAgreement")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["agreement_code"], str) and data["agreement_code"]
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "EXPIRED",
                              "TERMINATED")


def assert_assignment(data: dict):
    _assert_common_fields(data, "TerritoryAssignment")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert data["coverage_type"] in ("EXCLUSIVE", "SHARED")
    assert isinstance(data["starts_on"], str)
    assert isinstance(data["ends_on"], str)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_sales_target(data: dict):
    _assert_common_fields(data, "SalesTarget")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_quarter"], int)
    assert 1 <= data["period_quarter"] <= 4
    assert isinstance(data["target_units"], int) and data["target_units"] > 0
    assert isinstance(data["achieved_units"], int) and data["achieved_units"] >= 0
    assert data["final_discount_rate"] is None or isinstance(
        data["final_discount_rate"], (int, float))
    assert data["status"] in ("OPEN", "CLOSED_MET", "CLOSED_MISSED")


def assert_unit_sale(data: dict):
    _assert_common_fields(data, "UnitSale")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["unit_serial"], str) and data["unit_serial"]
    assert isinstance(data["sale_date"], str)
    assert isinstance(data["list_price_cents"], int)
    assert data["list_price_cents"] > 0
    assert isinstance(data["provisional_discount_cents"], int)
    assert data["final_discount_cents"] is None or isinstance(
        data["final_discount_cents"], int)
    assert data["status"] in ("REPORTED", "ACCEPTED", "REJECTED", "VOIDED")


def assert_advance(data: dict):
    _assert_common_fields(data, "FloorPlanAdvance")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["unit_serial"], str) and data["unit_serial"]
    assert isinstance(data["advance_cents"], int) and data["advance_cents"] > 0
    assert isinstance(data["paid_curtailments_cents"], int)
    assert 0 <= data["paid_curtailments_cents"] <= data["advance_cents"]
    assert isinstance(data["accrued_interest_cents"], int)
    assert data["accrued_interest_cents"] >= 0
    assert data["status"] in ("OPEN", "CURTAILED", "PAST_DUE", "PAID_OFF",
                              "DEFAULTED")


def assert_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["unit_serial"], str) and data["unit_serial"]
    assert isinstance(data["parts_cost_cents"], int)
    assert data["parts_cost_cents"] >= 0
    assert isinstance(data["labor_hours"], (int, float))
    assert data["labor_hours"] >= 0
    assert isinstance(data["claim_amount_cents"], int)
    assert data["paid_amount_cents"] is None or isinstance(
        data["paid_amount_cents"], int)
    assert data["chargeback_amount_cents"] is None or isinstance(
        data["chargeback_amount_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "PAID",
                              "AUDIT_FLAGGED", "CHARGED_BACK", "DISPUTED")


def assert_parts_return(data: dict):
    _assert_common_fields(data, "PartsReturn")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["return_year"], int)
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    for line in data["lines"]:
        assert isinstance(line["part_number"], str) and line["part_number"]
        assert isinstance(line["quantity"], int) and line["quantity"] > 0
        assert isinstance(line["unit_credit_cents"], int)
        assert line["unit_credit_cents"] > 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "CREDITED", "REJECTED",
                              "REVERSED")


def assert_certification(data: dict):
    _assert_common_fields(data, "Certification")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["cert_code"], str) and data["cert_code"]
    assert isinstance(data["earned_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ("PENDING_VERIFICATION", "ACTIVE", "REJECTED",
                              "EXPIRED")


def assert_lead(data: dict):
    _assert_common_fields(data, "Lead")
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert isinstance(data["product_line"], str) and data["product_line"]
    assert isinstance(data["estimated_value_cents"], int)
    assert data["estimated_value_cents"] > 0
    assert isinstance(data["contact_name"], str)
    assert data["routed_dealer_id"] is None or is_valid_uuid(
        data["routed_dealer_id"])
    assert data["routed_assignment_id"] is None or is_valid_uuid(
        data["routed_assignment_id"])
    assert isinstance(data["declined_dealer_ids"], list)
    assert data["status"] in ("NEW", "ROUTED", "DECLINED", "ORPHANED",
                              "EXPIRED", "ACCEPTED")


def assert_scorecard(data: dict):
    """Validate a scorecard response (PRD 3.8 field set)."""
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_quarter"], int)
    assert data["variant"] in ("STRICT", "INCLUSIVE")
    for field in ("sales_score", "service_score", "training_score",
                  "parts_score", "total_score"):
        assert isinstance(data[field], (int, float)), \
            f"scorecard.{field} must be numeric, got {data.get(field)}"
        assert 0 <= data[field] <= 100, \
            f"scorecard.{field} out of range: {data[field]}"
