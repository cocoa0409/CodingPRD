"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version, for entities that carry the full set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_bike_model(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["model_class"] in {"STANDARD", "EBIKE", "CARGO_EBIKE"}
    assert data["status"] in {"ACTIVE", "RETIRED"}
    for f in ("monthly_fee_cents", "daily_rate_cents", "purchase_price_cents",
              "deposit_cents", "fleet_size", "total_bikes", "available_count"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_account(data: dict):
    assert_common_fields(data)
    assert data["account_type"] in {"SUBSCRIBER", "FLEET"}
    assert data["status"] in {"ACTIVE", "SUSPENDED"}
    assert data["rental_cap"] >= 1
    assert data["wallet_credit_cents"] >= 0
    assert data["active_rental_count"] >= 0


def assert_rental(data: dict):
    assert_common_fields(data)
    assert data["rental_mode"] in {"MONTHLY", "DAILY"}
    assert data["lifecycle_status"] in {
        "RESERVED", "DELIVERED", "ACTIVE", "IN_SERVICE",
        "RETURN_REQUESTED", "RETURNED", "BOUGHT_OUT", "CANCELLED",
    }
    assert data["billing_status"] in {
        "DEPOSIT_HELD", "BILLING_ACTIVE", "SETTLED", "WRITTEN_OFF",
    }
    assert data["deposit_cents"] >= 0
    assert data["completed_cycles"] >= 0


def assert_bike(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("model_id", "")), "model_id must be a valid UUID"
    assert data["bike_status"] in {"AVAILABLE", "RESERVED", "OUT", "SERVICING", "RETIRED"}


def assert_delivery(data: dict):
    assert_common_fields(data)
    assert data["delivery_type"] in {"INITIAL", "SWAP", "PICKUP"}
    assert data["status"] in {"SCHEDULED", "COMPLETED", "CANCELLED"}


def assert_service_ticket(data: dict):
    assert_common_fields(data)
    assert data["issue_type"] in {"FLAT_TIRE", "BRAKE", "BATTERY", "MOTOR", "OTHER"}
    assert data["severity"] in {"MINOR", "MAJOR", "CRITICAL"}
    assert data["status"] in {"OPEN", "IN_PROGRESS", "RESOLVED", "REOPENED", "CLOSED"}


def assert_coverage_claim(data: dict):
    assert_common_fields(data)
    assert data["claim_type"] in {"THEFT", "DAMAGE"}
    assert data["status"] in {"FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "CLOSED"}
    assert data["approved_payout_cents"] >= 0


def assert_buyout_offer(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"QUOTED", "ACCEPTED"}
    assert data["quoted_price_cents"] >= 0
    assert data["equity_credit_cents"] >= 0


def assert_fleet_invoice(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"ISSUED", "PAID"}
    assert data["line_count"] >= 0
    assert data["amount_due_cents"] >= 0


def assert_inspection_report(data: dict):
    """InspectionReport is append-only: id + created_at only, no version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["bike_condition"] in {"GOOD", "WORN", "DAMAGED"}


def assert_no_version_field(data: dict):
    """InspectionReport carries no version field (common_fields:false)."""
    assert "version" not in data, "InspectionReport must NOT expose a version field"
