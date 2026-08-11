"""Every calculation rule, written exactly in the pinned order and precision."""

from datetime import timedelta
from decimal import Decimal

import constants as K
from util import D, rhu, rhu_int, trunc, ceil_div, parse_dt, parse_date, fmt_dt


# ---------------------------------------------------------------------------
# hours
# ---------------------------------------------------------------------------

def time_entry_hours(started_at_utc, ended_at_utc):
    """raw_hours truncated to 4dp; rounded_hours = raw snapped to the quarter hour."""
    delta = parse_dt(ended_at_utc) - parse_dt(started_at_utc)
    raw = trunc(D(delta.total_seconds()) / D(3600), 4)
    inc = D(K.TIME_ROUNDING_INCREMENT_HOURS)
    rounded = rhu(rhu(raw / inc, 0) * inc, 2)
    return raw, rounded


def crew_billable_hours(eligible_raw, eligible_rounded):
    """PORTAL_VIEW rounds each entry first then sums; BILLING_VIEW sums raw then rounds."""
    inc = D(K.TIME_ROUNDING_INCREMENT_HOURS)
    portal = rhu(sum(eligible_rounded, D(0)), 2)
    raw_total = sum(eligible_raw, D(0))
    billing = rhu(rhu(raw_total / inc, 0) * inc, 2)
    return portal, billing


def crew_applied_hours(billing_hours, billing_mode):
    if billing_mode == "HOURLY":
        return rhu(max(D(billing_hours), D(K.HOURLY_MIN_CALLOUT_HOURS)), 2)
    return rhu(D(billing_hours), 2)


def crew_overtime_split(applied_hours):
    applied = D(applied_hours)
    overtime = max(D(0), applied - D(K.HOURLY_OT_DAILY_THRESHOLD_HOURS))
    overtime = rhu(overtime, 2)
    regular = rhu(applied - overtime, 2)
    return regular, overtime


def crew_assignment_labor_cents(regular_hours, overtime_hours, rate_cents):
    """The two components are rounded SEPARATELY and then added."""
    rate = D(rate_cents)
    regular_part = rhu_int(D(regular_hours) * rate)
    overtime_part = rhu_int(D(overtime_hours) * rate * D(K.HOURLY_OT_MULTIPLIER))
    return regular_part + overtime_part


# ---------------------------------------------------------------------------
# billing pipelines
# ---------------------------------------------------------------------------

def package_base_charge(package_tier):
    return K.PACKAGE_TIER_CENTS[package_tier]


def package_overage_charge(billing_hours_total, package_tier):
    allowance = D(K.PACKAGE_INCLUDED_HOURS[package_tier])
    overage = max(D(0), D(billing_hours_total) - allowance)
    return rhu_int(overage * D(K.PACKAGE_OVERAGE_RATE_CENTS_PER_HOUR))


def travel_surcharge(mileage_miles):
    m = D(mileage_miles)
    band1 = max(D(0), min(m, D(K.TRAVEL_BAND1_MAX_MILES)) - D(K.TRAVEL_FREE_MILES))
    band2 = max(D(0), m - D(K.TRAVEL_BAND1_MAX_MILES))
    return (rhu_int(band1 * D(K.TRAVEL_BAND1_RATE_CENTS_PER_MILE))
            + rhu_int(band2 * D(K.TRAVEL_BAND2_RATE_CENTS_PER_MILE)))


def stairs_surcharge(origin_stairs_flights, crew_confirmed_count):
    billable = max(0, int(origin_stairs_flights) - K.STAIRS_INCLUDED_FLIGHTS)
    return billable * K.STAIRS_FEE_CENTS_PER_FLIGHT_PER_CREW * int(crew_confirmed_count)


def long_carry_surcharge(origin_long_carry_feet):
    excess = max(D(0), D(origin_long_carry_feet) - D(K.LONG_CARRY_FREE_FEET))
    if excess <= 0:
        return 0
    blocks = ceil_div(excess, 25)
    return blocks * K.LONG_CARRY_FEE_CENTS_PER_25_FEET


def package_deposit_schedule(contracted_cents):
    contracted = D(contracted_cents)
    signing = rhu_int(contracted * D(K.PACKAGE_DEPOSIT_PCT_SIGNING))
    pack_start = rhu_int(contracted * D(K.PACKAGE_DEPOSIT_PCT_PACK_START))
    close_out = int(contracted_cents) - signing - pack_start
    return signing, pack_start, close_out


# ---------------------------------------------------------------------------
# trucks, crew, rooms
# ---------------------------------------------------------------------------

def truck_trip_count(volume_cft, truck_capacity_cft, truck_count):
    combined = D(truck_capacity_cft) * D(truck_count)
    volume = D(volume_cft)
    if combined <= 0:
        return 1 if volume > 0 else 0
    full = int(volume / combined)
    remainder = volume - (D(full) * combined)
    trips = full + (1 if remainder > D(K.TRUCK_PARTIAL_TRIP_THRESHOLD_PCT) * combined else 0)
    if volume > 0 and trips == 0:
        trips = 1
    return trips


def crew_min_required(home_tier):
    return K.CREW_MIN_BY_HOME_TIER[home_tier]


def room_effective_capacity(nominal_linear_inches, approved_addendum_linear_inches,
                            placement_status):
    if placement_status == "APPROVED":
        value = (D(nominal_linear_inches) * D(K.APPROVED_CAPACITY_FACTOR)
                 + D(approved_addendum_linear_inches))
    else:
        value = D(nominal_linear_inches) * D(K.PROVISIONAL_CAPACITY_FACTOR)
    return rhu(value, 2)


def room_volume_allowance(nominal_volume_cft):
    return rhu(D(nominal_volume_cft) * D(K.ROOM_VOLUME_SAFETY_FACTOR), 2)


def engagement_volume_estimate_heuristic(home_tier):
    return rhu(D(K.ROOM_COUNT_BY_HOME_TIER[home_tier]) * D(K.VOLUME_PER_ROOM_CFT), 2)


# ---------------------------------------------------------------------------
# dispositions
# ---------------------------------------------------------------------------

def donation_receipt_value(disposition, appraisal_source, appraised_value_cents):
    if disposition != "DONATE":
        return 0
    if appraisal_source == "APPRAISED":
        raw = D(appraised_value_cents) * D(K.DONATION_APPRAISED_FACTOR)
    elif appraisal_source == "SELF_REPORTED":
        raw = D(appraised_value_cents) * D(K.DONATION_SELF_REPORT_FACTOR)
    else:
        raw = D(0)
    return min(rhu_int(raw), K.DONATION_RECEIPT_CAP_CENTS)


# ---------------------------------------------------------------------------
# consignment
# ---------------------------------------------------------------------------

def consignment_current_price(list_price_cents, markdown_round):
    pct = D(K.MARKDOWN_ROUND_PCT[markdown_round])
    return rhu_int(D(list_price_cents) * (D(1) - pct))


def consignment_commission(gross_sale_price_cents):
    g = D(gross_sale_price_cents)
    if g <= D(K.COMMISSION_BAND1_MAX_CENTS):
        rate = D(K.COMMISSION_BAND1_RATE)
    elif g <= D(K.COMMISSION_BAND2_MAX_CENTS):
        rate = D(K.COMMISSION_BAND2_RATE)
    else:
        rate = D(K.COMMISSION_BAND3_RATE)
    return rhu_int(g * rate)


def consignment_fees(item_count):
    photo = min(int(item_count) * K.CONSIGN_PHOTO_FEE_CENTS_PER_ITEM,
                K.CONSIGN_PHOTO_FEE_CAP_CENTS)
    return K.CONSIGN_PICKUP_FEE_CENTS + photo


def consignment_net_proceeds(gross_sale_price_cents, commission_cents, fees_cents):
    return max(0, int(gross_sale_price_cents) - int(commission_cents) - int(fees_cents))


def disposal_fee(total_volume_cft):
    return max(K.DISPOSAL_MIN_FEE_CENTS,
               rhu_int(D(total_volume_cft) * D(K.DISPOSAL_FEE_CENTS_PER_CFT)))


# ---------------------------------------------------------------------------
# vendors
# ---------------------------------------------------------------------------

def vendor_holdback(quoted_cents, holdback_pct):
    return rhu_int(D(quoted_cents) * D(holdback_pct))


# ---------------------------------------------------------------------------
# invoice
# ---------------------------------------------------------------------------

def invoice_coordination_fee(subtotal_cents):
    subtotal = D(subtotal_cents)
    if subtotal <= D(K.COORD_FEE_TIER1_MAX_CENTS):
        cap = K.COORD_FEE_TIER1_CAP_CENTS
    elif subtotal <= D(K.COORD_FEE_TIER2_MAX_CENTS):
        cap = K.COORD_FEE_TIER2_CAP_CENTS
    else:
        cap = K.COORD_FEE_TIER3_CAP_CENTS
    return min(rhu_int(subtotal * D(K.COORD_FEE_PCT)), cap)


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------

def milestone_due_on(scheduled_move_start_utc, milestone_key):
    base = parse_dt(scheduled_move_start_utc).date()
    return (base + timedelta(days=K.MILESTONE_OFFSET_DAYS[milestone_key])).isoformat()


def punch_due_at(created_at, severity):
    return fmt_dt(parse_dt(created_at) + timedelta(hours=K.PUNCH_SLA_HOURS[severity]))


def progress_pct(milestones):
    return sum(K.MILESTONE_WEIGHT[m["milestone_key"]]
               for m in milestones if m["status"] == "COMPLETE")


def days_between(earlier_date_str, later_date_str):
    return (parse_date(later_date_str) - parse_date(earlier_date_str)).days
