"""Domain assertions shared across the suite.

These wrap the repetitive field-by-field checks the PRD's arithmetic sections demand
(facility ledger, issuance charges, settlement waterfall, screening scores) plus the
shape rules from PRD 2.4-2.6 (integer minor units, millisecond instants, end-of-day
deadline instants, version monotonicity).
"""

import re
from typing import Any, Dict, Iterable, Mapping, Optional

_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

END_OF_DAY_SUFFIX = "T23:59:59.999Z"


# ----------------------------------------------------------------------
# Shape helpers
# ----------------------------------------------------------------------
def assert_instant_with_milliseconds(value: Any, label: str = "instant") -> None:
    """Instant-typed fields are ISO-8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _INSTANT_RE.match(value), (
        f"{label} must be ISO-8601 UTC with exactly three fractional digits, got {value!r}"
    )


def assert_calendar_date(value: Any, label: str = "date") -> None:
    """Date-typed fields are plain YYYY-MM-DD with no time component."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _DATE_RE.match(value), f"{label} must be YYYY-MM-DD, got {value!r}"


def assert_end_of_day_instant(value: Any, expected_date: str, label: str = "deadline") -> None:
    """A date-derived deadline instant lands on the final millisecond of its day."""
    assert value == expected_date + END_OF_DAY_SUFFIX, (
        f"{label} must be {expected_date}{END_OF_DAY_SUFFIX}, got {value!r}"
    )


def assert_integer_minor_units(entity: Mapping[str, Any], *fields: str) -> None:
    """Monetary amounts are integer minor units, never floats or strings."""
    for field in fields:
        value = entity.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r}"
        )


def assert_fields_equal(entity: Mapping[str, Any], **expected: Any) -> None:
    """Assert a batch of field values, reporting every mismatch at once."""
    mismatches = []
    for field, want in expected.items():
        got = entity.get(field, "<<missing>>")
        if got != want:
            mismatches.append(f"{field}: expected {want!r}, got {got!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_absent(entity: Mapping[str, Any], *fields: str) -> None:
    """Assert the entity does not carry the named keys at all."""
    present = [f for f in fields if f in entity]
    assert not present, f"unexpected fields present: {present}"


def assert_version_is(entity: Mapping[str, Any], expected: int) -> None:
    assert entity.get("version") == expected, (
        f"version expected {expected}, got {entity.get('version')!r}"
    )


def assert_conserved(before: Any, after: Any, label: str = "value") -> None:
    """A compensating pair must return the quantity to its starting value."""
    assert before == after, f"{label} not conserved: before={before!r} after={after!r}"


# ----------------------------------------------------------------------
# Facility ledger
# ----------------------------------------------------------------------
def assert_facility_ledger(
    facility: Mapping[str, Any],
    allocated_cents: Optional[int] = None,
    available_cents: Optional[int] = None,
    restrict_threshold_cents: Optional[int] = None,
    utilisation_posture: Optional[str] = None,
    status: Optional[str] = None,
    suspended_reason: Any = "<<skip>>",
) -> None:
    """Check the facility's ledger triple plus its posture/status pair."""
    expected: Dict[str, Any] = {}
    if allocated_cents is not None:
        expected["allocated_cents"] = allocated_cents
    if available_cents is not None:
        expected["available_cents"] = available_cents
    if restrict_threshold_cents is not None:
        expected["restrict_threshold_cents"] = restrict_threshold_cents
    if utilisation_posture is not None:
        expected["utilisation_posture"] = utilisation_posture
    if status is not None:
        expected["status"] = status
    if suspended_reason != "<<skip>>":
        expected["suspended_reason"] = suspended_reason
    assert_fields_equal(facility, **expected)


def assert_ledger_identity(facility: Mapping[str, Any]) -> None:
    """`available_cents` is the residue of the limit after allocations."""
    limit = facility["limit_cents"]
    allocated = facility["allocated_cents"]
    available = facility["available_cents"]
    assert available == limit - allocated, (
        f"available_cents {available} != limit_cents {limit} - allocated_cents {allocated}"
    )


# ----------------------------------------------------------------------
# Issuance charges
# ----------------------------------------------------------------------
def assert_issuance_charges(
    credit: Mapping[str, Any],
    gross_exposure_cents: Optional[int] = None,
    commission_bps_applied: Optional[int] = None,
    base_commission_cents: Optional[int] = None,
    confirmation_charge_cents: Optional[int] = None,
    total_charge_cents: Optional[int] = None,
    chargeable_utilisation_cents: Optional[int] = None,
    committed_allocation_cents: Optional[int] = None,
    max_drawable_cents: Optional[int] = None,
) -> None:
    """Check the issuance pricing chain field by field."""
    expected: Dict[str, Any] = {}
    for field, want in (
        ("gross_exposure_cents", gross_exposure_cents),
        ("commission_bps_applied", commission_bps_applied),
        ("base_commission_cents", base_commission_cents),
        ("confirmation_charge_cents", confirmation_charge_cents),
        ("total_charge_cents", total_charge_cents),
        ("chargeable_utilisation_cents", chargeable_utilisation_cents),
        ("committed_allocation_cents", committed_allocation_cents),
        ("max_drawable_cents", max_drawable_cents),
    ):
        if want is not None:
            expected[field] = want
    assert_fields_equal(credit, **expected)


def assert_charge_sum(credit: Mapping[str, Any]) -> None:
    """`total_charge_cents` is the sum of the base and confirmation components."""
    assert credit["total_charge_cents"] == (
        credit["base_commission_cents"] + credit["confirmation_charge_cents"]
    ), (
        "total_charge_cents "
        f"{credit['total_charge_cents']} != base {credit['base_commission_cents']}"
        f" + confirmation {credit['confirmation_charge_cents']}"
    )


def assert_chargeable_sum(credit: Mapping[str, Any]) -> None:
    """`chargeable_utilisation_cents` is the committed allocation plus total charges."""
    assert credit["chargeable_utilisation_cents"] == (
        credit["committed_allocation_cents"] + credit["total_charge_cents"]
    ), (
        "chargeable_utilisation_cents "
        f"{credit['chargeable_utilisation_cents']} != committed "
        f"{credit['committed_allocation_cents']} + charges {credit['total_charge_cents']}"
    )


# ----------------------------------------------------------------------
# Drawing ledger on the credit
# ----------------------------------------------------------------------
def assert_credit_drawing_ledger(
    credit: Mapping[str, Any],
    drawn_settled_cents: Optional[int] = None,
    reserved_cents: Optional[int] = None,
    available_cents: Optional[int] = None,
    max_drawable_cents: Optional[int] = None,
) -> None:
    expected: Dict[str, Any] = {}
    for field, want in (
        ("drawn_settled_cents", drawn_settled_cents),
        ("reserved_cents", reserved_cents),
        ("available_cents", available_cents),
        ("max_drawable_cents", max_drawable_cents),
    ):
        if want is not None:
            expected[field] = want
    assert_fields_equal(credit, **expected)


def assert_drawing_identity(credit: Mapping[str, Any]) -> None:
    """The drawing headroom is the drawable ceiling less reserved and settled amounts."""
    expected = (
        credit["max_drawable_cents"]
        - credit["reserved_cents"]
        - credit["drawn_settled_cents"]
    )
    assert credit["available_cents"] == expected, (
        f"credit available_cents {credit['available_cents']} != "
        f"max_drawable {credit['max_drawable_cents']} - reserved "
        f"{credit['reserved_cents']} - drawn_settled {credit['drawn_settled_cents']}"
    )


# ----------------------------------------------------------------------
# Settlement waterfall
# ----------------------------------------------------------------------
def assert_settlement_waterfall(
    claim: Mapping[str, Any],
    variant_applied: Optional[str] = None,
    commission_bps_applied: Optional[int] = None,
    commission_cents: Optional[int] = None,
    discount_cents: Optional[int] = None,
    doc_examination_fee_cents: Optional[int] = None,
    net_proceeds_cents: Optional[int] = None,
    days_to_maturity: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    expected: Dict[str, Any] = {}
    for field, want in (
        ("variant_applied", variant_applied),
        ("commission_bps_applied", commission_bps_applied),
        ("commission_cents", commission_cents),
        ("discount_cents", discount_cents),
        ("doc_examination_fee_cents", doc_examination_fee_cents),
        ("net_proceeds_cents", net_proceeds_cents),
        ("days_to_maturity", days_to_maturity),
        ("status", status),
    ):
        if want is not None:
            expected[field] = want
    assert_fields_equal(claim, **expected)


def assert_net_proceeds_identity(claim: Mapping[str, Any], drawn_amount_cents: int) -> None:
    """Net proceeds are the drawn amount less commission, discount and document fees."""
    expected = (
        drawn_amount_cents
        - claim["commission_cents"]
        - claim["discount_cents"]
        - claim["doc_examination_fee_cents"]
    )
    assert claim["net_proceeds_cents"] == expected, (
        f"net_proceeds_cents {claim['net_proceeds_cents']} != drawn "
        f"{drawn_amount_cents} - commission {claim['commission_cents']} - "
        f"discount {claim['discount_cents']} - docs {claim['doc_examination_fee_cents']}"
    )


# ----------------------------------------------------------------------
# Screening
# ----------------------------------------------------------------------
def assert_screening_outcome(
    check: Mapping[str, Any],
    result: Optional[str] = None,
    risk_score: Optional[int] = None,
    country_hits: Optional[int] = None,
    dual_use_hits: Optional[int] = None,
    keyword_hits: Optional[int] = None,
    transit_hits: Optional[int] = None,
    scope: Optional[str] = None,
    screened_by_user_id: Optional[str] = None,
) -> None:
    expected: Dict[str, Any] = {}
    for field, want in (
        ("result", result),
        ("risk_score", risk_score),
        ("country_hits", country_hits),
        ("dual_use_hits", dual_use_hits),
        ("keyword_hits", keyword_hits),
        ("transit_hits", transit_hits),
        ("scope", scope),
        ("screened_by_user_id", screened_by_user_id),
    ):
        if want is not None:
            expected[field] = want
    assert_fields_equal(check, **expected)


# ----------------------------------------------------------------------
# Sweep report
# ----------------------------------------------------------------------
def assert_sweep_counters(report: Mapping[str, Any], **expected: int) -> None:
    """Assert named sweep counters; unnamed counters are left unchecked."""
    assert_fields_equal(report, **expected)


def assert_all_sweep_counters_zero(report: Mapping[str, Any], counters: Iterable[str]) -> None:
    nonzero = {c: report.get(c) for c in counters if report.get(c) != 0}
    assert not nonzero, f"expected an idempotent no-op sweep, got {nonzero}"


# ----------------------------------------------------------------------
# Ordering
# ----------------------------------------------------------------------
def assert_ordered_by(rows: Iterable[Mapping[str, Any]], field: str, descending: bool = False) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows are not ordered by {field} "
        f"{'DESC' if descending else 'ASC'}: {values}"
    )
