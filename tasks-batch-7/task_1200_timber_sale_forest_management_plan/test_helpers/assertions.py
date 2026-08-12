"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_forester(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("license_no"), str)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("email"), str)


def assert_landowner(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("email"), str)
    assert isinstance(data.get("tax_id"), str)


def assert_buyer(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("company_name"), str)
    assert isinstance(data.get("license_no"), str)
    assert isinstance(data.get("prior_defaults"), int)


def assert_contractor(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("company_name"), str)
    assert isinstance(data.get("license_no"), str)


def assert_tract(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("county"), str)
    assert data.get("status") in ("OPEN", "ENROLLED_CONSERVATION")
    assert isinstance(data.get("version"), int)


def assert_stand(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("tract_id"), str)
    assert isinstance(data.get("acres"), (int, float))
    assert isinstance(data.get("primary_species"), str)


def assert_cruise(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("stand_id"), str)
    assert data.get("status") in (
        "DRAFT", "TALLIED", "RECONCILED", "CERTIFIED", "SUPERSEDED", "VOID"
    )
    assert isinstance(data.get("version"), int)


def assert_prescription(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in (
        "DRAFT", "PROPOSED", "APPROVED", "ACTIVE", "COMPLETED", "WITHDRAWN"
    )


def assert_sale(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in (
        "DRAFT", "OFFERED", "BIDDING_OPEN", "BIDDING_CLOSED",
        "AWARDED", "NO_SALE", "CANCELLED",
    )
    assert isinstance(data.get("version"), int)


def assert_bid(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in (
        "SUBMITTED", "SUPERSEDED", "WITHDRAWN", "DISQUALIFIED", "WINNING", "LOST"
    )
    assert isinstance(data.get("bid_total_cents"), int)


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in (
        "PENDING_BOND", "ACTIVE", "HARVESTING", "SUSPENDED",
        "HARVEST_COMPLETE", "DEFAULTED", "TERMINATED", "CLOSED",
    )
    assert isinstance(data.get("required_bond_amount_cents"), int)
    assert isinstance(data.get("cumulative_verified_bf"), int)
    assert isinstance(data.get("billed_total_cents"), int)
    assert isinstance(data.get("disbursed_total_cents"), int)
    assert isinstance(data.get("refunded_total_cents"), int)
    assert isinstance(data.get("holdback_balance_cents"), int)
    assert isinstance(data.get("consulting_fee_total_cents"), int)


def assert_bond(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ("POSTED", "FORFEIT_CLAIMED", "FORFEITED", "RELEASED")
    assert isinstance(data.get("amount_cents"), int)


def assert_scale_ticket(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ("DRAFT", "VERIFIED", "DISPUTED", "VOID")
    assert isinstance(data.get("bf_doyle"), int)
    assert isinstance(data.get("bf_international"), int)
    assert isinstance(data.get("bf_governing"), int)
    assert isinstance(data.get("log_count"), int)


def assert_settlement(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ("DRAFT", "APPROVED", "PAID", "REFUNDED", "VOID")
    assert isinstance(data.get("gross_cents"), int)
    assert isinstance(data.get("holdback_cents"), int)
    assert isinstance(data.get("fee_cents"), int)
    assert isinstance(data.get("net_cents"), int)


def assert_inspection(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in (
        "SCHEDULED", "CONDUCTED", "COMPLIANT", "NONCOMPLIANT", "CORRECTIVE_VERIFIED"
    )


def assert_obligation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in (
        "IMPOSED", "PLANTED", "SURVEYED", "SATISFIED", "REPLANT_REQUIRED", "DELINQUENT"
    )


def assert_survey(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ("RECORDED", "FINALIZED", "VOID")


def assert_carbon_valuation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ("VALUED", "ACCEPTED", "REJECTED", "SUPERSEDED")
    assert isinstance(data.get("gross_npv_cents"), int)
    assert isinstance(data.get("net_npv_cents"), int)
    assert data.get("recommendation") in ("CONSERVATION_FAVORED", "TIMBER_FAVORED")


def assert_settlement_invariants(data: dict):
    """Domain invariants: net = gross - holdback - fee (PRD §3.6)."""
    assert data["net_cents"] == data["gross_cents"] - data["holdback_cents"] - data["fee_cents"]


def assert_bond_waterfall_invariants(data: dict):
    """Forfeiture waterfall conservation: buckets sum to amount_cents (PRD §3.5)."""
    if data.get("status") == "FORFEITED":
        total = (
            data["admin_fee_cents"]
            + data["remediation_offset_cents"]
            + data["shortfall_offset_cents"]
            + data["refunded_cents"]
        )
        assert total == data["amount_cents"], (
            f"Waterfall buckets {total} must equal amount_cents {data['amount_cents']}"
        )
