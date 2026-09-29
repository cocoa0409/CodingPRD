"""Domain assertions built on the generic ones.

The arithmetic helpers here re-derive PRD formulas independently (round-half-up
to two decimals, the 25-pascal normalization, the six-step rebate arithmetic) so
that a test can pin an expected number without hard-coding it in two places.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ADMIN_FEE_RATE,
    CO_MAX_PPM,
    CO_WARN_PPM,
    DRAFT_MIN_PA,
    FLOW_EXPONENT,
    REFERENCE_PRESSURE_PA,
    SPILLAGE_MAX_SECONDS,
    TIER_BONUS_BANDS,
    TIER_BONUS_NONE,
    VERDICT_FAIL,
    VERDICT_MARGINAL,
    VERDICT_PASS,
    WCD_LIMIT_PA,
)


# ---------------------------------------------------------------------------
# Rounding discipline (PRD 2.6)
# ---------------------------------------------------------------------------
def round_half_up(value: float, places: int = 2) -> float:
    """"rounded to **2 decimal places using round-half-up"."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def round_cents_half_up(value: float) -> int:
    """"rounded half-up to a whole number of cents"."""
    return int(Decimal(repr(float(value))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def assert_two_decimals(value: Any, label: str = "value") -> None:
    """A derived decimal quantity must already be rounded to two places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round_half_up(value, 2) == float(value), (
        f"{label} must carry at most two decimals, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Envelope-adjacent field discipline (PRD 2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the full identity set: id, created_at, updated_at and version.

    "Every other record type in this system ... carries the full set of `id`,
    `created_at`, `updated_at` and `version`."
    """
    assert is_valid_uuid(entity.get("id")), f"id must be a UUID, got {entity.get('id')!r}"
    assert "_" not in str(entity["id"]), (
        "id must be a UUID with no type prefix"
    )
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"created_at must be ISO 8601, got {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"updated_at must be ISO 8601, got {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_fields(entity: Dict[str, Any]) -> None:
    """Assert the reduced identity set of an append-only measurement row.

    "Two record types are append-only measurement rows and therefore carry only
    `id` and `created_at` — they have **no** `updated_at` and **no** `version`
    field at all."
    """
    assert is_valid_uuid(entity.get("id")), f"id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"created_at must be ISO 8601, got {entity.get('created_at')!r}"
    )
    assert "updated_at" not in entity, "append-only rows carry no updated_at"
    assert "version" not in entity, "append-only rows carry no version"


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """Check the four pagination fields of PRD 2.3 against expectations."""
    if limit is not None:
        assert meta["limit"] == limit, f"expected meta.limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"expected meta.offset {offset}, got {meta['offset']}"
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected meta.total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected meta.has_more {has_more}, got {meta['has_more']}"
        )


def assert_request_id(meta: Dict[str, Any]) -> None:
    """"a server-generated unique identifier for the request that starts with `req_`"."""
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )


# ---------------------------------------------------------------------------
# Leakage normalization (PRD 3.3)
# ---------------------------------------------------------------------------
def normalize_to_cfm25(measured_leakage_cfm: float, test_pressure_pa: float) -> float:
    """Step one of the pinned two-step order.

    "multiplying `measured_leakage_cfm` by the ratio of 25 to `test_pressure_pa`
    raised to the power of the flow exponent 0.60, and rounds that product
    half-up to two decimal places".
    """
    raw = measured_leakage_cfm * (
        (REFERENCE_PRESSURE_PA / test_pressure_pa) ** FLOW_EXPONENT
    )
    return round_half_up(raw, 2)


def leakage_per_100_sqft(
    normalized_leakage_cfm25: float, conditioned_floor_area_sqft: float
) -> float:
    """Step two, computed "from the already-rounded normalized leakage value"."""
    return round_half_up(
        normalized_leakage_cfm25 / (conditioned_floor_area_sqft / 100.0), 2
    )


def reduction_pct(pre_cfm25: float, post_cfm25: float) -> float:
    """"subtracting `post_leakage_cfm25` from `pre_leakage_cfm25`, dividing that
    difference by `pre_leakage_cfm25`, multiplying by 100"."""
    return round_half_up((pre_cfm25 - post_cfm25) / pre_cfm25 * 100.0, 2)


def variance_pct(spot_check_cfm25: float, post_leakage_cfm25: float) -> float:
    """"the absolute difference between `spot_check_cfm25` and the report's
    `post_leakage_cfm25`, divided by the report's `post_leakage_cfm25`,
    multiplied by 100"."""
    return round_half_up(
        abs(spot_check_cfm25 - post_leakage_cfm25) / post_leakage_cfm25 * 100.0, 2
    )


def seal_rate_cfm_per_min(
    earlier_cfm: float, later_cfm: float, earlier_elapsed_s: int, later_elapsed_s: int
) -> float:
    """"taking the `instantaneous_leakage_cfm` of the point two sequence positions
    earlier, subtracting the `instantaneous_leakage_cfm` of the point just
    stored, and dividing that drop by the elapsed time between the two points
    expressed in minutes"."""
    minutes = (later_elapsed_s - earlier_elapsed_s) / 60.0
    return round_half_up((earlier_cfm - later_cfm) / minutes, 2)


def deviation_pct(measured_cfm: float, design_cfm: float) -> float:
    """"subtracting `design_cfm` from `measured_cfm`, dividing by `design_cfm`,
    multiplying by 100"."""
    return round_half_up((measured_cfm - design_cfm) / design_cfm * 100.0, 2)


# ---------------------------------------------------------------------------
# Combustion verdict (PRD 3.4)
# ---------------------------------------------------------------------------
def expected_verdict(
    appliance_type: str,
    spillage_seconds: int,
    co_ppm_air_free: float,
    draft_pressure_pa: float,
    worst_case_depressurization_pa: float,
) -> str:
    """The three ordered branches of the verdict, "Readings are used as supplied"."""
    ceiling = CO_MAX_PPM[appliance_type]
    warn = CO_WARN_PPM[appliance_type]
    wcd_limit = WCD_LIMIT_PA[appliance_type]
    if (
        co_ppm_air_free > ceiling
        or spillage_seconds > SPILLAGE_MAX_SECONDS
        or (
            worst_case_depressurization_pa > wcd_limit
            and draft_pressure_pa < DRAFT_MIN_PA
        )
    ):
        return VERDICT_FAIL
    if co_ppm_air_free >= warn or spillage_seconds == SPILLAGE_MAX_SECONDS:
        return VERDICT_MARGINAL
    return VERDICT_PASS


# ---------------------------------------------------------------------------
# Rebate arithmetic (PRD 3.8)
# ---------------------------------------------------------------------------
def expected_tier_bonus_pct(reduction_pct_whole_house_basis: float) -> float:
    """"Each band boundary is inclusive at its lower edge"."""
    for floor, bonus in TIER_BONUS_BANDS:
        if reduction_pct_whole_house_basis >= floor:
            return bonus
    return TIER_BONUS_NONE


def expected_per_cfm_candidate_cents(
    rate_cents_per_cfm_reduced: int, cfm_reduced_whole_house: float
) -> int:
    return round_cents_half_up(rate_cents_per_cfm_reduced * cfm_reduced_whole_house)


def expected_percent_of_invoice_candidate_cents(
    invoice_amount_cents: int, pct_of_invoice_bps: int
) -> int:
    return round_cents_half_up(invoice_amount_cents * pct_of_invoice_bps / 10000.0)


def expected_capped_subtotal_cents(base_cents: int, tier_bonus_pct: float, cap_cents: int) -> int:
    """"The bonused subtotal is the base multiplied by one plus `tier_bonus_pct`,
    rounded half-up to a whole number of cents. `capped_subtotal_cents` is then
    the smaller of that bonused subtotal and the program's `cap_cents`"."""
    bonused = round_cents_half_up(base_cents * (1.0 + tier_bonus_pct))
    return min(bonused, cap_cents)


def expected_admin_fee_cents(capped_subtotal_cents: int) -> int:
    """"five percent of `capped_subtotal_cents` ... computed **after** the cap"."""
    return round_cents_half_up(capped_subtotal_cents * ADMIN_FEE_RATE)


# ---------------------------------------------------------------------------
# The two ledgers (PRD 2.10, 2.11)
# ---------------------------------------------------------------------------
def assert_leakage_ledger(
    duct_system: Dict[str, Any],
    baseline_leakage_cfm25: Optional[float],
    working_leakage_cfm25: Optional[float],
    sealed_leakage_reduction_cfm: float,
) -> None:
    """Pin all three fields of the duct system's leakage ledger at once."""
    assert duct_system["baseline_leakage_cfm25"] == baseline_leakage_cfm25, (
        f"expected baseline_leakage_cfm25 {baseline_leakage_cfm25}, "
        f"got {duct_system['baseline_leakage_cfm25']}"
    )
    assert duct_system["working_leakage_cfm25"] == working_leakage_cfm25, (
        f"expected working_leakage_cfm25 {working_leakage_cfm25}, "
        f"got {duct_system['working_leakage_cfm25']}"
    )
    assert duct_system["sealed_leakage_reduction_cfm"] == sealed_leakage_reduction_cfm, (
        f"expected sealed_leakage_reduction_cfm {sealed_leakage_reduction_cfm}, "
        f"got {duct_system['sealed_leakage_reduction_cfm']}"
    )


def assert_ledger_identity(duct_system: Dict[str, Any]) -> None:
    """"`sealed_leakage_reduction_cfm` is the difference obtained by subtracting
    `working_leakage_cfm25` from `baseline_leakage_cfm25`"."""
    baseline = duct_system["baseline_leakage_cfm25"]
    working = duct_system["working_leakage_cfm25"]
    reduction = duct_system["sealed_leakage_reduction_cfm"]
    assert baseline is not None and working is not None, (
        "the ledger identity is only meaningful once a baseline exists"
    )
    assert round_half_up(baseline - working, 2) == reduction, (
        f"ledger identity broken: {baseline} - {working} != {reduction}"
    )


def assert_program_ledger(
    program: Dict[str, Any],
    committed_rebate_cents: int,
    paid_rebate_cents: int,
    remaining_budget_cents: int,
) -> None:
    """Pin the three-part money ledger of PRD 2.11."""
    assert program["committed_rebate_cents"] == committed_rebate_cents, (
        f"expected committed_rebate_cents {committed_rebate_cents}, "
        f"got {program['committed_rebate_cents']}"
    )
    assert program["paid_rebate_cents"] == paid_rebate_cents, (
        f"expected paid_rebate_cents {paid_rebate_cents}, "
        f"got {program['paid_rebate_cents']}"
    )
    assert program["remaining_budget_cents"] == remaining_budget_cents, (
        f"expected remaining_budget_cents {remaining_budget_cents}, "
        f"got {program['remaining_budget_cents']}"
    )


def assert_program_ledger_identity(program: Dict[str, Any]) -> None:
    """"`remaining_budget_cents` is `annual_budget_cents` less
    `committed_rebate_cents` less `paid_rebate_cents`"."""
    assert program["remaining_budget_cents"] == (
        program["annual_budget_cents"]
        - program["committed_rebate_cents"]
        - program["paid_rebate_cents"]
    ), "the program budget identity does not hold"


def assert_all_cents_integers(entity: Dict[str, Any]) -> None:
    """"Monetary quantities are integer cents throughout; there are no fractional
    cents anywhere in the rebate arithmetic"."""
    for key, value in entity.items():
        if key.endswith("_cents") and value is not None:
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{key} must be an integer number of cents, got {value!r}"
            )


def assert_ordered_by(rows: Iterable[Dict[str, Any]], field: str) -> None:
    """Assert a list response is ascending in `field`."""
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows are not ascending in {field}: {values}"
