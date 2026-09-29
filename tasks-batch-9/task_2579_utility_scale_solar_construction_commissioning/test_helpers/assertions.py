"""Domain assertions shared by the suite.

Each helper states one invariant the PRD imposes, so a test asserts the
invariant by name rather than restating the arithmetic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

Json = Dict[str, Any]

MONEY_TOLERANCE = 0
RATIO_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# System fields (PRD 2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Json) -> None:
    """`id`, `created_at`, `updated_at` and `version` are present and well formed."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"created_at is not ISO-8601: {entity['created_at']!r}"
    assert is_iso8601_timestamp(
        entity["updated_at"]
    ), f"updated_at is not ISO-8601: {entity['updated_at']!r}"
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1, f"version starts at 1, got {entity['version']}"


def assert_versionless_interval(interval: Json) -> None:
    """A measurement interval carries only `id` and `created_at`."""
    assert is_valid_uuid(interval["id"]), f"id is not a UUID: {interval['id']!r}"
    assert is_iso8601_timestamp(
        interval["created_at"]
    ), f"created_at is not ISO-8601: {interval['created_at']!r}"
    assert "updated_at" not in interval, "an interval must not expose updated_at"
    assert "version" not in interval, "an interval must not expose version"


def assert_created_fresh(entity: Json) -> None:
    """A newly created row is at version 1 with matching timestamps."""
    assert_common_fields(entity)
    assert entity["version"] == 1, f"a new row starts at version 1, got {entity['version']}"
    assert entity["created_at"] == entity["updated_at"]


def assert_version_is(entity: Json, expected: int) -> None:
    assert (
        entity["version"] == expected
    ), f"expected version {expected}, got {entity['version']}"


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def assert_page_meta(
    meta: Json,
    *,
    total: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """`meta` carries the pagination counters, optionally at fixed values."""
    for key in ("total_count", "limit", "offset"):
        assert key in meta, f"pagination meta is missing {key}"
        assert isinstance(meta[key], int), f"{key} must be an integer"
    if total is not None:
        assert (
            meta["total_count"] == total
        ), f"expected total_count {total}, got {meta['total_count']}"
    if has_more is not None:
        assert (
            meta["has_more"] is has_more
        ), f"expected has_more {has_more}, got {meta['has_more']}"
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_ids_equal(rows: Sequence[Json], expected_ids: Iterable[str]) -> None:
    """The page holds exactly these rows, order-insensitively."""
    assert {row["id"] for row in rows} == set(expected_ids)


def assert_contains_id(rows: Sequence[Json], entity_id: str) -> None:
    assert entity_id in {row["id"] for row in rows}, f"{entity_id} is absent from the page"


def assert_excludes_id(rows: Sequence[Json], entity_id: str) -> None:
    assert entity_id not in {row["id"] for row in rows}, f"{entity_id} leaked into the page"


def assert_instant_equals(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Two ISO-8601 UTC strings denote the same instant.

    The PRD fixes the spelling of `created_at` and `updated_at` (three
    fractional digits) but says nothing about the spelling of the domain
    instants it derives — `rain_blackout_until` is only "`occurred_at` advanced
    by 48 hours" and `energized_at` is only "the current logical-clock instant".
    Comparing the parsed instants keeps the exact-instant assertion the PRD does
    make without importing a serialization choice it never states.
    """
    assert isinstance(actual, str), f"{label} must be an ISO-8601 string, got {actual!r}"

    def _parse(value: str) -> datetime:
        text = value.strip()
        assert text.endswith("Z"), f"{label} must be a UTC instant ending in Z, got {value!r}"
        body = text[:-1]
        if "." not in body:
            body += ".000000"
        return datetime.strptime(body, "%Y-%m-%dT%H:%M:%S.%f")

    assert _parse(actual) == _parse(
        expected
    ), f"expected {label} at instant {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Money and ratios
# ---------------------------------------------------------------------------
def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """A money field is an integer count of cents at exactly the expected value."""
    assert isinstance(actual, int) and not isinstance(
        actual, bool
    ), f"{label} must be an integer number of cents, got {actual!r}"
    assert actual == expected, f"expected {label} {expected} cents, got {actual}"


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    """A two-decimal derived figure matches to a hundredth."""
    assert actual == pytest.approx(
        expected, abs=RATIO_TOLERANCE
    ), f"expected {label} {expected}, got {actual}"


# ---------------------------------------------------------------------------
# PRD 3.1 — project scope and settlement
# ---------------------------------------------------------------------------
def assert_project_state(
    project: Json,
    *,
    mc_readiness: Optional[str] = None,
    blocks_mc_ready_count: Optional[int] = None,
    milestone_state: Optional[str] = None,
    tax_credit_status: Optional[str] = None,
) -> None:
    if mc_readiness is not None:
        assert (
            project["mc_readiness"] == mc_readiness
        ), f"expected mc_readiness {mc_readiness}, got {project['mc_readiness']}"
    if blocks_mc_ready_count is not None:
        assert project["blocks_mc_ready_count"] == blocks_mc_ready_count, (
            f"expected blocks_mc_ready_count {blocks_mc_ready_count}, "
            f"got {project['blocks_mc_ready_count']}"
        )
    if milestone_state is not None:
        assert (
            project["milestone_state"] == milestone_state
        ), f"expected milestone_state {milestone_state}, got {project['milestone_state']}"
    if tax_credit_status is not None:
        assert (
            project["tax_credit_status"] == tax_credit_status
        ), f"expected tax_credit_status {tax_credit_status}, got {project['tax_credit_status']}"


def assert_waterfall(
    summary: Json,
    *,
    adjusted_contract_cents: Optional[int] = None,
    ld_cap_cents: Optional[int] = None,
    delay_days: Optional[int] = None,
    ld_assessed_cents: Optional[int] = None,
    retainage_held_cents: Optional[int] = None,
    punchlist_holdback_cents: Optional[int] = None,
    sc_payment_due_cents: Optional[int] = None,
    final_payment_cents: Optional[int] = None,
) -> None:
    """The figures the settlement ladder freezes, checked in one call."""
    if adjusted_contract_cents is not None:
        assert_cents(
            summary["adjusted_contract_cents"],
            adjusted_contract_cents,
            "adjusted_contract_cents",
        )
    if ld_cap_cents is not None:
        assert_cents(summary["ld_cap_cents"], ld_cap_cents, "ld_cap_cents")
    if delay_days is not None:
        assert (
            summary["delay_days"] == delay_days
        ), f"expected delay_days {delay_days}, got {summary['delay_days']}"
    if ld_assessed_cents is not None:
        assert_cents(summary["ld_assessed_cents"], ld_assessed_cents, "ld_assessed_cents")
    if retainage_held_cents is not None:
        assert_cents(
            summary["retainage_held_cents"], retainage_held_cents, "retainage_held_cents"
        )
    if punchlist_holdback_cents is not None:
        assert_cents(
            summary["punchlist_holdback_cents"],
            punchlist_holdback_cents,
            "punchlist_holdback_cents",
        )
    if sc_payment_due_cents is not None:
        assert_cents(
            summary["sc_payment_due_cents"], sc_payment_due_cents, "sc_payment_due_cents"
        )
    if final_payment_cents is not None:
        assert_cents(
            summary["final_payment_cents"], final_payment_cents, "final_payment_cents"
        )


def assert_waterfall_zeroed(summary: Json) -> None:
    """Before substantial completion every frozen figure of the ladder reads zero."""
    for key in (
        "delay_days",
        "ld_cap_cents",
        "ld_assessed_cents",
        "retainage_held_cents",
        "punchlist_holdback_cents",
        "sc_payment_due_cents",
        "final_payment_cents",
    ):
        assert summary[key] == 0, f"expected {key} 0, got {summary[key]}"


# ---------------------------------------------------------------------------
# PRD 3.2 — grading areas
# ---------------------------------------------------------------------------
def assert_grading_area_state(
    area: Json,
    *,
    status: Optional[str] = None,
    permit_status: Optional[str] = None,
    disturbed_acreage_current: Optional[float] = None,
    bmp_deficiency_open: Optional[bool] = None,
) -> None:
    if status is not None:
        assert area["status"] == status, f"expected status {status}, got {area['status']}"
    if permit_status is not None:
        assert (
            area["permit_status"] == permit_status
        ), f"expected permit_status {permit_status}, got {area['permit_status']}"
    if disturbed_acreage_current is not None:
        assert_ratio(
            area["disturbed_acreage_current"],
            disturbed_acreage_current,
            "disturbed_acreage_current",
        )
    if bmp_deficiency_open is not None:
        assert (
            area["bmp_deficiency_open"] is bmp_deficiency_open
        ), f"expected bmp_deficiency_open {bmp_deficiency_open}, got {area['bmp_deficiency_open']}"


# ---------------------------------------------------------------------------
# PRD 3.3 — yard zones and deliveries
# ---------------------------------------------------------------------------
def assert_pallet_conservation(zone: Json) -> None:
    """Reserved plus available pallets always equals the zone's capacity."""
    assert (
        zone["reserved_pallets"] + zone["available_pallets"] == zone["pallet_capacity"]
    ), (
        "pallet capacity must split into reserved and available: "
        f"{zone['reserved_pallets']} + {zone['available_pallets']} != {zone['pallet_capacity']}"
    )


def assert_zone_occupancy(
    zone: Json, *, reserved_pallets: int, available_pallets: int
) -> None:
    assert (
        zone["reserved_pallets"] == reserved_pallets
    ), f"expected reserved_pallets {reserved_pallets}, got {zone['reserved_pallets']}"
    assert (
        zone["available_pallets"] == available_pallets
    ), f"expected available_pallets {available_pallets}, got {zone['available_pallets']}"
    assert_pallet_conservation(zone)


def assert_delivery_receipt(
    delivery: Json,
    *,
    status: str,
    accepted_unit_qty: int,
    damage_ratio: float,
) -> None:
    assert (
        delivery["status"] == status
    ), f"expected delivery status {status}, got {delivery['status']}"
    assert (
        delivery["accepted_unit_qty"] == accepted_unit_qty
    ), f"expected accepted_unit_qty {accepted_unit_qty}, got {delivery['accepted_unit_qty']}"
    assert_ratio(delivery["damage_ratio"], damage_ratio, "damage_ratio")


# ---------------------------------------------------------------------------
# PRD 3.4 / 3.5 — blocks, piles, circuits
# ---------------------------------------------------------------------------
def assert_block_counters(
    block: Json,
    *,
    piles_accepted_count: Optional[int] = None,
    piles_refused_count: Optional[int] = None,
    circuits_wired_count: Optional[int] = None,
    circuits_tested_count: Optional[int] = None,
    circuits_failed_count: Optional[int] = None,
    mc_ready: Optional[bool] = None,
    mechanical_status: Optional[str] = None,
    electrical_status: Optional[str] = None,
) -> None:
    """The five rollup counters, the two status dimensions and `mc_ready`."""
    for name, expected in (
        ("piles_accepted_count", piles_accepted_count),
        ("piles_refused_count", piles_refused_count),
        ("circuits_wired_count", circuits_wired_count),
        ("circuits_tested_count", circuits_tested_count),
        ("circuits_failed_count", circuits_failed_count),
    ):
        if expected is not None:
            assert (
                block[name] == expected
            ), f"expected {name} {expected}, got {block[name]}"
    if mc_ready is not None:
        assert (
            block["mc_ready"] is mc_ready
        ), f"expected mc_ready {mc_ready}, got {block['mc_ready']}"
    if mechanical_status is not None:
        assert (
            block["mechanical_status"] == mechanical_status
        ), f"expected mechanical_status {mechanical_status}, got {block['mechanical_status']}"
    if electrical_status is not None:
        assert (
            block["electrical_status"] == electrical_status
        ), f"expected electrical_status {electrical_status}, got {block['electrical_status']}"


def assert_pile_disposition(pile: Json, expected_status: str) -> None:
    assert (
        pile["status"] == expected_status
    ), f"expected pile status {expected_status}, got {pile['status']}"


def assert_string_test_failure(circuit: Json, expected_reason: str) -> None:
    assert (
        circuit["status"] == "FAILED"
    ), f"a failed test leaves the circuit FAILED, got {circuit['status']}"
    assert (
        circuit["test_failure_reason"] == expected_reason
    ), f"expected test_failure_reason {expected_reason}, got {circuit['test_failure_reason']}"


# ---------------------------------------------------------------------------
# PRD 3.7 — commissioning
# ---------------------------------------------------------------------------
def assert_commissioning_result(
    test: Json,
    *,
    status: Optional[str] = None,
    interval_count: Optional[int] = None,
    valid_interval_count: Optional[int] = None,
    reported_kw_ac: Optional[float] = None,
    pass_threshold_kw_ac: Optional[float] = None,
    reported_performance_ratio: Optional[float] = None,
) -> None:
    """The status a finalization lands on and the figures it reports."""
    if status is not None:
        assert test["status"] == status, f"expected test status {status}, got {test['status']}"
    if interval_count is not None:
        assert (
            test["interval_count"] == interval_count
        ), f"expected interval_count {interval_count}, got {test['interval_count']}"
    if valid_interval_count is not None:
        assert test["valid_interval_count"] == valid_interval_count, (
            f"expected valid_interval_count {valid_interval_count}, "
            f"got {test['valid_interval_count']}"
        )
    if reported_kw_ac is not None:
        assert_ratio(test["reported_kw_ac"], reported_kw_ac, "reported_kw_ac")
    if pass_threshold_kw_ac is not None:
        assert_ratio(
            test["pass_threshold_kw_ac"], pass_threshold_kw_ac, "pass_threshold_kw_ac"
        )
    if reported_performance_ratio is not None:
        assert test["reported_performance_ratio"] == pytest.approx(
            reported_performance_ratio, abs=0.0001
        ), (
            f"expected reported_performance_ratio {reported_performance_ratio}, "
            f"got {test['reported_performance_ratio']}"
        )


# ---------------------------------------------------------------------------
# PRD 3.8 — certified payroll
# ---------------------------------------------------------------------------
def assert_hour_conservation(week: Json) -> None:
    """Apprentice hours plus journeyworker hours always equals the week total."""
    assert week["apprentice_hours"] + week["journeyworker_hours"] == pytest.approx(
        week["total_hours"], abs=RATIO_TOLERANCE
    ), (
        "week hours must split into apprentice and journeyworker: "
        f"{week['apprentice_hours']} + {week['journeyworker_hours']} != {week['total_hours']}"
    )


def assert_week_totals(
    week: Json,
    *,
    total_hours: float,
    journeyworker_hours: float,
    apprentice_hours: float,
    apprentice_pct: Optional[float] = None,
    version: Optional[int] = None,
) -> None:
    assert_ratio(week["total_hours"], total_hours, "total_hours")
    assert_ratio(week["journeyworker_hours"], journeyworker_hours, "journeyworker_hours")
    assert_ratio(week["apprentice_hours"], apprentice_hours, "apprentice_hours")
    if apprentice_pct is not None:
        assert_ratio(week["apprentice_pct"], apprentice_pct, "apprentice_pct")
    if version is not None:
        assert_version_is(week, version)
    assert_hour_conservation(week)


def assert_compliance_run(
    run: Json,
    *,
    apprentice_hours_pct: Optional[float] = None,
    apprenticeship_basis_applied: Optional[str] = None,
    wage_restitution_owed_cents: Optional[int] = None,
    wage_liquidated_damages_cents: Optional[int] = None,
    tax_credit_status: Optional[str] = None,
) -> None:
    """The five figures a labor-compliance run records."""
    if apprentice_hours_pct is not None:
        assert_ratio(
            run["apprentice_hours_pct"], apprentice_hours_pct, "apprentice_hours_pct"
        )
    if apprenticeship_basis_applied is not None:
        assert run["apprenticeship_basis_applied"] == apprenticeship_basis_applied, (
            f"expected apprenticeship_basis_applied {apprenticeship_basis_applied}, "
            f"got {run['apprenticeship_basis_applied']}"
        )
    if wage_restitution_owed_cents is not None:
        assert_cents(
            run["wage_restitution_owed_cents"],
            wage_restitution_owed_cents,
            "wage_restitution_owed_cents",
        )
    if wage_liquidated_damages_cents is not None:
        assert_cents(
            run["wage_liquidated_damages_cents"],
            wage_liquidated_damages_cents,
            "wage_liquidated_damages_cents",
        )
    if tax_credit_status is not None:
        assert (
            run["tax_credit_status"] == tax_credit_status
        ), f"expected tax_credit_status {tax_credit_status}, got {run['tax_credit_status']}"


# ---------------------------------------------------------------------------
# Read-your-write (PRD 2.9)
# ---------------------------------------------------------------------------
def assert_same_entity(write_body: Json, read_body: Json, *fields: str) -> None:
    """A write response and the following read agree field by field."""
    assert write_body["id"] == read_body["id"]
    checked = fields or tuple(
        key for key in write_body if key not in {"created_at", "updated_at"}
    )
    for field in checked:
        assert write_body[field] == read_body[field], (
            f"{field} differs between the write response and the next read: "
            f"{write_body[field]!r} != {read_body[field]!r}"
        )
