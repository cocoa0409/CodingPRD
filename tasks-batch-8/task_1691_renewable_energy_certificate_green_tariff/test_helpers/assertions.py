"""Entity assertions and domain invariant checkers.

Every assert_* validates the PRD §2.5 common field set (id, created_at,
updated_at, version) plus the entity's declared fields and status enum.
Retirement is the PRD §2.5 exception: assert_retirement requires the ABSENCE
of updated_at and version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

GENERATOR_STATUSES = [
    "REGISTERED", "VERIFICATION", "ACTIVE", "REJECTED", "SUSPENDED", "DECOMMISSIONED"
]
READING_STATUSES = ["SUBMITTED", "ATTESTED", "REJECTED", "ACCEPTED", "VOIDED"]
ACCOUNT_TYPES = ["GENERATOR", "BROKER", "PROGRAM"]
ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED"]
CERTIFICATE_STATUSES = ["ACTIVE", "LOCKED", "RETIRED", "REVOKED"]
TRADE_STATUSES = ["PROPOSED", "ACCEPTED", "SETTLED", "FAILED", "CANCELLED", "EXPIRED"]
SETTLEMENT_MODES = ["GROSS", "NET"]
MARKET_CLASSES = ["VOLUNTARY", "COMPLIANCE"]
PROGRAM_STATUSES = ["DRAFT", "OPEN", "ARCHIVED"]
SUBSCRIPTION_STATUSES = ["PENDING", "ACTIVE", "WAITLISTED", "SUSPENDED", "TERMINATED"]
BILL_STATUSES = ["DRAFT", "ISSUED", "DISPUTED", "VOID"]
RETIREMENT_PURPOSES = ["VOLUNTARY_PROGRAM", "COMPLIANCE", "WHOLESALE_CLAIM"]
OBLIGATION_STATUSES = ["OPEN", "MET", "CLOSED_MET", "CLOSED_SHORTFALL"]
REPORT_SCOPES = ["VOLUNTARY_PROGRAM", "COMPLIANCE_OBLIGATION"]
REPORT_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]
TECHNOLOGIES = ["SOLAR", "WIND", "HYDRO", "BIOMASS", "GEOTHERMAL"]


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_generator(data: dict):
    _assert_common_fields(data, "Generator")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["facility_code"], str) and data["facility_code"]
    assert data["technology"] in TECHNOLOGIES
    assert isinstance(data["nameplate_capacity_kw"], int) and data["nameplate_capacity_kw"] > 0
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["commissioning_date"], str)
    assert data["status"] in GENERATOR_STATUSES
    assert data.get("rejection_reason") is None or isinstance(data["rejection_reason"], str)
    assert isinstance(data["cumulative_accepted_kwh"], int) and data["cumulative_accepted_kwh"] >= 0
    assert isinstance(data["carryover_kwh"], int) and data["carryover_kwh"] >= 0
    assert isinstance(data["lifetime_minted_mwh"], int) and data["lifetime_minted_mwh"] >= 0
    assert isinstance(data["next_serial"], int) and data["next_serial"] >= 1


def assert_meter_reading(data: dict):
    _assert_common_fields(data, "MeterReading")
    assert is_valid_uuid(data.get("generator_id", "")), "MeterReading.generator_id must be a UUID"
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data["metered_kwh"], int) and data["metered_kwh"] > 0
    assert data["status"] in READING_STATUSES
    assert isinstance(data.get("submitted_by_user_id"), str) and data["submitted_by_user_id"]
    assert data.get("attested_by_user_id") is None or isinstance(data["attested_by_user_id"], str)
    assert data.get("rejection_reason") is None or isinstance(data["rejection_reason"], str)
    assert isinstance(data["minted"], bool)
    assert data.get("minted_vintage_month") is None or isinstance(
        data["minted_vintage_month"], str
    )


def assert_account(data: dict):
    _assert_common_fields(data, "Account")
    assert data["account_type"] in ACCOUNT_TYPES
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert data["status"] in ACCOUNT_STATUSES
    assert isinstance(data["failure_strikes"], int) and data["failure_strikes"] >= 0
    assert isinstance(data["active_holdings_mwh"], int) and data["active_holdings_mwh"] >= 0
    assert isinstance(data["locked_holdings_mwh"], int) and data["locked_holdings_mwh"] >= 0


def assert_certificate(data: dict):
    _assert_common_fields(data, "Certificate")
    assert is_valid_uuid(data.get("generator_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["vintage_month"], str) and len(data["vintage_month"]) == 7
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["technology"] in TECHNOLOGIES
    assert isinstance(data["serial_prefix"], str) and data["serial_prefix"]
    assert isinstance(data["serial_start"], int) and data["serial_start"] >= 1
    assert isinstance(data["serial_end"], int)
    assert isinstance(data["quantity_mwh"], int) and data["quantity_mwh"] > 0
    # PRD §2.9: a batch of N units occupies exactly N consecutive serials.
    assert data["serial_end"] == data["serial_start"] + data["quantity_mwh"] - 1, (
        f"serial_end {data['serial_end']} != serial_start {data['serial_start']} "
        f"+ quantity {data['quantity_mwh']} - 1"
    )
    assert data["status"] in CERTIFICATE_STATUSES


def assert_trade(data: dict):
    _assert_common_fields(data, "Trade")
    assert is_valid_uuid(data.get("from_account_id", ""))
    assert is_valid_uuid(data.get("to_account_id", ""))
    assert isinstance(data["items"], list) and len(data["items"]) >= 1
    for item in data["items"]:
        assert is_valid_uuid(item.get("certificate_id", ""))
        assert isinstance(item["quantity_mwh"], int) and item["quantity_mwh"] >= 1
    assert isinstance(data["unit_price_cents_per_mwh"], int) and data[
        "unit_price_cents_per_mwh"
    ] > 0
    assert data["settlement_mode"] in SETTLEMENT_MODES
    assert data["status"] in TRADE_STATUSES
    assert is_iso8601_timestamp(data.get("proposed_at", ""))
    for field in ("accepted_at", "settlement_deadline", "settled_at"):
        assert data.get(field) is None or is_iso8601_timestamp(data[field])
    for field in (
        "total_line_cents", "broker_fee_cents", "buyer_total_cents", "seller_proceeds_cents"
    ):
        assert data.get(field) is None or (
            isinstance(data[field], int) and data[field] >= 0
        )


def assert_program(data: dict):
    _assert_common_fields(data, "Program")
    assert isinstance(data["name"], str) and data["name"]
    assert data["market_class"] in MARKET_CLASSES
    assert isinstance(data["eligible_region_codes"], list)
    assert isinstance(data["eligible_technologies"], list)
    assert isinstance(data["capacity_cap_kw"], int) and data["capacity_cap_kw"] > 0
    assert isinstance(data["rate_tiers"], list) and len(data["rate_tiers"]) >= 1
    assert isinstance(data["annual_claim_cap_mwh"], int) and data["annual_claim_cap_mwh"] > 0
    assert data.get("holding_account_id") is None or isinstance(data["holding_account_id"], str)
    assert data["status"] in PROGRAM_STATUSES
    assert isinstance(data["committed_capacity_kw"], int) and data["committed_capacity_kw"] >= 0
    assert isinstance(data["retired_mwh_current_year"], int)
    # PRD §3.5: committed capacity may never exceed the cap.
    assert data["committed_capacity_kw"] <= data["capacity_cap_kw"], (
        f"committed_capacity_kw {data['committed_capacity_kw']} exceeds "
        f"capacity_cap_kw {data['capacity_cap_kw']}"
    )


def assert_subscription(data: dict):
    _assert_common_fields(data, "Subscription")
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["utility_account_no"], str) and data["utility_account_no"]
    assert isinstance(data["allocation_kw"], int) and data["allocation_kw"] > 0
    assert isinstance(data["estimated_usage_kwh"], int) and data["estimated_usage_kwh"] > 0
    assert data["status"] in SUBSCRIPTION_STATUSES
    for field in ("activated_at", "waitlisted_at", "terminated_at"):
        assert data.get(field) is None or is_iso8601_timestamp(data[field])


def assert_bill(data: dict):
    _assert_common_fields(data, "Bill")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["usage_kwh"], int) and data["usage_kwh"] >= 0
    assert isinstance(data["charges_cents"], int) and data["charges_cents"] >= 0
    assert data["status"] in BILL_STATUSES
    assert isinstance(data["provisional_credit_cents"], int) and data[
        "provisional_credit_cents"
    ] >= 0
    assert data.get("issued_credit_cents") is None or isinstance(data["issued_credit_cents"], int)
    for field in ("proration_active_days", "proration_days_in_period"):
        assert data.get(field) is None or isinstance(data[field], int)
    assert data.get("issued_at") is None or is_iso8601_timestamp(data["issued_at"])


def assert_retirement(data: dict):
    # PRD §2.5: retirement rows are immutable and carry ONLY id + created_at
    # of the common fields; updated_at and version are absent.
    assert is_valid_uuid(data.get("id", "")), "Retirement.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "Retirement must not carry updated_at"
    assert "version" not in data, "Retirement must not carry version"
    assert is_valid_uuid(data.get("certificate_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["purpose"] in RETIREMENT_PURPOSES
    assert isinstance(data["quantity_mwh"], int) and data["quantity_mwh"] > 0
    assert isinstance(data["vintage_month"], str) and len(data["vintage_month"]) == 7
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["technology"] in TECHNOLOGIES
    assert data.get("claimed_in_report_id") is None or isinstance(
        data["claimed_in_report_id"], str
    )


def assert_obligation(data: dict):
    _assert_common_fields(data, "ComplianceObligation")
    assert isinstance(data["lse_name"], str) and data["lse_name"]
    assert isinstance(data["year"], int)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["required_mwh"], int) and data["required_mwh"] > 0
    assert isinstance(data["penalty_rate_cents_per_mwh"], int)
    assert isinstance(data["covered_mwh"], int) and data["covered_mwh"] >= 0
    assert data["status"] in OBLIGATION_STATUSES
    assert data.get("penalty_cents") is None or isinstance(data["penalty_cents"], int)


def assert_claim_report(data: dict):
    _assert_common_fields(data, "ClaimReport")
    assert data["scope"] in REPORT_SCOPES
    assert isinstance(data["report_year"], int)
    assert data["status"] in REPORT_STATUSES
    assert isinstance(data["retirement_ids"], list)
    for rid in data["retirement_ids"]:
        assert is_valid_uuid(rid), f"pinned retirement id {rid!r} must be a UUID"
    assert isinstance(data["total_mwh"], int) and data["total_mwh"] >= 0
    assert isinstance(data["totals_by_technology"], dict)
    assert isinstance(data["totals_by_region"], dict)
    # PRD §3.9 reconciliation invariant: each bucket map sums to total_mwh.
    assert sum(data["totals_by_technology"].values()) == data["total_mwh"], (
        "totals_by_technology must reconcile to total_mwh"
    )
    assert sum(data["totals_by_region"].values()) == data["total_mwh"], (
        "totals_by_region must reconcile to total_mwh"
    )
    assert data.get("submitted_by_user_id") is None or isinstance(
        data["submitted_by_user_id"], str
    )
    assert data.get("rejection_reason") is None or isinstance(data["rejection_reason"], str)


def assert_holdings_conservation(account_a: dict, account_b: dict, total_mwh: int):
    """Two accounts' active holdings sum exactly to total_mwh (PRD §2.9)."""
    assert account_a["active_holdings_mwh"] + account_b["active_holdings_mwh"] == total_mwh, (
        f"holdings not conserved: {account_a['active_holdings_mwh']} + "
        f"{account_b['active_holdings_mwh']} != {total_mwh}"
    )
