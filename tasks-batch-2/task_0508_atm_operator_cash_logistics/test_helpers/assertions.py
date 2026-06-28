"""Entity assertions and domain invariant checkers (ATM Cash Logistics API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_site_merchant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["commission_pct_bps"], int)
    assert isinstance(data["commission_flat_per_wd_cents"], int)
    assert isinstance(data["commission_monthly_ceiling_cents"], int)
    assert data["commission_basis"] in ("GREATER_OF", "PCT_ONLY", "FLAT_ONLY")
    assert data["payout_status"] in ("ACTIVE", "SUSPENDED")


def assert_vault(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["provisioned_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["in_transit_cents"], int)
    assert isinstance(data["in_machine_cents"], int)
    assert_vault_conservation(data)


def assert_vault_conservation(data: dict):
    """Conserved-quantity invariant (PRD §2.7): balance + in_transit + in_machine == provisioned."""
    total = data["balance_cents"] + data["in_transit_cents"] + data["in_machine_cents"]
    assert total == data["provisioned_cents"], (
        f"vault conservation broken: {data['balance_cents']} + {data['in_transit_cents']} "
        f"+ {data['in_machine_cents']} = {total} != provisioned {data['provisioned_cents']}"
    )
    assert data["balance_cents"] >= 0, "balance_cents must be non-negative"


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["carrier_name"], str) and len(data["carrier_name"]) > 0
    assert is_valid_uuid(data.get("vault_id", "")), "vault_id must be a valid UUID"
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_location(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["jurisdiction_code"] in ("CA", "NY", "TX", "FL")
    assert is_valid_uuid(data.get("site_merchant_id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data["address"], str)


def assert_atm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["serial_no"], str) and len(data["serial_no"]) > 0
    assert is_valid_uuid(data.get("location_id", ""))
    assert isinstance(data["note_denomination_cents"], int)
    assert isinstance(data["surcharge_cents"], int)
    assert data["operational_status"] in ("IN_SERVICE", "FAULTED", "OUT_OF_SERVICE")
    assert data["cash_status"] in ("EMPTY", "AWAITING_LOAD", "LOADED", "LOW", "RECONCILING")
    assert isinstance(data["monthly_wd_count"], int)
    assert isinstance(data["loaded_cents"], int)
    assert isinstance(data["dispensed_cents_since_load"], int)


def assert_cassette(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("atm_id", ""))
    assert data["position"] in ("C1", "C2", "C3", "C4")
    assert isinstance(data["loaded_cents"], int)
    assert isinstance(data["dispensed_cents"], int)
    assert data["balance_status"] in ("BALANCED", "OVER", "SHORT")


def assert_replenishment_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("atm_id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data["order_amount_cents"], int)
    assert data["forecast_basis"] in ("FORWARD", "CHRONOLOGICAL")
    assert data["status"] in ("SCHEDULED", "DISPATCHED", "LOADED", "SETTLED", "RECALLED")


def assert_transaction(data: dict):
    """Transaction is append-only — id + created_at only, NO updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("atm_id", ""))
    assert data["kind"] in ("WITHDRAWAL", "BALANCE_INQUIRY")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["surcharge_cents"], int)


def assert_cash_count(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("atm_id", ""))
    assert isinstance(data["counted_cents"], int)
    assert isinstance(data["expected_remaining_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["outcome"] in ("BALANCED", "OVER", "SHORT")
    assert isinstance(data["tolerance_cents"], int)


def assert_service_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("atm_id", ""))
    assert data["fault_kind"] in ("CASH_JAM", "CARD_READER", "NETWORK", "DISPENSER")
    assert data["severity"] in ("MINOR", "MAJOR")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED", "CANCELLED")
    assert isinstance(data["reopen_count"], int)


def assert_settlement_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("atm_id", ""))
    assert data["status"] in ("DRAFT", "SETTLED")


def assert_settlement_run_revenue(data: dict):
    """Computed revenue fields present and internally consistent (PRD §3.10)."""
    assert isinstance(data["withdrawal_count"], int)
    assert isinstance(data["surcharge_revenue_cents"], int)
    assert isinstance(data["interchange_revenue_cents"], int)
    assert isinstance(data["network_fee_cents"], int)
    assert isinstance(data["net_operator_revenue_cents"], int)
    expected_net = (
        data["surcharge_revenue_cents"]
        + data["interchange_revenue_cents"]
        - data["network_fee_cents"]
    )
    assert data["net_operator_revenue_cents"] == expected_net, (
        f"net_operator_revenue_cents {data['net_operator_revenue_cents']} != "
        f"surcharge {data['surcharge_revenue_cents']} + interchange "
        f"{data['interchange_revenue_cents']} - network {data['network_fee_cents']}"
    )


def assert_commission_statement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("settlement_run_id", ""))
    assert is_valid_uuid(data.get("site_merchant_id", ""))
    assert isinstance(data["pct_amount_cents"], int)
    assert isinstance(data["flat_amount_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["operator_keeps_cents"], int)
    assert data["status"] in ("ACCRUED", "PAID", "VOIDED")


def assert_fee_disclosure(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("atm_id", ""))
    assert isinstance(data["disclosed_surcharge_cents"], int)
    assert data["jurisdiction_code"] in ("CA", "NY", "TX", "FL")
    assert isinstance(data["regulatory_cap_cents"], int)
    assert isinstance(data["ack_text_present"], bool)
    assert data["status"] in ("DRAFT", "APPROVED", "REJECTED")
