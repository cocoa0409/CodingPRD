"""Entity assertions and small domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BriefStatus,
    BrandStatus,
    CreatorStatus,
    DealStatus,
    DeliverableStatus,
    DisclosureCheckStatus,
    DisputeStatus,
    InvoiceStatus,
    PerformanceReportStatus,
    PitchStatus,
    PayoutStatus,
    ReshootStatus,
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def assert_instant_equals(actual: str, expected: str) -> None:
    """Two timestamps denote the same instant (serialization may differ)."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def _assert_common(data: dict) -> None:
    """Common system-managed properties shared by every resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def _assert_int(data: dict, field: str, minimum=None) -> None:
    assert isinstance(data.get(field), int) and not isinstance(
        data.get(field), bool
    ), f"{field} must be an integer"
    if minimum is not None:
        assert data[field] >= minimum, f"{field} must be >= {minimum}"


def assert_creator(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("handle"), str) and data["handle"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert data.get("status") in [s.value for s in CreatorStatus]
    for f in ("followers", "avg_views_30d", "engagement_rate_bps"):
        _assert_int(data, f, 0)
    # The rate card is computed on activation (PRD §3.1); before that the
    # fields may legitimately be null on an APPLIED/SCREENING creator.
    for f in ("rate_card_cpm_cents", "rate_card_flat_cents"):
        if data.get(f) is not None:
            _assert_int(data, f, 0)
    for f in (
        "compliance_strikes",
        "lifetime_billed_cents",
        "pending_disclosure_count",
    ):
        _assert_int(data, f, 0)


def assert_brand(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in [s.value for s in BrandStatus]
    assert isinstance(data.get("credit_hold"), bool)
    _assert_int(data, "outstanding_balance_cents", 0)


def assert_brief(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("brand_id"), str) and data["brand_id"]
    assert data.get("status") in [s.value for s in BriefStatus]
    for f in (
        "min_followers",
        "min_engagement_bps",
        "slots_committed",
    ):
        _assert_int(data, f, 0)
    _assert_int(data, "slots_total", 1)
    _assert_int(data, "budget_cents", 1)
    _assert_int(data, "deliverables_per_slot", 1)
    _assert_int(data, "usage_rights_days", 1)
    _assert_int(data, "exclusivity_days", 0)
    assert isinstance(data.get("whitelisting_required"), bool)
    _assert_int(data, "revision_rounds_included", 0)


def assert_pitch(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("brief_id"), str) and data["brief_id"]
    assert isinstance(data.get("creator_id"), str) and data["creator_id"]
    assert data.get("status") in [s.value for s in PitchStatus]
    _assert_int(data, "proposed_fee_cents", 1)
    _assert_int(data, "negotiation_rounds", 0)


def assert_deal(data: dict) -> None:
    _assert_common(data)
    for f in ("pitch_id", "brief_id", "creator_id", "brand_id"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be set"
    assert data.get("status") in [s.value for s in DealStatus]
    _assert_int(data, "negotiation_rounds", 0)
    _assert_int(data, "fee_base_cents", 1)
    _assert_int(data, "terms_version", 0)
    _assert_int(data, "bonus_accrued_cents", 0)
    if data.get("fee_total_cents") is not None:
        _assert_int(data, "fee_total_cents", 1)


def assert_deliverable(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("deal_id"), str) and data["deal_id"]
    assert data.get("status") in [s.value for s in DeliverableStatus]
    _assert_int(data, "revision_rounds_used", 0)
    _assert_int(data, "reshoot_count", 0)


def assert_disclosure_check(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("deliverable_id"), str) and data["deliverable_id"]
    assert data.get("status") in [s.value for s in DisclosureCheckStatus]
    _assert_int(data, "recheck_count", 0)
    for f in ("has_ad_hashtag", "verbal_disclosure", "platform_tool_used"):
        assert isinstance(data.get(f), bool), f"{f} must be boolean"


def assert_performance_report(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("deal_id"), str) and data["deal_id"]
    assert data.get("status") in [s.value for s in PerformanceReportStatus]
    for f in ("views", "likes", "comments", "shares"):
        _assert_int(data, f, 0)
    _assert_int(data, "provisional_bonus_cents", 0)
    if data.get("final_bonus_cents") is not None:
        _assert_int(data, "final_bonus_cents", 0)


def assert_invoice(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("deal_id"), str) and data["deal_id"]
    assert isinstance(data.get("brand_id"), str) and data["brand_id"]
    assert data.get("status") in [s.value for s in InvoiceStatus]
    for f in (
        "fee_line_cents",
        "service_line_cents",
        "bonus_line_cents",
        "total_cents",
        "late_fee_cents",
    ):
        _assert_int(data, f, 0)
    assert data["total_cents"] == (
        data["fee_line_cents"]
        + data["service_line_cents"]
        + data["bonus_line_cents"]
    ), "total_cents must equal the sum of the three rounded lines"


def assert_payout(data: dict) -> None:
    _assert_common(data)
    for f in ("invoice_id", "deal_id", "creator_id"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be set"
    assert data.get("status") in [s.value for s in PayoutStatus]
    _assert_int(data, "gross_cents", 0)
    _assert_int(data, "commission_rate_bps", 0)
    _assert_int(data, "commission_cents", 0)
    _assert_int(data, "net_cents", 0)
    assert data["net_cents"] == data["gross_cents"] - data["commission_cents"], (
        "net_cents must equal gross_cents minus commission_cents"
    )


def assert_dispute(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("deal_id"), str) and data["deal_id"]
    assert data.get("status") in [s.value for s in DisputeStatus]
    assert data.get("raised_by_role") in ("CREATOR", "BRAND")


def assert_reshoot(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data.get("deliverable_id"), str) and data["deliverable_id"]
    assert data.get("status") in [s.value for s in ReshootStatus]
