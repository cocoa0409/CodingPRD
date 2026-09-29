"""Domain assertions layered on the framework primitives."""
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import APPEND_ONLY_FORBIDDEN_FIELDS

# --------------------------------------------------------------------------
# Shape helpers
# --------------------------------------------------------------------------


def assert_identity_fields(entity: Dict[str, Any]) -> None:
    """Every resource carries a server-generated UUID id and a created_at."""
    assert is_valid_uuid(entity.get("id")), "id is not a UUID: {}".format(
        entity.get("id")
    )
    assert is_iso8601_timestamp(
        entity.get("created_at")
    ), "created_at is not ISO-8601: {}".format(entity.get("created_at"))


def assert_mutable_audit_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A mutable resource additionally carries updated_at and an integer version."""
    assert_identity_fields(entity)
    assert is_iso8601_timestamp(
        entity.get("updated_at")
    ), "updated_at is not ISO-8601: {}".format(entity.get("updated_at"))
    version = entity.get("version")
    assert isinstance(version, int) and not isinstance(
        version, bool
    ), "version is not an integer: {!r}".format(version)
    assert version >= 1, "version must start at 1, got {}".format(version)
    if expected_version is not None:
        assert version == expected_version, "expected version {}, got {}".format(
            expected_version, version
        )


def assert_append_only_shape(entity: Dict[str, Any]) -> None:
    """An append-only journal row carries id and created_at and nothing else of
    the audit quartet: updated_at and version must be absent, not null."""
    assert_identity_fields(entity)
    for field in APPEND_ONLY_FORBIDDEN_FIELDS:
        assert field not in entity, (
            "append-only resource must omit {!r} entirely, but the field is "
            "present with value {!r}".format(field, entity.get(field))
        )


def assert_envelope_meta(meta: Dict[str, Any]) -> None:
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith(
        "req_"
    ), "api_request_id must be a req_-prefixed string, got {!r}".format(request_id)


# --------------------------------------------------------------------------
# Money and score arithmetic
# --------------------------------------------------------------------------


def assert_integer_cents(value: Any, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), "{} must be an integer number of cents, got {!r}".format(label, value)


def assert_two_decimal_score(value: Any, label: str = "score") -> None:
    """Scores are carried to two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(
        value, bool
    ), "{} must be numeric, got {!r}".format(label, value)
    assert round(float(value), 2) == float(value), (
        "{} must be pinned to two decimal places, got {!r}".format(label, value)
    )


# --------------------------------------------------------------------------
# Entity-level assertions
# --------------------------------------------------------------------------


def assert_vendor_shape(vendor: Dict[str, Any]) -> None:
    assert_mutable_audit_fields(vendor)
    assert_integer_cents(vendor.get("protest_fee_balance_cents"), "protest_fee_balance_cents")
    assert isinstance(vendor.get("debarment_strike_count"), int)
    assert vendor.get("eligibility_status") in {"ELIGIBLE", "SUSPENDED", "DEBARRED"}


def assert_solicitation_shape(solicitation: Dict[str, Any]) -> None:
    assert_mutable_audit_fields(solicitation)
    assert_integer_cents(
        solicitation.get("estimated_value_cents"), "estimated_value_cents"
    )
    assert_integer_cents(solicitation.get("protest_escrow_cents"), "protest_escrow_cents")
    assert isinstance(solicitation.get("addendum_count"), int)
    assert isinstance(solicitation.get("cumulative_extension_days"), int)


def assert_bid_shape(bid: Dict[str, Any]) -> None:
    assert_mutable_audit_fields(bid)
    assert_integer_cents(bid.get("total_price_cents"), "total_price_cents")
    assert_integer_cents(
        bid.get("informality_loading_cents"), "informality_loading_cents"
    )
    assert isinstance(bid.get("acknowledged_addendum_sequences"), list)
    assert isinstance(bid.get("nonresponsive_reason_codes"), list)


def assert_award_money(
    award: Dict[str, Any],
    base_cents: int,
    fee_rate: float,
    fee_cents: int,
    reserve_cents: int,
) -> None:
    """The five award money fields, including the additive identity of step five."""
    assert award["base_obligation_cents"] == base_cents
    assert award["administrative_fee_rate"] == fee_rate
    assert award["administrative_fee_cents"] == fee_cents
    assert award["protest_risk_reserve_cents"] == reserve_cents
    assert (
        award["award_total_obligation_cents"] == base_cents + fee_cents + reserve_cents
    ), "award total must be base + fee + reserve"


def assert_protest_fee(protest: Dict[str, Any], expected_fee_cents: int) -> None:
    assert_integer_cents(protest.get("filing_fee_cents"), "filing_fee_cents")
    assert protest["filing_fee_cents"] == expected_fee_cents, (
        "expected filing_fee_cents {}, got {}".format(
            expected_fee_cents, protest["filing_fee_cents"]
        )
    )


def assert_severity(
    proceeding: Dict[str, Any],
    aggravating_total: float,
    mitigating_credit: float,
    severity: float,
) -> None:
    assert proceeding["aggravating_total_points"] == aggravating_total
    assert proceeding["mitigating_credit_points"] == mitigating_credit
    assert proceeding["severity_score"] == severity


def assert_nonresponsive_with(
    bid: Dict[str, Any], expected_codes: Iterable[str]
) -> None:
    assert bid["responsiveness_status"] == "NONRESPONSIVE", (
        "expected NONRESPONSIVE, got {}".format(bid["responsiveness_status"])
    )
    codes = bid.get("nonresponsive_reason_codes") or []
    for code in expected_codes:
        assert code in codes, "expected reason code {} in {}".format(code, codes)


def assert_sequence_numbers_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    sequences = [row["sequence_number"] for row in rows]
    assert sequences == sorted(sequences), (
        "rows must be ordered by ascending sequence_number, got {}".format(sequences)
    )


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        "rows must be ordered by ascending created_at, got {}".format(stamps)
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, "expected total_count {}, got {}".format(
            total_count, meta["total_count"]
        )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
    if has_more is not None:
        assert meta["has_more"] is has_more, "expected has_more {}, got {}".format(
            has_more, meta["has_more"]
        )
