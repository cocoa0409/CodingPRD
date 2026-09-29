"""Domain-shaped assertion helpers.

Each helper asserts one PRD concept so that a failure message names the concept
rather than a raw dictionary key.
"""

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Json = Dict[str, Any]

# --------------------------------------------------------------------------
# Instants (PRD S2.4: ISO 8601 UTC timestamps with three fractional digits)
# --------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """An ISO 8601 UTC instant as a ``datetime``, tolerant of the fraction."""
    assert isinstance(value, str), "expected an ISO 8601 instant, got %r" % (value,)
    text = value.strip()
    assert text.endswith("Z"), "expected a UTC instant ending in Z, got %r" % (value,)
    text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000000")[:6]
        text = "%s.%s" % (head, frac)
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Two ISO 8601 instants name the same moment.

    Compared as instants rather than as strings, because the PRD fixes the moment
    while leaving the rendering of a trailing zero fraction unconstrained.
    """
    assert parse_instant(actual) == parse_instant(expected), (
        "%s: expected %s, got %s" % (label, expected, actual)
    )


_INSTANT_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_instant_shape(actual: Any, label: str = "instant") -> None:
    """PRD S2.4: "both ISO 8601 UTC timestamps with three fractional digits".

    Used for the row-audit stamps `created_at` and `updated_at`, whose *source* the
    PRD never fixes: S2.5 binds the logical clock to "all deadline, validity-window
    and service-level comparisons", so only the rendering is specified here.
    """
    assert isinstance(actual, str), "%s: expected a string instant, got %r" % (label, actual)
    assert _INSTANT_SHAPE.match(actual), (
        "%s: expected an ISO 8601 UTC instant with three fractional digits, got %r"
        % (label, actual)
    )




# --------------------------------------------------------------------------
# Claims: the three status dimensions (PRD S2.3)
# --------------------------------------------------------------------------
def assert_claim_dimensions(
    claim: Json,
    assessment_status: Optional[str] = None,
    fee_status: Optional[str] = None,
    credit_status: Optional[str] = None,
) -> None:
    if assessment_status is not None:
        assert claim["assessment_status"] == assessment_status, (
            "assessment_status: expected %s, got %s" % (assessment_status, claim["assessment_status"])
        )
    if fee_status is not None:
        assert claim["fee_status"] == fee_status, (
            "fee_status: expected %s, got %s" % (fee_status, claim["fee_status"])
        )
    if credit_status is not None:
        assert claim["credit_status"] == credit_status, (
            "credit_status: expected %s, got %s" % (credit_status, claim["credit_status"])
        )


def assert_hold_reason(claim: Json, expected: Optional[str]) -> None:
    assert claim["hold_reason"] == expected, (
        "hold_reason: expected %r, got %r" % (expected, claim["hold_reason"])
    )


# --------------------------------------------------------------------------
# The four-counter credit ledger (PRD S3.3)
# --------------------------------------------------------------------------
def assert_ledger(
    student: Json,
    reserved: Optional[int] = None,
    awarded: Optional[int] = None,
    posted: Optional[int] = None,
    upper_division_committed: Optional[int] = None,
    fee_paid_net_cents: Optional[int] = None,
) -> None:
    expectations = [
        ("pla_credits_reserved", reserved),
        ("pla_credits_awarded", awarded),
        ("pla_credits_posted", posted),
        ("pla_upper_division_committed", upper_division_committed),
        ("fee_paid_net_cents", fee_paid_net_cents),
    ]
    for field, expected in expectations:
        if expected is not None:
            assert student[field] == expected, (
                "%s: expected %s, got %s" % (field, expected, student[field])
            )


# --------------------------------------------------------------------------
# Invoices (PRD S3.10)
# --------------------------------------------------------------------------
def assert_invoice_money(
    invoice: Json,
    subtotal_cents: Optional[int] = None,
    discount_bp: Optional[int] = None,
    discount_cents: Optional[int] = None,
    total_cents: Optional[int] = None,
    paid_cents: Optional[int] = None,
    refunded_cents: Optional[int] = None,
    waived_cents: Optional[int] = None,
    balance_due_cents: Optional[int] = None,
    recompute_count: Optional[int] = None,
) -> None:
    expectations = [
        ("subtotal_cents", subtotal_cents),
        ("discount_bp", discount_bp),
        ("discount_cents", discount_cents),
        ("total_cents", total_cents),
        ("paid_cents", paid_cents),
        ("refunded_cents", refunded_cents),
        ("waived_cents", waived_cents),
        ("balance_due_cents", balance_due_cents),
        ("recompute_count", recompute_count),
    ]
    for field, expected in expectations:
        if expected is not None:
            actual = invoice[field]
            assert isinstance(actual, int) and not isinstance(actual, bool), (
                "%s must be an integer count, got %r" % (field, actual)
            )
            assert actual == expected, "%s: expected %s, got %s" % (field, expected, actual)


def line_amounts(invoice: Json) -> Dict[str, int]:
    """The invoice's ``lines`` array collapsed to ``line_type -> amount_cents``."""
    return {line["line_type"]: line["amount_cents"] for line in invoice["lines"]}


def assert_line(invoice: Json, line_type: str, amount_cents: int) -> None:
    amounts = line_amounts(invoice)
    assert line_type in amounts, "line %s missing from %s" % (line_type, sorted(amounts))
    assert amounts[line_type] == amount_cents, (
        "line %s: expected %s, got %s" % (line_type, amount_cents, amounts[line_type])
    )


def assert_line_absent(invoice: Json, line_type: str) -> None:
    amounts = line_amounts(invoice)
    assert line_type not in amounts, "line %s should be omitted, found %s" % (
        line_type, amounts.get(line_type)
    )


def assert_lines_exactly(invoice: Json, expected: Sequence[Tuple[str, int]]) -> None:
    """The whole ``lines`` array, in order, as ``(line_type, amount_cents)`` pairs."""
    actual = [(line["line_type"], line["amount_cents"]) for line in invoice["lines"]]
    assert actual == list(expected), "lines: expected %s, got %s" % (list(expected), actual)


# --------------------------------------------------------------------------
# Assignments and service levels (PRD S3.6)
# --------------------------------------------------------------------------
def assert_sla(
    assignment: Json,
    sla_hours: Optional[int] = None,
    due_at: Optional[str] = None,
    at_risk_at: Optional[str] = None,
    sla_state: Optional[str] = None,
    elapsed_bp: Optional[int] = None,
) -> None:
    expectations = [
        ("sla_hours", sla_hours),
        ("sla_state", sla_state),
        ("elapsed_bp", elapsed_bp),
    ]
    for field, expected in expectations:
        if expected is not None:
            assert assignment[field] == expected, (
                "%s: expected %r, got %r" % (field, expected, assignment[field])
            )
    if due_at is not None:
        assert_instant(assignment["due_at"], due_at, "due_at")
    if at_risk_at is not None:
        assert_instant(assignment["at_risk_at"], at_risk_at, "at_risk_at")


# --------------------------------------------------------------------------
# Graduation audit (PRD S3.11)
# --------------------------------------------------------------------------
def assert_audit(audit: Json, **expected: Any) -> None:
    for field, value in expected.items():
        assert field in audit, "graduation audit is missing %s" % field
        assert audit[field] == value, "%s: expected %r, got %r" % (field, value, audit[field])


# --------------------------------------------------------------------------
# Field-set shape (PRD S3.1, S3.4)
# --------------------------------------------------------------------------
def assert_common_fields_present(resource: Json) -> None:
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in resource, "expected common field %s" % field


def assert_only_id_and_created_at(resource: Json) -> None:
    """A resource that "carries only an ``id`` and a ``created_at``"."""
    assert "id" in resource and "created_at" in resource
    assert "updated_at" not in resource, "updated_at must be absent, got %r" % resource.get("updated_at")
    assert "version" not in resource, "version must be absent, got %r" % resource.get("version")


def assert_fields_equal(resource: Json, **expected: Any) -> None:
    for field, value in expected.items():
        assert field in resource, "expected field %s in %s" % (field, sorted(resource))
        assert resource[field] == value, "%s: expected %r, got %r" % (field, value, resource[field])


def ids_of(rows: Iterable[Json]) -> List[str]:
    return [row["id"] for row in rows]
