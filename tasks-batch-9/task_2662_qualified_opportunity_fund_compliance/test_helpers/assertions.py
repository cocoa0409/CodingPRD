"""
Domain assertions for the Qualified Opportunity Fund compliance API.

These wrap the repetitive shape and rounding checks the PRD imposes: the common
property set, the immutable-ledger exception, money at two decimals,
percentages at four, and the two conserved quantities.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    MONEY_DECIMALS,
    PERCENT_DECIMALS,
    REQUEST_ID_PREFIX,
)


# =========================================================================
# Identifiers and timestamps
# =========================================================================


def assert_bare_uuid(value: Any, label: str = "id") -> None:
    """The PRD mints ids as bare UUIDs, with no entity-type prefix."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    assert is_valid_uuid(value), f"{label} must be a bare UUID, got {value!r}"
    assert "_" not in value, f"{label} must carry no prefix, got {value!r}"


def assert_iso_timestamp(value: Any, label: str = "timestamp") -> None:
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"


# =========================================================================
# Common property set
# =========================================================================


def assert_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """Every mutable entity carries id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"{label} is missing common property {field!r}"
    assert_bare_uuid(entity["id"], f"{label}.id")
    assert_iso_timestamp(entity["created_at"], f"{label}.created_at")
    assert_iso_timestamp(entity["updated_at"], f"{label}.updated_at")
    assert isinstance(entity["version"], int), f"{label}.version must be an integer"
    assert entity["version"] >= 1, f"{label}.version must start at 1"


def assert_ledger_fields(entity: Dict[str, Any], label: str = "expenditure") -> None:
    """
    The immutable ledger row carries only id and created_at from the common set:
    it has no updated_at and no version.
    """
    for field in ("id", "created_at"):
        assert field in entity, f"{label} is missing common property {field!r}"
    assert_bare_uuid(entity["id"], f"{label}.id")
    assert_iso_timestamp(entity["created_at"], f"{label}.created_at")
    assert "updated_at" not in entity, f"{label} must not carry updated_at"
    assert "version" not in entity, f"{label} must not carry version"


def assert_version_is(entity: Dict[str, Any], expected: int, label: str = "entity") -> None:
    actual = entity.get("version")
    assert actual == expected, (
        f"Expected {label}.version == {expected}, got {actual}"
    )


# =========================================================================
# Envelope
# =========================================================================


def assert_request_id_prefixed(meta: Dict[str, Any]) -> None:
    """meta.api_request_id begins with the declared prefix."""
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str), "meta.api_request_id must be a string"
    assert request_id.startswith(REQUEST_ID_PREFIX), (
        f"meta.api_request_id must begin with {REQUEST_ID_PREFIX!r}, got {request_id!r}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Assert the paginated envelope's meta counters."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"Expected total_count == {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"Expected has_more == {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, (
            f"Expected limit == {limit}, got {meta['limit']}"
        )
    if offset is not None:
        assert meta["offset"] == offset, (
            f"Expected offset == {offset}, got {meta['offset']}"
        )


# =========================================================================
# Rounding
# =========================================================================


def assert_money(value: Any, expected: float, label: str = "amount") -> None:
    """Money is carried to two decimals."""
    assert value is not None, f"{label} must not be null"
    actual = float(value)
    assert round(actual, MONEY_DECIMALS) == round(float(expected), MONEY_DECIMALS), (
        f"Expected {label} == {expected:.2f}, got {actual}"
    )


def assert_percent(value: Any, expected: float, label: str = "percentage") -> None:
    """Percentages and fractions are carried to four decimals."""
    assert value is not None, f"{label} must not be null"
    actual = float(value)
    assert round(actual, PERCENT_DECIMALS) == round(
        float(expected), PERCENT_DECIMALS
    ), f"Expected {label} == {expected:.4f}, got {actual}"


def assert_money_precision(value: Any, label: str = "amount") -> None:
    """The stored value carries no more than two decimal places."""
    actual = float(value)
    assert round(actual, MONEY_DECIMALS) == actual, (
        f"{label} must be carried to two decimals, got {actual}"
    )


def assert_percent_precision(value: Any, label: str = "percentage") -> None:
    """The stored value carries no more than four decimal places."""
    actual = float(value)
    assert round(actual, PERCENT_DECIMALS) == actual, (
        f"{label} must be carried to four decimals, got {actual}"
    )


# =========================================================================
# Fund ledger
# =========================================================================


def assert_fund_aggregates(
    fund: Dict[str, Any],
    aggregate_asset_basis: Optional[float] = None,
    aggregate_qualified_basis: Optional[float] = None,
    aggregate_afs_value: Optional[float] = None,
    aggregate_qualified_afs_value: Optional[float] = None,
) -> None:
    """Assert any subset of the fund's four asset-test aggregates."""
    expectations = {
        "aggregate_asset_basis": aggregate_asset_basis,
        "aggregate_qualified_basis": aggregate_qualified_basis,
        "aggregate_afs_value": aggregate_afs_value,
        "aggregate_qualified_afs_value": aggregate_qualified_afs_value,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert_money(fund[field], expected, f"Fund.{field}")


def assert_fund_state(
    fund: Dict[str, Any],
    certification_status: Optional[str] = None,
    compliance_posture: Optional[str] = None,
) -> None:
    """
    Assert either or both of the fund's two independent state dimensions.
    """
    if certification_status is not None:
        assert fund["certification_status"] == certification_status, (
            f"Expected certification_status == {certification_status}, "
            f"got {fund['certification_status']}"
        )
    if compliance_posture is not None:
        assert fund["compliance_posture"] == compliance_posture, (
            f"Expected compliance_posture == {compliance_posture}, "
            f"got {fund['compliance_posture']}"
        )


# =========================================================================
# Asset test measurement
# =========================================================================


def assert_asset_test_measurement(
    test: Dict[str, Any],
    qualified_numerator: Optional[float] = None,
    total_denominator: Optional[float] = None,
    ratio_pct: Optional[float] = None,
    result: Optional[str] = None,
    shortfall_amount: Optional[float] = None,
    failed_month_count: Optional[int] = None,
    included_asset_count: Optional[int] = None,
    valuation_method: Optional[str] = None,
) -> None:
    """Assert any subset of a measured asset test's computed outputs."""
    if qualified_numerator is not None:
        assert_money(
            test["qualified_numerator"], qualified_numerator, "AssetTest.qualified_numerator"
        )
    if total_denominator is not None:
        assert_money(
            test["total_denominator"], total_denominator, "AssetTest.total_denominator"
        )
    if ratio_pct is not None:
        assert_percent(test["ratio_pct"], ratio_pct, "AssetTest.ratio_pct")
    if result is not None:
        assert test["result"] == result, (
            f"Expected AssetTest.result == {result}, got {test['result']}"
        )
    if shortfall_amount is not None:
        assert_money(
            test["shortfall_amount"], shortfall_amount, "AssetTest.shortfall_amount"
        )
    if failed_month_count is not None:
        assert test["failed_month_count"] == failed_month_count, (
            f"Expected AssetTest.failed_month_count == {failed_month_count}, "
            f"got {test['failed_month_count']}"
        )
    if included_asset_count is not None:
        assert test["included_asset_count"] == included_asset_count, (
            f"Expected AssetTest.included_asset_count == {included_asset_count}, "
            f"got {test['included_asset_count']}"
        )
    if valuation_method is not None:
        assert test["valuation_method"] == valuation_method, (
            f"Expected AssetTest.valuation_method == {valuation_method}, "
            f"got {test['valuation_method']}"
        )


def assert_business_test_prongs(
    test: Dict[str, Any],
    gross_income_pct: Optional[float] = None,
    intangibles_pct: Optional[float] = None,
    nqfp_pct: Optional[float] = None,
    gross_income_prong: Optional[str] = None,
    intangibles_prong: Optional[str] = None,
    nqfp_prong: Optional[str] = None,
) -> None:
    """Assert any subset of a measured QOZB test's three prongs."""
    if gross_income_pct is not None:
        assert_percent(
            test["gross_income_pct"], gross_income_pct, "BusinessTest.gross_income_pct"
        )
    if intangibles_pct is not None:
        assert_percent(
            test["intangibles_pct"], intangibles_pct, "BusinessTest.intangibles_pct"
        )
    if nqfp_pct is not None:
        assert_percent(test["nqfp_pct"], nqfp_pct, "BusinessTest.nqfp_pct")
    for field, expected in (
        ("gross_income_prong", gross_income_prong),
        ("intangibles_prong", intangibles_prong),
        ("nqfp_prong", nqfp_prong),
    ):
        if expected is not None:
            assert test[field] == expected, (
                f"Expected BusinessTest.{field} == {expected}, got {test[field]}"
            )


# =========================================================================
# Conserved quantities
# =========================================================================


def assert_gain_dollars_conserved(
    gain: Dict[str, Any], elections: Iterable[Dict[str, Any]]
) -> None:
    """
    The gain's eligible_amount always equals its unelected_amount plus the sum
    of elected_amount over its elections that are not REVOKED.
    """
    live_total = sum(
        float(election["elected_amount"])
        for election in elections
        if election["status"] != "REVOKED"
    )
    expected = round(float(gain["unelected_amount"]) + live_total, MONEY_DECIMALS)
    actual = round(float(gain["eligible_amount"]), MONEY_DECIMALS)
    assert actual == expected, (
        "Gain dollars are not conserved: eligible_amount "
        f"{actual} != unelected_amount {gain['unelected_amount']} + "
        f"live elected total {live_total}"
    )


def assert_noncompliance_months_conserved(
    fund: Dict[str, Any], assessments: Iterable[Dict[str, Any]]
) -> None:
    """
    The fund's cumulative_penalty_months always equals the sum of
    failed_month_count over its assessments in ASSESSED, CURE_REQUESTED or
    UPHELD.
    """
    counting_states = {"ASSESSED", "CURE_REQUESTED", "UPHELD"}
    expected = sum(
        int(assessment["failed_month_count"])
        for assessment in assessments
        if assessment["status"] in counting_states
    )
    actual = int(fund["cumulative_penalty_months"])
    assert actual == expected, (
        "Noncompliance months are not conserved: "
        f"Fund.cumulative_penalty_months {actual} != summed failed_month_count {expected}"
    )


# =========================================================================
# Segregation of duties
# =========================================================================


def assert_distinct_measurer_and_certifier(test: Dict[str, Any]) -> None:
    """A certified test records two different user handles."""
    measured_by = test.get("measured_by_user_id")
    certified_by = test.get("certified_by_user_id")
    assert measured_by, "measured_by_user_id must be recorded on a measured test"
    assert certified_by, "certified_by_user_id must be recorded on a certified test"
    assert measured_by != certified_by, (
        f"The certifier must differ from the measurer, both were {measured_by!r}"
    )


def assert_ids_unique(entities: List[Dict[str, Any]], label: str = "entities") -> None:
    ids = [entity["id"] for entity in entities]
    assert len(ids) == len(set(ids)), f"{label} contain duplicate ids: {ids}"
