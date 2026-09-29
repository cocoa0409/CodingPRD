"""Domain-specific assertions and reference arithmetic.

The reference helpers here reimplement the PRD's arithmetic exactly as the PRD
words it — the rounding discipline of §2.6, the nested clamp of §3.3, the
truncated surplus ratio of §3.8 and the largest-remainder split — so that a
test can state an expected figure either as a literal or as the output of the
same words the contract uses.
"""

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ADMIN_FEE_BPS_BY_TIER,
    AGE_BAND_FACTOR_BPS,
    BENEFIT_TIER_ADDON_CENTS,
    BPS_PAR,
    COMPOSITE_WEIGHT_ACCESS_BPS,
    COMPOSITE_WEIGHT_HEDIS_BPS,
    COMPOSITE_WEIGHT_PATIENT_EXPERIENCE_BPS,
    PMPM_CEILING_CENTS,
    PMPM_FLOOR_CENTS,
    POOL_DEFICIT_LOSS_RATIO_BPS,
    SHARED_SAVINGS_SHARE_BPS_BY_TIER,
    SURPLUS_TIER_1_MAX_RATIO_BPS,
    SURPLUS_TIER_2_MAX_RATIO_BPS,
    WITHHOLD_RELEASE_BANDS,
    WITHHOLD_RELEASE_BELOW_ALL_BANDS_BPS,
)

# ---------------------------------------------------------------------------
# Rounding primitives (PRD §2.6)
# ---------------------------------------------------------------------------


def round_half_up(numerator: int, denominator: int) -> int:
    """Round a rational to a whole unit, halves away from zero."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_value(value: Fraction) -> int:
    return round_half_up(value.numerator, value.denominator)


def truncate_toward_zero(numerator: int, denominator: int) -> int:
    """Truncate a rational toward zero rather than rounding it."""
    magnitude = abs(numerator) // abs(denominator)
    sign = -1 if (numerator < 0) != (denominator < 0) else 1
    return sign * magnitude


# ---------------------------------------------------------------------------
# Audit-field assertions (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_versioned_resource(resource: Dict[str, Any], expected_version: Optional[int] = None):
    """Assert the four audit fields carried by eleven of the twelve types."""
    assert is_valid_uuid(resource["id"]), f"id is not a bare UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert "updated_at" in resource, "updated_at must be present on this resource"
    assert is_iso8601_timestamp(resource["updated_at"]), resource["updated_at"]
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_row_resource(row: Dict[str, Any]):
    """Assert a file row carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "updated_at" not in row, "a file row must not expose updated_at"
    assert "version" not in row, "a file row must not expose version"


def assert_instant(value: str, expected: Optional[str] = None):
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC instant: {value!r}"
    if expected is not None:
        assert value == expected, f"expected instant {expected}, got {value}"


# ---------------------------------------------------------------------------
# Field-set assertions
# ---------------------------------------------------------------------------


def assert_fields(resource: Dict[str, Any], expected: Dict[str, Any]):
    """Assert every named field equals its expected value, reporting all misses."""
    mismatches = []
    for field, want in expected.items():
        assert field in resource, f"missing field {field!r} in {sorted(resource)}"
        got = resource[field]
        if got != want:
            mismatches.append(f"{field}: expected {want!r}, got {got!r}")
    assert not mismatches, "; ".join(mismatches)


# ---------------------------------------------------------------------------
# Per-member capitation components (PRD §3.3)
# ---------------------------------------------------------------------------


def expected_pmpm_components(
    base_pmpm_cents: int,
    age_band: str,
    benefit_tier: str,
    risk_score_bps: int,
    quality_withhold_bps: int,
) -> Tuple[int, int, int]:
    """Return ``(gross_pmpm_cents, withhold_cents, net_pmpm_cents)``.

    The risk-adjusted product is rounded once at the end of the chain, the flat
    tier add-on is applied after that rounding, and the clamp is nested: the
    floor is applied first and the ceiling second.
    """
    product = (
        Fraction(base_pmpm_cents)
        * Fraction(AGE_BAND_FACTOR_BPS[age_band], BPS_PAR)
        * Fraction(risk_score_bps, BPS_PAR)
    )
    raw = round_half_up_value(product) + BENEFIT_TIER_ADDON_CENTS[benefit_tier]
    clamped = max(raw, PMPM_FLOOR_CENTS)
    gross = min(clamped, PMPM_CEILING_CENTS)
    withhold = round_half_up(gross * quality_withhold_bps, BPS_PAR)
    return gross, withhold, gross - withhold


def assert_pmpm_components(
    enrollee: Dict[str, Any], gross: int, withhold: int, net: int
):
    assert_fields(
        enrollee,
        {
            "gross_pmpm_cents": gross,
            "withhold_cents": withhold,
            "net_pmpm_cents": net,
        },
    )


# ---------------------------------------------------------------------------
# Remittance waterfall (PRD §3.5)
# ---------------------------------------------------------------------------


def expected_remittance_waterfall(
    expected_capitation_cents: int,
    claimed_capitation_cents: int,
    retro_adjustment_cents: int,
    quality_withhold_bps: int,
    institutional_pool_share_bps: int,
) -> Dict[str, int]:
    """Reproduce the seven-step remittance waterfall."""
    variance = (
        claimed_capitation_cents + retro_adjustment_cents - expected_capitation_cents
    )
    withhold = round_half_up(expected_capitation_cents * quality_withhold_bps, BPS_PAR)
    net_payable = expected_capitation_cents - withhold + retro_adjustment_cents
    institutional = round_half_up(net_payable * institutional_pool_share_bps, BPS_PAR)
    return {
        "expected_capitation_cents": expected_capitation_cents,
        "claimed_capitation_cents": claimed_capitation_cents,
        "retro_adjustment_cents": retro_adjustment_cents,
        "variance_cents": variance,
        "withhold_cents": withhold,
        "net_payable_cents": net_payable,
        "institutional_allocation_cents": institutional,
        "professional_allocation_cents": net_payable - institutional,
    }


def assert_allocations_resum(remittance: Dict[str, Any]):
    """The two allocations must re-sum to net payable with zero drift."""
    total = (
        remittance["institutional_allocation_cents"]
        + remittance["professional_allocation_cents"]
    )
    assert total == remittance["net_payable_cents"], (
        "institutional plus professional must equal net_payable_cents: "
        f"{total} != {remittance['net_payable_cents']}"
    )


# ---------------------------------------------------------------------------
# Pool loss ratio and deficit (PRD §3.5)
# ---------------------------------------------------------------------------


def expected_loss_ratio_bps(funded_cents: int, paid_claims_cents: int) -> int:
    if funded_cents == 0:
        return 0
    return round_half_up(paid_claims_cents * BPS_PAR, funded_cents)


def expected_deficit_flag(loss_ratio_bps: int) -> bool:
    return loss_ratio_bps > POOL_DEFICIT_LOSS_RATIO_BPS


def assert_pool_loss_position(
    pool: Dict[str, Any], loss_ratio_bps: int, deficit_flag: bool
):
    assert_fields(pool, {"loss_ratio_bps": loss_ratio_bps, "deficit_flag": deficit_flag})


# ---------------------------------------------------------------------------
# IBNR reserve (PRD §3.7)
# ---------------------------------------------------------------------------


def expected_completion_factor_reserve(
    paid_claims_cents: int, ibnr_completion_factor_bps: int
) -> int:
    ultimate = round_half_up(paid_claims_cents * BPS_PAR, ibnr_completion_factor_bps)
    return max(ultimate - paid_claims_cents, 0)


def expected_pmpm_loss_ratio_reserve(
    paid_claims_cents: int, target_claims_pmpm_cents: int, member_months_bps: int
) -> int:
    expected = round_half_up(target_claims_pmpm_cents * member_months_bps, BPS_PAR)
    return max(expected - paid_claims_cents, 0)


# ---------------------------------------------------------------------------
# Stop-loss recovery (PRD §3.7)
# ---------------------------------------------------------------------------


def expected_recovery_figures(
    eligible_paid_cents: int, attachment_cents: int, reinsurance_recovery_bps: int
) -> Dict[str, int]:
    excess = max(eligible_paid_cents - attachment_cents, 0)
    return {
        "attachment_cents": attachment_cents,
        "eligible_paid_cents": eligible_paid_cents,
        "excess_cents": excess,
        "recovery_cents": round_half_up(excess * reinsurance_recovery_bps, BPS_PAR),
    }


# ---------------------------------------------------------------------------
# Quality composite and withhold release (PRD §3.8)
# ---------------------------------------------------------------------------


def expected_composite_score_bps(
    hedis_composite_bps: int, access_score_bps: int, patient_experience_bps: int
) -> int:
    accumulated = (
        Fraction(hedis_composite_bps * COMPOSITE_WEIGHT_HEDIS_BPS, BPS_PAR)
        + Fraction(
            patient_experience_bps * COMPOSITE_WEIGHT_PATIENT_EXPERIENCE_BPS, BPS_PAR
        )
        + Fraction(access_score_bps * COMPOSITE_WEIGHT_ACCESS_BPS, BPS_PAR)
    )
    return round_half_up_value(accumulated)


def expected_withhold_release_bps(composite_score_bps: int) -> int:
    for threshold, release in WITHHOLD_RELEASE_BANDS:
        if composite_score_bps >= threshold:
            return release
    return WITHHOLD_RELEASE_BELOW_ALL_BANDS_BPS


# ---------------------------------------------------------------------------
# Settlement waterfall (PRD §3.8)
# ---------------------------------------------------------------------------


def expected_settlement_waterfall(
    funded_cents: int,
    paid_claims_cents: int,
    stop_loss_recovery_cents: int,
    ibnr_reserve_cents: int,
) -> Dict[str, Any]:
    """Reproduce the nine-step settlement waterfall in its pinned order."""
    gross_claims = paid_claims_cents
    net_claims = gross_claims - stop_loss_recovery_cents + ibnr_reserve_cents
    raw_surplus = funded_cents - net_claims

    if raw_surplus <= 0 or funded_cents == 0:
        surplus_ratio_bps = 0
    else:
        surplus_ratio_bps = truncate_toward_zero(raw_surplus * BPS_PAR, funded_cents)

    if raw_surplus <= 0:
        tier = "NONE"
    elif surplus_ratio_bps <= SURPLUS_TIER_1_MAX_RATIO_BPS:
        tier = "TIER_1"
    elif surplus_ratio_bps <= SURPLUS_TIER_2_MAX_RATIO_BPS:
        tier = "TIER_2"
    else:
        tier = "TIER_3"

    admin_fee_bps = ADMIN_FEE_BPS_BY_TIER[tier]
    surplus_floored = max(raw_surplus, 0)
    admin_fee = round_half_up(surplus_floored * admin_fee_bps, BPS_PAR)
    distributable = surplus_floored - admin_fee
    shared_savings = round_half_up(
        distributable * SHARED_SAVINGS_SHARE_BPS_BY_TIER[tier], BPS_PAR
    )
    return {
        "gross_claims_cents": gross_claims,
        "stop_loss_recovery_cents": stop_loss_recovery_cents,
        "ibnr_reserve_cents": ibnr_reserve_cents,
        "net_claims_cents": net_claims,
        "raw_surplus_cents": raw_surplus,
        "surplus_ratio_bps": surplus_ratio_bps,
        "surplus_tier": tier,
        "admin_fee_bps": admin_fee_bps,
        "admin_fee_cents": admin_fee,
        "distributable_surplus_cents": distributable,
        "shared_savings_pool_cents": shared_savings,
    }


# ---------------------------------------------------------------------------
# Largest-remainder allocation (PRD §2.6 and §3.8)
# ---------------------------------------------------------------------------


def largest_remainder_allocation(total: int, weights: Sequence[int]) -> List[int]:
    """Split ``total`` across ``weights`` by floor plus one-cent-at-a-time.

    ``weights`` must already be in the contractual participant order —
    ``created_at`` ascending then ``npi`` ascending — because that order is what
    breaks ties on equal fractional parts.
    """
    weight_sum = sum(weights)
    if weight_sum == 0:
        return [0 for _ in weights]

    exact = [Fraction(total * w, weight_sum) for w in weights]
    floors = [int(value // 1) for value in exact]
    leftover = total - sum(floors)

    order = sorted(
        range(len(weights)),
        key=lambda i: (-(exact[i] - floors[i]), i),
    )
    for position in range(leftover):
        floors[order[position]] += 1
    return floors


def assert_allocation_is_exact(total: int, allocated: Sequence[int]):
    assert sum(allocated) == total, (
        f"largest-remainder allocation must sum to exactly {total}, got {sum(allocated)}"
    )


# ---------------------------------------------------------------------------
# Ledger conservation (PRD §2.9)
# ---------------------------------------------------------------------------


def assert_accrual_invariant(agreement: Dict[str, Any], remittances: Sequence[Dict[str, Any]]):
    """``accrued_capitation_cents`` equals the sum over RECONCILED/POSTED rows."""
    expected = sum(
        r["expected_capitation_cents"] + r["retro_adjustment_cents"]
        for r in remittances
        if r["status"] in ("RECONCILED", "POSTED")
    )
    assert agreement["accrued_capitation_cents"] == expected, (
        "accrued_capitation_cents must equal the sum of expected plus retro over "
        f"RECONCILED/POSTED remittances: {agreement['accrued_capitation_cents']} != {expected}"
    )


def assert_active_assignment_counts(
    agreement: Dict[str, Any], assignments: Sequence[Dict[str, Any]]
):
    """``total_assigned_members`` equals the count of ACTIVE assignment rows."""
    expected = sum(1 for a in assignments if a["status"] == "ACTIVE")
    assert agreement["total_assigned_members"] == expected, (
        "total_assigned_members must equal the count of ACTIVE assignments: "
        f"{agreement['total_assigned_members']} != {expected}"
    )


def assert_panel_size(physician: Dict[str, Any], expected: int):
    assert physician["panel_size"] == expected, (
        f"panel_size must equal the count of ACTIVE assignments: "
        f"{physician['panel_size']} != {expected}"
    )


# ---------------------------------------------------------------------------
# Pagination meta (PRD §2.3)
# ---------------------------------------------------------------------------


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
):
    assert_fields(
        meta,
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
    )


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]):
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"
