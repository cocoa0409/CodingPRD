"""
Domain assertion helpers.

The per-entity checkers assert the shape every response of that entity must
have: a UUID id, ISO-8601 timestamps, the declared enum domains, and - for the
ten row types that carry the common system fields - an ``updated_at`` and a
positive integer ``version``. The three append-only journal row types are
checked with the opposite expectation: they must NOT expose ``updated_at`` or
``version``.

The invariant checkers assert the two conserved quantities: the funding ledger
identity and the inventory-area identity.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ADMIN_RATE,
    ASBESTOS_GRADES,
    ASBESTOS_SURCHARGE_PCT,
    COUNTY_OVERHEAD_PCT,
    DEMO_BASE_CENTS,
    DEMO_RATE_PER_SQFT_CENTS,
    MOW_RATE_PER_KSQFT_CENTS,
    RESERVE_FLOOR_PCT,
    SECURE_BASE_CENTS,
    SECURE_RATE_PER_OPENING_CENTS,
)
from .types import (
    AGREEMENT_STATUSES,
    APPLICANT_TYPES,
    APPLICATION_STATUSES,
    CUSTODY_STATUSES,
    DISCHARGE_MODES,
    ELIGIBILITY_STATUSES,
    FUNDING_RESTRICTIONS,
    FUNDING_SOURCE_TYPES,
    FUNDING_STATUSES,
    ORDER_STATUSES,
    PACKET_STATUSES,
    PROGRAMS,
    RUN_STATUSES,
    SCREENING_OUTCOMES,
    STRUCTURE_GRADES,
    TITLE_ACTION_STATUSES,
    TITLE_ACTION_TYPES,
    TITLE_STATUSES,
    WORK_TYPES,
)


# ─── rounding helpers ────────────────────────────────────────────────────────
def round_half_up(value: float, decimals: int = 0) -> float:
    """
    Half-up rounding, the rule the API applies to every monetary and ratio
    result. Python's built-in ``round`` is half-to-even and would disagree on
    exact .5 boundaries, which is precisely where the pinned values live.
    """
    factor = 10 ** decimals
    scaled = value * factor
    # Nudge away from binary-float representation error before flooring.
    shifted = scaled + 0.5
    if abs(shifted - round(shifted)) < 1e-9:
        shifted = round(shifted)
    result = int(shifted) if shifted >= 0 else -int(-shifted + 0.5)
    return result / factor if decimals else float(result)


def expected_reserve_floor_cents(authorized_cents: int) -> int:
    """The 5 percent reserve floor a funding source must carry."""
    return int(round_half_up(RESERVE_FLOOR_PCT * authorized_cents))


def expected_admin_fee_cents(committed_subtotal_cents: int) -> int:
    """The 7.5 percent administrative fee on a run's committed subtotal."""
    return int(round_half_up(ADMIN_RATE * committed_subtotal_cents))


def expected_order_estimate_cents(subtotal_cents: int) -> int:
    """
    Apply the second of the two pinned rounding stages: county overhead is
    computed on the already-rounded line-item subtotal and rounded once.
    """
    return subtotal_cents + int(round_half_up(COUNTY_OVERHEAD_PCT * subtotal_cents))


def expected_mow_estimate_cents(lot_area_sqft: int) -> int:
    """Mow cost: whole thousand-square-foot blocks, then county overhead."""
    blocks = -(-lot_area_sqft // 1000)  # ceiling division
    return expected_order_estimate_cents(blocks * MOW_RATE_PER_KSQFT_CENTS)


def expected_secure_estimate_cents(openings_count: int) -> int:
    """Secure cost: a base charge plus a per-opening charge, then overhead."""
    subtotal = SECURE_BASE_CENTS + int(
        round_half_up(openings_count * SECURE_RATE_PER_OPENING_CENTS)
    )
    return expected_order_estimate_cents(subtotal)


def expected_demolition_estimate_cents(
    lot_area_sqft: int, structure_condition_grade: str
) -> int:
    """
    Demolition cost: a base charge, a per-square-foot charge and - for the two
    worst structure grades - an asbestos surcharge on the sum of those two. Each
    line item is rounded to whole cents before the lines are summed, and the
    county overhead is applied once to that sum.
    """
    per_sqft = int(round_half_up(lot_area_sqft * DEMO_RATE_PER_SQFT_CENTS))
    asbestos = 0
    if structure_condition_grade in ASBESTOS_GRADES:
        asbestos = int(
            round_half_up(ASBESTOS_SURCHARGE_PCT * (DEMO_BASE_CENTS + per_sqft))
        )
    return expected_order_estimate_cents(DEMO_BASE_CENTS + per_sqft + asbestos)


# ─── shared field checks ─────────────────────────────────────────────────────
def assert_common_fields(row: Dict[str, Any]) -> None:
    """Assert the four common system fields every mutable row carries."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not ISO 8601: {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at is not ISO 8601: {row.get('updated_at')!r}"
    )
    assert isinstance(row["version"], int) and row["version"] >= 1, (
        f"version must be a positive integer, got {row.get('version')!r}"
    )


def assert_append_only_fields(row: Dict[str, Any]) -> None:
    """
    Assert an append-only journal row: a UUID id and a created_at, and neither
    updated_at nor version, because nothing ever modifies these rows.
    """
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not ISO 8601: {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, (
        "append-only rows must not expose updated_at, got "
        f"{row.get('updated_at')!r}"
    )
    assert "version" not in row, (
        f"append-only rows must not expose version, got {row.get('version')!r}"
    )


def _assert_enum(row: Dict[str, Any], field: str, domain: Iterable[str]) -> None:
    assert row[field] in tuple(domain), (
        f"{field} must be one of {tuple(domain)}, got {row.get(field)!r}"
    )


def _assert_optional_timestamp(row: Dict[str, Any], field: str) -> None:
    value = row.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), (
            f"{field} is not ISO 8601: {value!r}"
        )


# ─── per-entity checkers ─────────────────────────────────────────────────────
def assert_property(row: Dict[str, Any]) -> None:
    """Assert the shape of a Property registry row."""
    assert_common_fields(row)
    _assert_enum(row, "structure_condition_grade", STRUCTURE_GRADES)
    _assert_enum(row, "custody_status", CUSTODY_STATUSES)
    _assert_enum(row, "title_status", TITLE_STATUSES)
    for field in (
        "situs_ward",
        "lot_area_sqft",
        "assessed_value_cents",
        "vacancy_months",
        "nuisance_complaint_count",
        "open_code_violation_count",
        "delinquent_tax_balance_cents",
        "pre_acquisition_delinquency_cents",
        "acquisition_cost_cents",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
    assert isinstance(row["structure_present"], bool)
    assert isinstance(row["secured"], bool)
    assert isinstance(row["current_blight_score"], (int, float))
    for field in ("acquired_at", "last_mow_at", "demolished_at", "listed_at"):
        _assert_optional_timestamp(row, field)


def assert_funding_source(row: Dict[str, Any]) -> None:
    """Assert the shape of a FundingSource row and its ledger identity."""
    assert_common_fields(row)
    _assert_enum(row, "source_type", FUNDING_SOURCE_TYPES)
    _assert_enum(row, "restriction", FUNDING_RESTRICTIONS)
    _assert_enum(row, "status", FUNDING_STATUSES)
    for field in (
        "authorized_cents",
        "committed_cents",
        "disbursed_cents",
        "available_cents",
        "reserve_floor_cents",
        "open_run_count",
        "recaptured_cents",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
    assert_ledger_identity(row)


def assert_acquisition_packet(row: Dict[str, Any]) -> None:
    """Assert the shape of an AcquisitionPacket row."""
    assert_common_fields(row)
    _assert_enum(row, "status", PACKET_STATUSES)
    assert row["channel"] in ("TAX_FORECLOSURE", "DONATION", "NEGOTIATED_PURCHASE")
    for field in ("offer_price_cents", "title_search_fee_cents", "committed_cents"):
        assert isinstance(row[field], int), f"{field} must be an integer"
    assert isinstance(row["initiated_by_user_id"], str) and row["initiated_by_user_id"]


def assert_title_action(row: Dict[str, Any]) -> None:
    """Assert the shape of a TitleAction row."""
    assert_common_fields(row)
    _assert_enum(row, "action_type", TITLE_ACTION_TYPES)
    _assert_enum(row, "status", TITLE_ACTION_STATUSES)
    assert isinstance(row["round_no"], int) and row["round_no"] >= 1
    assert is_iso8601_timestamp(row["filed_at"])
    _assert_optional_timestamp(row, "adjudicated_at")


def assert_contractor(row: Dict[str, Any]) -> None:
    """Assert the shape of a Contractor row."""
    assert_common_fields(row)
    assert is_iso8601_timestamp(row["license_expires_on"])
    assert isinstance(row["max_concurrent_crews"], int)
    assert isinstance(row["specialties"], list)
    for entry in row["specialties"]:
        assert entry in WORK_TYPES, f"unknown specialty {entry!r}"
    assert isinstance(row["debarred"], bool)


def assert_maintenance_order(row: Dict[str, Any]) -> None:
    """Assert the shape of a MaintenanceOrder row."""
    assert_common_fields(row)
    _assert_enum(row, "work_type", WORK_TYPES)
    _assert_enum(row, "status", ORDER_STATUSES)
    assert is_iso8601_timestamp(row["window_start"])
    assert is_iso8601_timestamp(row["window_end"])
    assert row["window_end"] > row["window_start"], (
        "window_end must be strictly after window_start"
    )
    assert isinstance(row["estimated_cost_cents"], int)
    _assert_optional_timestamp(row, "completed_at")


def assert_demolition_run(row: Dict[str, Any]) -> None:
    """Assert the shape of a DemolitionRun row."""
    assert_common_fields(row)
    _assert_enum(row, "status", RUN_STATUSES)
    for field in (
        "run_sequence",
        "budget_cents",
        "provisional_cap_cents",
        "properties_selected_count",
        "skipped_property_count",
        "committed_subtotal_cents",
        "admin_fee_cents",
        "total_committed_cents",
        "orders_created_count",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
    assert isinstance(row["selected_property_ids"], list)
    assert isinstance(row["skipped_property_ids"], list)
    assert row["properties_selected_count"] == len(row["selected_property_ids"])
    assert row["skipped_property_count"] == len(row["skipped_property_ids"])
    assert row["total_committed_cents"] <= row["budget_cents"], (
        "the provisional cap guarantees the total commitment fits the budget"
    )
    _assert_optional_timestamp(row, "executed_at")


def assert_applicant(row: Dict[str, Any]) -> None:
    """Assert the shape of an Applicant row."""
    assert_common_fields(row)
    _assert_enum(row, "applicant_type", APPLICANT_TYPES)
    _assert_enum(row, "eligibility_status", ELIGIBILITY_STATUSES)
    for field in (
        "reverter_count",
        "good_standing_count",
        "delinquent_tax_total_cents",
        "open_code_violation_total",
        "recent_reverter_count",
        "conveyed_property_count",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
    _assert_optional_timestamp(row, "last_reverter_at")


def assert_disposition_application(row: Dict[str, Any]) -> None:
    """Assert the shape of a DispositionApplication row."""
    assert_common_fields(row)
    _assert_enum(row, "program", PROGRAMS)
    _assert_enum(row, "status", APPLICATION_STATUSES)
    for field in ("offer_price_cents", "quoted_price_cents", "revision_round",
                  "screening_count"):
        assert isinstance(row[field], int), f"{field} must be an integer"
    _assert_optional_timestamp(row, "submitted_at")
    _assert_optional_timestamp(row, "board_decision_at")


def assert_development_agreement(row: Dict[str, Any]) -> None:
    """Assert the shape of a DevelopmentAgreement row."""
    assert_common_fields(row)
    _assert_enum(row, "status", AGREEMENT_STATUSES)
    _assert_enum(row, "discharge_mode", DISCHARGE_MODES)
    for field in (
        "milestone_count",
        "milestones_completed",
        "abatement_years",
        "projected_improved_value_cents",
        "sale_price_cents",
        "discharged_tax_cents",
        "abatement_annual_cents",
        "abatement_total_cents",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer"
    assert isinstance(row["reverter_clause_active"], bool)
    assert is_iso8601_timestamp(row["performance_deadline"])
    assert is_iso8601_timestamp(row["executed_at"])
    for field in ("cure_deadline", "complied_at", "reverted_at"):
        _assert_optional_timestamp(row, field)
    assert row["abatement_total_cents"] == (
        row["abatement_annual_cents"] * row["abatement_years"]
    ), "the total abatement is the annual figure times the number of years"


def assert_parcel_adjacency(row: Dict[str, Any]) -> None:
    """Assert the shape of a ParcelAdjacency edge (append-only)."""
    assert_append_only_fields(row)
    assert is_valid_uuid(row["property_id"])
    assert is_valid_uuid(row["adjacent_property_id"])
    assert row["property_id"] != row["adjacent_property_id"], (
        "an adjacency edge may never join a parcel to itself"
    )
    assert isinstance(row["shared_boundary_feet"], (int, float))


def assert_reuse_hearing(row: Dict[str, Any]) -> None:
    """Assert the shape of a ReuseHearing record (append-only)."""
    assert_append_only_fields(row)
    assert is_iso8601_timestamp(row["hearing_at"])
    assert isinstance(row["comment_count"], int)
    assert isinstance(row["support_count"], int)
    assert row["support_count"] <= row["comment_count"], (
        "support_count may never exceed comment_count"
    )
    assert isinstance(row["support_ratio"], (int, float))


def assert_eligibility_screening(row: Dict[str, Any]) -> None:
    """Assert the shape of an EligibilityScreening record (append-only)."""
    assert_append_only_fields(row)
    _assert_enum(row, "outcome", SCREENING_OUTCOMES)
    assert isinstance(row["sequence_no"], int) and row["sequence_no"] >= 1
    assert is_iso8601_timestamp(row["screened_at"])
    assert isinstance(row["disqualifiers"], list)
    assert isinstance(row["eligibility_score"], (int, float))
    assert 0 <= row["eligibility_score"] <= 100
    if row["disqualifiers"]:
        assert row["outcome"] == "FAIL", (
            "a screening with disqualifiers cannot pass"
        )
    else:
        assert row["outcome"] == "PASS", (
            "a screening with no disqualifiers cannot fail"
        )


# ─── invariant checkers ──────────────────────────────────────────────────────
def assert_ledger_identity(funding_source: Dict[str, Any]) -> None:
    """
    Assert the conserved funding identity:
    authorized_cents == available_cents + committed_cents + disbursed_cents.
    """
    total = (
        funding_source["available_cents"]
        + funding_source["committed_cents"]
        + funding_source["disbursed_cents"]
    )
    assert funding_source["authorized_cents"] == total, (
        "ledger identity broken: authorized "
        f"{funding_source['authorized_cents']} != available "
        f"{funding_source['available_cents']} + committed "
        f"{funding_source['committed_cents']} + disbursed "
        f"{funding_source['disbursed_cents']}"
    )


def assert_ledger_position(
    funding_source: Dict[str, Any],
    *,
    authorized_cents: Optional[int] = None,
    committed_cents: Optional[int] = None,
    disbursed_cents: Optional[int] = None,
    available_cents: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    """Assert a specific ledger position, and the identity alongside it."""
    if authorized_cents is not None:
        assert funding_source["authorized_cents"] == authorized_cents
    if committed_cents is not None:
        assert funding_source["committed_cents"] == committed_cents, (
            f"committed_cents {funding_source['committed_cents']} != {committed_cents}"
        )
    if disbursed_cents is not None:
        assert funding_source["disbursed_cents"] == disbursed_cents, (
            f"disbursed_cents {funding_source['disbursed_cents']} != {disbursed_cents}"
        )
    if available_cents is not None:
        assert funding_source["available_cents"] == available_cents, (
            f"available_cents {funding_source['available_cents']} != {available_cents}"
        )
    if status is not None:
        assert funding_source["status"] == status, (
            f"funding status {funding_source['status']} != {status}"
        )
    assert_ledger_identity(funding_source)


def assert_inventory_area_conserved(summary: Dict[str, Any], total_sqft: int) -> None:
    """
    Assert the conserved inventory-area identity: inventory area plus conveyed
    area accounts for every square foot the authority has ever taken in.
    """
    actual = summary["inventory_area_sqft"] + summary["conveyed_area_sqft"]
    assert actual == total_sqft, (
        f"inventory {summary['inventory_area_sqft']} + conveyed "
        f"{summary['conveyed_area_sqft']} = {actual}, expected {total_sqft}"
    )


def assert_same_instant(actual: Optional[str], expected: Optional[str]) -> None:
    """
    Assert that two ISO-8601 UTC strings name the same instant.

    The PRD pins a three-fractional-digit rendering for ``created_at``,
    ``updated_at`` and ``api_request_timestamp`` only; it says nothing about how
    the business instants (``window_start``, ``listed_at``, ``executed_at``,
    ``cure_deadline``, ``reverted_at``, ``last_reverter_at``, ``swept_at``) are
    rendered, so both ``...T00:00:00Z`` and ``...T00:00:00.000Z`` are faithful
    spellings of the same instant. The instant itself is what the PRD pins, and
    that is what this compares.
    """
    assert actual is not None, f"expected the instant {expected}, got null"
    assert is_iso8601_timestamp(actual), f"{actual} is not an ISO-8601 UTC timestamp"
    parsed_actual = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    parsed_expected = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
    assert parsed_actual == parsed_expected, (
        f"instant {actual} != expected {expected}"
    )


def assert_score(actual: float, expected: float) -> None:
    """
    Assert a blight score. Scores are carried to one decimal place, so an exact
    numeric comparison is what the contract calls for.
    """
    assert float(actual) == float(expected), (
        f"blight score {actual} != expected {expected}"
    )
