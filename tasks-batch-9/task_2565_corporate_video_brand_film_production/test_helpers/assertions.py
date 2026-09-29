"""Domain assertions for the corporate video production contract.

These wrap the recurring shape checks so a test body reads as the rule it is
testing rather than as a pile of dictionary lookups. Nothing here invents a rule:
every helper states, in its own docstring, the PRD sentence it enforces.
"""

from typing import Any, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import DEFAULT_CLOCK
from .factories import parse_ts, same_instant
from .types import COMMON_FIELD_NAMES


# ─── Common envelope and common fields (PRD §2.2, §2.4) ────────────────────


def assert_common_fields(row: dict) -> None:
    """Every resource carries the same four fields.

    PRD §2.4: "Every resource in this system — projects, budget lines, deliverables,
    cuts, change orders, talent engagements, locations, shoot days, compliance
    certificates, crew members, crew bookings and equipment reservations — carries the
    same four system-managed properties, with no exceptions and no entity omitting any
    of them". `id` is a UUID, the two stamps are UTC instants, and `version` starts at 1
    and only ever rises.
    """
    for field in COMMON_FIELD_NAMES:
        assert field in row, f"missing common field {field}: {sorted(row)}"
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int), type(row["version"])
    assert row["version"] >= 1, row["version"]


def assert_fields_present(row: dict, field_names: Iterable[str]) -> None:
    """Assert a resource projects exactly the fields the contract names for it."""
    missing = [name for name in field_names if name not in row]
    assert not missing, f"missing fields {missing}: {sorted(row)}"


def created_row(response: Any, expected_status: int = 201) -> dict:
    """Validate a creation response and hand back its `data` object."""
    row = get_success_data(response, expected_status=expected_status)
    assert isinstance(row, dict), type(row)
    assert_common_fields(row)
    return row


def ok_row(response: Any) -> dict:
    """Validate a 200 response and hand back its `data` object."""
    row = get_success_data(response, expected_status=200)
    assert isinstance(row, dict), type(row)
    return row


# ─── Timestamps (PRD §2.4, §2.5) ────────────────────────────────────────────


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    """Compare two instants by the moment they denote, not by their spelling.

    PRD §2.4 renders stored stamps "with three fractional digits", so a value read
    back off a row is the same instant as a whole-second literal even though the
    two strings differ character for character.
    """
    assert actual is not None, f"expected the instant {expected}, got null"
    assert same_instant(actual, expected), f"{actual!r} is not the instant {expected!r}"


def assert_at_default_clock(actual: Optional[str]) -> None:
    """The stamp is the logical clock's untouched starting value.

    PRD §2.5: "Every run begins with the clock at `2026-08-01T00:00:00Z`."
    """
    assert_instant_equals(actual, DEFAULT_CLOCK)


def assert_stamps_advanced(before: dict, after: dict) -> None:
    """A mutation moves `updated_at` forward and leaves `created_at` alone."""
    assert same_instant(before["created_at"], after["created_at"]), (
        f"created_at moved: {before['created_at']!r} -> {after['created_at']!r}"
    )
    assert parse_ts(after["updated_at"]) >= parse_ts(before["updated_at"]), (
        f"updated_at went backwards: {before['updated_at']!r} -> {after['updated_at']!r}"
    )


# ─── Version counters (PRD §2.4, §2.10) ─────────────────────────────────────


def assert_version_is(row: dict, expected: int) -> None:
    assert row["version"] == expected, f"version {row['version']} != {expected}"


def assert_version_bumped(before: dict, after: dict, by: int = 1) -> None:
    """A write that changes a row raises that row's `version`.

    PRD §2.4: "`version` (integer): a counter that starts at 1 on creation and
    increments by 1 on every mutation of the row, including mutations the server performs
    on its own initiative as part of a cascade."
    """
    assert after["version"] == before["version"] + by, (
        f"version {before['version']} -> {after['version']}, expected +{by}"
    )


def assert_version_unchanged(before: dict, after: dict) -> None:
    """A refused write leaves the row, including its counter, untouched."""
    assert after["version"] == before["version"], (
        f"version moved on a refused write: {before['version']} -> {after['version']}"
    )


# ─── The twin cost ledgers (PRD §2.7) ───────────────────────────────────────


def assert_ledgers(
    project: dict,
    provisional_cents: Optional[int] = None,
    committed_cents: Optional[int] = None,
    approved_cents: Optional[int] = ...,  # type: ignore[assignment]
    variance_cents: Optional[int] = None,
) -> None:
    """Assert the project's four money fields together.

    PRD §2.7 defines `provisional_cost_cents` and `committed_cost_cents` as two
    sums over the same rows under different status filters, and states that
    "`budget_variance_cents` is `provisional_cost_cents` minus
    `approved_budget_cents`, and is reported as 0 for as long as
    `approved_budget_cents` is null."
    """
    if provisional_cents is not None:
        assert project["provisional_cost_cents"] == provisional_cents, (
            f"provisional {project['provisional_cost_cents']} != {provisional_cents}"
        )
    if committed_cents is not None:
        assert project["committed_cost_cents"] == committed_cents, (
            f"committed {project['committed_cost_cents']} != {committed_cents}"
        )
    if approved_cents is not ...:
        assert project["approved_budget_cents"] == approved_cents, (
            f"approved {project['approved_budget_cents']} != {approved_cents}"
        )
    if variance_cents is not None:
        assert project["budget_variance_cents"] == variance_cents, (
            f"variance {project['budget_variance_cents']} != {variance_cents}"
        )


def assert_variance_is_zero_while_unapproved(project: dict) -> None:
    """Variance reads 0 until a budget is approved.

    PRD §2.7: "`budget_variance_cents` is `provisional_cost_cents` minus
    `approved_budget_cents`, and is reported as 0 for as long as
    `approved_budget_cents` is null."
    """
    assert project["approved_budget_cents"] is None, project["approved_budget_cents"]
    assert project["budget_variance_cents"] == 0, project["budget_variance_cents"]


# ─── Collections (PRD §2.3) ─────────────────────────────────────────────────


def assert_total_count(response: Any, expected: int) -> list:
    """Assert a listing's `total_count` and hand back its rows.

    PRD §2.3: "Every list response sets `response_type` to `"array"`, returns the rows
    as the envelope's `data` array, and carries `limit`, `offset`, `total_count` and
    `has_more` inside `meta`."
    """
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, f"total_count {meta['total_count']} != {expected}"
    return rows


def assert_empty_listing(response: Any) -> None:
    """A refused write must leave nothing behind for a listing to find."""
    rows = assert_total_count(response, 0)
    assert rows == [], rows


def assert_ordered_by(rows: Sequence[dict], *field_names: str) -> None:
    """Assert rows arrive in the contract's declared order.

    PRD §2.3 fixes a deterministic order per collection: "shoot days are ordered by
    `call_time` ascending and then by `created_at` ascending as a tie-break, and crew
    bookings are ordered by `call_time` ascending and then by `created_at` ascending."
    """
    def key(row: dict) -> tuple:
        return tuple(
            parse_ts(row[name]) if isinstance(row[name], str) and "T" in row[name] else row[name]
            for name in field_names
        )

    keys = [key(row) for row in rows]
    assert keys == sorted(keys), f"rows are not ordered by {field_names}: {keys}"


def ids_of(rows: Iterable[dict]) -> list:
    return [row["id"] for row in rows]


# ─── Per-entity state assertions ────────────────────────────────────────────


def assert_project_state(
    project: dict,
    status: Optional[str] = None,
    review_gate: Optional[str] = None,
    archive_status: Optional[str] = None,
    round_entitlement_balance: Optional[int] = None,
) -> None:
    """Assert a project's status axes and its conserved round balance.

    PRD §3.1 opens a project at `status` `DRAFT` with `review_gate` `OPEN` and
    `archive_status` `NOT_PACKAGED`; §3.8 keeps `round_entitlement_balance` on the
    project rather than on any one deliverable.
    """
    if status is not None:
        assert project["status"] == status, f"project status {project['status']} != {status}"
    if review_gate is not None:
        assert project["review_gate"] == review_gate, (
            f"review_gate {project['review_gate']} != {review_gate}"
        )
    if round_entitlement_balance is not None:
        assert project["round_entitlement_balance"] == round_entitlement_balance, (
            f"round_entitlement_balance {project['round_entitlement_balance']}"
            f" != {round_entitlement_balance}"
        )
    if archive_status is not None:
        assert project["archive_status"] == archive_status, (
            f"archive_status {project['archive_status']} != {archive_status}"
        )


def assert_deliverable_state(
    deliverable: dict,
    status: Optional[str] = None,
    version_count: Optional[int] = None,
    consumed_review_rounds: Optional[int] = None,
    granted_extra_rounds: Optional[int] = None,
    round_entitlement: Optional[int] = None,
) -> None:
    """Assert a deliverable's status and its four counters (PRD §3.1, §3.8)."""
    if status is not None:
        assert deliverable["status"] == status, f"deliverable status {deliverable['status']} != {status}"
    if version_count is not None:
        assert deliverable["version_count"] == version_count, (
            f"version_count {deliverable['version_count']} != {version_count}"
        )
    if consumed_review_rounds is not None:
        assert deliverable["consumed_review_rounds"] == consumed_review_rounds, (
            f"consumed_review_rounds {deliverable['consumed_review_rounds']}"
            f" != {consumed_review_rounds}"
        )
    if granted_extra_rounds is not None:
        assert deliverable["granted_extra_rounds"] == granted_extra_rounds, (
            f"granted_extra_rounds {deliverable['granted_extra_rounds']} != {granted_extra_rounds}"
        )
    if round_entitlement is not None:
        assert deliverable["round_entitlement"] == round_entitlement, (
            f"round_entitlement {deliverable['round_entitlement']} != {round_entitlement}"
        )


def assert_entitlement_columns_agree(deliverable: dict, contracted_rounds: int) -> None:
    """A deliverable's entitlement is the contract plus what was granted to it.

    PRD §3.8: "`granted_extra_rounds` is the sum of `additional_rounds_granted`
    across that deliverable's `APPROVED` change orders, and `round_entitlement` is
    the project's `contracted_revision_rounds` plus that sum."
    """
    expected = contracted_rounds + deliverable["granted_extra_rounds"]
    assert deliverable["round_entitlement"] == expected, (
        f"round_entitlement {deliverable['round_entitlement']} != {contracted_rounds}"
        f" + {deliverable['granted_extra_rounds']}"
    )


def assert_balance_conserved(
    project: dict, granted_on_approved: int, consumed_across_deliverables: int
) -> None:
    """The project-wide balance is the conserved quantity of PRD §3.8.

    "`round_entitlement_balance` is the project's `contracted_revision_rounds`,
    plus the `additional_rounds_granted` of every change order on any deliverable
    of the project whose `status` is `APPROVED`, minus the `consumed_review_rounds`
    of every deliverable of the project."
    """
    expected = (
        project["contracted_revision_rounds"] + granted_on_approved - consumed_across_deliverables
    )
    assert project["round_entitlement_balance"] == expected, (
        f"round_entitlement_balance {project['round_entitlement_balance']} != {expected}"
    )


def assert_version_axes(
    version: dict,
    review_status: Optional[str] = None,
    technical_status: Optional[str] = None,
    qc_failure_reasons: Optional[Sequence[str]] = None,
    round_index: Optional[int] = None,
) -> None:
    """Assert a cut's two orthogonal status axes and its QC findings (PRD §3.8)."""
    if review_status is not None:
        assert version["review_status"] == review_status, (
            f"review_status {version['review_status']} != {review_status}"
        )
    if technical_status is not None:
        assert version["technical_status"] == technical_status, (
            f"technical_status {version['technical_status']} != {technical_status}"
        )
    if qc_failure_reasons is not None:
        # PRD §3.8 fixes the order the findings are "appended" in, so this is a
        # sequence comparison and not a set comparison.
        assert list(version["qc_failure_reasons"]) == list(qc_failure_reasons), (
            f"qc_failure_reasons {version['qc_failure_reasons']} != {list(qc_failure_reasons)}"
        )
    if round_index is not None:
        assert version["round_index"] == round_index, (
            f"round_index {version['round_index']} != {round_index}"
        )


def assert_shoot_day_state(
    day: dict,
    status: Optional[str] = None,
    compliance_posture: Optional[str] = None,
    call_sheet_status: Optional[str] = None,
    confirmed_crew_count: Optional[int] = None,
    day_cost_cents: Optional[int] = None,
) -> None:
    """Assert a shoot day's status, posture, call sheet and rollups (PRD §3.5)."""
    if status is not None:
        assert day["status"] == status, f"shoot day status {day['status']} != {status}"
    if compliance_posture is not None:
        assert day["compliance_posture"] == compliance_posture, (
            f"compliance_posture {day['compliance_posture']} != {compliance_posture}"
        )
    if call_sheet_status is not None:
        assert day["call_sheet_status"] == call_sheet_status, (
            f"call_sheet_status {day['call_sheet_status']} != {call_sheet_status}"
        )
    if confirmed_crew_count is not None:
        assert day["confirmed_crew_count"] == confirmed_crew_count, (
            f"confirmed_crew_count {day['confirmed_crew_count']} != {confirmed_crew_count}"
        )
    if day_cost_cents is not None:
        assert day["day_cost_cents"] == day_cost_cents, (
            f"day_cost_cents {day['day_cost_cents']} != {day_cost_cents}"
        )


def assert_booking_components(
    booking: dict,
    straight_time_cents: Optional[int] = None,
    overtime_tier1_cents: Optional[int] = None,
    overtime_tier2_cents: Optional[int] = None,
    cost_cents: Optional[int] = None,
    scheduled_hours: Optional[float] = None,
    status: Optional[str] = None,
) -> None:
    """Assert a crew booking's three cost components and their sum (PRD §3.6)."""
    if status is not None:
        assert booking["status"] == status, f"booking status {booking['status']} != {status}"
    if straight_time_cents is not None:
        assert booking["straight_time_cents"] == straight_time_cents, (
            f"straight_time_cents {booking['straight_time_cents']} != {straight_time_cents}"
        )
    if overtime_tier1_cents is not None:
        assert booking["overtime_tier1_cents"] == overtime_tier1_cents, (
            f"overtime_tier1_cents {booking['overtime_tier1_cents']} != {overtime_tier1_cents}"
        )
    if overtime_tier2_cents is not None:
        assert booking["overtime_tier2_cents"] == overtime_tier2_cents, (
            f"overtime_tier2_cents {booking['overtime_tier2_cents']} != {overtime_tier2_cents}"
        )
    if scheduled_hours is not None:
        assert float(booking["scheduled_hours"]) == float(scheduled_hours), (
            f"scheduled_hours {booking['scheduled_hours']} != {scheduled_hours}"
        )
    if cost_cents is not None:
        assert booking["cost_cents"] == cost_cents, (
            f"cost_cents {booking['cost_cents']} != {cost_cents}"
        )


def assert_booking_sum(booking: dict) -> None:
    """The booking's total is exactly its three components added up.

    PRD §3.6: "`cost_cents` is the sum of those three components, rounded half up to
    whole cents exactly once at the end, per §2.6."
    """
    total = (
        booking["straight_time_cents"]
        + booking["overtime_tier1_cents"]
        + booking["overtime_tier2_cents"]
    )
    assert booking["cost_cents"] == total, f"cost_cents {booking['cost_cents']} != {total}"


def assert_talent_comp(
    engagement: dict,
    base_fee_cents: Optional[int] = None,
    usage_load_cents: Optional[int] = None,
    reuse_fee_cents: Optional[int] = None,
    pension_health_cents: Optional[int] = None,
    agent_fee_cents: Optional[int] = None,
    total_comp_cents: Optional[int] = None,
    comp_basis: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    """Assert a talent engagement's per-component compensation (PRD §3.3)."""
    expectations = {
        "base_fee_cents": base_fee_cents,
        "usage_load_cents": usage_load_cents,
        "reuse_fee_cents": reuse_fee_cents,
        "pension_health_cents": pension_health_cents,
        "agent_fee_cents": agent_fee_cents,
        "total_comp_cents": total_comp_cents,
        "comp_basis": comp_basis,
        "status": status,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert engagement[field] == expected, f"{field} {engagement[field]} != {expected}"


def assert_change_order(
    change_order: dict,
    labor_cents: Optional[int] = None,
    rush_pct: Optional[float] = None,
    rush_cents: Optional[int] = None,
    subtotal_cents: Optional[int] = None,
    producer_fee_pct: Optional[float] = None,
    producer_fee_cents: Optional[int] = None,
    amount_cents: Optional[int] = None,
    status: Optional[str] = None,
    trigger_reason: Optional[str] = None,
) -> None:
    """Assert a change order's priced components (PRD §3.9)."""
    expectations = {
        "labor_cents": labor_cents,
        "rush_pct": rush_pct,
        "rush_cents": rush_cents,
        "subtotal_cents": subtotal_cents,
        "producer_fee_pct": producer_fee_pct,
        "producer_fee_cents": producer_fee_cents,
        "amount_cents": amount_cents,
        "status": status,
        "trigger_reason": trigger_reason,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert change_order[field] == expected, f"{field} {change_order[field]} != {expected}"


def assert_cert_statuses(cert: dict, status: str, effective_status: str) -> None:
    """Assert the stored status and the derived one separately.

    PRD §3.5: `effective_status` reads `EXPIRED` when an issued certificate's
    window has passed, and "in every other case it simply equals the stored
    `status`".
    """
    assert cert["status"] == status, f"cert status {cert['status']} != {status}"
    assert cert["effective_status"] == effective_status, (
        f"effective_status {cert['effective_status']} != {effective_status}"
    )


def assert_budget_line(
    line: dict,
    extended_cents: Optional[int] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
) -> None:
    """Assert a budget line's extended amount and commitment status (PRD §3.2)."""
    if extended_cents is not None:
        assert line["extended_cents"] == extended_cents, (
            f"extended_cents {line['extended_cents']} != {extended_cents}"
        )
    if status is not None:
        assert line["status"] == status, f"budget line status {line['status']} != {status}"
    if category is not None:
        assert line["category"] == category, f"category {line['category']} != {category}"


def assert_reservation(
    reservation: dict,
    rental_days: Optional[int] = None,
    total_cost_cents: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    """Assert an equipment reservation's rental days, cost and status (PRD §3.6)."""
    if rental_days is not None:
        assert reservation["rental_days"] == rental_days, (
            f"rental_days {reservation['rental_days']} != {rental_days}"
        )
    if total_cost_cents is not None:
        assert reservation["total_cost_cents"] == total_cost_cents, (
            f"total_cost_cents {reservation['total_cost_cents']} != {total_cost_cents}"
        )
    if status is not None:
        assert reservation["status"] == status, f"reservation status {reservation['status']} != {status}"


def assert_unchanged(before: dict, after: dict, *field_names: str) -> None:
    """Assert a refused write left the named fields exactly as they were."""
    for name in field_names:
        assert before[name] == after[name], (
            f"{name} changed on a refused write: {before[name]!r} -> {after[name]!r}"
        )
