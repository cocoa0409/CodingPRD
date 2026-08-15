"""Entity assertions and domain invariant checkers (PRD sections 2.2-3.8)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """SyndicationEvent / DomainEvent carry only id + created_at (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_brokerage(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["home_state_code"] in [
        "FL", "CA", "WA", "NY", "TX", "RI", "MD", "NC", "SC", "MA", "GA", "NJ",
    ]
    assert isinstance(data["escrow_account_ref"], str)
    assert isinstance(data["license_no"], str)


def assert_broker_agent(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("brokerage_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["split_pct_basis"], int)
    assert 0 <= data["split_pct_basis"] <= 9000
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_client(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ["SELLER", "BUYER", "BOTH"]
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_vessel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["hin"], str) and len(data["hin"]) == 12
    assert data["documentation_mode"] in ["USCG", "STATE"]
    assert data["liens_status"] in ["CLEAN", "ENCUMBERED"]


def assert_listing(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "ACTIVE", "SUSPENDED", "UNDER_CONTRACT", "CLOSED", "EXPIRED", "CANCELLED",
    ]
    assert data["syndication_status"] in ["NOT_SENT", "SYNDICATED", "STALE", "WITHDRAWN"]
    assert isinstance(data["list_price_cents"], int)


def assert_offer(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "PENDING", "COUNTERED", "ACCEPTED", "REJECTED", "EXPIRED",
        "WITHDRAWN", "CLOSED", "FAILED",
    ]
    assert isinstance(data["round_no"], int) and data["round_no"] >= 1
    assert isinstance(data["offer_price_cents"], int)
    assert isinstance(data["deposit_pct_basis"], int)


def assert_contingency(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ["SURVEY", "SEA_TRIAL", "FINANCING", "DOCUMENTATION"]
    assert data["status"] in ["OPEN", "SATISFIED", "WAIVED", "OBJECTED", "EXPIRED"]


def assert_escrow_entry(data: dict):
    _assert_common_fields(data)
    assert data["entry_type"] in ["DEPOSIT", "RELEASE", "REFUND", "FORFEIT"]
    assert data["status"] in [
        "PENDING", "CLEARED", "DISBURSED", "REFUNDED", "FORFEITED", "VOIDED",
    ]
    assert isinstance(data["amount_cents"], int)


def assert_lien(data: dict):
    _assert_common_fields(data)
    assert data["instrument_type"] in ["PREFERRED_MORTGAGE", "UCC1", "MECHANIC"]
    assert data["status"] in ["RECORDED", "PARTIALLY_SATISFIED", "SATISFIED", "RELEASED"]
    assert isinstance(data["amount_cents"], int)


def assert_documentation_record(data: dict):
    _assert_common_fields(data)
    assert data["record_kind"] in ["USCG_COD", "STATE_TITLE", "ABSTRACT"]
    assert data["status"] in ["VALID", "SUPERSEDED", "TRANSFERRED", "REVOKED"]


def assert_closing_statement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "BALANCED", "APPROVED", "DISBURSED", "VOIDED"]
    assert data["rounding_mode"] in ["PER_LINE_THEN_SUM", "SUM_THEN_PER_LINE"]


def assert_tax_assessment(data: dict):
    _assert_common_fields(data)
    assert data["assessment_kind"] in ["SALES_TAX", "USE_TAX"]
    assert data["exemption_code"] in ["NONE", "OFFSHORE_DELIVERY", "NONRESIDENT_REMOVAL"]
    assert data["status"] in ["ASSESSED", "FILED", "EXEMPT", "VOIDED"]


def assert_title_transfer(data: dict):
    _assert_common_fields(data)
    assert data["warranty_of_title"] in ["FULL", "QUITCLAIM", "SPECIAL"]
    assert data["status"] in ["DRAFT", "EXECUTED", "RECORDED", "REVOKED"]


def assert_syndication_event(data: dict):
    _assert_append_only_fields(data)
    assert data["channel"] in ["YACHTWORLD", "BOATS_COM", "BOATTRADER", "DENISON_MLS"]
    assert data["outcome"] in ["ACKED", "REJECTED"]


def assert_commission_side_split_invariant(statement: dict):
    """PRD 3.7: the two sides sum exactly to commission_cents, always."""
    total = statement["listing_side_cents"] + statement["selling_side_cents"]
    assert total == statement["commission_cents"], (
        f"listing_side_cents + selling_side_cents must equal commission_cents; "
        f"got {statement['listing_side_cents']} + {statement['selling_side_cents']} "
        f"!= {statement['commission_cents']}"
    )
