"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 timestamp/date from the API into an aware datetime."""
    assert isinstance(value, str), f"expected ISO string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_fund(data: dict):
    _assert_common(data)
    for field in (
        "legal_name", "ein", "waterfall_hurdle_rate_bps", "waterfall_catchup_bps",
        "waterfall_carry_bps", "foreign_ownership_cap_pct_bps",
        "management_fee_rate_bps", "fee_discount_threshold_cents", "fee_discount_bps",
    ):
        assert field in data, f"Fund missing field {field}"


def assert_tax_year(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "OPEN", "BOOKS_CLOSED", "ALLOCATED", "UNDER_REVIEW", "APPROVED", "COMPLETED",
    ]
    assert isinstance(data["management_fee_cents"], int)
    assert isinstance(data["net_ordinary_income_cents"], int)


def assert_partner(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]
    assert data["partner_type"] in [
        "US_INDIVIDUAL", "US_ENTITY", "TAX_EXEMPT", "FOREIGN_INDIVIDUAL", "FOREIGN_ENTITY",
    ]
    assert data["partner_class"] in ["GENERAL", "LIMITED"]
    assert isinstance(data["is_foreign"], bool)
    for field in (
        "capital_account_balance_cents", "tax_basis_cents",
        "excess_distribution_gain_cents", "current_ownership_pct_bps",
    ):
        assert isinstance(data[field], int), f"{field} must be int cents/bps"
    assert data["tax_basis_cents"] >= 0, "tax basis floors at zero (PRD §3.2)"


def assert_capital_event(data: dict):
    _assert_common(data)
    assert data["event_type"] in [
        "CONTRIBUTION", "DISTRIBUTION", "ALLOCATION_SHARE",
        "TRANSFER_IN", "TRANSFER_OUT", "ADJUSTMENT",
    ]
    assert data["status"] in ["POSTED", "REVERSED"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_transfer(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "CONFIRMED", "SETTLED", "CANCELLED"]
    assert isinstance(data["pct_bps"], int)


def assert_allocation_run(data: dict):
    _assert_common(data)
    assert data["status"] in ["COMPUTED", "LOCKED", "STALE", "SUPERSEDED"]
    assert data["run_kind"] in ["PROVISIONAL", "FINAL"]
    assert isinstance(data["run_seq"], int) and data["run_seq"] >= 1


def assert_allocation_line(data: dict):
    _assert_common(data)
    assert data["category"] in ["ORDINARY", "CAPITAL_GAIN", "INTEREST"]
    assert isinstance(data["amount_cents"], int)
    assert data["applied_mechanism"] in [
        "PRO_RATA", "SPECIAL", "PREFERRED", "CATCHUP", "RESIDUAL",
    ]


def assert_special_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED"]
    assert data["category"] in ["ORDINARY", "CAPITAL_GAIN", "INTEREST"]
    assert isinstance(data["target_pct_bps"], int)


def assert_composite_filing(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "FILED", "ACCEPTED"]
    assert isinstance(data["included_partner_ids"], list)
    assert isinstance(data["total_state_source_income_cents"], int)
    assert isinstance(data["total_composite_tax_cents"], int)


def assert_withholding_record(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACCRUED", "PARTIALLY_REMITTED", "REMITTED", "RECONCILED"]
    assert data["method"] in ["SAFE_HARBOR", "CURRENT_ACTUAL"]
    assert data["quarter"] in [1, 2, 3, 4]
    assert data["rate_bps"] in [3700, 2100]
    assert isinstance(data["accrued_cents"], int)
    assert isinstance(data["remitted_cents"], int)
    assert isinstance(data["penalty_cents"], int)


def assert_k1_package(data: dict):
    _assert_common(data)
    assert data["prep_status"] in ["GENERATED", "REVIEWED", "APPROVED", "DELIVERED", "SUPERSEDED"]
    assert data["delivery_status"] in ["PENDING", "SENT", "ACKNOWLEDGED", "BOUNCED"]
    assert isinstance(data["generation"], int) and data["generation"] >= 1
    assert isinstance(data["line_snapshot"], dict)


def assert_k1_amendment(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPENED", "IN_PREP", "IN_REVIEW", "ISSUED"]
    assert data["reason"] in [
        "ALLOCATION_CHANGE", "PARTNER_DATA_FIX", "STATE_REAPPORTIONMENT", "LATE_K1_CORRECTION",
    ]


def assert_investor_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "ANSWERED", "REOPENED", "CLOSED"]
    assert data["category"] in [
        "ALLOCATION_QUESTION", "WITHHOLDING_QUESTION", "DELIVERY_ISSUE",
        "AMENDED_K1_QUESTION", "STATE_FILING_QUESTION",
    ]
    assert isinstance(data["is_escalated"], bool)


def assert_partner_ledger_invariants(data: dict):
    """Domain invariants on the partner's derived ledger readings (PRD §3.2)."""
    assert data["tax_basis_cents"] >= 0, "tax basis never goes below zero"
    assert data["excess_distribution_gain_cents"] >= 0, "excess distribution gain is non-negative"


def find_line(lines: list, partner_id: str, category: str) -> dict:
    """Locate the single allocation line for (partner, category) in a run."""
    matches = [
        l for l in lines
        if l.get("partner_id") == partner_id and l.get("category") == category
    ]
    assert len(matches) == 1, (
        f"expected exactly one line for partner {partner_id} / {category}, got {len(matches)}"
    )
    return matches[0]
