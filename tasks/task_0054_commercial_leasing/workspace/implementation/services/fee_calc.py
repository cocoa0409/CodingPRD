"""Fee bill calculation per §3.7."""
from decimal import Decimal

import db
from clock import parse_iso, is_first_of_month
from errors import err
from services.calendar_utils import months_between, first_of_month
from services.money import D, round_half_up


PROPERTY_FEE_CAP_CENTS_PER_SQM_PER_MONTH = 5000


def _validate_period_alignment(period_start, period_end) -> int:
    """Ensure period_start and period_end are 1st-of-month UTC midnight; return months_in_period."""
    if not is_first_of_month(period_start):
        raise err("ERR_VALIDATION", "period_start must be the 1st of a month at UTC midnight")
    if not is_first_of_month(period_end):
        raise err("ERR_VALIDATION", "period_end must be the 1st of a month at UTC midnight")
    if period_end <= period_start:
        raise err("ERR_INVALID_DATE_RANGE", "period_end must be later than period_start")
    return months_between(period_start, period_end)


def compute_property_fee(*, unit: dict, period_start, period_end,
                          property_fee_mode: str,
                          rate_per_sqm_per_month_cents=None,
                          fixed_rate_cents_per_month=None) -> int:
    months = _validate_period_alignment(period_start, period_end)
    area = D(unit["area_sqm"])
    if property_fee_mode == "BY_AREA":
        if rate_per_sqm_per_month_cents is None:
            raise err("ERR_VALIDATION", "rate_per_sqm_per_month_cents required for BY_AREA")
        amount = round_half_up(area * D(rate_per_sqm_per_month_cents) * D(months))
    elif property_fee_mode == "FIXED_RATE":
        if fixed_rate_cents_per_month is None:
            raise err("ERR_VALIDATION", "fixed_rate_cents_per_month required for FIXED_RATE")
        amount = int(fixed_rate_cents_per_month) * months
    else:
        raise err("ERR_VALIDATION", f"Unknown property_fee_mode: {property_fee_mode}")
    cap = round_half_up(D(PROPERTY_FEE_CAP_CENTS_PER_SQM_PER_MONTH) * area * D(months))
    return min(amount, cap)


def compute_energy_fee(*, this_unit: dict, period_start, period_end,
                        energy_mode: str, tariff_per_kwh_cents: int,
                        sub_meter_kwh=None, shared_total_kwh=None,
                        shared_meter_group_unit_ids=None) -> int:
    # The period for energy fees does not strictly need to be month-aligned per scaffold,
    # but PRD §3.7 implies issuance is per period.
    # We do not enforce alignment for energy bills; only validate that period_end > period_start.
    if period_end <= period_start:
        raise err("ERR_INVALID_DATE_RANGE", "period_end must be later than period_start")
    if tariff_per_kwh_cents is None or tariff_per_kwh_cents <= 0:
        raise err("ERR_VALIDATION", "tariff_per_kwh_cents must be > 0")
    if energy_mode == "SUB_METER":
        if sub_meter_kwh is None or sub_meter_kwh < 0:
            raise err("ERR_VALIDATION", "sub_meter_kwh required and must be >= 0")
        return round_half_up(D(sub_meter_kwh) * D(tariff_per_kwh_cents))
    if energy_mode == "ALLOCATED":
        if shared_total_kwh is None or shared_total_kwh < 0:
            raise err("ERR_VALIDATION", "shared_total_kwh required and must be >= 0")
        if not isinstance(shared_meter_group_unit_ids, list) or len(shared_meter_group_unit_ids) < 2:
            raise err("ERR_VALIDATION", "shared_meter_group_unit_ids must have >= 2 entries")
        if this_unit["id"] not in shared_meter_group_unit_ids:
            raise err("ERR_VALIDATION", "shared_meter_group_unit_ids must include this bill's unit_id")
        # Lookup all units; if any missing, ERR_NOT_FOUND.
        group_units = []
        for uid in shared_meter_group_unit_ids:
            u = db.units.get(uid)
            if u is None:
                raise err("ERR_NOT_FOUND", f"Unit {uid} in shared_meter_group_unit_ids not found")
            group_units.append(u)
        total_area = sum(D(u["area_sqm"]) for u in group_units)
        if total_area <= 0:
            raise err("ERR_VALIDATION", "Total group area must be positive")
        my_share_kwh = D(shared_total_kwh) * D(this_unit["area_sqm"]) / total_area
        my_amount = round_half_up(my_share_kwh * D(tariff_per_kwh_cents))

        # Canonical-unit remainder absorption:
        # Find lexicographically smallest unit_id in the group.
        canonical_uid = min(shared_meter_group_unit_ids)
        if this_unit["id"] == canonical_uid:
            # Compute the round-half-up of group total.
            group_total_amount = round_half_up(D(shared_total_kwh) * D(tariff_per_kwh_cents))
            # Compute the sum of each other unit's rounded share.
            others_sum = 0
            for u in group_units:
                if u["id"] == canonical_uid:
                    continue
                share = D(shared_total_kwh) * D(u["area_sqm"]) / total_area
                others_sum += round_half_up(share * D(tariff_per_kwh_cents))
            # Canonical absorbs the remainder so the sum equals group_total_amount.
            my_amount = group_total_amount - others_sum
        return my_amount
    raise err("ERR_VALIDATION", f"Unknown energy_mode: {energy_mode}")
