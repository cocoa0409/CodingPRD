"""Domain assertion helpers for the season pass API.

Each helper checks one PRD-declared invariant and reports the offending values
when it fails, so a failure names the rule rather than the line number.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ------------------------------------------------------------- timestamps ----


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating `Z` and fractional seconds."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected_iso: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 instants denote the same moment."""
    assert actual is not None, f"{label} is missing"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label} should be the instant {expected_iso}, got {actual!r}"
    )


def assert_hhmm_equals(actual: Any, expected_hhmm: str, label: str = "arrival window") -> None:
    """Assert an `HH:MM` clock time, tolerating a seconds component."""
    assert isinstance(actual, str), f"{label} should be a string, got {actual!r}"
    normalised = actual[:5]
    assert normalised == expected_hhmm, (
        f"{label} should be {expected_hhmm}, got {actual!r}"
    )


# ---------------------------------------------------------------- versions ---


def assert_version(row: Dict[str, Any], expected: int, label: str = "record") -> None:
    assert row.get("version") == expected, (
        f"{label} version should be {expected}, got {row.get('version')!r}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any], label: str = "record") -> None:
    """Assert a refused write left the row's optimistic-lock version alone."""
    assert after.get("version") == before.get("version"), (
        f"{label} version should be unchanged at {before.get('version')!r}, "
        f"got {after.get('version')!r}"
    )


def assert_audit_fields(row: Dict[str, Any], label: str = "record") -> None:
    """Assert the record carries the audit fields no record in this system omits."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in row and row[field] is not None, f"{label} is missing {field}"
    assert isinstance(row["version"], int) and row["version"] >= 1, (
        f"{label} version should be a positive integer, got {row['version']!r}"
    )
    parse_instant(row["created_at"])
    parse_instant(row["updated_at"])


# ------------------------------------------------------------ season passes --


def assert_ledger_identity(pass_row: Dict[str, Any]) -> None:
    """billed_total_cents == paid_to_date_cents + credited_amount_cents + outstanding_balance_cents."""
    billed = pass_row["billed_total_cents"]
    paid = pass_row["paid_to_date_cents"]
    credited = pass_row["credited_amount_cents"]
    outstanding = pass_row["outstanding_balance_cents"]
    assert billed == paid + credited + outstanding, (
        "the money ledger identity is broken: "
        f"billed_total_cents {billed} != paid_to_date_cents {paid} "
        f"+ credited_amount_cents {credited} + outstanding_balance_cents {outstanding}"
    )


def assert_ledger(
    pass_row: Dict[str, Any],
    *,
    billed: Optional[int] = None,
    paid: Optional[int] = None,
    credited: Optional[int] = None,
    outstanding: Optional[int] = None,
    contract: Optional[int] = None,
) -> None:
    """Assert the money ledger figures and then the identity that binds them."""
    if contract is not None:
        assert pass_row["contract_value_cents"] == contract, (
            f"contract_value_cents should be {contract}, got {pass_row['contract_value_cents']}"
        )
    if billed is not None:
        assert pass_row["billed_total_cents"] == billed, (
            f"billed_total_cents should be {billed}, got {pass_row['billed_total_cents']}"
        )
    if paid is not None:
        assert pass_row["paid_to_date_cents"] == paid, (
            f"paid_to_date_cents should be {paid}, got {pass_row['paid_to_date_cents']}"
        )
    if credited is not None:
        assert pass_row["credited_amount_cents"] == credited, (
            f"credited_amount_cents should be {credited}, got {pass_row['credited_amount_cents']}"
        )
    if outstanding is not None:
        assert pass_row["outstanding_balance_cents"] == outstanding, (
            f"outstanding_balance_cents should be {outstanding}, "
            f"got {pass_row['outstanding_balance_cents']}"
        )
    assert_ledger_identity(pass_row)


def assert_pass_dimensions(
    pass_row: Dict[str, Any],
    *,
    pass_status: Optional[str] = None,
    billing_status: Optional[str] = None,
) -> None:
    """Assert the two independent status dimensions of a season pass."""
    if pass_status is not None:
        assert pass_row["pass_status"] == pass_status, (
            f"pass_status should be {pass_status}, got {pass_row['pass_status']!r}"
        )
    if billing_status is not None:
        assert pass_row["billing_status"] == billing_status, (
            f"billing_status should be {billing_status}, got {pass_row['billing_status']!r}"
        )


# ------------------------------------------------------------- park days -----


def assert_day_posture(
    day: Dict[str, Any],
    *,
    utilization: Optional[float] = None,
    day_class: Optional[str] = None,
    slot_capacity: Optional[int] = None,
    window_capacity: Optional[int] = None,
) -> None:
    """Assert the derived capacity posture of an operating day."""
    if utilization is not None:
        actual = day["forecast_utilization_pct"]
        assert abs(float(actual) - utilization) < 1e-9, (
            f"forecast_utilization_pct should be {utilization}, got {actual!r}"
        )
    if day_class is not None:
        assert day["day_class"] == day_class, (
            f"day_class should be {day_class}, got {day['day_class']!r}"
        )
    if slot_capacity is not None:
        assert day["reservation_slot_capacity"] == slot_capacity, (
            f"reservation_slot_capacity should be {slot_capacity}, "
            f"got {day['reservation_slot_capacity']!r}"
        )
    if window_capacity is not None:
        assert day["window_slot_capacity"] == window_capacity, (
            f"window_slot_capacity should be {window_capacity}, "
            f"got {day['window_slot_capacity']!r}"
        )


def assert_day_counters(
    day: Dict[str, Any],
    *,
    reserved: Optional[int] = None,
    released: Optional[int] = None,
    redeemed: Optional[int] = None,
    no_show: Optional[int] = None,
    remaining: Optional[int] = None,
    grant: Optional[int] = None,
) -> None:
    """Assert the live slot counters an operating day carries."""
    expectations = [
        ("reserved_count", reserved),
        ("released_count", released),
        ("redeemed_count", redeemed),
        ("no_show_count", no_show),
        ("remaining_slot_count", remaining),
        ("grant_count", grant),
    ]
    for field, expected in expectations:
        if expected is not None:
            assert day[field] == expected, (
                f"{field} should be {expected}, got {day[field]!r}"
            )


def assert_grant_count_conserved(day: Dict[str, Any]) -> None:
    """grant_count accounts for every reservation ever granted on the day.

    Every granted reservation is still counted in exactly one of the outcome
    counters, so the outcome counters must sum back to the audit counter.
    """
    outcomes = (
        day["reserved_count"]
        + day["released_count"]
        + day["redeemed_count"]
        + day["no_show_count"]
    )
    assert outcomes == day["grant_count"], (
        "reserved + released + redeemed + no_show should equal grant_count "
        f"{day['grant_count']}, got {outcomes} "
        f"(reserved {day['reserved_count']}, released {day['released_count']}, "
        f"redeemed {day['redeemed_count']}, no_show {day['no_show_count']})"
    )


# --------------------------------------------------------- payment plans -----


def assert_plan_amortization(
    plan: Dict[str, Any],
    *,
    financed: int,
    monthly: int,
    final: int,
    installment_count: int,
) -> None:
    """Assert the three amortisation figures and the no-drift invariant."""
    assert plan["installment_count"] == installment_count, (
        f"installment_count should be {installment_count}, got {plan['installment_count']!r}"
    )
    assert plan["financed_amount_cents"] == financed, (
        f"financed_amount_cents should be {financed}, got {plan['financed_amount_cents']!r}"
    )
    assert plan["monthly_amount_cents"] == monthly, (
        f"monthly_amount_cents should be {monthly}, got {plan['monthly_amount_cents']!r}"
    )
    assert plan["final_installment_cents"] == final, (
        f"final_installment_cents should be {final}, got {plan['final_installment_cents']!r}"
    )
    total = monthly * (installment_count - 1) + final
    assert total == financed, (
        f"the schedule drifts: {installment_count - 1} x {monthly} + {final} = {total}, "
        f"but financed_amount_cents is {financed}"
    )


def assert_installment_schedule(
    rows: Sequence[Dict[str, Any]],
    expected: Sequence[Tuple[int, int, str]],
) -> None:
    """Assert (sequence_no, amount_cents, due_date) triples in the given order."""
    assert len(rows) == len(expected), (
        f"expected {len(expected)} installments, got {len(rows)}"
    )
    for row, (sequence_no, amount_cents, due_date) in zip(rows, expected):
        assert row["sequence_no"] == sequence_no, (
            f"expected sequence_no {sequence_no}, got {row['sequence_no']!r}"
        )
        assert row["amount_cents"] == amount_cents, (
            f"installment {sequence_no} amount_cents should be {amount_cents}, "
            f"got {row['amount_cents']!r}"
        )
        assert row["due_date"] == due_date, (
            f"installment {sequence_no} due_date should be {due_date}, got {row['due_date']!r}"
        )


def assert_installment_statuses(rows: Sequence[Dict[str, Any]], expected: Sequence[str]) -> None:
    """Assert the installment status sequence in due-date order."""
    actual = [row["status"] for row in rows]
    assert actual == list(expected), (
        f"installment statuses should be {list(expected)} in due-date order, got {actual}"
    )


def assert_installments_sum_to_financed(rows: Sequence[Dict[str, Any]], financed: int) -> None:
    total = sum(row["amount_cents"] for row in rows)
    assert total == financed, (
        f"the installment amounts sum to {total} but the financed amount is {financed}"
    )


# -------------------------------------------------------- upgrade orders -----


def assert_upgrade_settlement(
    order: Dict[str, Any],
    *,
    gross: Optional[int] = None,
    raw_credit: Optional[int] = None,
    credit: Optional[int] = None,
    net: Optional[int] = None,
    admin_fee: Optional[int] = None,
    total_due: Optional[int] = None,
) -> None:
    """Assert the settlement breakdown an upgrade order reports."""
    expectations = [
        ("gross_delta_cents", gross),
        ("raw_credit_cents", raw_credit),
        ("credit_cents", credit),
        ("net_delta_cents", net),
        ("admin_fee_cents", admin_fee),
        ("total_due_cents", total_due),
    ]
    for field, expected in expectations:
        if expected is not None:
            assert order[field] == expected, (
                f"{field} should be {expected}, got {order[field]!r}"
            )


# ------------------------------------------------------- revenue summary -----


def assert_revenue_summary(
    summary: Dict[str, Any],
    *,
    base: Optional[int] = None,
    recognized: Optional[int] = None,
    deferred: Optional[int] = None,
    forfeited: Optional[int] = None,
    active_passes: Optional[int] = None,
    visits: Optional[int] = None,
    visits_per_active_pass: Optional[float] = None,
    spend: Optional[int] = None,
    spend_per_visit: Optional[int] = None,
) -> None:
    """Assert the nine reported figures of the programme revenue analysis."""
    integer_expectations = [
        ("base_revenue_cents", base),
        ("recognized_revenue_cents", recognized),
        ("deferred_revenue_cents", deferred),
        ("forfeited_revenue_cents", forfeited),
        ("active_pass_count", active_passes),
        ("total_visit_count", visits),
        ("total_in_park_spend_cents", spend),
        ("spend_per_visit_cents", spend_per_visit),
    ]
    for field, expected in integer_expectations:
        if expected is not None:
            assert summary[field] == expected, (
                f"{field} should be {expected}, got {summary[field]!r}"
            )
    if visits_per_active_pass is not None:
        actual = float(summary["visits_per_active_pass"])
        assert abs(actual - visits_per_active_pass) < 1e-9, (
            f"visits_per_active_pass should be {visits_per_active_pass}, got {actual!r}"
        )


def assert_billing_run_counts(result: Dict[str, Any], **expected: int) -> None:
    """Assert the counters a billing run reports; keyword names are the fields."""
    for field, value in expected.items():
        assert result[field] == value, (
            f"billing run {field} should be {value}, got {result[field]!r}"
        )


# ------------------------------------------------------------- orderings -----


def assert_ordered_by(
    rows: Sequence[Dict[str, Any]], field: str, descending: bool = False
) -> None:
    """Assert a listing is ordered on the given field."""
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows should be ordered by {field} "
        f"{'DESC' if descending else 'ASC'}, got {values}"
    )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def find_by_id(rows: Iterable[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError(f"no row with id {row_id} in the listing")
