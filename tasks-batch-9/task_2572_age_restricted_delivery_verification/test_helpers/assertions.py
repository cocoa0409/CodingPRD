"""Domain-specific assertion helpers.

Each helper encodes a rule the PRD states, so a test can restate the rule once
and let the helper check every field it touches with a descriptive message.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    LINE_STATE_INCLUDED,
    SCORE_TOLERANCE,
    UNIT_TOLERANCE,
)


# ---------------------------------------------------------------------------
# Identity, timestamps and revision counters (PRD 2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource but a capture artifact carries id/created_at/updated_at/version."""
    assert is_valid_uuid(row.get("id")), f"`id` must be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"`created_at` must be an ISO 8601 UTC timestamp, got {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at")), (
        f"`updated_at` must be an ISO 8601 UTC timestamp, got {row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int), (
        f"`version` must be an integer, got {row.get('version')!r}"
    )
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected `version` {expected_version}, got {row['version']}"
        )


def assert_instant_equal(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants by value rather than by spelling.

    PRD 2.4 pins "three fractional digits" on the timestamps the server mints,
    while a fixture's clock constant is written without them. What a PRD rule
    such as 3.8's "`recorded_at` stamped from the logical clock" asserts is the
    instant's identity, so both sides are normalised before comparison.
    """
    assert actual is not None, f"`{label}` must be present"
    assert is_iso8601_timestamp(actual), (
        f"`{label}` must be an ISO 8601 UTC timestamp, got {actual!r}"
    )
    normalise = lambda s: datetime.strptime(  # noqa: E731
        s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z"
    ) if "." in s else datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    assert normalise(actual) == normalise(expected), (
        f"`{label}` must be the instant {expected}; got {actual}"
    )


def assert_versionless_row(row: Dict[str, Any]) -> None:
    """A capture artifact carries only `id` and `created_at` (PRD 2.4)."""
    assert is_valid_uuid(row.get("id")), f"`id` must be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"`created_at` must be an ISO 8601 UTC timestamp, got {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, "a capture artifact must not carry `updated_at`"
    assert "version" not in row, "a capture artifact must not carry `version`"


# ---------------------------------------------------------------------------
# Numeric precision (PRD 2.9)
# ---------------------------------------------------------------------------
def assert_units_equal(actual: Any, expected: float, label: str = "restricted units") -> None:
    """Restricted-unit figures are carried to two decimal places."""
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(expected, abs=UNIT_TOLERANCE), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_score_equal(actual: Any, expected: float, label: str = "score") -> None:
    """Risk and compliance scores are carried to two decimal places."""
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_confidence_equal(actual: Any, expected: float) -> None:
    """Identity confidence is carried to four decimal places (PRD 2.9)."""
    assert actual is not None, "`confidence` must not be null"
    assert float(actual) == pytest.approx(expected, abs=0.00005), (
        f"`confidence`: expected {expected:.4f}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, label: str) -> None:
    """Money is handled exclusively in whole integer cents (PRD 2.9)."""
    assert isinstance(actual, int), f"{label} must be an integer number of cents, got {actual!r}"
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_money_conserved(order: Dict[str, Any]) -> None:
    """`refunded_cents` plus `retained_cents` equals `charged_cents` exactly (PRD 2.9)."""
    refunded = order["refunded_cents"]
    retained = order["retained_cents"]
    charged = order["charged_cents"]
    assert refunded + retained == charged, (
        "refunded_cents + retained_cents must equal charged_cents exactly: "
        f"{refunded} + {retained} != {charged}"
    )


# ---------------------------------------------------------------------------
# Orders (PRD 3.3)
# ---------------------------------------------------------------------------
def assert_order_states(
    order: Dict[str, Any],
    compliance_state: Optional[str] = None,
    fulfillment_state: Optional[str] = None,
) -> None:
    """The two order state dimensions are asserted independently (PRD 1, PRD 3.3)."""
    if compliance_state is not None:
        assert order["compliance_state"] == compliance_state, (
            f"expected compliance_state {compliance_state}, got {order['compliance_state']}"
        )
    if fulfillment_state is not None:
        assert order["fulfillment_state"] == fulfillment_state, (
            f"expected fulfillment_state {fulfillment_state}, got {order['fulfillment_state']}"
        )


def assert_new_order_defaults(order: Dict[str, Any]) -> None:
    """A new order's declared default field set (PRD 3.3)."""
    assert order["restriction_types"] == [], "a new order carries no restriction types"
    assert order["applied_policy_ids"] == [], "a new order carries no applied policy ids"
    assert_cents(order["charged_cents"], 0, "charged_cents")
    assert_cents(order["item_subtotal_cents"], 0, "item_subtotal_cents")
    assert_units_equal(order["provisional_restricted_units"], 0.00, "provisional_restricted_units")
    assert_cents(order["restocking_fee_cents"], 0, "restocking_fee_cents")
    assert_cents(order["refunded_cents"], 0, "refunded_cents")
    assert_cents(order["retained_cents"], 0, "retained_cents")
    for field in (
        "final_restricted_units",
        "submitted_at",
        "dispatched_at",
        "delivered_at",
        "hold_reason",
        "clearance_actor_user_id",
    ):
        assert order[field] is None, f"a new order's `{field}` must be null, got {order[field]!r}"


def assert_line_snapshot(
    line: Dict[str, Any],
    unit_price_cents: int,
    units_per_item_snapshot: float,
    quantity: int,
) -> None:
    """A line snapshots the catalogue figures and derives its own total (PRD 3.3)."""
    assert_cents(line["unit_price_cents"], unit_price_cents, "unit_price_cents")
    assert_units_equal(
        line["units_per_item_snapshot"], units_per_item_snapshot, "units_per_item_snapshot"
    )
    assert line["quantity"] == quantity, f"expected quantity {quantity}, got {line['quantity']}"
    assert_cents(line["line_total_cents"], quantity * unit_price_cents, "line_total_cents")
    assert line["line_state"] == LINE_STATE_INCLUDED, (
        f"a new line opens INCLUDED, got {line['line_state']}"
    )


def assert_restriction_types(order: Dict[str, Any], expected: List[str]) -> None:
    """`restriction_types` is the distinct non-NONE set sorted ascending (PRD 3.3)."""
    assert order["restriction_types"] == expected, (
        f"expected restriction_types {expected}, got {order['restriction_types']}"
    )


# ---------------------------------------------------------------------------
# Delivery partners (PRD 3.4)
# ---------------------------------------------------------------------------
def assert_partner_gate(
    partner: Dict[str, Any],
    posture: Optional[str] = None,
    open_case_count: Optional[int] = None,
    open_critical_case_count: Optional[int] = None,
    license_risk_score: Optional[float] = None,
    lifetime_risk_score: Optional[float] = None,
) -> None:
    """The derived posture and the counters it reads (PRD 3.4)."""
    if posture is not None:
        assert partner["posture"] == posture, (
            f"expected posture {posture}, got {partner['posture']}"
        )
    if open_case_count is not None:
        assert partner["open_case_count"] == open_case_count, (
            f"expected open_case_count {open_case_count}, got {partner['open_case_count']}"
        )
    if open_critical_case_count is not None:
        assert partner["open_critical_case_count"] == open_critical_case_count, (
            f"expected open_critical_case_count {open_critical_case_count}, "
            f"got {partner['open_critical_case_count']}"
        )
    if license_risk_score is not None:
        assert_score_equal(partner["license_risk_score"], license_risk_score, "license_risk_score")
    if lifetime_risk_score is not None:
        assert_score_equal(
            partner["lifetime_risk_score"], lifetime_risk_score, "lifetime_risk_score"
        )


# ---------------------------------------------------------------------------
# Couriers (PRD 3.5)
# ---------------------------------------------------------------------------
def assert_courier_gates(
    courier: Dict[str, Any],
    certification_state: Optional[str] = None,
    dispatch_eligible: Optional[bool] = None,
    compliance_score: Optional[float] = None,
    compliant_handover_count: Optional[int] = None,
) -> None:
    """The courier's two derived gates and the score that feeds them (PRD 3.5)."""
    if certification_state is not None:
        assert courier["certification_state"] == certification_state, (
            f"expected certification_state {certification_state}, "
            f"got {courier['certification_state']}"
        )
    if dispatch_eligible is not None:
        assert courier["dispatch_eligible"] is dispatch_eligible, (
            f"expected dispatch_eligible {dispatch_eligible}, got {courier['dispatch_eligible']}"
        )
    if compliance_score is not None:
        assert_score_equal(courier["compliance_score"], compliance_score, "compliance_score")
    if compliant_handover_count is not None:
        assert courier["compliant_handover_count"] == compliant_handover_count, (
            f"expected compliant_handover_count {compliant_handover_count}, "
            f"got {courier['compliant_handover_count']}"
        )


# ---------------------------------------------------------------------------
# Delivery attempts (PRD 3.6)
# ---------------------------------------------------------------------------
def assert_attempt_state(attempt: Dict[str, Any], state: str) -> None:
    assert attempt["state"] == state, (
        f"expected attempt state {state}, got {attempt['state']}"
    )


def assert_fresh_attempt_defaults(attempt: Dict[str, Any]) -> None:
    """A newly created attempt's declared null field set (PRD 3.6)."""
    for field in (
        "document_type",
        "document_expires_on",
        "scan_performed",
        "scanned_dob",
        "recipient_name",
        "recipient_age_years",
        "refusal_reason",
        "abort_reason",
    ):
        assert attempt[field] is None, (
            f"a new attempt's `{field}` must be null, got {attempt[field]!r}"
        )
    assert attempt["observed_indicators"] == [], "a new attempt's observed_indicators is empty"
    assert attempt["id_check_compliant"] is False, "a new attempt is not id_check_compliant"


# ---------------------------------------------------------------------------
# Violation cases and plans (PRD 3.9)
# ---------------------------------------------------------------------------
def assert_case_state(case: Dict[str, Any], state: str) -> None:
    assert case["state"] == state, f"expected case state {state}, got {case['state']}"


def assert_plan_state(plan: Dict[str, Any], state: str) -> None:
    assert plan["state"] == state, f"expected plan state {state}, got {plan['state']}"


def assert_new_case_defaults(case: Dict[str, Any]) -> None:
    """A new case opens OPEN with zero rounds and no decision (PRD 3.9)."""
    assert case["investigation_rounds"] == 0, (
        f"a new case opens with investigation_rounds 0, got {case['investigation_rounds']}"
    )
    assert_score_equal(case["risk_contribution"], 0.00, "risk_contribution")
    for field in (
        "assessed_severity",
        "decided_at",
        "substantiated_by_user_id",
        "response_due_at",
        "partner_response_text",
        "notes",
    ):
        assert case[field] is None, (
            f"a new case's `{field}` must be null, got {case[field]!r}"
        )


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def assert_page_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """List results are ordered by `created_at` ascending (PRD 2.3)."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at ascending: {stamps}"


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]
