"""Domain assertion helpers for the medical office building leasing API."""
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AGING_TIER_EARLY_MAX_DAYS,
    AGING_TIER_MIDDLE_MAX_DAYS,
    AGING_TIER_WEIGHT_EARLY,
    AGING_TIER_WEIGHT_LATE,
    AGING_TIER_WEIGHT_MIDDLE,
    APPRAISAL_CEILING_FACTOR,
    APPRAISAL_FLOOR_FACTOR,
    HOLDOVER_MULTIPLIER,
    PUBLISHED_CEILING_FACTOR,
    PUBLISHED_FLOOR_FACTOR,
    STAFF_STALL_MONTHLY_RATE,
    SUITE_CLASS_PREMIUM_PSF,
    WAIVER_TIER_LOW_MAX,
    WAIVER_TIER_MID_MAX,
    WAIVER_TIER_PCT_HIGH,
    WAIVER_TIER_PCT_LOW,
    WAIVER_TIER_PCT_MID,
)


# --- Rounding primitives --------------------------------------------------
def round_money(value) -> float:
    """PRD: monetary amounts are rounded half up to 2 decimal places."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_share(value) -> float:
    """PRD: share and percentage fields are rounded half up to 4 decimal places."""
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def assert_money_equals(actual, expected, label: str = "amount") -> None:
    """Compare a monetary field against an exact 2-decimal expectation."""
    assert actual is not None, "expected {} to be present, got None".format(label)
    assert round_money(actual) == round_money(expected), (
        "{}: expected {}, got {}".format(label, round_money(expected), actual)
    )


def assert_share_equals(actual, expected, label: str = "share") -> None:
    """Compare a 4-decimal share/percentage field against an exact expectation."""
    assert actual is not None, "expected {} to be present, got None".format(label)
    assert round_share(actual) == round_share(expected), (
        "{}: expected {}, got {}".format(label, round_share(expected), actual)
    )


def assert_money_2dp(value, label: str = "amount") -> None:
    """A monetary field carries no more than 2 decimal places and is non-negative."""
    assert value is not None, "expected {} to be present".format(label)
    quantised = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == quantised, (
        "{}: {} is not a 2-decimal money value".format(label, value)
    )
    assert float(value) >= 0.0, "{}: {} is negative".format(label, value)


def assert_share_4dp_in_unit_range(value, label: str = "share") -> None:
    """A share field carries 4 decimals and lies within 0.0000 .. 1.0000."""
    assert value is not None, "expected {} to be present".format(label)
    quantised = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == quantised, (
        "{}: {} is not a 4-decimal share".format(label, value)
    )
    assert 0.0 <= float(value) <= 1.0, "{}: {} outside 0.0000..1.0000".format(label, value)


# --- Common field envelope -------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity but TILineItem carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), "id is not a UUID: {}".format(entity["id"])
    assert is_iso8601_timestamp(entity["created_at"]), (
        "created_at is not ISO 8601: {}".format(entity["created_at"])
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        "updated_at is not ISO 8601: {}".format(entity["updated_at"])
    )
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        "version must be a positive integer, got {}".format(entity["version"])
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            "expected version {}, got {}".format(expected_version, entity["version"])
        )


def assert_line_item_has_no_version_fields(line_item: Dict[str, Any]) -> None:
    """TILineItem has no updated_at field and no version field at all."""
    assert is_valid_uuid(line_item["id"]), "id is not a UUID: {}".format(line_item["id"])
    assert is_iso8601_timestamp(line_item["created_at"]), (
        "created_at is not ISO 8601: {}".format(line_item["created_at"])
    )
    assert "updated_at" not in line_item, "TILineItem must not carry updated_at"
    assert "version" not in line_item, "TILineItem must not carry version"


def assert_version_advanced_by(before: Dict[str, Any], after: Dict[str, Any],
                               steps: int = 1) -> None:
    """A mutation advances version by the stated number of steps."""
    assert after["version"] == before["version"] + steps, (
        "expected version {} -> {}, got {}".format(
            before["version"], before["version"] + steps, after["version"])
    )


def assert_date(value, label: str = "date") -> None:
    """A calendar date field is rendered as YYYY-MM-DD."""
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        "{}: {} is not a YYYY-MM-DD date".format(label, value)
    )


# --- Fair-market-value band -----------------------------------------------
def published_psf(market_base_rent_psf_annual: float, suite_class: str) -> float:
    """The published figure: the building rate card plus the suite class premium."""
    return round_money(Decimal(str(market_base_rent_psf_annual))
                       + Decimal(str(SUITE_CLASS_PREMIUM_PSF[suite_class])))


def published_band(market_base_rent_psf_annual: float, suite_class: str):
    """The published floor is 80% of the published figure and the ceiling 115%."""
    figure = Decimal(str(published_psf(market_base_rent_psf_annual, suite_class)))
    return (round_money(figure * Decimal(str(PUBLISHED_FLOOR_FACTOR))),
            round_money(figure * Decimal(str(PUBLISHED_CEILING_FACTOR))))


def appraisal_band(opinion_midpoint_psf: float):
    """The appraisal band is 90% and 110% of the controlling midpoint."""
    midpoint = Decimal(str(opinion_midpoint_psf))
    return (round_money(midpoint * Decimal(str(APPRAISAL_FLOOR_FACTOR))),
            round_money(midpoint * Decimal(str(APPRAISAL_CEILING_FACTOR))))


def certified_band(market_base_rent_psf_annual: float, suite_class: str,
                   opinion_midpoint_psf: Optional[float] = None):
    """The nested clamp: greater of the two floors, lesser of the two ceilings."""
    p_floor, p_ceiling = published_band(market_base_rent_psf_annual, suite_class)
    if opinion_midpoint_psf is None:
        return (p_floor, p_ceiling)
    a_floor, a_ceiling = appraisal_band(opinion_midpoint_psf)
    return (max(a_floor, p_floor), min(a_ceiling, p_ceiling))


def assert_certified_band(lease: Dict[str, Any], expected_floor: float,
                          expected_ceiling: float) -> None:
    """The certified band is recorded on the lease at 2 decimal places."""
    assert_money_equals(lease["certified_fmv_floor_psf"], expected_floor,
                        "certified_fmv_floor_psf")
    assert_money_equals(lease["certified_fmv_ceiling_psf"], expected_ceiling,
                        "certified_fmv_ceiling_psf")


def assert_provisional_rent_variant(lease: Dict[str, Any], expected_provisional: float) -> None:
    """Before certification the lease is carried at the rate card with a null variance."""
    assert_money_equals(lease["provisional_base_rent_annual"], expected_provisional,
                        "provisional_base_rent_annual")
    assert_money_equals(lease["effective_base_rent_annual"], expected_provisional,
                        "effective_base_rent_annual")
    assert lease["certified_base_rent_annual"] is None, "certified_base_rent_annual must be null"
    assert lease["fmv_variance_annual"] is None, "fmv_variance_annual must be null"
    assert lease["fmv_variance_pct"] is None, "fmv_variance_pct must be null"


def assert_certified_rent_variant(lease: Dict[str, Any], expected_certified: float,
                                  expected_provisional: float,
                                  holdover: bool = False) -> None:
    """After certification the lease is carried at the negotiated rate with a signed variance."""
    assert_money_equals(lease["certified_base_rent_annual"], expected_certified,
                        "certified_base_rent_annual")
    expected_effective = (round_money(Decimal(str(expected_certified))
                                      * Decimal(str(HOLDOVER_MULTIPLIER)))
                          if holdover else expected_certified)
    assert_money_equals(lease["effective_base_rent_annual"], expected_effective,
                        "effective_base_rent_annual")
    delta = round_money(expected_certified - expected_provisional)
    assert_money_equals(lease["fmv_variance_annual"], delta, "fmv_variance_annual")
    assert_share_equals(lease["fmv_variance_pct"],
                        round_share(Decimal(str(delta)) / Decimal(str(expected_provisional))),
                        "fmv_variance_pct")


# --- Tenant improvement cost split ----------------------------------------
def expected_effective_share(target_suite_class: str, category: str,
                             override: Optional[float],
                             project_default: float) -> float:
    """Category rule, then line override, then the project default."""
    if category == "SHIELDING" and target_suite_class == "IMAGING":
        return 1.0000
    if override is not None:
        return round_share(override)
    return round_share(project_default)


def expected_line_split(cost_amount: float, effective_share_pct: float):
    """The landlord amount is rounded; the tenant amount is the remainder."""
    landlord = round_money(Decimal(str(cost_amount)) * Decimal(str(effective_share_pct)))
    return (landlord, round_money(Decimal(str(cost_amount)) - Decimal(str(landlord))))


def assert_line_split(line_item: Dict[str, Any], expected_share: float,
                      expected_landlord: float, expected_tenant: float) -> None:
    """Line-level cost shares are rounded per line item, before any summation."""
    assert_share_equals(line_item["effective_share_pct"], expected_share,
                        "effective_share_pct")
    assert_money_equals(line_item["landlord_share_amount"], expected_landlord,
                        "landlord_share_amount")
    assert_money_equals(line_item["tenant_share_amount"], expected_tenant,
                        "tenant_share_amount")
    assert round_money(Decimal(str(expected_landlord)) + Decimal(str(expected_tenant))) == \
        round_money(line_item["cost_amount"]), "line shares must add back to cost_amount"


def assert_project_rollups(project: Dict[str, Any], expected_landlord_total: float,
                           expected_tenant_total: float,
                           expected_allowance_remaining: float,
                           expected_line_count: Optional[int] = None) -> None:
    """Project totals are sums of the already-rounded per-line figures."""
    assert_money_equals(project["landlord_committed_amount"], expected_landlord_total,
                        "landlord_committed_amount")
    assert_money_equals(project["tenant_committed_amount"], expected_tenant_total,
                        "tenant_committed_amount")
    assert_money_equals(project["allowance_remaining"], expected_allowance_remaining,
                        "allowance_remaining")
    if expected_line_count is not None:
        assert project["line_item_count"] == expected_line_count, (
            "expected line_item_count {}, got {}".format(
                expected_line_count, project["line_item_count"])
        )


# --- Monthly occupancy invoice --------------------------------------------
def expected_waiver_tier_pct(pre_waiver_total: float) -> float:
    """The tier is keyed on the combined figure with inclusive upper bounds."""
    if round_money(pre_waiver_total) <= WAIVER_TIER_LOW_MAX:
        return WAIVER_TIER_PCT_LOW
    if round_money(pre_waiver_total) <= WAIVER_TIER_MID_MAX:
        return WAIVER_TIER_PCT_MID
    return WAIVER_TIER_PCT_HIGH


def expected_invoice_total(effective_base_rent_annual: float,
                          operating_expense_annual_psf: float,
                          rentable_sf: int,
                          staff_stalls: int = 0,
                          patient_stalls: int = 0):
    """The six numbered steps of the invoice build, in their pinned order."""
    base_rent = round_money(Decimal(str(effective_base_rent_annual)) / Decimal(12))
    cam = round_money(
        Decimal(str(operating_expense_annual_psf)) * Decimal(str(rentable_sf)) / Decimal(12))
    parking_gross = round_money(
        Decimal(str(staff_stalls)) * Decimal(str(STAFF_STALL_MONTHLY_RATE)))
    pre_waiver = round_money(
        Decimal(str(base_rent)) + Decimal(str(cam)) + Decimal(str(parking_gross)))
    tier_pct = expected_waiver_tier_pct(pre_waiver)
    waiver = round_money(Decimal(str(parking_gross)) * Decimal(str(tier_pct)))
    total = round_money(Decimal(str(pre_waiver)) - Decimal(str(waiver)))
    return {
        "base_rent_amount": base_rent,
        "cam_amount": cam,
        "parking_fee_gross": parking_gross,
        "pre_waiver_total": pre_waiver,
        "parking_waiver_tier_pct": tier_pct,
        "parking_waiver_amount": waiver,
        "total_amount": total,
    }


def assert_invoice_breakdown(invoice: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Every one of the six numbered invoice components is checked."""
    assert_money_equals(invoice["base_rent_amount"], expected["base_rent_amount"],
                        "base_rent_amount")
    assert_money_equals(invoice["cam_amount"], expected["cam_amount"], "cam_amount")
    assert_money_equals(invoice["parking_fee_gross"], expected["parking_fee_gross"],
                        "parking_fee_gross")
    assert_money_equals(invoice["pre_waiver_total"], expected["pre_waiver_total"],
                        "pre_waiver_total")
    assert_share_equals(invoice["parking_waiver_tier_pct"],
                        expected["parking_waiver_tier_pct"], "parking_waiver_tier_pct")
    assert_money_equals(invoice["parking_waiver_amount"], expected["parking_waiver_amount"],
                        "parking_waiver_amount")
    assert_money_equals(invoice["total_amount"], expected["total_amount"], "total_amount")


def expected_aging_weight(day_count: int) -> int:
    """The weight tiers are keyed on the day count itself, not on days past grace."""
    if day_count <= AGING_TIER_EARLY_MAX_DAYS:
        return AGING_TIER_WEIGHT_EARLY
    if day_count <= AGING_TIER_MIDDLE_MAX_DAYS:
        return AGING_TIER_WEIGHT_MIDDLE
    return AGING_TIER_WEIGHT_LATE


def assert_delinquency_freeze(invoice: Dict[str, Any], expected_day_count: int) -> None:
    """The day count is frozen into days_past_due_at_flag with its tier weight."""
    assert invoice["status"] == "DELINQUENT", (
        "expected DELINQUENT, got {}".format(invoice["status"])
    )
    assert invoice["days_past_due_at_flag"] == expected_day_count, (
        "expected days_past_due_at_flag {}, got {}".format(
            expected_day_count, invoice["days_past_due_at_flag"])
    )
    assert invoice["delinquency_tier_weight"] == expected_aging_weight(expected_day_count), (
        "expected delinquency_tier_weight {}, got {}".format(
            expected_aging_weight(expected_day_count), invoice["delinquency_tier_weight"])
    )


# --- Tenant mix and posture -----------------------------------------------
def expected_posture(anchor_share_pct: float, leased_sf: int,
                     frozen: bool = False) -> str:
    """FROZEN overrides; above 0.7500 RESTRICTED; above 0.6000 ANCHOR_CONCENTRATED."""
    if frozen:
        return "FROZEN"
    if leased_sf == 0:
        return "BALANCED"
    if round_share(anchor_share_pct) > 0.7500:
        return "RESTRICTED"
    if round_share(anchor_share_pct) > 0.6000:
        return "ANCHOR_CONCENTRATED"
    return "BALANCED"


def assert_mix_figures(building: Dict[str, Any], anchor_sf: int, independent_sf: int,
                       leased_sf: int, vacant_sf: int, anchor_share_pct: float,
                       posture: str) -> None:
    """The six tenant-mix figures are recomputed together on every transition."""
    assert building["anchor_rentable_sf"] == anchor_sf, (
        "expected anchor_rentable_sf {}, got {}".format(anchor_sf,
                                                        building["anchor_rentable_sf"]))
    assert building["independent_rentable_sf"] == independent_sf, (
        "expected independent_rentable_sf {}, got {}".format(
            independent_sf, building["independent_rentable_sf"]))
    assert building["leased_rentable_sf"] == leased_sf, (
        "expected leased_rentable_sf {}, got {}".format(leased_sf,
                                                        building["leased_rentable_sf"]))
    assert building["vacant_rentable_sf"] == vacant_sf, (
        "expected vacant_rentable_sf {}, got {}".format(vacant_sf,
                                                        building["vacant_rentable_sf"]))
    assert_share_equals(building["anchor_share_pct"], anchor_share_pct, "anchor_share_pct")
    assert building["tenant_mix_posture"] == posture, (
        "expected tenant_mix_posture {}, got {}".format(posture,
                                                        building["tenant_mix_posture"]))


# --- Parking pool ---------------------------------------------------------
def expected_patient_reserve_minimum(total_parking_stalls: int,
                                     patient_min_reserve_pct: float) -> int:
    """The reserve minimum is raised to the next whole stall by ceiling."""
    return int(math.ceil(total_parking_stalls * float(patient_min_reserve_pct)))


def assert_parking_counters(building: Dict[str, Any], staff: int, patient: int,
                            unallocated: int) -> None:
    """The three counters sum to total_parking_stalls after every pool movement."""
    assert building["staff_allocated_stalls"] == staff, (
        "expected staff_allocated_stalls {}, got {}".format(
            staff, building["staff_allocated_stalls"]))
    assert building["patient_allocated_stalls"] == patient, (
        "expected patient_allocated_stalls {}, got {}".format(
            patient, building["patient_allocated_stalls"]))
    assert building["unallocated_stalls"] == unallocated, (
        "expected unallocated_stalls {}, got {}".format(
            unallocated, building["unallocated_stalls"]))
    assert staff + patient + unallocated == building["total_parking_stalls"], (
        "the three counters must sum to total_parking_stalls")


# --- Listing helpers ------------------------------------------------------
def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_total_count(meta: Dict[str, Any], expected: int) -> None:
    assert meta["total_count"] == expected, (
        "expected total_count {}, got {}".format(expected, meta["total_count"]))


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Collections are ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), "rows are not in created_at ascending order"
