"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Compare two ISO 8601 timestamps as instants.

    PRD §2.4 pins the VALUES of sent_at/effective_at/expires_at (derived from
    the logical clock) and §3 pins the day arithmetic, but no PRD sentence pins
    the string rendering of these fields (§2.5's three-fractional-digit format
    is stated only for created_at). Both "2026-09-02T09:00:00Z" and
    "2026-09-02T09:00:00.000Z" are PRD-conformant renderings of the same
    instant, so assertions compare parsed instants, never raw strings.
    """
    def _parse(s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    assert _parse(actual) == _parse(expected), (
        f"{label}: {actual!r} != {expected!r} (compared as instants)")

from .types import (
    AccountStatus,
    BatchStatus,
    ElectionChannel,
    ElectionStatus,
    FeeStatus,
    FeeType,
    NoticeParameter,
    NoticeStatus,
    OfferStatus,
    OfferTrigger,
    OfferType,
    PostingOrderPolicy,
    ProgramStatus,
    ReportStatus,
    RoutingBand,
    TransactionStatus,
    TransactionType,
    WaiverKind,
    WaiverReason,
    WaiverStatus,
)


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer")


def assert_overdraft_program(data: dict):
    _assert_common_fields(data, "program")
    assert isinstance(data["name"], str) and data["name"]
    for field in (
        "fee_amount_cents", "daily_fee_cap_cents", "max_daily_fees_count",
        "de_minimis_threshold_cents", "sustained_overdraft_days_threshold",
        "sustained_overdraft_fee_cents", "charge_off_grace_business_days",
        "notice_window_days", "steering_fee_count_threshold",
        "steering_window_days", "offer_expiry_days",
    ):
        assert isinstance(data[field], int), f"program.{field} must be an integer"
    assert data["posting_order_policy"] in [p.value for p in PostingOrderPolicy]
    assert isinstance(data["current_disclosure_version"], str)
    assert data["status"] in [s.value for s in ProgramStatus]


def assert_deposit_account(data: dict):
    _assert_common_fields(data, "account")
    assert is_valid_uuid(data.get("program_id", "")), "account.program_id must be a UUID"
    assert isinstance(data["holder_name"], str) and data["holder_name"]
    assert data["status"] in [s.value for s in AccountStatus]
    for field in (
        "ledger_balance_cents", "consecutive_negative_business_days",
        "restricted_business_days", "lifetime_fees_assessed_cents",
        "lifetime_fees_waived_cents", "charged_off_cents", "recovered_cents",
        "charge_off_original_cents",
    ):
        assert isinstance(data[field], int), f"account.{field} must be an integer"


def assert_opt_in_election(data: dict):
    _assert_common_fields(data, "election")
    assert is_valid_uuid(data.get("account_id", "")), "election.account_id must be a UUID"
    assert data["status"] in [s.value for s in ElectionStatus]
    assert data["channel"] in [c.value for c in ElectionChannel]
    assert isinstance(data["disclosure_version"], str)
    assert is_iso8601_timestamp(data.get("elected_at", ""))
    assert is_iso8601_timestamp(data.get("last_changed_at", ""))


def assert_account_transaction(data: dict):
    _assert_common_fields(data, "transaction")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["type"] in [t.value for t in TransactionType]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in [s.value for s in TransactionStatus]
    assert isinstance(data["authorized_date"], str)


def assert_posting_batch(data: dict):
    _assert_common_fields(data, "batch")
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["business_date"], str)
    assert data["status"] in [s.value for s in BatchStatus]
    for field in (
        "items_posted_count", "items_returned_count",
        "fees_assessed_count", "fees_assessed_cents",
    ):
        assert isinstance(data[field], int), f"batch.{field} must be an integer"


def assert_overdraft_fee(data: dict):
    _assert_common_fields(data, "fee")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["fee_type"] in [t.value for t in FeeType]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["waived_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert data["outstanding_cents"] == data["amount_cents"] - data["waived_cents"], (
        "fee.outstanding_cents must equal amount_cents - waived_cents")
    assert data["status"] in [s.value for s in FeeStatus]


def assert_fee_waiver_request(data: dict):
    _assert_common_fields(data, "waiver_request")
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["fee_ids"], list) and len(data["fee_ids"]) > 0
    assert data["kind"] in [k.value for k in WaiverKind]
    assert data["reason_code"] in [r.value for r in WaiverReason]
    assert isinstance(data["computed_total_cents"], int)
    assert data["routing_band"] in [b.value for b in RoutingBand]
    assert data["status"] in [s.value for s in WaiverStatus]
    assert isinstance(data["created_by_user_id"], str)
    assert isinstance(data["created_by_role"], str)


def assert_waiver_request_item(data: dict):
    # Per PRD §2.5 the waiver request item carries only id + created_at;
    # updated_at and version are absent.
    assert is_valid_uuid(data.get("id", "")), "waiver_item.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "waiver_item must not carry updated_at"
    assert "version" not in data, "waiver_item must not carry version"
    assert is_valid_uuid(data.get("waiver_request_id", ""))
    assert is_valid_uuid(data.get("fee_id", ""))
    assert isinstance(data["waived_cents"], int)


def assert_program_change_notice(data: dict):
    _assert_common_fields(data, "notice")
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["parameter"] in [p.value for p in NoticeParameter]
    assert isinstance(data["new_value"], str)
    assert data["status"] in [s.value for s in NoticeStatus]


def assert_education_offer(data: dict):
    _assert_common_fields(data, "offer")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["offer_type"] in [t.value for t in OfferType]
    assert data["trigger_reason"] in [t.value for t in OfferTrigger]
    assert data["status"] in [s.value for s in OfferStatus]
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_regulatory_report(data: dict):
    _assert_common_fields(data, "report")
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in [s.value for s in ReportStatus]


def assert_chargeoff_invariant(account: dict):
    """PRD §3.2: charged_off_cents + recovered_cents == charge_off_original_cents."""
    assert (
        account["charged_off_cents"] + account["recovered_cents"]
        == account["charge_off_original_cents"]
    ), (
        f"Charge-off invariant violated: {account['charged_off_cents']} + "
        f"{account['recovered_cents']} != {account['charge_off_original_cents']}")


def assert_fee_net_position(account: dict, expected_net: int):
    """Conserved quantity: ledger + lifetime assessed - lifetime waived."""
    actual = (
        account["ledger_balance_cents"]
        + account["lifetime_fees_assessed_cents"]
        - account["lifetime_fees_waived_cents"]
    )
    assert actual == expected_net, (
        f"Net position {actual} != expected {expected_net} "
        f"(ledger {account['ledger_balance_cents']}, "
        f"assessed {account['lifetime_fees_assessed_cents']}, "
        f"waived {account['lifetime_fees_waived_cents']})")
