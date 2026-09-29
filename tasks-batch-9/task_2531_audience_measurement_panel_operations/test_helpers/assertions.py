"""Domain assertions and pure reference calculators.

Two kinds of helper live here. The ``assert_*`` functions check shape rules the
PRD states once and applies everywhere -- the common-property quartet of PRD 2.5
and the three conserved quantities of PRD 2.9. The ``expected_*`` functions are
pure re-implementations of PRD formulas, written to follow the PRD's pinned
evaluation and rounding order exactly ("applied at each named step rather than
only at the end"), so a test can assert a computed field against an
independently derived figure instead of a hand-copied literal.
"""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from test_helpers.constants import (
    CELL_SURCHARGE_CENTS,
    COMPLIANCE_BONUS_PCT,
    COMPLIANCE_BONUS_THRESHOLD,
    FAULT_PENALTY_PCT,
    HOLD_CREDIT_PCT,
    IMPACT_ASCRIPTION_DIVISOR,
    IMPACT_CAP_DIVISOR,
    IMPACT_SUBSCORE_CAP,
    IMPACT_TUNING_DIVISOR,
    IMPACT_WEIGHT_ASCRIPTION,
    IMPACT_WEIGHT_CAP,
    IMPACT_WEIGHT_TUNING,
    INCENTIVE_BOOST_PCT,
    INCENTIVE_PERIOD_CAP_CENTS,
    METHODOLOGY_CREDIT_FACTOR,
    MINUTES_PER_DAY,
    NOTIFICATION_LEAD_HOURS,
    OOH_SUPPLEMENT_PCT,
    ON_TARGET_THRESHOLD,
    PENALTY_RATE_150000_PLUS,
    PENALTY_RATE_80000_TO_149999,
    PENALTY_RATE_UNDER_80000,
    SECONDS_PER_DAY,
    SECONDS_PER_TENURE_MONTH,
    TENURE_BAND_6M,
    TENURE_BAND_24M,
    TENURE_MULTIPLIER_24M_PLUS,
    TENURE_MULTIPLIER_6M_TO_23M,
    TENURE_MULTIPLIER_UNDER_6M,
    TIER_MATERIAL_THRESHOLD,
    TIER_MODERATE_THRESHOLD,
    VOLUME_BRACKET_LOW_CEILING,
    VOLUME_BRACKET_MID_CEILING,
    VOLUME_DISCOUNT_RATE_150000_PLUS,
    VOLUME_DISCOUNT_RATE_80000_TO_149999,
    VOLUME_DISCOUNT_RATE_UNDER_80000,
)

# ----------------------------------------------------------------------
# Rounding (PRD 2.8)
# ----------------------------------------------------------------------

def round_half_up(value: Any, places: int) -> float:
    """Round half up to `places` decimals, the only rounding mode the PRD uses."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_half_up_to_int(value: Any) -> int:
    """Round half up to a whole unit -- a whole cent, minute or household."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------
# Common record properties (PRD 2.5)
# ----------------------------------------------------------------------

def assert_common_properties(record: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """`id` a UUID, both timestamps ISO 8601, `version` an int starting at 1."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int), record["version"]
    assert record["version"] >= 1
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_freshly_created(record: Dict[str, Any]) -> None:
    """A row written for the first time: `version` 1 and the two stamps equal."""
    assert_common_properties(record, expected_version=1)
    assert record["created_at"] == record["updated_at"]


def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    """A mutation, including one performed by a cascade, moves `version` by `by`."""
    assert after["id"] == before["id"]
    assert after["version"] == before["version"] + by, (
        f"version moved {before['version']} -> {after['version']}, expected +{by}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A rejected write leaves the row's `version` and `updated_at` alone."""
    assert after["id"] == before["id"]
    assert after["version"] == before["version"], (
        f"version moved {before['version']} -> {after['version']} on a rejected write"
    )
    assert after["updated_at"] == before["updated_at"]


# ----------------------------------------------------------------------
# Conserved quantities (PRD 2.9)
# ----------------------------------------------------------------------

def assert_intab_count_matches_active(cell: Dict[str, Any], households: Iterable[Dict[str, Any]]) -> None:
    """"A quota cell's `intab_count` is ... precisely the number of households of
    that cell whose `status` is `ACTIVE`.\""""
    active = [h for h in households if h["quota_cell_id"] == cell["id"] and h["status"] == "ACTIVE"]
    assert cell["intab_count"] == len(active), (
        f"intab_count {cell['intab_count']} but {len(active)} ACTIVE households"
    )


def assert_committed_matches_household_ledger(
    market: Dict[str, Any], households: Iterable[Dict[str, Any]]
) -> None:
    """Committed cents equal the sum of `incentive_accrued_cents` over every
    household of the market, "whatever their status\"."""
    total = sum(h["incentive_accrued_cents"] for h in households if h["market_id"] == market["id"])
    assert market["incentive_budget_committed_cents"] == total, (
        f"committed {market['incentive_budget_committed_cents']} but ledger sums to {total}"
    )


def assert_reserved_matches_armed_cells(
    market: Dict[str, Any], cells: Iterable[Dict[str, Any]]
) -> None:
    """Reserved cents equal the sum of the boost reservation over armed cells."""
    total = sum(
        expected_boost_reservation(c["base_incentive_cents"], c["target_households"])
        for c in cells
        if c["market_id"] == market["id"] and c["incentive_boost_active"]
    )
    assert market["incentive_budget_reserved_cents"] == total, (
        f"reserved {market['incentive_budget_reserved_cents']} but armed cells sum to {total}"
    )


# ----------------------------------------------------------------------
# Quota cell fill and market posture (PRD 3.1)
# ----------------------------------------------------------------------

def expected_fill_rate(intab_count: int, target_households: int) -> float:
    """"the in-tab count divided by `target_households`, rounded half up to 4
    decimal places.\""""
    return round_half_up(Decimal(intab_count) / Decimal(target_households), 4)


def expected_quota_status(fill_rate: float) -> str:
    """`FILLED` at 1.0000 or more, `ON_TARGET` at 0.8000 or more, else `UNDER_TARGET`."""
    if fill_rate >= 1.0000:
        return "FILLED"
    if fill_rate >= ON_TARGET_THRESHOLD:
        return "ON_TARGET"
    return "UNDER_TARGET"


def expected_boost_reservation(base_incentive_cents: int, target_households: int) -> int:
    """"`base_incentive_cents` multiplied by one quarter and by `target_households`,
    rounded half up to a whole cent.\""""
    return round_half_up_to_int(
        Decimal(base_incentive_cents) * Decimal(str(INCENTIVE_BOOST_PCT)) * Decimal(target_households)
    )


def expected_recruitment_posture(
    open_audit_count: int,
    quota_cell_count: int,
    filled_cell_count: int,
    under_target_cell_count: int,
) -> str:
    """The four clauses of PRD 3.1, walked in order, first match winning."""
    if open_audit_count >= 1:
        return "FROZEN"
    if quota_cell_count >= 1 and filled_cell_count == quota_cell_count:
        return "CLOSED"
    if under_target_cell_count == 0:
        return "RESTRICTED"
    return "OPEN"


# ----------------------------------------------------------------------
# Enumeration verdict (PRD 3.2)
# ----------------------------------------------------------------------

def expected_enumeration_verdict(
    roster_persons_count: int,
    tv_sets_count: int,
    persons_count: int,
    age_days: Optional[int],
    is_first_submission: bool,
) -> str:
    """`COMPLIANT` when all three tests pass, `NONCOMPLIANT` when any of them fails."""
    roster_ok = roster_persons_count == persons_count
    sets_ok = tv_sets_count >= 1
    timeliness_ok = True if not is_first_submission else (age_days is not None and age_days <= 14)
    return "COMPLIANT" if (roster_ok and sets_ok and timeliness_ok) else "NONCOMPLIANT"


def whole_days_between(earlier_epoch_seconds: int, later_epoch_seconds: int) -> int:
    """Elapsed seconds divided by 86400 and floored -- the PRD's age in whole days."""
    return (later_epoch_seconds - earlier_epoch_seconds) // SECONDS_PER_DAY


# ----------------------------------------------------------------------
# Meter coverage scan (PRD 3.3)
# ----------------------------------------------------------------------

def expected_suspect_floor(fault_missing_minutes_threshold: int) -> int:
    """"the rule set's `fault_missing_minutes_threshold` divided by two and rounded
    half up to a whole number.\""""
    return round_half_up_to_int(Decimal(fault_missing_minutes_threshold) / Decimal(2))


def expected_scan_health(missing_minutes: int, threshold: int, current_health: str) -> str:
    """Both comparisons inclusive at the bottom; the scan only ever escalates."""
    floor_minutes = expected_suspect_floor(threshold)
    if missing_minutes >= threshold:
        return "FAULTED"
    if current_health == "FAULTED":
        return "FAULTED"
    if missing_minutes >= floor_minutes:
        return "SUSPECT"
    return current_health


# ----------------------------------------------------------------------
# The editing pass (PRD 3.6)
# ----------------------------------------------------------------------

def expected_usable_minutes(tuning_minutes: int, source_methodology: str) -> int:
    """"`tuning_minutes` multiplied by the credit factor of its `source_methodology`
    and rounded half up to a whole minute.\""""
    factor = METHODOLOGY_CREDIT_FACTOR[source_methodology]
    return round_half_up_to_int(Decimal(tuning_minutes) * Decimal(str(factor)))


# ----------------------------------------------------------------------
# Compliance rates (PRD 3.6, 3.7)
# ----------------------------------------------------------------------

def expected_compliance_rate(compliant_days: int, evaluated_days: int) -> float:
    """"the compliant days divided by the evaluated days, rounded half up to 4
    decimal places, and is 0.0000 when there are no evaluated days at all.\""""
    if evaluated_days == 0:
        return 0.0
    return round_half_up(Decimal(compliant_days) / Decimal(evaluated_days), 4)


def expected_run_evaluated_days(window_minutes: int) -> int:
    """"the run's `window_minutes` divided by 1440 and rounded up.\""""
    return math.ceil(window_minutes / MINUTES_PER_DAY)


# ----------------------------------------------------------------------
# Weighting, capping and projection (PRD 3.7)
# ----------------------------------------------------------------------

def expected_base_weight(population_households: int, denominator: int) -> float:
    """Cell population over the variant denominator, rounded half up to 4 places."""
    return round_half_up(Decimal(population_households) / Decimal(denominator), 4)


def expected_cap(base_weights: Sequence[float], outlier_weight_ratio_cap: float) -> Tuple[float, float]:
    """Return (mean_base, cap), both rounded half up to 4 decimal places."""
    mass = sum(Decimal(str(w)) for w in base_weights)
    mean_base = round_half_up(mass / Decimal(len(base_weights)), 4)
    cap = round_half_up(Decimal(str(mean_base)) * Decimal(str(outlier_weight_ratio_cap)), 4)
    return mean_base, cap


def expected_adjusted_weights(
    base_weights: Sequence[float], outlier_weight_ratio_cap: float
) -> Tuple[List[float], float, List[bool]]:
    """The single-pass cap-and-redistribute of PRD 3.7.

    `base_weights` must already be in `created_at` ascending order, which is the
    order every tie-break in the pass depends on. Returns the adjusted weights,
    the conserved `total_weight_mass`, and the per-row `capped` flags.
    """
    mass = sum(Decimal(str(w)) for w in base_weights)
    _, cap = expected_cap(base_weights, outlier_weight_ratio_cap)
    cap_dec = Decimal(str(cap))
    capped_flags = [Decimal(str(w)) > cap_dec for w in base_weights]
    if not any(capped_flags):
        return [round_half_up(w, 4) for w in base_weights], round_half_up(mass, 4), capped_flags

    excess = sum(Decimal(str(w)) - cap_dec for w, f in zip(base_weights, capped_flags) if f)
    receiver_mass = sum(Decimal(str(w)) for w, f in zip(base_weights, capped_flags) if not f)
    adjusted: List[Decimal] = []
    for weight, is_capped in zip(base_weights, capped_flags):
        if is_capped:
            adjusted.append(cap_dec)
        else:
            share = Decimal(
                str(round_half_up(excess * Decimal(str(weight)) / receiver_mass, 4))
            )
            adjusted.append(Decimal(str(weight)) + share)
    drift = mass - sum(adjusted)
    first_receiver = next(i for i, f in enumerate(capped_flags) if not f)
    adjusted[first_receiver] = adjusted[first_receiver] + drift
    return [round_half_up(a, 4) for a in adjusted], round_half_up(sum(adjusted), 4), capped_flags


def expected_contribution(adjusted_weight: float, usable_minutes: int, window_minutes: int) -> float:
    """"its `adjusted_weight` multiplied by its summed usable minutes and divided by
    the run's `window_minutes`, rounded half up to 2 decimal places.\""""
    return round_half_up(
        Decimal(str(adjusted_weight)) * Decimal(usable_minutes) / Decimal(window_minutes), 2
    )


def expected_projected_average_audience(contributions: Sequence[float]) -> int:
    """The sum of the already-rounded contributions, then rounded to a whole count."""
    raw_total = sum(Decimal(str(c)) for c in contributions)
    return round_half_up_to_int(raw_total)


# ----------------------------------------------------------------------
# Cooperation incentive accrual (PRD 3.4)
# ----------------------------------------------------------------------

def expected_tenure_months(recruited_at_epoch: int, now_epoch: int) -> int:
    """"divided by 2592000 seconds and floored -- thirty-day months.\""""
    return (now_epoch - recruited_at_epoch) // SECONDS_PER_TENURE_MONTH


def expected_tenure_multiplier(tenure_months: int) -> float:
    """1.000 under 6 months, 1.075 from 6 to under 24, 1.150 from 24 up."""
    if tenure_months >= TENURE_BAND_24M:
        return TENURE_MULTIPLIER_24M_PLUS
    if tenure_months >= TENURE_BAND_6M:
        return TENURE_MULTIPLIER_6M_TO_23M
    return TENURE_MULTIPLIER_UNDER_6M


def expected_accrual_breakdown(
    base_incentive_cents: int,
    effective_incentive_multiplier: float,
    tenure_months: int,
    compliance_rate_rolling_30: float,
    has_installed_portable_ooh: bool,
    has_faulted_meter: bool,
) -> Dict[str, int]:
    """The nine numbered steps of PRD 3.4, each rounding to whole cents in turn.

    Returned keys mirror the PRD's own step names so a failing test can point at
    the step that diverged rather than only at the final figure.
    """
    tenure_multiplier = expected_tenure_multiplier(tenure_months)
    cell_base = round_half_up_to_int(
        Decimal(base_incentive_cents) * Decimal(str(effective_incentive_multiplier))
    )
    tenure_amount = round_half_up_to_int(Decimal(cell_base) * Decimal(str(tenure_multiplier)))
    compliance_bonus = (
        round_half_up_to_int(Decimal(tenure_amount) * Decimal(str(COMPLIANCE_BONUS_PCT)))
        if compliance_rate_rolling_30 >= COMPLIANCE_BONUS_THRESHOLD
        else 0
    )
    ooh_supplement = (
        round_half_up_to_int(Decimal(tenure_amount) * Decimal(str(OOH_SUPPLEMENT_PCT)))
        if has_installed_portable_ooh
        else 0
    )
    gross = tenure_amount + compliance_bonus + ooh_supplement
    fault_penalty = (
        round_half_up_to_int(Decimal(gross) * Decimal(str(FAULT_PENALTY_PCT)))
        if has_faulted_meter
        else 0
    )
    period_amount = min(gross - fault_penalty, INCENTIVE_PERIOD_CAP_CENTS)
    return {
        "tenure_months": tenure_months,
        "tenure_multiplier": tenure_multiplier,
        "cell_base": cell_base,
        "tenure_amount": tenure_amount,
        "compliance_bonus": compliance_bonus,
        "ooh_supplement": ooh_supplement,
        "gross": gross,
        "fault_penalty": fault_penalty,
        "period_amount": period_amount,
    }


def expected_accrued_cents(*args: Any, **kwargs: Any) -> int:
    """The step 9 figure alone, for tests that only care about the total."""
    return expected_accrual_breakdown(*args, **kwargs)["period_amount"]


# ----------------------------------------------------------------------
# Deliverable billing (PRD 3.8)
# ----------------------------------------------------------------------

def expected_volume_discount_rate(gross_cents: int) -> float:
    """Keyed on the gross figure: 0.00 / 0.10 / 0.15 across 80000 and 150000."""
    if gross_cents >= VOLUME_BRACKET_MID_CEILING:
        return VOLUME_DISCOUNT_RATE_150000_PLUS
    if gross_cents >= VOLUME_BRACKET_LOW_CEILING:
        return VOLUME_DISCOUNT_RATE_80000_TO_149999
    return VOLUME_DISCOUNT_RATE_UNDER_80000


def expected_penalty_rate(gross_cents: int) -> float:
    """Also keyed on the gross figure and never on the discounted net."""
    if gross_cents >= VOLUME_BRACKET_MID_CEILING:
        return PENALTY_RATE_150000_PLUS
    if gross_cents >= VOLUME_BRACKET_LOW_CEILING:
        return PENALTY_RATE_80000_TO_149999
    return PENALTY_RATE_UNDER_80000


def expected_days_late(due_at_epoch: int, now_epoch: int) -> int:
    """"rounded **up** to a whole day and floored at 0.\""""
    if now_epoch <= due_at_epoch:
        return 0
    return math.ceil((now_epoch - due_at_epoch) / SECONDS_PER_DAY)


def expected_billing(
    tier_base_fee_cents: int,
    requested_cell_count: int,
    days_late: int = 0,
) -> Dict[str, Any]:
    """The seven steps of PRD 3.8, both brackets keyed on `gross_cents`."""
    gross_cents = tier_base_fee_cents + requested_cell_count * CELL_SURCHARGE_CENTS
    discount_rate = expected_volume_discount_rate(gross_cents)
    discount_cents = round_half_up_to_int(Decimal(gross_cents) * Decimal(str(discount_rate)))
    penalty_rate = expected_penalty_rate(gross_cents)
    late_penalty_cents = round_half_up_to_int(
        Decimal(gross_cents) * Decimal(str(penalty_rate)) * Decimal(days_late)
    )
    total_cents = max(gross_cents - discount_cents - late_penalty_cents, 0)
    return {
        "gross_cents": gross_cents,
        "volume_discount_rate": discount_rate,
        "discount_cents": discount_cents,
        "days_late": days_late,
        "penalty_rate": penalty_rate,
        "late_penalty_cents": late_penalty_cents,
        "total_cents": total_cents,
    }


def assert_billing_matches(row: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Compare the four persisted money fields against a reference breakdown."""
    for field in ("gross_cents", "discount_cents", "late_penalty_cents", "total_cents"):
        assert row[field] == expected[field], (
            f"{field}: got {row[field]}, expected {expected[field]} (breakdown {expected})"
        )


def expected_hold_credit_cents(tier_base_fee_cents: int) -> int:
    """"5 percent of that client's `tier_base_fee_cents`, rounded half up to a
    whole cent.\""""
    return round_half_up_to_int(Decimal(tier_base_fee_cents) * Decimal(str(HOLD_CREDIT_PCT)))


# ----------------------------------------------------------------------
# Methodology impact score (PRD 3.9)
# ----------------------------------------------------------------------

def expected_impact_subscores(
    target: Dict[str, Any], proposed: Dict[str, Any]
) -> Dict[str, float]:
    """Three absolute differences over their divisors, each capped at 1.0."""
    cap_sub = min(
        abs(Decimal(str(proposed["outlier_weight_ratio_cap"])) - Decimal(str(target["outlier_weight_ratio_cap"])))
        / Decimal(str(IMPACT_CAP_DIVISOR)),
        Decimal(str(IMPACT_SUBSCORE_CAP)),
    )
    tuning_sub = min(
        abs(Decimal(proposed["invalid_tuning_max_minutes"]) - Decimal(target["invalid_tuning_max_minutes"]))
        / Decimal(IMPACT_TUNING_DIVISOR),
        Decimal(str(IMPACT_SUBSCORE_CAP)),
    )
    ascription_sub = min(
        abs(
            Decimal(proposed["missing_interval_ascription_minutes"])
            - Decimal(target["missing_interval_ascription_minutes"])
        )
        / Decimal(IMPACT_ASCRIPTION_DIVISOR),
        Decimal(str(IMPACT_SUBSCORE_CAP)),
    )
    return {"cap": cap_sub, "tuning": tuning_sub, "ascription": ascription_sub}


def expected_impact_delta_pct(target: Dict[str, Any], proposed: Dict[str, Any]) -> float:
    """0.40 cap + 0.35 tuning + 0.25 ascription, rounded half up to 4 places."""
    subs = expected_impact_subscores(target, proposed)
    raw = (
        Decimal(str(IMPACT_WEIGHT_CAP)) * subs["cap"]
        + Decimal(str(IMPACT_WEIGHT_TUNING)) * subs["tuning"]
        + Decimal(str(IMPACT_WEIGHT_ASCRIPTION)) * subs["ascription"]
    )
    return round_half_up(raw, 4)


def expected_impact_tier(impact_delta_pct: float) -> str:
    """`MATERIAL` at 0.1500 up, `MODERATE` at 0.0500 up, `MINOR` below."""
    if impact_delta_pct >= TIER_MATERIAL_THRESHOLD:
        return "MATERIAL"
    if impact_delta_pct >= TIER_MODERATE_THRESHOLD:
        return "MODERATE"
    return "MINOR"


def expected_notification_lead_hours(impact_tier: str) -> int:
    """72 hours for `MINOR`, 336 for `MODERATE`, 720 for `MATERIAL`."""
    return NOTIFICATION_LEAD_HOURS[impact_tier]


# ----------------------------------------------------------------------
# Ordering helpers
# ----------------------------------------------------------------------

def assert_ordered_by(
    rows: Sequence[Dict[str, Any]], keys: Sequence[Tuple[str, str]]
) -> None:
    """Assert `rows` are non-decreasing under a list of (field, "asc"|"desc")."""
    def sort_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
        return tuple(row[field] for field, _ in keys)

    for earlier, later in zip(rows, rows[1:]):
        for field, direction in keys:
            left, right = earlier[field], later[field]
            if left == right:
                continue
            if direction == "asc":
                assert left < right, f"{field} not ascending: {left!r} then {right!r}"
            else:
                assert left > right, f"{field} not descending: {left!r} then {right!r}"
            break


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """The `id` column of a collection page, for order-sensitive comparisons."""
    return [row["id"] for row in rows]
